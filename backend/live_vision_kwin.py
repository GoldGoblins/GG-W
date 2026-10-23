"""KDE's native, application-authorized screen transport; raw pipes, no files.

The dedicated capture executable declares ScreenShot2 in its own desktop entry.
Capture still begins only on a start/observation request and obeys the same RAM,
idle, session, socket ownership and explicit-stop limits as the portal provider.
"""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import select
import threading
import time

from backend.live_vision import MAX_DETAIL_BYTES, atomic_ram_file, ram_root


class NativeKWin:
    """Mixin for the existing bounded Capture service."""

    def __init__(self):
        super().__init__()
        self.native_stop = threading.Event()
        self.native_worker = None
        self.preview_worker = None
        self.preview_queue = None
        self.native_detail = None
        self.native_screen = None
        self.native_scale = 1.
        self.native_frames = 0
        # A connector name is routing metadata, not a screen image or grant.
        # Keep the same target even if the bounded service later restarts.
        try:
            binding = json.loads((ram_root()/'native-source.json').read_text())
            self.native_screen = binding['screen']
            self.source_position = binding.get('position')
        except (OSError,ValueError,KeyError):
            pass

    def status(self):
        value = super().status()
        with self.detail_lock:
            detail = getattr(self,'native_detail',None)
        amount = detail[0].width*detail[0].height*3 if detail else 0
        value.update(provider='kde-native', requires_selection=False,
                     timestamp_kind='capture_completed_monotonic',
                     detail_buffer_bytes=amount,
                     buffer_bytes=value['ring_buffer_bytes']+amount,
                     detail_size=list(detail[0].size) if detail else None,
                     detail_age_ms=round((time.monotonic()-detail[1])*1000) if detail else None)
        return value

    def start(self):
        if self.state in {'starting','live'}:
            self.last_use = time.monotonic()
            return False
        self.stop()
        self.started = self.last_use = self.first_pending_at = time.monotonic()
        self.state,self.reason = 'starting','Kopplar till KDE:s skärmström'
        self.native_stop = threading.Event()
        self.preview_queue = queue.Queue(maxsize=1)
        self.native_worker = threading.Thread(target=self._native_loop,daemon=True)
        self.preview_worker = threading.Thread(target=self._preview_loop,daemon=True)
        self.preview_worker.start()
        self.native_worker.start()
        self.publish()
        return False

    def _raw_frame(self):
        from PIL import Image
        read_fd,write_fd = os.pipe2(os.O_CLOEXEC)
        try:
            fd_list = self.Gio.UnixFDList.new()
            slot = fd_list.append(write_fd)
            options = {k:self.GLib.Variant('b',v) for k,v in {
                'include-cursor':True,'native-resolution':True,
                'hide-caller-windows':False}.items()}
            signature = '(sa{sv}h)' if self.native_screen else '(a{sv}h)'
            args = (self.native_screen,options,slot) if self.native_screen else (options,slot)
            result,_ = self.bus.call_with_unix_fd_list_sync(
                'org.kde.KWin.ScreenShot2','/org/kde/KWin/ScreenShot2',
                'org.kde.KWin.ScreenShot2',
                'CaptureScreen' if self.native_screen else 'CaptureActiveScreen',
                self.GLib.Variant(signature,args),self.GLib.VariantType.new('(a{sv})'),
                self.Gio.DBusCallFlags.NONE,2000,fd_list,None)
            props = result.unpack()[0]
            width,height,stride = (int(props[k]) for k in ['width','height','stride'])
            size = stride*height
            if width<=0 or height<=0 or size<=0 or size>MAX_DETAIL_BYTES:
                raise RuntimeError('Skärmbilden överskrider RAM-gränsen')
            raw = bytearray()
            deadline = time.monotonic()+2
            while len(raw)<size:
                remaining = deadline-time.monotonic()
                if self.native_stop.is_set() or remaining<=0:
                    raise RuntimeError('Skärmbilden blev inte färdig')
                if not select.select([read_fd],[],[],remaining)[0]:
                    raise RuntimeError('Skärmbilden blev inte färdig')
                data = os.read(read_fd,min(256*1024,size-len(raw)))
                if not data:
                    raise RuntimeError('Skärmbildens pipe stängdes')
                raw.extend(data)
            # Qt QImage formats, with explicit byte layout on this little-endian
            # Fedora host. Refuse unknown/HDR layouts rather than misread color.
            layout = {4:'BGRX',5:'BGRX',6:'BGRX',13:'RGB',16:'RGBX',
                      17:'RGBX',18:'RGBX'}.get(int(props['format']))
            if layout is None:
                raise RuntimeError('Skärmens pixelformat stöds inte')
            image = Image.frombytes('RGB',(width,height),bytes(raw),'raw',layout,stride)
            captured = time.monotonic()
            if not self.native_screen:
                screen = props.get('screen')
                if not isinstance(screen,str) or not screen:
                    raise RuntimeError('KDE gav ingen beständig skärmidentitet')
                self.native_screen = screen
                # This workstation's approved single monitor starts at (0,0).
                # Native pixels use the reported scale for logical coordinates.
                self.source_position = [0,0]
                atomic_ram_file('native-source.json',json.dumps({
                    'screen':screen,'position':self.source_position}).encode())
            self.native_scale = float(props.get('scale',1.)) or 1.
            self.source_size = [round(width/self.native_scale),round(height/self.native_scale)]
            self.source_pixel_size = [width,height]
            if width>4096 or height>2160:
                image.thumbnail((4096,2160))
            return image,captured
        finally:
            os.close(read_fd); os.close(write_fd)

    def _native_loop(self):
        stopping = self.native_stop
        frames = self.preview_queue
        while not stopping.is_set():
            cycle = time.monotonic()
            try:
                image,captured = self._raw_frame()
                if stopping.is_set():
                    return
                with self.detail_lock:
                    self.native_frames += 1
                    self.native_detail = (image,captured,captured-self.started,self.native_frames)
                # One pending preview reference; native acquisition need not wait
                # for JPEG encoding. Replace old work rather than grow a backlog.
                try:
                    frames.put_nowait((image,captured))
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    frames.put_nowait((image,captured))
                if self.state=='starting':
                    self.state,self.reason = 'live',''
            except Exception:
                if not stopping.is_set():
                    # Do not expose DBus paths, capture bytes, or authorization
                    # material in logs/status. An explicit next request may retry.
                    self.GLib.idle_add(lambda:self.stop(
                        'KDE:s skärmkoppling kunde inte läsa bilden',state='error')
                        if self.native_stop is stopping else False)
                return
            stopping.wait(max(0,1/25-(time.monotonic()-cycle)))

    def _preview_loop(self):
        from PIL import Image
        stopping,frames = self.native_stop,self.preview_queue
        while not stopping.is_set():
            try:
                image,captured = frames.get(timeout=.1)
            except queue.Empty:
                continue
            preview = image.copy()
            preview.thumbnail((1280,800),Image.Resampling.BILINEAR)
            stream = io.BytesIO(); preview.save(stream,'JPEG',quality=78)
            if stopping.is_set():
                return
            self.preview_size = list(preview.size)
            self.ring.append(stream.getvalue(),preview.width,preview.height,None,captured=captured)

    def _detail_observation(self):
        with self.detail_lock:
            detail = self.native_detail
        if detail is None:
            raise RuntimeError('Detaljbilden är inte klar ännu')
        image,captured,pts,seq = detail
        now = time.monotonic()
        if now-captured>2:
            raise RuntimeError('Detaljbilden är äldre än två sekunder')
        stream = io.BytesIO(); image.save(stream,'JPEG',quality=94,subsampling=0)
        encoded = stream.getvalue()
        if len(encoded)>MAX_DETAIL_BYTES:
            raise RuntimeError('Detaljbilden överskrider transportgränsen')
        with self.ring.lock:
            self.ring.delivered_at=now; self.ring.delivered_seq=seq
        return {'source':'screen','provider':'kde-native','image_kind':'native_detail',
                'requested_fps':25,'coverage_seconds':0,'largest_gap_ms':0,
                'requested_seconds':0,'frame_count':1,
                'timestamp_kind':'capture_completed_monotonic',
                'frames':[{'seq':seq,'age_ms':round((now-captured)*1000),
                           'pts_seconds':None,'capture_elapsed_seconds':pts,
                           'width':image.width,'height':image.height,
                           'jpeg':base64.b64encode(encoded).decode('ascii')}],
                'source_pixel_size':self.source_pixel_size,'detail_limit_size':[4096,2160],
                'delivery_means':'Image supplied to a tool; this does not assert model analysis.'}

    def stop(self,reason='',*,state='off'):
        stopping = getattr(self,'native_stop',None)
        if stopping is not None:
            stopping.set()
        worker = getattr(self,'native_worker',None)
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=3)
        self.native_worker = None
        preview = getattr(self,'preview_worker',None)
        if preview is not None and preview is not threading.current_thread():
            preview.join(timeout=2)
        self.preview_worker = None
        self.preview_queue = None
        with self.detail_lock:
            self.native_detail = None
        return super().stop(reason,state=state)
