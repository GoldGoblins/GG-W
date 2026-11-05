"""Explicit account-payment relay through an opted-in owned producer.

The existing producer-original submission channel keeps its authorization.
This separate channel carries only public account-signed documents. Queue
receipts and remote producer reports are never monetary execution evidence.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import re
import time

from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_parallel_dag import pack
from backend.gg_segmented_submission import SegmentedSubmissions,HASH

STATUS='ACCOUNT_RELAY_STATUS'
STATUS_ACK='ACCOUNT_RELAY_STATUS_ACK'
RESULT_FIELDS={'state','producer_index','blocks','original_durable','error'}
RESULT_STATES={'QUEUED','UNAVAILABLE','BUSY','REJECTED','NONCE_CONSUMED_OUTCOME_UNRESOLVED'}


class AccountPaymentRelay(SegmentedSubmissions):
    operation='ACCOUNT_PAYMENT_RELAY'
    acknowledgement='ACCOUNT_PAYMENT_RELAY_ACK'
    max_raw=wire.MAX_RAW
    max_queue_bytes=2*wire.MAX_RAW

    def __init__(self,service):
        self.service=service;self._enabled=False;self._index=None;self._block_size=5000
        self._requests=OrderedDict();self._outbound=OrderedDict();self._send_turn=0
        super().__init__(service.peer,lambda:())

    def _authorize(self,actor):
        if actor not in self.peer._roster:raise ValueError('GG_ACCOUNT_RELAY_UNKNOWN_PEER')
        if self.peer._roster[actor].get('node_role','producer') not in ('producer','replica','light'):
            raise ValueError('GG_ACCOUNT_RELAY_PEER_ROLE')

    def _sources(self):
        with self.lock:enabled=self._enabled
        return (self.service,) if enabled and not self.cancel.is_set() and not self.service._fault and not self.peer._cancel.is_set() else ()

    def enable(self,index=None,transactions_per_block=5000):
        if self.service.anchor['genesis']['schema']!='gg.native.genesis.v6':raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
        index=self.service._producer_index(index)
        if type(transactions_per_block) is not int or not 1<=transactions_per_block<=wire.MAX_PAYMENTS:raise ValueError('GG_ACCOUNT_RELAY_BLOCK_SIZE')
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self.actors or self.receiving:raise ValueError('GG_ACCOUNT_RELAY_BUSY')
            self._index=index;self._block_size=transactions_per_block;self._enabled=True
        return self.snapshot()

    def disable(self):
        # An already executing producer operation retains its own durable
        # originals/retry owner. Disable prevents new queue admission.
        with self.lock:self._enabled=False
        return self.snapshot()

    def enqueue(self,actor,raw,identifier,lease):
        self._authorize(actor)
        if not isinstance(raw,bytes) or not 0<len(raw)<=self.max_raw or hashlib.sha256(raw).hexdigest()!=identifier:
            raise ValueError('GG_SDK_SUBMISSION_INTEGRITY')
        with self.lock:
            if identifier in self.results or identifier in self._requests and self._requests[identifier] in self.actors:
                # The receive/local caller relinquishes its reservation on a
                # QUEUED receipt. A duplicate adopts no new queue item.
                lease.__exit__(None,None,None)
                return self._receipt('QUEUED',identifier)
            result=super().enqueue(actor,raw,identifier,lease)
            if result['state']=='QUEUED':
                self._requests[identifier]=actor;self._requests.move_to_end(identifier)
                while len(self._requests)>64:self._requests.popitem(last=False)
            return result

    def _submit(self,service,actor,raw):
        with self.lock:index=self._index;block_size=self._block_size;enabled=self._enabled
        result={'state':'UNAVAILABLE','producer_index':index,'blocks':[],'original_durable':False,'error':''}
        if not enabled:return result
        def check():
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            service.context.check()
        try:
            check();values=wire.decode_payment_document(raw,service.anchor,authenticated=True)
            rows=values.rows();sender=rows[0]['body']['sender'];nonce=int(rows[0]['body']['nonce'])
            if any(row['body']['sender']!=sender or int(row['body']['nonce'])!=nonce+offset for offset,row in enumerate(rows)):
                raise ValueError('GG_ACCOUNT_RELAY_SINGLE_CONTIGUOUS_ACCOUNT_REQUIRED')
            packet=service.requested_proof('account',sender,check=check,cancel=self.cancel,deadline=time.monotonic()+20)
            verified=financial.verify_account(packet,service.anchor,sender,binary=service.verifier.binary,stamp=service.verifier.stamp)
            account=verified['financial_account']
            if not verified['financial_account_exists']:raise ValueError('GG_ACCOUNT_RELAY_UNFUNDED_ACCOUNT')
            current=int(account['nonce']);trim=max(0,current-nonce)
            if trim>=len(values):return {**result,'state':'NONCE_CONSUMED_OUTCOME_UNRESOLVED'}
            if nonce+trim!=current:raise ValueError('GG_ACCOUNT_RELAY_NONCE_GAP')
            if sum(int(row['body']['amount_atomic'])+int(row['body'].get('max_fee_atomic','0')) for row in rows[trim:])>int(account['balance_atomic']):
                raise ValueError('GG_ACCOUNT_RELAY_INSUFFICIENT_CERTIFIED_FUNDS')
            remaining=values if trim==0 else values.suffix(trim)
            submitted=service.submit_signed(remaining,index,transactions_per_block=block_size)
            return {**result,'state':submitted['state'],'blocks':submitted['blocks'],'original_durable':submitted['original_durable']}
        except (ValueError,OSError) as error:
            code=str(error)
            return {**result,'state':'BUSY' if code=='GG_FINANCIAL_PRODUCER_BUSY' else 'REJECTED',
                    'error':code if re.fullmatch(r'GG_[A-Z0-9_]{1,96}',code) else 'GG_ACCOUNT_RELAY_UNAVAILABLE'}

    def reply_status(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'hash'} or type(payload['hash']) is not str or not HASH.fullmatch(payload['hash']):
            raise ValueError('GG_ACCOUNT_RELAY_STATUS_REQUEST')
        identifier=payload['hash']
        with self.lock:
            result=deepcopy(self.results.get(identifier));actor=self._requests.get(identifier)
            if result is not None and set(result)!=RESULT_FIELDS:
                result={'state':'UNAVAILABLE','producer_index':self._index,'blocks':[],'original_durable':False,'error':''}
            state='READY' if result is not None else 'WAIT' if actor in self.actors else 'UNAVAILABLE'
        return {'state':state,'hash':identifier,'result':result,'SDK_selected':False}

    def _query_status(self,owner,identifier,deadline):
        from backend.gg_lan_dag import MAX_FRAME,CONNECTION_SECONDS,_send
        def check():
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if time.monotonic()>=deadline:raise ValueError('GG_ACCOUNT_RELAY_DEADLINE')
        check();self.peer._pace_connection(owner,'INCOMING',cancel=self.cancel,deadline=deadline)
        with self.peer._connection(owner,deadline=deadline,cancel=self.cancel) as sock:
            session=self.peer._client_auth(sock,owner,min(deadline,time.monotonic()+CONNECTION_SECONDS),check=check)
            self.peer._credit('out:'+owner,_send(sock,self.peer._frame(session,0,STATUS,{'hash':identifier}),MAX_FRAME,deadline=deadline))
            value,size=self.peer._read(sock,MAX_FRAME,deadline=deadline,check=check)
            body=self.peer._check_frame(value,size,owner,session,0);reply=body['payload']
            if (body['kind']!=STATUS_ACK or not isinstance(reply,dict) or set(reply)!={'state','hash','result','SDK_selected'}
                    or reply['hash']!=identifier or reply['SDK_selected'] is not False or reply['state'] not in ('READY','WAIT','UNAVAILABLE')):
                raise ValueError('GG_ACCOUNT_RELAY_STATUS_RESPONSE')
            result=reply['result']
            if reply['state']=='READY':
                if (not isinstance(result,dict) or set(result)!=RESULT_FIELDS or result['state'] not in RESULT_STATES
                        or type(result['producer_index']) is not int or result['producer_index'] not in self.peer._roster[owner]['producer_indices']
                        or type(result['original_durable']) is not bool or not isinstance(result['blocks'],list) or len(result['blocks'])>wire.MAX_OWN_PIPELINE
                        or any(type(item) is not str or not HASH.fullmatch(item) for item in result['blocks'])
                        or type(result['error']) is not str or len(result['error'])>96):raise ValueError('GG_ACCOUNT_RELAY_STATUS_RESPONSE')
            elif result is not None:raise ValueError('GG_ACCOUNT_RELAY_STATUS_RESPONSE')
            return reply

    def submit_document(self,raw,owner=None):
        if self.service.anchor['genesis']['schema']!='gg.native.genesis.v6':raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
        # Local originals are authenticated before transport. Receiving peers
        # authenticate them again and native consensus validates execution.
        wire.decode_payment_document(raw,self.service.anchor,authenticated=True)
        eligible=sorted(key for key,row in self.peer._roster.items() if key!=self.peer.public_key and row.get('node_role','producer')=='producer')
        if owner is not None:
            if type(owner) is not str or owner not in eligible:raise ValueError('GG_ACCOUNT_RELAY_PRODUCER_PEER')
            eligible=[owner]
        if not eligible:raise ValueError('GG_ACCOUNT_RELAY_NO_PRODUCER')
        turn=self._send_turn%len(eligible);self._send_turn+=1;eligible=eligible[turn:]+eligible[:turn]
        identifier=hashlib.sha256(raw).hexdigest();deadline=time.monotonic()+30
        last={'state':'UNAVAILABLE','hash':identifier,'SDK_selected':False}
        for target in eligible:
            if time.monotonic()>=deadline:break
            try:
                ack=self.send(target,raw,deadline=min(deadline,time.monotonic()+20));last=ack
                if ack['state']!='QUEUED':continue
                reply={'state':'WAIT','result':None}
                for attempt in range(12):
                    if time.monotonic()>=deadline or self.cancel.is_set() or self.peer._cancel.is_set():break
                    try:reply=self._query_status(target,identifier,deadline)
                    except OSError:break
                    except ValueError as error:
                        if str(error) not in ('GG_ACCOUNT_RELAY_DEADLINE','GG_LAN_TIMEOUT','GG_LAN_STOPPED'):raise
                        break
                    if reply['state']!='WAIT':break
                    self.cancel.wait(min(.5,max(0,deadline-time.monotonic())))
                result={'state':'RELAY_'+reply['state'],'relay_peer':target,'relay_request':identifier,
                        'relay_transport_accepted':True,'producer_report':reply['result'],
                        'producer_report_is_execution_evidence':False,'SDK_selected':False,'payments_executed_asserted':False}
                with self.lock:
                    self._outbound[identifier]=deepcopy(result);self._outbound.move_to_end(identifier)
                    while len(self._outbound)>16:self._outbound.popitem(last=False)
                return result
            except OSError:continue
        return {'state':'RELAY_'+last['state'],'relay_request':identifier,'relay_transport_accepted':False,
                'producer_report':None,'producer_report_is_execution_evidence':False,'SDK_selected':False,'payments_executed_asserted':False}

    def snapshot(self):
        result=super().snapshot()
        with self.lock:result.update(enabled=self._enabled,producer_index=self._index,transactions_per_block=self._block_size,
                                    outbound=deepcopy(list(self._outbound.values())))
        return {**result,'scope':'ACCOUNT_SIGNED_PUBLIC_DOCUMENT_RELAY','account_signer_access':False,'validator_signing':False,
                'queue_receipt_is_execution_evidence':False,'enablement_persisted':False}

    def telemetry_revision(self):
        with self.lock:
            return (self._enabled,self._index,self._block_size,len(self.actors),len(self.receiving),self.bytes,
                    len(self.results),next(reversed(self.results),None),self.last_error,
                    tuple((key,row['state']) for key,row in self._outbound.items()))
