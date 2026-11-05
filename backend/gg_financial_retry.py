"""Finite owned recovery worker; no network, keys or threads at import.

The callback must use independently certified creator selection. Queue ACKs
never finish a job. No retries survive stop; cold resume is an explicit action.
"""
from copy import deepcopy
import re
import threading
import time

MAX_ATTEMPTS=16
MAX_SECONDS=180
TRANSIENT=frozenset(('GG_FINANCIAL_PROOF_UNAVAILABLE','GG_FINANCIAL_SUBMISSION_UNAVAILABLE',
    'GG_FINANCIAL_PRODUCER_STALE_CONTEXT','GG_DAG_RESOURCE_PAUSED','GG_FINANCIAL_PRODUCER_BUSY','GG_SDK_SUBMISSION_DEADLINE'))


class OwnedFinancialRetry:
    def __init__(self,step,*,attempts=MAX_ATTEMPTS,seconds=MAX_SECONDS,delay=2):
        if type(attempts) is not int or not 1<=attempts<=MAX_ATTEMPTS or not 0<seconds<=MAX_SECONDS or not 0<delay<=8:
            raise ValueError('GG_FINANCIAL_RETRY_LIMIT')
        self.step=step;self.attempts=attempts;self.seconds=seconds;self.delay=delay
        self.lock=threading.Lock();self.worker=None;self.cancel=None
        self.state={'state':'IDLE','worker_active':False,'attempts':0,'SDK_selected':False,
                    'payments_executed_asserted':False,'max_attempts':attempts,'max_seconds':seconds}

    def start(self,index):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():raise ValueError('GG_FINANCIAL_PRODUCER_BUSY')
            cancel=threading.Event();self.cancel=cancel
            self.state={'state':'RETRYING','worker_active':True,'attempts':0,'producer_index':index,'SDK_selected':False,
                        'payments_executed_asserted':False,'max_attempts':self.attempts,'max_seconds':self.seconds}
            self.worker=threading.Thread(target=self._run,args=(index,cancel),name='GG-financial-owned-retry',daemon=True)
            self.worker.start()

    def _run(self,index,cancel):
        deadline=time.monotonic()+self.seconds;finish='EXHAUSTED';error=''
        def check():
            if cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if time.monotonic()>=deadline:raise ValueError('GG_FINANCIAL_RETRY_EXHAUSTED')
        try:
            for number in range(1,self.attempts+1):
                check()
                with self.lock:self.state.update(attempts=number,state='RETRYING')
                try:
                    result=self.step(index,check,cancel,deadline)
                    check()
                    if result.get('state') not in ('IDLE','SELECTED','QUEUED','BUSY','UNAVAILABLE'):
                        raise ValueError('GG_FINANCIAL_RETRY_RESULT')
                    with self.lock:
                        self.state.update(pending_blocks=result.get('pending_blocks'),pending_payments=result.get('pending_payments'))
                    if result['state'] in ('IDLE','SELECTED'):finish=result['state'];break
                    error='';wait=self.delay if result['state']=='QUEUED' else min(8,self.delay*number)
                except OSError:
                    error='GG_FINANCIAL_RETRY_IO';wait=min(8,self.delay*number)
                except ValueError as exc:
                    if str(exc) not in TRANSIENT:raise
                    error=str(exc);wait=min(8,self.delay*number)
                if number<self.attempts:cancel.wait(min(wait,max(0,deadline-time.monotonic())))
        except ValueError as exc:
            error=str(exc) if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',str(exc)) else 'GG_FINANCIAL_RETRY_FAILED'
            finish='STOPPED' if error=='GG_LAN_STOPPED' else 'EXHAUSTED' if error=='GG_FINANCIAL_RETRY_EXHAUSTED' else 'FAULT'
        except Exception:
            finish='FAULT';error='GG_FINANCIAL_RETRY_FAILED'
        finally:
            with self.lock:self.state.update(state=finish,worker_active=False,SDK_selected=finish=='SELECTED',last_error=error)

    def snapshot(self):
        with self.lock:return deepcopy(self.state)

    def stop(self):
        with self.lock:
            if self.cancel is not None:self.cancel.set()

    def close(self):
        self.stop()
        with self.lock:worker=self.worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(10)
            if worker.is_alive():raise ValueError('GG_FINANCIAL_PRODUCER_STOP_TIMEOUT')
