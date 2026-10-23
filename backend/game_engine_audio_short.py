"""Bounded, nonblocking short-file decoding into the native stereo clip mixer."""
import array,math,os,shutil,struct,subprocess,time,weakref
from collections import OrderedDict
from pathlib import Path
from backend.game_engine_audio_stream import stop,DECODER_ADDRESS_LIMIT
MAX_BYTES=192000*10*2*4
class Decode:
    def __init__(self,path):
        ffmpeg=shutil.which('ffmpeg');limit=shutil.which('prlimit')
        if not ffmpeg or not limit:raise RuntimeError('Bounded audio decoder unavailable')
        path=Path(path).resolve()
        self.path=path
        if not path.is_file() or path.stat().st_size>16*1024*1024 or path.suffix.casefold() not in ('.wav','.mp3','.ogg'):raise ValueError('Unsupported short audio asset')
        command=[limit,'--as='+str(DECODER_ADDRESS_LIMIT),'--cpu=10','--core=0','--',ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-cpucount','1','-threads','1','-filter_threads','1','-filter_complex_threads','1','-protocol_whitelist','file,pipe','-format_whitelist','wav,mp3,ogg','-i',str(path),'-t','10.001','-vn','-sn','-dn','-threads','1','-c:a','pcm_f32le','-f','wav','-ac','2','pipe:1']
        env={**os.environ,'OMP_NUM_THREADS':'1','OMP_THREAD_LIMIT':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','MALLOC_ARENA_MAX':'2'}
        self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,env=env)
        os.set_blocking(self.process.stdout.fileno(),False);self._finalizer=weakref.finalize(self,stop,self.process)
        os.set_blocking(self.process.stderr.fileno(),False);self.diagnostic=b''
        self.data=bytearray();self.header=False;self.rate=None;self.deadline=time.monotonic()+5
    def pump(self):
        if time.monotonic()>self.deadline:raise TimeoutError('Short audio decoder deadline exceeded')
        try:self.diagnostic=(self.diagnostic+os.read(self.process.stderr.fileno(),4096))[-4096:]
        except BlockingIOError:pass
        try:chunk=os.read(self.process.stdout.fileno(),65536)
        except BlockingIOError:return None
        if chunk:
            if len(self.data)+len(chunk)>MAX_BYTES:raise ValueError('Short audio exceeds ten seconds')
            self.data.extend(chunk)
            if not self.header:
                if len(self.data)<12:return None
                if self.data[:4]!=b'RIFF' or self.data[8:12]!=b'WAVE':raise ValueError('Invalid decoded WAV stream')
                at=12
                while at+8<=len(self.data):
                    tag=bytes(self.data[at:at+4]);length=struct.unpack_from('<I',self.data,at+4)[0]
                    if tag==b'data':
                        if self.rate is None:raise ValueError('Decoded WAV format missing')
                        del self.data[:at+8];self.header=True;break
                    if at+8+length>4096:raise ValueError('Decoded WAV header capacity exceeded')
                    if at+8+length>len(self.data):break
                    if tag==b'fmt ':
                        if length<16:raise ValueError('Truncated decoded WAV format')
                        code,channels,rate=struct.unpack_from('<HHI',self.data,at+8)
                        bits=struct.unpack_from('<H',self.data,at+22)[0]
                        if code==65534 and length>=40:code=struct.unpack_from('<H',self.data,at+32)[0]
                        if code!=3 or channels!=2 or bits!=32 or not 8000<=rate<=192000:raise ValueError('Invalid decoded sound format')
                        self.rate=rate
                    at+=8+length+(length%2)
            if self.header and len(self.data)>self.rate*10*8:raise ValueError('Short audio exceeds ten seconds')
            return None
        if self.process.poll() is None:return None
        if self.process.returncode or not self.header or not self.data or len(self.data)%8:raise ValueError('Short audio decoding failed: '+self.diagnostic.decode('utf-8','replace')[-200:])
        values=array.array('f');values.frombytes(self.data)
        if any(not math.isfinite(x) for x in values):raise ValueError('Non-finite decoded audio')
        # Floating-point codecs may have small intersample overshoots; native clips
        # require finite samples in [-1,1]. Keep stereo channel order intact.
        for i,x in enumerate(values):values[i]=max(-1,min(1,x))
        self.close();return values
    def close(self):self._finalizer()

class ShortSounds:
    def __init__(self,audio):self.audio=audio;self.loaded=OrderedDict();self.pending={};self.errors=[];self.voices={};self.owned={};self.closed=False;self.free_ids=set(range(8,32));self.reserved={};self.costs={};self.bytes=0
    def _evict(self):
        key=next((k for k,(identity,rate) in self.loaded.items() if not self.audio.clip_active(identity)),None)
        if key is None:raise ValueError('Short sound cache is full of active clips')
        identity,_=self.loaded.pop(key);self.audio.release_clip(identity);self.free_ids.add(identity);self.bytes-=self.costs.pop(key,0)
    def play(self,path,*,gain=.5,bus=0,loop=False,pitch=1,frequency=None,unique=None,position=None,near=2,far=60,reverb=False):
        if self.closed:raise RuntimeError('Short sound player closed')
        path=Path(path).resolve();stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
        options={'gain':gain,'bus':bus,'loop':loop,'pitch':pitch,'frequency':frequency,'position':position,'near':near,'far':far,'reverb':reverb};request=(options,unique)
        if unique and unique in self.voices:
            voice,token=self.voices[unique]
            if self.audio.voice_token(voice)==token:return
        if unique and any(u==unique for decoder,queue in self.pending.values() for o,u in queue):return
        if key in self.loaded:self.loaded.move_to_end(key);self._play(self.loaded[key],request);return
        if key in self.pending:
            # Up to eight plays can share a decode; unique kits merge their request.
            queue=self.pending[key][1]
            if unique and any(u==unique for o,u in queue):return
            if len(queue)>=8:raise ValueError('Pending sound play capacity exceeded')
            queue.append(request);return
        if len(self.pending)>=4:raise ValueError('Short sound decode capacity exceeded')
        if not self.free_ids:self._evict()
        decoder=Decode(path);identity=min(self.free_ids);self.free_ids.remove(identity);self.reserved[key]=identity
        self.pending[key]=(decoder,[request])
    def _play(self,identity,request):
        options,unique=request;options=dict(options);frequency=options.pop('frequency');identity,rate=identity
        if frequency is not None:options['pitch']=frequency/rate
        voice=self.audio.play(identity,**options)
        if voice<0:raise ValueError('Native sound voice capacity exceeded')
        token=self.audio.voice_token(voice);self.owned[voice]=token
        if unique:self.voices[unique]=(voice,token)
    def move(self,unique,position):
        if self.closed:return False
        voice=self.voices.get(unique)
        if voice and self.audio.voice_token(voice[0])==voice[1]:
            self.audio.move_voice(*voice,position);return True
        # A decoded voice must start at the newest source, not its old IO position.
        for decoder,queue in self.pending.values():
            for options,key in queue:
                if key==unique:options['position']=list(position)
        return False
    def stop(self,unique,fade_ms=0):
        if self.closed:return
        for decoder,queue in self.pending.values():queue[:]=[(o,k) for o,k in queue if k!=unique]
        voice=self.voices.pop(unique,None)
        if voice and self.audio.voice_token(voice[0])==voice[1]:
            if fade_ms:self.audio.fade(voice[0],0,fade_ms,True)
            else:self.audio.stop_voice(*voice)
    def has(self,unique):
        voice=self.voices.get(unique)
        return bool(voice and self.audio.voice_token(voice[0])==voice[1]) or any(k==unique for decoder,queue in self.pending.values() for o,k in queue)
    def pump(self):
        for key,(decoder,queue) in list(self.pending.items()):
            try:
                values=decoder.pump()
                if values is None:continue
                cost=len(values)*values.itemsize
                while self.bytes+cost>56*1024*1024:self._evict()
                identity=self.reserved[key];self.audio.clip(identity,values,decoder.rate,channels=2);self.reserved.pop(key);self.loaded[key]=(identity,decoder.rate);self.costs[key]=cost;self.bytes+=cost
                del self.pending[key]
                for request in queue:self._play(self.loaded[key],request)
            except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
                decoder.close();self.pending.pop(key,None);self.errors=(self.errors+[str(exc)[:200]])[-16:]
                identity=self.reserved.pop(key,None)
                if identity is not None:self.free_ids.add(identity)
        for key,(voice,token) in list(self.voices.items()):
            if self.audio.voice_token(voice)!=token:self.voices.pop(key,None)
    def close(self):
        if self.closed:return
        self.closed=True
        for decoder,queue in self.pending.values():decoder.close()
        self.pending.clear()
        for voice,token in self.owned.items():
            self.audio.stop_voice(voice,token)
        for identity,rate in self.loaded.values():
            if not self.audio.clip_active(identity):self.audio.release_clip(identity)
        self.loaded.clear();self.costs.clear();self.bytes=0;self.reserved.clear();self.free_ids=set(range(8,32))
        self.owned.clear();self.voices.clear()
