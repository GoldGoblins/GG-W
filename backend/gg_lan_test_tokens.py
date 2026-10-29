"""Ephemeral test tokens ordered by one explicitly paired LAN coordinator.

This is a private test ledger, not DAG finality, a wallet or real assets. Each
peer owns its first producer RAM signer; domain separation distinguishes test
transfers from DAG proposals. All peers replay the coordinator's signed,
hash-chained receipts against exact balances and nonces.
"""
from __future__ import annotations

from copy import deepcopy
import re
import threading

from backend.gg_parallel_dag import digest, pack, _verify

ASSET='GG-LAN(TEST)'
DECIMALS=6
ALLOCATION_ATOMIC='1000000000'
MAX_TRANSFERS=4096
MAX_BATCH=16
_HEX=re.compile(r'^[0-9a-f]{64}$')
_SIG=re.compile(r'^[0-9a-f]{128}$')
_AMOUNT=re.compile(r'^[1-9][0-9]{0,18}$')
_TX=b'GG-LAN-TEST-TOKEN-TRANSFER-v1\0'
_RECEIPT=b'GG-LAN-TEST-TOKEN-RECEIPT-v1\0'


def _integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('GG_LAN_TOKEN_INTEGER')
    return value


def amount_atomic(value):
    if not isinstance(value,str) or not _AMOUNT.fullmatch(value) or int(value)>2**63-1:
        raise ValueError('GG_LAN_TOKEN_AMOUNT')
    return int(value)


def genesis(roster,coordinator):
    rows=sorted(({'peer_key':row['peer_key'],'account_key':row['producer_keys'][0]} for row in roster),key=lambda row:row['peer_key'])
    if (len(rows)!=3 or len({row['peer_key'] for row in rows})!=3 or coordinator not in {row['peer_key'] for row in rows}
            or any(not _HEX.fullmatch(str(row['peer_key'])) or not _HEX.fullmatch(str(row['account_key'])) for row in rows)
            or len({row['account_key'] for row in rows})!=3):raise ValueError('GG_LAN_TOKEN_ROSTER')
    return {'schema':'gg.lan-test-token.genesis.v1','asset':ASSET,'decimals':DECIMALS,
        'allocation_atomic':ALLOCATION_ATOMIC,'accounts':rows,'coordinator':coordinator,
        'authority':'SINGLE_PAIRED_COORDINATOR','financial_assets':False}


class TestTokenLedger:
    def __init__(self,network_id,descriptor,roster,coordinator,local_peer,local_signer,coordinator_signer=None):
        if not isinstance(network_id,str) or not _HEX.fullmatch(network_id):raise ValueError('GG_LAN_TOKEN_NETWORK')
        if descriptor!=genesis(roster,coordinator):raise ValueError('GG_LAN_TOKEN_GENESIS')
        self._network=network_id;self._descriptor=deepcopy(descriptor);self._coordinator=coordinator
        self._local=local_peer;self._signer=local_signer;self._authority=coordinator_signer
        self._accounts={row['peer_key']:row['account_key'] for row in descriptor['accounts']}
        self._labels={row['peer_key']:row['label'] for row in roster}
        if local_peer not in self._accounts or local_signer.pubkey().hex()!=self._accounts[local_peer]:raise ValueError('GG_LAN_TOKEN_OWN_SIGNER')
        if coordinator_signer is not None and (local_peer!=coordinator or coordinator_signer.pubkey().hex()!=coordinator):
            raise ValueError('GG_LAN_TOKEN_COORDINATOR_SIGNER')
        self._state={peer:{'balance_atomic':ALLOCATION_ATOMIC,'nonce':0} for peer in self._accounts}
        self._initial=digest({'network_id':network_id,'genesis':descriptor},b'GG-LAN-TEST-TOKEN-GENESIS-v1\0')
        self._head=self._initial;self._records=[];self._by_transaction={};self._lock=threading.RLock()

    def _root(self,state):
        return digest([{'peer_key':peer,'account_key':self._accounts[peer],**state[peer]} for peer in sorted(state)],b'GG-LAN-TEST-TOKEN-STATE-v1\0')

    def revision(self):
        with self._lock:return len(self._records)

    def status(self):
        with self._lock:return {'committed':len(self._records),'head':self._head,'state_root':self._root(self._state)}

    def head_at(self,sequence):
        _integer(sequence,0,MAX_TRANSFERS)
        with self._lock:
            if sequence>len(self._records):raise ValueError('GG_LAN_TOKEN_CURSOR')
            return self._initial if sequence==0 else digest(self._records[sequence-1]['body'],b'GG-LAN-TEST-TOKEN-RECEIPT-ID-v1\0')

    def snapshot(self):
        with self._lock:
            rows=[]
            for receipt in self._records[-8:]:
                body=receipt['body'];tx=body['transaction']['body']
                rows.append({'sequence':body['sequence'],'transaction_id':body['transaction_id'],
                    'sender_peer_key':tx['sender_peer_key'],'recipient_peer_key':tx['recipient_peer_key'],
                    'amount_atomic':tx['amount_atomic'],'state':'COORDINATOR_ORDERED_TEST_RECEIPT'})
            accounts=[{'peer_key':peer,'label':self._labels[peer],'account_key':self._accounts[peer],**self._state[peer]} for peer in sorted(self._state)]
            return {'enabled':True,'asset':ASSET,'symbol':ASSET,'decimals':DECIMALS,'authority':'SINGLE_PAIRED_COORDINATOR',
                'settlement':'SINGLE_PAIRED_COORDINATOR','accounts':accounts,'sequence':len(self._records),
                'coordinator':self._coordinator,'financial_assets':False,'dag_finality':False,
                'committed':len(self._records),'head':self._head,'state_root':self._root(self._state),
                'balances':deepcopy(accounts),
                'receipts':rows,'limits':{'max_transfers':MAX_TRANSFERS,'max_batch':MAX_BATCH},
                'scope':'PRIVATE_COORDINATOR_ORDERED_TEST_LEDGER'}

    def records(self,after,limit=MAX_BATCH):
        _integer(after,0,MAX_TRANSFERS);_integer(limit,1,MAX_BATCH)
        with self._lock:
            if after>len(self._records):raise ValueError('GG_LAN_TOKEN_CURSOR')
            return deepcopy(self._records[after:after+limit])

    def has_transaction(self,transaction):
        with self._lock:
            identifier=digest(transaction['body'],b'GG-LAN-TEST-TOKEN-TXID-v1\0')
            receipt=self._by_transaction.get(identifier)
            return receipt is not None and receipt['body']['transaction']==transaction

    def sign_batch(self,recipient_peer_key,amount,count=1,*,check=None):
        value=amount_atomic(amount);_integer(count,1,MAX_BATCH)
        with self._lock:
            if recipient_peer_key not in self._accounts or recipient_peer_key==self._local:raise ValueError('GG_LAN_TOKEN_RECIPIENT')
            source=self._state[self._local]
            if value*count>int(source['balance_atomic']):raise ValueError('GG_LAN_TOKEN_BALANCE')
            transactions=[]
            for offset in range(count):
                if check is not None:check()
                body={'schema':'gg.lan-test-token.transfer.v1','network_id':self._network,'asset':ASSET,
                    'sender_peer_key':self._local,'recipient_peer_key':recipient_peer_key,
                    'amount_atomic':amount,'nonce':source['nonce']+offset}
                transactions.append({'body':body,'signature':self._signer.sign_message(_TX+pack(body)).hex()})
            if check is not None:check()
            return transactions

    def _transaction(self,transaction):
        if not isinstance(transaction,dict) or set(transaction)!={'body','signature'} or len(pack(transaction))>2048:
            raise ValueError('GG_LAN_TOKEN_TRANSACTION')
        body=transaction['body'];signature=transaction['signature']
        expected={'schema','network_id','asset','sender_peer_key','recipient_peer_key','amount_atomic','nonce'}
        if (not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.lan-test-token.transfer.v1'
                or body.get('network_id')!=self._network or body.get('asset')!=ASSET):raise ValueError('GG_LAN_TOKEN_DOMAIN')
        source,target=body['sender_peer_key'],body['recipient_peer_key']
        if not isinstance(source,str) or not isinstance(target,str) or source not in self._accounts or target not in self._accounts or source==target:
            raise ValueError('GG_LAN_TOKEN_ACCOUNT')
        amount=amount_atomic(body['amount_atomic']);_integer(body['nonce'],0,MAX_TRANSFERS)
        if not isinstance(signature,str) or not _SIG.fullmatch(signature):raise ValueError('GG_LAN_TOKEN_SIGNATURE')
        _verify(self._accounts[source],_TX+pack(body),signature)
        return body,amount,digest(body,b'GG-LAN-TEST-TOKEN-TXID-v1\0')

    @staticmethod
    def _execute(state,body,amount):
        source=state[body['sender_peer_key']];target=state[body['recipient_peer_key']]
        if source['nonce']!=body['nonce']:raise ValueError('GG_LAN_TOKEN_NONCE')
        if int(source['balance_atomic'])<amount:raise ValueError('GG_LAN_TOKEN_BALANCE')
        source['balance_atomic']=str(int(source['balance_atomic'])-amount);source['nonce']+=1
        target['balance_atomic']=str(int(target['balance_atomic'])+amount)

    def commit_batch(self,transactions,*,check=None):
        if self._authority is None:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
        if not isinstance(transactions,list) or not 1<=len(transactions)<=MAX_BATCH:raise ValueError('GG_LAN_TOKEN_BATCH')
        with self._lock:
            state=deepcopy(self._state);records=[];returned=[];head=self._head;new_ids={}
            for transaction in transactions:
                if check is not None:check()
                body,amount,identifier=self._transaction(transaction)
                previous=self._by_transaction.get(identifier) or new_ids.get(identifier)
                if previous is not None:
                    if previous['body']['transaction']!=transaction:raise ValueError('GG_LAN_TOKEN_CHANGED_DUPLICATE')
                    returned.append(deepcopy(previous));continue
                if len(self._records)+len(records)>=MAX_TRANSFERS:raise ValueError('GG_LAN_TOKEN_RECORD_LIMIT')
                self._execute(state,body,amount)
                receipt_body={'schema':'gg.lan-test-token.receipt.v1','network_id':self._network,
                    'sequence':len(self._records)+len(records)+1,'previous':head,'transaction_id':identifier,
                    'transaction':deepcopy(transaction),'state_root':self._root(state)}
                receipt={'body':receipt_body,'signature':self._authority.sign_message(_RECEIPT+pack(receipt_body)).hex()}
                head=digest(receipt_body,b'GG-LAN-TEST-TOKEN-RECEIPT-ID-v1\0')
                records.append(receipt);returned.append(deepcopy(receipt));new_ids[identifier]=receipt
            if check is not None:check()
            self._state=state;self._records.extend(records);self._by_transaction.update(new_ids);self._head=head
            return returned

    def apply_receipts(self,receipts):
        if not isinstance(receipts,list) or len(receipts)>MAX_BATCH:raise ValueError('GG_LAN_TOKEN_BATCH')
        with self._lock:
            state=deepcopy(self._state);records=[];head=self._head;new_ids={}
            for receipt in receipts:
                if not isinstance(receipt,dict) or set(receipt)!={'body','signature'} or len(pack(receipt))>4096:
                    raise ValueError('GG_LAN_TOKEN_RECEIPT')
                body=receipt['body'];signature=receipt['signature']
                expected={'schema','network_id','sequence','previous','transaction_id','transaction','state_root'}
                if (not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.lan-test-token.receipt.v1'
                        or body.get('network_id')!=self._network):raise ValueError('GG_LAN_TOKEN_RECEIPT_DOMAIN')
                sequence=_integer(body['sequence'],1,MAX_TRANSFERS)
                if not isinstance(signature,str) or not _SIG.fullmatch(signature):raise ValueError('GG_LAN_TOKEN_RECEIPT_SIGNATURE')
                _verify(self._coordinator,_RECEIPT+pack(body),signature)
                if sequence<=len(self._records)+len(records):
                    previous=self._records[sequence-1] if sequence<=len(self._records) else records[sequence-len(self._records)-1]
                    if previous!=receipt:raise ValueError('GG_LAN_TOKEN_COORDINATOR_EQUIVOCATION')
                    continue
                if sequence!=len(self._records)+len(records)+1 or body['previous']!=head:raise ValueError('GG_LAN_TOKEN_RECEIPT_GAP')
                tx,amount,identifier=self._transaction(body['transaction'])
                if identifier!=body['transaction_id'] or identifier in self._by_transaction or identifier in new_ids:
                    raise ValueError('GG_LAN_TOKEN_RECEIPT_TRANSACTION')
                self._execute(state,tx,amount)
                if body['state_root']!=self._root(state):raise ValueError('GG_LAN_TOKEN_STATE_ROOT')
                records.append(deepcopy(receipt));new_ids[identifier]=records[-1]
                head=digest(body,b'GG-LAN-TEST-TOKEN-RECEIPT-ID-v1\0')
            self._state=state;self._records.extend(records);self._by_transaction.update(new_ids);self._head=head
            return self.status()

    def clear(self):
        with self._lock:self._signer=None;self._authority=None
