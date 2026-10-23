"""Bounded stereo decoding into the native mixer; FFmpeg provides file backpressure."""
from __future__ import annotations
import array,math,os,shutil,subprocess,weakref
from pathlib import Path

# This is virtual address space, including mapped codec/driver libraries and
# mandatory FFmpeg pipeline thread stacks. The six-thread pipeline measured
# 404 MiB at startup and failed intermittently at the old 512 MiB ceiling in
# the visible GPU client. Decoded PCM stays in the existing bounded rings.
DECODER_ADDRESS_LIMIT=1024*1024*1024

def stop(process):
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=.2)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
    if process.stdout:process.stdout.close()
    if process.stderr:process.stderr.close()
    if process.stdin and not process.stdin.closed:process.stdin.close()

class AudioFileStream:
    def __init__(self,audio,identity,path,*,loop=True,bus=1,gain=.22):
        ffmpeg=shutil.which('ffmpeg');limit=shutil.which('prlimit')
        if not ffmpeg or not limit:raise RuntimeError('Bounded audio file decoder unavailable')
        from backend.game_engine_audio_archive import ArchiveAudioSource,ArchiveFeed
        archive=isinstance(path,ArchiveAudioSource)
        if not archive:
            path=Path(path).resolve()
            if not path.is_file():raise ValueError('Audio file missing')
        self.audio=audio;self.identity=identity;self.path=path;self.pending=b'';self.ended=False;self.archive_loop=archive and loop;self.feeder=None
        self.audio.stream_create(identity,48000,48000)
        command=[limit,'--as='+str(DECODER_ADDRESS_LIMIT),'--core=0','--',ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-cpucount','1','-threads','1','-filter_threads','1','-filter_complex_threads','1']
        if loop and not archive:command+=['-stream_loop','-1']
        command+=['-protocol_whitelist','file,pipe','-format_whitelist','wav,mp3,ogg','-i','pipe:0' if archive else str(path),'-vn','-sn','-dn','-threads','1','-c:a','pcm_f32le','-f','f32le','-ac','2','-ar','48000','pipe:1']
        self.command=command;self.archive=archive
        if archive:self.feeder=ArchiveFeed(path,stop)
        self._decoder()
        self._finalizer=weakref.finalize(self,self.feeder.close if archive else stop,*(() if archive else (self.process,)))
        try:
            self.voice=self.audio.stream_play(identity,bus,gain)
            self.voice_generation=self.audio.voice_token(self.voice)
        except Exception:
            self._finalizer();raise
    def _decoder(self):
        # FFmpeg's filter-thread flags do not control libgomp and numerical
        # libraries loaded by the distribution's libavfilter build.
        env={**os.environ,'OMP_NUM_THREADS':'1','OMP_THREAD_LIMIT':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','MALLOC_ARENA_MAX':'2'}
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE if self.archive else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,env=env)
        os.set_blocking(self.process.stdout.fileno(),False)
        os.set_blocking(self.process.stderr.fileno(),False);self.diagnostic=b''
        if self.feeder:self.feeder.attach(self.process)
    def pump(self):
        if self.ended:return
        if self.feeder and self.feeder.error:raise RuntimeError('Archive audio: '+self.feeder.error)
        try:self.diagnostic=(self.diagnostic+os.read(self.process.stderr.fileno(),4096))[-4096:]
        except BlockingIOError:pass
        free=min(8192,self.audio.stream_free(self.identity))
        if not free:return
        if len(self.pending)<free*8:
            try:
                chunk=os.read(self.process.stdout.fileno(),free*8-len(self.pending))
                self.pending+=chunk
                if not chunk:
                    if self.process.poll() is None:return
                    if self.process.poll()!=0:
                        diagnostic=self.diagnostic.decode('utf-8','replace')
                        raise RuntimeError('Audio decoding failed: '+diagnostic[:420]+(' … '+diagnostic[-180:] if len(diagnostic)>420 else ''))
                    if self.archive_loop:
                        stop(self.process);self._decoder();return
                    frames=len(self.pending)//8
                    values=array.array('f');values.frombytes(self.pending[:frames*8])
                    self.audio.stream_write(self.identity,values,end=True);self.pending=b'';self.ended=True;self._finalizer();return
            except BlockingIOError:pass
        frames=min(free,len(self.pending)//8)
        if frames:
            values=array.array('f');values.frombytes(self.pending[:frames*8])
            accepted=self.audio.stream_write(self.identity,values)
            self.pending=self.pending[accepted*8:]
    def close(self,*,stop_voice=True):
        self._finalizer()
        if stop_voice:
            try:self.audio.stop_voice(self.voice,self.voice_generation)
            except RuntimeError:pass # Mixer teardown may precede a final stream cleanup.

class MusicStreams:
    """Independent zone music, Lua music and ambience with two rotating slots."""
    PAIRS={'zone':(0,1),'lua':(2,3),'ambience':(4,5)}
    def __init__(self,audio):self.audio=audio;self.streams={};self.current={};self.last={};self.pending={};self.paused={};self.errors=[]
    def play(self,path,channel='lua',gain=.22,fade_ms=500,*,loop=True,fade_in_ms=None,fade_out_ms=None):
        if channel not in self.PAIRS:raise ValueError('Unknown audio stream channel')
        if isinstance(gain,bool) or not isinstance(gain,(int,float)) or not math.isfinite(gain) or not 0<=gain<=1:raise ValueError('Invalid stream gain')
        outgoing=fade_ms if fade_out_ms is None else fade_out_ms
        incoming=fade_ms if fade_in_ms is None else fade_in_ms
        for duration in (incoming,outgoing):
            if isinstance(duration,bool) or not isinstance(duration,int) or not 0<=duration<=60000:raise ValueError('Invalid stream fade')
        from backend.game_engine_audio_archive import ArchiveAudioSource
        if not isinstance(path,ArchiveAudioSource):
            path=Path(path).resolve()
            if not path.is_file():raise ValueError('Audio file missing')
        pair=self.PAIRS[channel]
        previous=self.current.get(channel);last=self.last.get(channel);identity=pair[1] if last==pair[0] else pair[0]
        if identity in self.streams:
            old=self.streams[identity]
            if self.audio.stream_active(identity)>=0:self.audio.fade(old.voice,0,15,True)
            old.close(stop_voice=False);old.ended=True
            # Rapid requests wait for the 15 ms stop before reusing a ring.
            self.pending[channel]=(path,gain,incoming,outgoing,loop);return False
        fade_in=incoming if previous is not None or fade_in_ms is not None else 0
        stream=AudioFileStream(self.audio,identity,path,gain=0 if fade_in else gain,bus=2 if channel=='ambience' else 1,loop=loop)
        if previous in self.streams and self.audio.stream_active(previous)>=0:self.audio.fade(self.streams[previous].voice,0,outgoing,True)
        if fade_in:self.audio.fade(stream.voice,gain,fade_in)
        self.streams[identity]=stream;self.current[channel]=identity;self.last[channel]=identity
        if self.paused.get(channel):self.audio.pause(stream.voice,True)
        return True
    def pump(self):
        for identity,stream in list(self.streams.items()):
            if self.audio.stream_active(identity)<0:stream.close();del self.streams[identity]
            else:
                try:stream.pump()
                except (OSError,RuntimeError) as exc:
                    self.errors=(self.errors+['Music decode: '+str(exc)[:200]])[-16:]
                    stream.close(stop_voice=False);stream.ended=True;self.audio.fade(stream.voice,0,15,True)
        for channel,(path,gain,ms,out_ms,loop) in list(self.pending.items()):
            pair=self.PAIRS[channel]
            identity=pair[1] if self.last.get(channel)==pair[0] else pair[0]
            if identity not in self.streams:
                del self.pending[channel]
                self.play(path,channel,gain,loop=loop,fade_in_ms=ms,fade_out_ms=out_ms)
    def active(self,channel):
        identity=self.current.get(channel)
        return identity in self.streams and self.audio.stream_active(identity)>=0
    def pinned_paths(self):
        return {s.path for s in self.streams.values()}|{row[0] for row in self.pending.values()}
    def pause(self,channel,paused=True):
        self.paused[channel]=bool(paused)
        identity=self.current.get(channel)
        if identity in self.streams and self.audio.stream_active(identity)>=0:self.audio.pause(self.streams[identity].voice,paused)
    def stop(self,channel='lua',fade_ms=500):
        self.pending.pop(channel,None)
        self.paused.pop(channel,None)
        identity=self.current.pop(channel,None)
        if identity in self.streams and self.audio.stream_active(identity)>=0:self.audio.fade(self.streams[identity].voice,0,fade_ms,True)
    def close(self):
        for stream in self.streams.values():stream.close()
        self.streams.clear()
        self.pending.clear();self.current.clear();self.last.clear();self.paused.clear()
