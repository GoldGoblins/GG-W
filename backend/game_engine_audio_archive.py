"""Bounded original MPQ sectors feeding a local decoder with pipe backpressure."""
from dataclasses import dataclass
from pathlib import Path
from queue import Queue,Empty
from threading import Event,Thread
from backend.game_engine_adapter_assets import asset_path
from backend.game_engine_adapter_formats import NativeFormats

@dataclass(frozen=True)
class ArchiveAudioSource:
    directory:Path
    entry:str
    size:int
    def __post_init__(self):
        directory=asset_path(str(self.directory));object.__setattr__(self,'directory',directory)
        if not directory.is_dir() or not isinstance(self.entry,str) or not 0<len(self.entry)<=512 or self.entry.rsplit('.',1)[-1].lower() not in ('wav','mp3','ogg'):raise ValueError('Invalid archive audio source')
        if isinstance(self.size,bool) or not isinstance(self.size,int) or not 0<self.size<=512*1024*1024:raise ValueError('Invalid archive audio size')
    def __str__(self):return self.entry

class ArchiveFeed:
    def __init__(self,source,stop_process):
        self.source=source;self.stop_process=stop_process;self.stopped=Event();self.jobs=Queue(maxsize=1);self.process=None;self.error='';self.bytes_read=0;self.reads=0;self.loops=0
        self.thread=Thread(target=self._run,name='gg-mpq-audio',daemon=True);self.thread.start()
    def attach(self,process):
        self.process=process;self.jobs.put_nowait(process)
    def _run(self):
        reader=None
        try:
            reader=NativeFormats();reader.request('mount_chain',path=str(self.source.directory),timeout=3)
            opened=reader.request('archive_audio_open',entry=self.source.entry);identity=opened['id']
            if opened['size']!=self.source.size:raise ValueError('Archive audio source changed')
            while not self.stopped.is_set():
                try:process=self.jobs.get(timeout=.05)
                except Empty:continue
                position=0
                try:
                    while position<self.source.size and not self.stopped.is_set():
                        packet,data=NativeFormats._unpack(reader.request('archive_audio_read',id=identity,position=position,limit=65536,timeout=3))
                        if not data or packet['position']!=position+len(data):raise ValueError('Archive audio read stalled')
                        position=packet['position'];self.bytes_read+=len(data);self.reads+=1
                        remaining=memoryview(data)
                        while remaining and not self.stopped.is_set():
                            written=process.stdin.write(remaining[:16384])
                            if not written:raise OSError('Archive decoder pipe stalled')
                            remaining=remaining[written:]
                    self.loops+=position==self.source.size
                except BrokenPipeError:pass # The decoder owns its exit-status diagnostic.
                except OSError:
                    if process.poll() is None and not self.stopped.is_set():raise
                finally:
                    if process.stdin and not process.stdin.closed:process.stdin.close()
        except Exception as exc:
            if not self.stopped.is_set():
                self.error=str(exc)[:240]
                if self.process and self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        finally:
            if reader:reader.close()
    def close(self):
        self.stopped.set()
        if self.process:self.stop_process(self.process)
        self.thread.join(timeout=.25)
