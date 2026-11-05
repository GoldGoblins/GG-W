"""Explicit offline restoration of one owned nonvoting observer, never a signer."""
import math
import time
from pathlib import Path

from backend import gg_financial_archive as archive,gg_node_store as nodes,gg_observer_profile as observers
from backend import gg_native_pipe_lifecycle as native_pipes
from backend.gg_financial_authority import OwnedFinancialSession
from backend.gg_dag_checkpoint import certificate_tip
from backend.platform_files import is_link


def restore_observer(profile,path,observer,*,timeout=1800,tools=None,check=lambda:None):
    if (type(timeout) not in (int,float) or not math.isfinite(timeout) or not 1<=timeout<=14400
            or not isinstance(path,(str,Path)) or not str(path) or len(str(path))>4096):
        raise ValueError('GG_OBSERVER_RECOVERY_ARGUMENTS')
    native_pipes.FINANCIAL_HISTORY.retire()
    owner=None;member=None;transferred=False;deadline=time.monotonic()+timeout
    def remaining():
        check();left=deadline-time.monotonic()
        if left<=0:raise ValueError('GG_FINANCIAL_HISTORY_TIMEOUT')
        return left
    try:
        check();owner=nodes.NodeProfile.open(profile,migrate=False)
        context=OwnedFinancialSession(owner,owner.session());anchor=context.anchor()
        if context.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        from backend import gg_financial_dag as financial
        if anchor['genesis']['financial_dag']['schema'] not in financial.SESSION_SOURCE_SCHEMAS:raise ValueError('GG_FINANCIAL_SESSION_ANCHOR_REQUIRED')
        member=observers.ObserverProfile.open(observer)
        if member.anchor()!=anchor or member.public_grant()['body']['owner_peer_key']!=context.public_key:
            raise ValueError('GG_SDK_VALIDATOR_OWNER')
        if member._body['fault']:raise ValueError(member._body['fault'])
        saved=owner.consensus_observation()
        if saved is not None and saved['fault']:raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        original=Path(path).expanduser()
        if not original.is_absolute() or is_link(original):raise ValueError('GG_FINANCIAL_HISTORY_PATH')
        request={**anchor,'archive_path':str(original.resolve(strict=True))}
        floor=owner._consensus_tip(saved) if saved is not None else None
        remembered=member.public_certificate()
        if remembered is not None:
            member_floor=certificate_tip(remembered,anchor)
            if floor is not None and floor[0]==member_floor[0] and floor!=member_floor:
                raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            if floor is None or member_floor[0]>floor[0]:floor=member_floor
        if floor is not None:
            request.update(minimum_certificate_height=floor[0],minimum_certificate_block=floor[1])
        verified=archive._run('verify',request,owner,tools=tools,timeout=remaining(),check=check,related=(member,),close_on_pending=(member,owner))
        if verified.get('sdk_recovery_available') is not True or verified.get('archive_version')!=2:
            raise ValueError('GG_OBSERVER_RECOVERY_PUBLIC_SDK_CONTEXT_REQUIRED')
        certificate=verified['certificate'];digest=verified['archive_sha256']
        check();member.prepare_recovery(digest,certificate)
        request.update(certificate=certificate,expected_archive_sha256=digest,observer_grant=member.public_grant(),restore_root=str(member.root/'native'))
        recovered=archive._run('observer-restore',request,owner,tools=tools,timeout=remaining(),check=check,related=(member,),close_on_pending=(member,owner))
        if recovered['archive_sha256']!=digest or recovered['certificate']!=certificate:
            raise ValueError('GG_OBSERVER_RECOVERY_INTENT_CHANGED')
        member.finish_recovery(digest,certificate)
        owner.save_consensus_certificate(certificate)
        return {**{key:value for key,value in recovered.items() if key!='certificate'},
            'observer_profile':member.name,'observer':member.snapshot()}
    except native_pipes.NativePipeStopPending as failure:
        transferred=failure.transferred(member,owner)
        raise
    finally:
        if not transferred:
            if member is not None:member.close()
            if owner is not None:owner.close()
