"""Bounded optional peer enrollment over the already authenticated LAN.

Offering a grant never opens/unlocks/starts a validator or changes membership.
Only the owner's existing work loop can persist it in already owned profiles.
An ACK is a peer-admission receipt, never SDK connectivity or finality evidence.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import ipaddress
import threading

from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_consensus_membership import anchor_from_bundle
from backend.gg_native_observer import validate_grant,MAX_GRANTS
from backend.gg_parallel_dag import pack
from backend.gg_lan_admission import RefillBudget

SCHEMA='gg.native.observer-admission-ack.v1'
DOMAIN=b'GG-NATIVE-OBSERVER-ADMISSION-ACK-v1\0'
MAX_GRANT_BYTES=4096
STATES=('WAIT','READY','UNAVAILABLE','STOPPED')


def grant_hash(grant):return hashlib.sha256(DOMAIN+pack(grant)).hexdigest()


def validate_ack(value,grant,anchor,receiver):
    try:
        expected={row['body']['validator_key'] for row in anchor['genesis']['membership']['validators']
            if row['body']['owner_peer_key']==receiver}
        if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','grant_hash','state','admitted_validator_keys'}
                or len(pack(value))>1024 or value['schema']!=SCHEMA or value['genesis_hash']!=anchor['genesis_hash']
                or value['grant_hash']!=grant_hash(grant) or value['state'] not in STATES or not expected):raise ValueError()
        keys=value['admitted_validator_keys']
        if (not isinstance(keys,list) or len(keys)>4 or any(type(key) is not str for key in keys)
                or keys!=sorted(set(keys)) or not set(keys)<=expected
                or (value['state']=='READY')!=bool(keys)):raise ValueError()
        return deepcopy(value)
    except (ValueError,KeyError,TypeError,OverflowError,RecursionError):raise ValueError('GG_OBSERVER_ADMISSION_ACK_INVALID') from None


class EnrollmentInbox:
    """At most six immutable grants; no thread/socket/secret is created here."""
    def __init__(self,peer,profiles):
        if not callable(profiles):raise ValueError('GG_OBSERVER_ADMISSION_OWNER')
        self.peer=peer;self._profiles=profiles;self._lock=threading.Lock();self._work=threading.Lock()
        self._cancel=threading.Event();self._entries=OrderedDict()
        self._binding=None
        self._budget=RefillBudget(32*1024,8,maximum_actors=3,period=4)

    def _context(self):
        peer=self.peer
        if self._cancel.is_set() or peer._cancel.is_set():raise ValueError('GG_OBSERVER_ADMISSION_STOPPED')
        bundle=peer._bundle;coordinator=peer._trusted
        if bundle is None:raise ValueError('GG_OBSERVER_ADMISSION_SESSION_REQUIRED')
        raw=pack(bundle)
        with self._lock:
            bound=self._binding
            if bound is not None:
                if raw!=bound[0] or coordinator!=bound[1]:raise ValueError('GG_OBSERVER_ADMISSION_SESSION_CHANGED')
                return bundle,coordinator,deepcopy(bound[2])
        anchor=anchor_from_bundle(bundle,coordinator)
        with self._lock:
            if self._binding is None:self._binding=(raw,coordinator,deepcopy(anchor))
            elif self._binding[:2]!=(raw,coordinator):raise ValueError('GG_OBSERVER_ADMISSION_SESSION_CHANGED')
        return bundle,coordinator,anchor

    def _targets(self,anchor):
        result=[]
        # The callback takes only the runtime dictionary lock. Never open a
        # profile or wait for its disk transaction on the network handler.
        for profile in self._profiles():
            if not isinstance(profile,ValidatorProfile):raise ValueError('GG_OBSERVER_ADMISSION_OWNER')
            body=profile._body
            if (profile._closed or profile._failed or profile._lease is None or body is None or body['fault']
                    or body['anchor'] is None):continue
            invite=body['invite']
            if (invite['body']['owner_peer_key']==self.peer.public_key and body['anchor']['genesis_hash']==anchor['genesis_hash']
                    and invite in anchor['genesis']['membership']['validators']):result.append(profile)
        if len(result)>4:raise ValueError('GG_OBSERVER_ADMISSION_OWNER')
        return tuple(result)

    @staticmethod
    def _ack(grant,anchor,state,keys=()):
        return {'schema':SCHEMA,'genesis_hash':anchor['genesis_hash'],'grant_hash':grant_hash(grant),
            'state':state,'admitted_validator_keys':sorted(keys)}

    def offer(self,authenticated_owner,grant):
        """Called only after the LAN's owner/session/frame authentication."""
        if len(pack(grant))>MAX_GRANT_BYTES:raise ValueError('GG_OBSERVER_ADMISSION_LIMIT')
        if (not isinstance(grant,dict) or not isinstance(grant.get('body'),dict)
                or grant['body'].get('owner_peer_key')!=authenticated_owner):raise ValueError('GG_OBSERVER_ADMISSION_AUTH_OWNER')
        bundle,coordinator,anchor=self._context()
        if authenticated_owner not in self.peer._roster:raise ValueError('GG_OBSERVER_ADMISSION_AUTH_OWNER')
        identifier=grant_hash(grant);producer=grant['body'].get('producer_key')
        with self._lock:
            existing=self._entries.get(producer) if type(producer) is str else None
            cached=existing is not None and existing['id']==identifier and existing['genesis_hash']==anchor['genesis_hash']
        if cached:
            # Exact previously verified bytes in this immutable session. ACK
            # polling must not consume new-signature credit while disk is slow.
            body=deepcopy(existing['grant']['body'])
        else:
            if not self._budget.take(authenticated_owner,len(pack(grant)),1):raise ValueError('GG_OBSERVER_ADMISSION_RATE')
            body=validate_grant(grant,bundle,coordinator)
        if ipaddress.ip_address(body['host']) not in self.peer.allowed:raise ValueError('GG_OBSERVER_ADMISSION_SUBNET')
        targets=self._targets(anchor)
        if not targets:return self._ack(grant,anchor,'UNAVAILABLE')
        producer=body['producer_key']
        with self._lock:
            if self._cancel.is_set():return self._ack(grant,anchor,'STOPPED')
            existing=self._entries.get(producer)
            if existing is not None and existing['id']!=identifier:raise ValueError('GG_OBSERVER_ADMISSION_DELEGATION_EXISTS')
            if existing is None:
                if len(self._entries)>=MAX_GRANTS:raise ValueError('GG_OBSERVER_ADMISSION_LIMIT')
                existing={'id':identifier,'grant':deepcopy(grant),'genesis_hash':anchor['genesis_hash'],'keys':set(),'queued':True,'last_error':''}
                self._entries[producer]=existing
            if existing['genesis_hash']!=anchor['genesis_hash']:raise ValueError('GG_OBSERVER_ADMISSION_SESSION_CHANGED')
            keys=existing['keys']&{profile._body['invite']['body']['validator_key'] for profile in targets}
            if {profile._body['invite']['body']['validator_key'] for profile in targets}-keys:existing['queued']=True
            return self._ack(grant,anchor,'READY' if keys else 'WAIT',keys)

    def serve_one(self):
        """One bounded owner-loop job. A handler never waits for these writes."""
        if self._cancel.is_set() or not self._work.acquire(blocking=False):return False
        try:
            bundle,coordinator,anchor=self._context()
            with self._lock:
                pending=next(((key,row) for key,row in self._entries.items() if row['queued']),None)
                if pending is None:return False
                producer,selected=pending;self._entries.move_to_end(producer)
                selected['queued']=False;grant=deepcopy(selected['grant'])
            if selected['genesis_hash']!=anchor['genesis_hash']:raise ValueError('GG_OBSERVER_ADMISSION_SESSION_CHANGED')
            validate_grant(grant,bundle,coordinator)
            for profile in self._targets(anchor):
                if self._cancel.is_set() or self.peer._cancel.is_set():break
                try:
                    profile.admit_observer(grant)
                    with self._lock:
                        selected['keys'].add(profile._body['invite']['body']['validator_key']);selected['last_error']=''
                except (ValueError,OSError) as error:
                    code=str(error)
                    with self._lock:selected['last_error']=code if code.startswith('GG_') and len(code)<=96 else 'GG_OBSERVER_ADMISSION_WRITE_FAILED'
            return True
        finally:self._work.release()

    def request_stop(self):self._cancel.set()

    def snapshot(self):
        with self._lock:return {'state':'STOPPED' if self._cancel.is_set() else 'ACTIVE',
            'grants':len(self._entries),'pending':sum(row['queued'] for row in self._entries.values()),
            'admitted_profiles':sum(len(row['keys']) for row in self._entries.values()),
            'last_errors':[row['last_error'] for row in self._entries.values() if row['last_error']],
            'receipt_is_native_connectivity':False}
