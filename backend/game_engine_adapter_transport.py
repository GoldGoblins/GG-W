"""Bounded request transport shared by the native UI and format workers."""
from __future__ import annotations
import json,os,queue,subprocess,threading,time,weakref
from backend.platform_process import background_options
from backend.platform_support import terminate_process_tree
MAX_MESSAGE=16*1024*1024
def stop_worker(process):
    if process.poll() is None:
        if os.name=='nt':terminate_process_tree(process.pid,force=True)
        else:process.terminate()
        try:process.wait(timeout=.3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
    for pipe in (process.stdin,process.stdout,process.stderr):
        if pipe:pipe.close()
class BoundedWorker:
    def _start_worker(self,command,env):
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,bufsize=0,**background_options())
        self._finalizer=weakref.finalize(self,stop_worker,self.process);self._lock=threading.Lock();self._pending=b'';self.closed=False
        self._requests=queue.Queue(maxsize=1);self._responses=queue.Queue(maxsize=1)
        # Pipe handles cannot be passed to Windows select(). Persistent IO
        # threads keep the same deadlines and byte bounds without one thread
        # pair per request. Threads own no worker object/finalizer references.
        process=self.process;requests=self._requests;responses=self._responses
        def emit(value):
            try:responses.put(value,timeout=1)
            except queue.Full:pass
        def read():
            pending=bytearray()
            try:
                while True:
                    chunk=os.read(process.stdout.fileno(),65536)
                    if not chunk:raise RuntimeError('Native worker exited')
                    pending.extend(chunk)
                    if len(pending)>MAX_MESSAGE:raise TimeoutError('Native response capacity exceeded')
                    while b'\n' in pending:
                        line,_,tail=pending.partition(b'\n');pending=bytearray(tail)
                        responses.put(bytes(line),timeout=1)
            except (OSError,ValueError,RuntimeError,TimeoutError,queue.Full) as exc:emit(exc)
        def write():
            while True:
                item=requests.get()
                if item is None:return
                packet,done,errors=item
                try:
                    at=0
                    while at<len(packet):
                        count=os.write(process.stdin.fileno(),packet[at:at+65536])
                        if count<=0:raise BrokenPipeError()
                        at+=count
                except (OSError,ValueError) as exc:errors.append(exc)
                finally:done.set()
        self._read_thread=threading.Thread(target=read,daemon=True);self._read_thread.start()
        self._write_thread=threading.Thread(target=write,daemon=True);self._write_thread.start()
    def request(self,op,*,timeout=.3,**kwargs):
        with self._lock:
            if self.closed:raise RuntimeError('Native worker stopped')
            if self.process.poll() is not None:self.close();raise RuntimeError('Native worker stopped')
            packet=json.dumps({'op':op,**kwargs},ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()+b'\n'
            if len(packet)>MAX_MESSAGE:raise ValueError('Native message capacity exceeded')
            if timeout<=0:raise ValueError('Invalid native worker deadline')
            deadline=time.monotonic()+timeout;done=threading.Event();errors=[]
            self._requests.put_nowait((packet,done,errors))
            if not done.wait(max(0,deadline-time.monotonic())):return self._timeout('Native worker exceeded its time budget: '+op)
            if errors:self.close();raise RuntimeError('Native worker stopped') from None
            try:line=self._responses.get(timeout=max(0,deadline-time.monotonic()))
            except queue.Empty:return self._timeout('Native worker exceeded its time budget: '+op)
            if isinstance(line,Exception):self.close();raise line
            try:answer=json.loads(line)
            except (ValueError,UnicodeError):self.close();raise RuntimeError('Invalid native worker response') from None
            if not answer['ok']:raise ValueError(answer.get('error','Native worker error'))
            return answer.get('result')
    def _timeout(self,message='Native worker exceeded its time budget'):
        self.close();raise TimeoutError(message)
    def close(self):
        if self.closed:return
        self.closed=True;self._finalizer()
        try:self._requests.put_nowait(None)
        except queue.Full:pass
