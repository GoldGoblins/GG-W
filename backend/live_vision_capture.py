"""Wayland portal/PipeWire capture. Imported only by the capture subprocess."""
from __future__ import annotations

import base64
import io
import json
import os
import signal
import socket
import socketserver
import struct
import threading
import time
import uuid
from backend import sensitive_ui_guard

from backend.live_vision import (FrameRing, IDLE_SECONDS, SESSION_SECONDS,
                                MAX_DETAIL_BYTES, MAX_RING_BYTES, MAX_REPLY_BYTES,
                                _recv_exact, atomic_ram_file, ram_root)


class Capture:
    def __init__(self):
        # stdio MCP intentionally inherits few environment variables. The
        # user's standard session bus still permits the visible OS portal;
        # do not rely on DISPLAY or copy another process's environment.
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            from pathlib import Path
            session_bus = Path(runtime) / "bus"
            if not session_bus.is_socket() or session_bus.stat().st_uid != os.getuid():
                raise RuntimeError("Ingen skrivbordssession finns för skärmdelningsportalen")
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(session_bus)
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstVideo", "1.0")
        from gi.repository import Gio, GLib, Gst, GstVideo
        self.Gio, self.GLib, self.Gst = Gio, GLib, Gst
        self.GstVideo = GstVideo
        Gst.init(None)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.loop = GLib.MainLoop()
        self.ring = FrameRing()
        self.detail_lock = threading.Lock()
        self.detail = None
        self.detail_seq = 0
        self.preview_size = None
        self.source_pixel_size = None
        self.pipeline = None
        self.session = None
        self.remote_fd = None
        self.subscriptions = []
        self.pending_requests = []
        self.generation = 0
        self.state = "off"
        self.reason = ""
        self.source_size = None
        self.source_position = None
        self.started = 0.0
        self.last_use = time.monotonic()
        self.first_pending_at = 0.0
        self.GLib.timeout_add(1000, self.tick)

    def status(self):
        value = self.ring.status()
        with self.detail_lock:
            detail = self.detail
        detail_bytes = detail[0].get_buffer().get_size() if detail else 0
        value.update(ring_buffer_bytes=value["buffer_bytes"], detail_buffer_bytes=detail_bytes,
                     buffer_bytes=value["buffer_bytes"] + detail_bytes,
                     buffer_limit_bytes=MAX_RING_BYTES + MAX_DETAIL_BYTES,
                     detail_size=[detail[3].width, detail[3].height] if detail else None,
                     detail_age_ms=round((time.monotonic() - detail[1]) * 1000) if detail else None,
                     preview_size=self.preview_size, source_pixel_size=self.source_pixel_size)
        value.update(state=self.state, reason=self.reason, updated_at=time.time(),
                     source_size=self.source_size, source_position=self.source_position,
                     idle_limit_seconds=IDLE_SECONDS, session_limit_seconds=SESSION_SECONDS)
        return value

    def publish(self):
        atomic_ram_file("status.json", json.dumps(self.status(), ensure_ascii=False).encode())

    def tick(self):
        now = time.monotonic()
        if self.state in {"selecting", "starting", "live"}:
            if now - self.last_use > IDLE_SECONDS or now - self.started > SESSION_SECONDS:
                self.stop("Fångsten stängdes efter inaktivitet eller sessionens tidsgräns")
            elif self.state == "selecting" and now - self.first_pending_at > 120:
                self.stop("Skärmdelningen valdes inte inom två minuter")
            elif self.state == "starting" and now - self.first_pending_at > 20:
                self.stop("Skärmfångsten gav inga bilder", state="error")
        elif now - self.last_use > IDLE_SECONDS:
            self.loop.quit()
        self.publish()
        return True

    def _portal(self, method, arguments):
        return self.bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                  "org.freedesktop.portal.ScreenCast", method, arguments, None,
                                  self.Gio.DBusCallFlags.NONE, 10000, None)

    def _request(self, method, signature, arguments, options, callback):
        token = "gg_eyes_" + uuid.uuid4().hex
        options = {**options, "handle_token": self.GLib.Variant("s", token)}
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        generation = self.generation
        subscription = 0
        def received(connection, sender_name, object_path, interface_name, signal_name, parameters, user_data):
            self.bus.signal_unsubscribe(subscription)
            if subscription in self.subscriptions:
                self.subscriptions.remove(subscription)
            if path in self.pending_requests:
                self.pending_requests.remove(path)
            if generation != self.generation:
                return
            code, values = parameters.unpack()
            if code:
                self.stop("Skärmdelningen avbröts eller nekades")
                return
            try:
                callback(values)
            except Exception:
                self.stop("PipeWire-fångsten kunde inte öppnas", state="error")
        subscription = self.bus.signal_subscribe("org.freedesktop.portal.Desktop",
                                                  "org.freedesktop.portal.Request", "Response", path,
                                                  None, self.Gio.DBusSignalFlags.NONE, received, None)
        self.subscriptions.append(subscription)
        self.pending_requests.append(path)
        reply = self._portal(method, self.GLib.Variant(signature, (*arguments, options)))
        if reply.unpack()[0] != path:
            raise RuntimeError("Portal returned an unexpected request path")

    def start(self):
        sensitive_ui_guard.require_capture_allowed()
        if self.state in {"selecting", "starting", "live"}:
            self.last_use = time.monotonic()
            return False
        self.stop()
        self.started = self.last_use = self.first_pending_at = time.monotonic()
        self.state = "selecting"
        self.reason = "Välj skärmen i Fedoras delningsruta"
        self.publish()
        try:
            options = {"session_handle_token": self.GLib.Variant("s", "gg_eyes_" + uuid.uuid4().hex)}
            self._request("CreateSession", "(a{sv})", (), options, self._created)
        except Exception:
            self.stop("Fedoras skärmdelningsportal kunde inte öppnas", state="error")
        return False

    def _created(self, result):
        self.session = result["session_handle"]
        subscription = self.bus.signal_subscribe("org.freedesktop.portal.Desktop",
                                                  "org.freedesktop.portal.Session", "Closed", self.session,
                                                  None, self.Gio.DBusSignalFlags.NONE,
                                                  lambda *args: self.stop("Skärmdelningen stängdes"), None)
        self.subscriptions.append(subscription)
        options = {"types": self.GLib.Variant("u", 1), "multiple": self.GLib.Variant("b", False),
                   "cursor_mode": self.GLib.Variant("u", 2)}
        self._request("SelectSources", "(oa{sv})", (self.session,), options, self._selected)

    def _selected(self, result):
        self._request("Start", "(osa{sv})", (self.session, ""), {}, self._opened)

    def _opened(self, result):
        streams = result.get("streams", [])
        if not streams:
            raise RuntimeError("No screen stream")
        node, properties = streams[0]
        self.source_size = properties.get("size")
        self.source_position = properties.get("position")
        reply, fd_list = self.bus.call_with_unix_fd_list_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.ScreenCast", "OpenPipeWireRemote",
            self.GLib.Variant("(oa{sv})", (self.session, {})), self.GLib.VariantType.new("(h)"),
            self.Gio.DBusCallFlags.NONE, 10000, None, None)
        self.remote_fd = fd_list.get(reply.unpack()[0])
        width, height = 1280, 720
        if self.source_size and self.source_size[0] > 0 and self.source_size[1] > 0:
            scale = min(1.0, 1280 / self.source_size[0], 800 / self.source_size[1])
            width = max(2, int(self.source_size[0] * scale) // 2 * 2)
            height = max(2, int(self.source_size[1] * scale) // 2 * 2)
        description = (
            "pipewiresrc name=screen do-timestamp=true max-buffers=3 "
            "! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream "
            "! videorate drop-only=true max-rate=25 "
            "! video/x-raw,framerate=25/1 ! tee name=views "
            "views. ! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream "
            "! videoconvert ! videoscale "
            "! video/x-raw,format=RGB,width=[1,4096],height=[1,2160],pixel-aspect-ratio=1/1 "
            "! appsink name=detail emit-signals=true max-buffers=1 drop=true sync=false "
            "views. ! queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream "
            "! videoconvert ! videoscale add-borders=true "
            f"! video/x-raw,format=I420,width={width},height={height},pixel-aspect-ratio=1/1 "
            "! jpegenc quality=78 "
            "! appsink name=frames emit-signals=true max-buffers=1 drop=true sync=false"
        )
        self.pipeline = self.Gst.parse_launch(description)
        source = self.pipeline.get_by_name("screen")
        source.set_property("fd", self.remote_fd)
        # New portal versions supply a serial, older versions a node ID.
        serial = properties.get("pipewire-serial")
        if serial is not None and source.find_property("target-object"):
            source.set_property("target-object", str(serial))
        else:
            source.set_property("path", str(node))
        sink = self.pipeline.get_by_name("frames")
        sink.connect("new-sample", self._sample)
        self.pipeline.get_by_name("detail").connect("new-sample", self._detail_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._message)
        self.state, self.reason = "starting", "Väntar på första bilden"
        self.first_pending_at = time.monotonic()
        self.publish()
        if self.pipeline.set_state(self.Gst.State.PLAYING) == self.Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Screen pipeline refused playback")

    def _sample(self, sink):
        if sensitive_ui_guard.active():
            self.ring.clear()
            with self.detail_lock:self.detail=None
            self.GLib.idle_add(self.stop,'SENSITIVE_UI_ACTIVE')
            return self.Gst.FlowReturn.FLUSHING
        sample = sink.emit("pull-sample")
        if sample is None:
            return self.Gst.FlowReturn.EOS
        buffer = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        self.preview_size = [caps.get_value("width"), caps.get_value("height")]
        data = buffer.extract_dup(0, buffer.get_size())
        pts = buffer.pts / self.Gst.SECOND if buffer.pts != self.Gst.CLOCK_TIME_NONE else None
        self.ring.append(data, caps.get_value("width"), caps.get_value("height"), pts)
        if self.state == "starting":
            self.state, self.reason = "live", ""
        return self.Gst.FlowReturn.OK

    def _detail_sample(self, sink):
        if sensitive_ui_guard.active():
            self.ring.clear()
            with self.detail_lock:self.detail=None
            self.GLib.idle_add(self.stop,'SENSITIVE_UI_ACTIVE')
            return self.Gst.FlowReturn.FLUSHING
        sample = sink.emit("pull-sample")
        if sample is None:
            return self.Gst.FlowReturn.EOS
        buffer = sample.get_buffer()
        if buffer.get_size() > MAX_DETAIL_BYTES:
            return self.Gst.FlowReturn.OK
        info = self.GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        pts = buffer.pts / self.Gst.SECOND if buffer.pts != self.Gst.CLOCK_TIME_NONE else None
        # Keep one referenced RGB sample. Do not encode or accumulate native
        # screenshots on every frame; encode only when an observation is asked.
        with self.detail_lock:
            self.detail_seq += 1
            self.detail = (sample, time.monotonic(), pts, info, self.detail_seq)
        pipeline = self.pipeline
        source_caps = pipeline.get_by_name("screen").get_static_pad("src").get_current_caps() if pipeline else None
        if source_caps:
            source = source_caps.get_structure(0)
            self.source_pixel_size = [source.get_value("width"), source.get_value("height")]
        return self.Gst.FlowReturn.OK

    def _detail_observation(self):
        guard_token=sensitive_ui_guard.capture_token()
        from PIL import Image
        with self.detail_lock:
            detail = self.detail
        if detail is None:
            raise RuntimeError("Detaljbilden är inte klar ännu")
        sample, captured, pts, info, seq = detail
        if time.monotonic() - captured > 2:
            raise RuntimeError("Detaljbilden är äldre än två sekunder")
        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())
        image = Image.frombytes("RGB", (info.width, info.height), data, "raw", "RGB", info.stride[0])
        stream = io.BytesIO()
        image.save(stream, "JPEG", quality=94, subsampling=0)
        encoded = stream.getvalue()
        if len(encoded) > MAX_DETAIL_BYTES:
            raise RuntimeError("Detaljbilden överskred transportens bildgräns")
        now = time.monotonic()
        sensitive_ui_guard.require_capture_allowed(guard_token)
        with self.ring.lock:
            self.ring.delivered_at = now
            self.ring.delivered_seq = seq
        return {"source": "screen", "image_kind": "native_detail", "requested_fps": 25,
                "coverage_seconds": 0, "largest_gap_ms": 0, "requested_seconds": 0, "frame_count": 1,
                "frames": [{"seq": seq, "age_ms": round((now - captured) * 1000),
                            "pts_seconds": pts, "width": info.width, "height": info.height,
                            "jpeg": base64.b64encode(encoded).decode("ascii")}],
                "source_pixel_size": self.source_pixel_size,
                "detail_limit_size": [4096, 2160],
                "delivery_means": "Image supplied to a tool; this does not assert that a model analyzed it."}

    def _message(self, bus, message):
        if message.type == self.Gst.MessageType.ERROR:
            self.stop("Skärmfångsten rapporterade ett fel", state="error")
        elif message.type == self.Gst.MessageType.EOS:
            self.stop("Skärmdelningen tog slut")

    def stop(self, reason="", *, state="off"):
        self.generation += 1
        for subscription in self.subscriptions:
            self.bus.signal_unsubscribe(subscription)
        self.subscriptions.clear()
        if self.pipeline is not None:
            pipeline, self.pipeline = self.pipeline, None
            bus = pipeline.get_bus()
            bus.remove_signal_watch()
            pipeline.set_state(self.Gst.State.NULL)
        if self.remote_fd is not None:
            os.close(self.remote_fd)
            self.remote_fd = None
        for path in self.pending_requests:
            self.bus.call("org.freedesktop.portal.Desktop", path, "org.freedesktop.portal.Request",
                          "Close", None, None, self.Gio.DBusCallFlags.NONE, 1000, None, None)
        self.pending_requests.clear()
        if self.session:
            self.bus.call("org.freedesktop.portal.Desktop", self.session, "org.freedesktop.portal.Session",
                          "Close", None, None, self.Gio.DBusCallFlags.NONE, 1000, None, None)
            self.session = None
        self.ring.clear()
        with self.detail_lock:
            self.detail = None
        self.preview_size = None
        self.source_pixel_size = None
        for path in ram_root().glob("view-*.jpg"):
            path.unlink(missing_ok=True)
        self.state, self.reason = state, reason
        self.publish()
        return False

    def command(self, command):
        if not isinstance(command, dict):
            raise ValueError("Screen command must be an object")
        op = command.get("op")
        guard_token=sensitive_ui_guard.capture_token() if op not in {'status','stop'} else None
        if op == "status":
            return self.status()
        if op == "start":
            self.last_use = time.monotonic()
            self.GLib.idle_add(self.start)
            native = hasattr(self,"native_stop")
            return {"state": "requested", "message": ("Ansluter direkt till KDE:s skärmström"
                    if native else "Välj skärmen i Fedoras delningsruta"),
                    "requires_selection":not native,"target_fps":25}
        if op == "stop":
            done = threading.Event()
            def stop():
                self.stop()
                done.set()
                return False
            self.GLib.idle_add(stop)
            if not done.wait(3):
                raise RuntimeError("Capture did not acknowledge stop")
            return {"state": "off"}
        if op in {"frame", "clip"}:
            self.last_use = time.monotonic()
            if self.state not in {"starting","live"} and hasattr(self,"native_stop"):
                self.GLib.idle_add(self.start)
                deadline = time.monotonic()+3
                while self.state != "live" and time.monotonic()<deadline:
                    time.sleep(.025)
                    if self.state == "error":
                        break
            elif self.state == "starting" and hasattr(self,"native_stop"):
                deadline = time.monotonic()+3
                while self.state == "starting" and time.monotonic()<deadline:
                    time.sleep(.025)
            if self.state != "live":
                raise RuntimeError(self.reason or "Skärmfångsten är inte aktiv")
            if op == "frame" and float(command.get("age", 0)) == 0:
                result = self._detail_observation()
            else:
                result = self.ring.observation(seconds=command.get("seconds", 0) if op == "clip" else 0,
                                               fps=command.get("fps", 25), age=command.get("age", 0))
                result["image_kind"] = "motion_preview"
            result.update(source_size=self.source_size, source_position=self.source_position)
            if hasattr(self,"native_stop"):
                result.update(provider="kde-native",timestamp_kind="capture_completed_monotonic")
            sensitive_ui_guard.require_capture_allowed(guard_token)
            return result
        raise ValueError("Unknown screen operation")


def serve(*,native=False):
    import fcntl
    root = ram_root()
    with (root / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if native:
            from backend.live_vision_kwin import NativeKWin
            class NativeCapture(NativeKWin,Capture):
                pass
            capture = NativeCapture()
        else:
            capture = Capture()
        path = root / "capture.sock"
        path.unlink(missing_ok=True)
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.settimeout(10)
                    peer = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if peer[1] != os.getuid():
                        return
                    size = struct.unpack("!I", _recv_exact(self.request, 4))[0]
                    if size > 8192:
                        return
                    result = capture.command(json.loads(_recv_exact(self.request, size)))
                    body = json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False).encode()
                    if len(body) > MAX_REPLY_BYTES:
                        raise RuntimeError("Observation exceeds transport limit")
                except (ValueError, OSError, RuntimeError) as exc:
                    body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode()
                try:
                    self.request.sendall(struct.pack("!I", len(body)) + body)
                except OSError:
                    pass
        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        server = Server(str(path), Handler)
        path.chmod(0o600)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        capture.publish()
        def end(*args):
            capture.GLib.idle_add(capture.loop.quit)
        signal.signal(signal.SIGTERM, end)
        signal.signal(signal.SIGINT, end)
        try:
            capture.loop.run()
        finally:
            capture.stop()
            server.shutdown()
            server.server_close()
            path.unlink(missing_ok=True)
