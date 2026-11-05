"""Owned offline financial history export/replay and application-store recovery.

Pins/floors come from protected profiles. Public history never supplies its own
network trust. No operation imports keys or declares a validator ready to vote.
"""
from pathlib import Path
import math
import os
import re
import subprocess
import time

from backend import gg_consensus as native,gg_node_store as nodes,gg_consensus_profile as validators
from backend import gg_observer_profile as observers,gg_posix_native as posix,gg_financial_account as accounts
from backend import gg_financial_dag as financial
from backend.gg_financial_authority import OwnedFinancialSession
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_dag_archive import _metadata
from backend.gg_native_process_policy import contain_owned_native
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_pipe_lifecycle as native_pipes
from backend.platform_files import is_link,set_private_mode

SCOPE='FULL_SELECTED_ORIGINAL_SIGNED_PAYMENTS_AND_SDK_APP_HEIGHT_REPLAY_WITH_PINNED_CERTIFICATE_NOT_CONSENSUS_OR_SIGNING_STATE_RECOVERY'
MODES={name:'financial-history-'+name for name in ('export','verify','restore')}
MODES['observer-restore']='financial-observer-restore'
OBSERVER_SCOPE='FULL_SELECTED_ORIGINAL_REPLAY_AND_AUTHENTICATED_SDK_OFFLINE_BOOTSTRAP_FOR_OWNED_NONVOTING_OBSERVER_NOT_SIGNER_RECOVERY_OR_LIVE_CONTACT'
HASH=re.compile(r'[0-9a-f]{64}')
BASE={'schema','genesis','genesis_hash','state','signed_header'}


def _public_destination(value):
    if not isinstance(value,(str,Path)) or not str(value) or len(str(value))>4096:raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    path=Path(value).expanduser()
    if not path.is_absolute() or is_link(path):raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    parent=path.parent.resolve(strict=True);path=parent/path.name
    for root in (nodes.ROOT,validators.ROOT,observers.ROOT,accounts.ROOT):
        if path.is_relative_to(Path(root).resolve()):raise ValueError('GG_FINANCIAL_HISTORY_PROTECTED_DESTINATION')
    return path


def _run(mode,request,owner,*,tools,timeout,check,related=(),close_on_pending=()):
    directory=Path(native.TOOLS if tools is None else tools)
    binary=native._installed_binary(directory);stamp=native._validate_binary_at(directory,binary)
    raw=native._pack(request)
    if len(raw)>512*1024:raise ValueError('GG_FINANCIAL_HISTORY_CONTEXT_LIMIT')
    environment=native._environment();environment.update(GOMAXPROCS='2',GOMEMLIMIT='384MiB')
    process=None;lease=None;deadline=time.monotonic()+timeout
    with native_pipes.FINANCIAL_HISTORY.operation((owner,*related),close_on_pending=close_on_pending) as retirement:
        try:
            check()
            if os.name=='nt':
                process=subprocess.Popen([str(binary),MODES[mode]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    cwd=owner.root,env=environment,creationflags=native_pipe_creation_flags())
            else:process=posix.launch(binary,cwd=owner.root,env=environment,arguments=(MODES[mode],))
            retirement.attach(process)
            lease=contain_owned_native(process,owner);retirement.lease=lease;pending=raw
            while True:
                check()
                if time.monotonic()>=deadline:raise ValueError('GG_FINANCIAL_HISTORY_TIMEOUT')
                try:output,_=process.communicate(input=pending,timeout=min(.25,max(.001,deadline-time.monotonic())));break
                except subprocess.TimeoutExpired:pending=None
            if len(output)>384*1024:raise ValueError('GG_FINANCIAL_HISTORY_RESULT_LIMIT')
            result=_metadata(output.strip())
            if process.returncode:
                code=result.get('error') if isinstance(result,dict) else None
                if type(code) is str and re.fullmatch(r'GG_[A-Z0-9_]{1,120}',code):raise ValueError(code)
                raise ValueError('GG_FINANCIAL_HISTORY_FAILED')
            certificate=result.get('certificate') if isinstance(result,dict) else None
            if (not isinstance(result,dict) or result.get('schema')!='gg.financial.archive.result.v1' or result.get('verified') is not True
                    or result.get('verification_scope')!=(OBSERVER_SCOPE if mode=='observer-restore' else SCOPE) or result.get('genesis_hash')!=request['genesis_hash']
                    or result.get('consensus_store_restored') is not (mode=='observer-restore')
                    or any(result.get(key) is not False for key in ('snapshot_trust_used','signing_keys_exported','validator_signing_state_restored','network_contact_asserted'))
                    or type(result.get('archive_sha256')) is not str or not HASH.fullmatch(result['archive_sha256'])
                    or not isinstance(certificate,dict) or set(certificate)!=BASE):raise ValueError('GG_FINANCIAL_HISTORY_RESULT')
            anchor={key:request[key] for key in ('genesis','genesis_hash')};tip=certificate_tip(certificate,anchor)
            if (tip[0]!=result.get('certificate_height') or tip[1]!=result.get('certificate_block')
                    or certificate['state']['state_root']!=result.get('state_root')
                    or certificate['state'].get('financial_dag')!=result.get('financial_commitment')):raise ValueError('GG_FINANCIAL_HISTORY_RESULT')
            if mode=='restore' and (result.get('application_store_restored') is not True or result.get('native_node_ready') is not False):
                raise ValueError('GG_FINANCIAL_HISTORY_RESULT')
            if mode=='observer-restore' and (result.get('application_store_restored') is not True or result.get('observer_store_restored') is not True
                    or result.get('sdk_offline_bootstrap_complete') is not True or result.get('consensus_signing') is not False
                    or result.get('native_node_ready') is not False):raise ValueError('GG_FINANCIAL_HISTORY_RESULT')
            if native._validate_binary_at(directory,binary)!=stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
            return result
        except OSError:raise ValueError('GG_FINANCIAL_HISTORY_UNAVAILABLE') from None


def history(mode,profile,path,*,validator=None,observer=None,destination=None,timeout=1800,tools=None,check=lambda:None):
    if (mode not in ('export','verify','restore') or type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=14400
            or not isinstance(path,(str,Path)) or not str(path)
            or mode=='export' and ((validator is None)==(observer is None) or destination is not None)
            or mode!='export' and (validator is not None or observer is not None) or (mode=='restore')!=(destination is not None)):
        raise ValueError('GG_FINANCIAL_HISTORY_ARGUMENTS')
    native_pipes.FINANCIAL_HISTORY.retire()
    owner=None;member=None;transferred=False
    try:
        check();owner=nodes.NodeProfile.open(profile,migrate=False)
        context=OwnedFinancialSession(owner,owner.session());anchor=context.anchor()
        if anchor['genesis']['financial_dag']['schema'] not in financial.SESSION_SOURCE_SCHEMAS:raise ValueError('GG_FINANCIAL_SESSION_ANCHOR_REQUIRED')
        saved=owner.consensus_observation()
        if saved is not None and saved['fault']:raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        request={**anchor};floor=owner._consensus_tip(saved) if saved is not None else None
        if mode=='export':
            member=validators.ValidatorProfile.open(validator) if validator is not None else observers.ObserverProfile.open(observer)
            identity=member.public_invite() if validator is not None else member.public_grant()
            if member.anchor()!=anchor or identity['body']['owner_peer_key']!=context.public_key:
                raise ValueError('GG_SDK_VALIDATOR_OWNER')
            certificate=member.public_certificate()
            if certificate is None:raise ValueError('GG_FINANCIAL_HISTORY_CERTIFICATE_REQUIRED')
            # Export is a read-only historical operation; it never lowers the
            # owner's newer shared floor or reports historical contact as live.
            floor=certificate_tip(certificate,anchor)
            request.update(archive_path=str(_public_destination(path)),root=str(member.root/'native'),certificate=certificate)
        else:
            original=Path(path).expanduser()
            if not original.is_absolute() or is_link(original):raise ValueError('GG_FINANCIAL_HISTORY_PATH')
            request['archive_path']=str(original.resolve(strict=True))
            if mode=='restore':
                target=_public_destination(destination)
                if not target.exists():target.mkdir(mode=0o700);set_private_mode(target,0o700)
                if not target.is_dir() or is_link(target):raise ValueError('GG_FINANCIAL_HISTORY_PATH')
                request['restore_root']=str(target)
        if floor is not None:request.update(minimum_certificate_height=floor[0],minimum_certificate_block=floor[1])
        result=_run(mode,request,owner,tools=tools,timeout=timeout,check=check,related=(member,),close_on_pending=(member,owner))
        if mode=='restore':
            # The native child returned this exact fully verified public core.
            # Saving it advances the owned anti-rollback floor, never a signer.
            owner.save_consensus_certificate(result['certificate'])
        return {key:value for key,value in result.items() if key!='certificate'}
    except native_pipes.NativePipeStopPending as failure:
        transferred=failure.transferred(member,owner)
        raise
    finally:
        if not transferred:
            if member is not None:member.close()
            if owner is not None:owner.close()
