"""Keep rig and mesh metadata off the per-frame JSON transport.

Transforms already go directly to retained Qt nodes. Send presentation rows
only on identity, equipment, visibility or locomotion changes. The complete
resident ID list removes departed nodes without rebuilding surviving rigs.
"""
from __future__ import annotations
import math


class RenderTransport:
    def __init__(self):
        self.signatures = {}

    @staticmethod
    def signature(row):
        asset = row.get('asset') or {}
        item = row.get('item') or {}
        item_asset = item.get('asset') or {}
        animation = row.get('animation') or {}
        return (row.get('kind'),row.get('sx'),row.get('sy'),row.get('sz'),row.get('color'),
            asset.get('id'),asset.get('mode'),asset.get('source'),repr(asset.get('root_offset_m')),
            asset.get('instance_rank'),asset.get('instance_budget'),
            item.get('instance_id'),item.get('location'),item_asset.get('mode'),item_asset.get('source'),
            tuple((e.get('instance_id'),e.get('equipped_slot'),e.get('definition_id'),
                repr(e.get('sockets')),repr(e.get('enchantments')),repr(e.get('affixes')),
                e.get('visual_visible'),e.get('visual_stowed'),repr(e.get('attachment')))
                for e in row.get('equipment',[])),
            row.get('vehicle'),row.get('hidden'),row.get('motion_state'),animation.get('state'),
            asset.get('clip'),asset.get('runtime_clip'),round(float(animation.get('cadence_hz') or 0)*8))

    def prepare(self, snapshot):
        if not isinstance(snapshot,dict):return snapshot
        if snapshot.get('schema') != 'gg.game-engine.render-snapshot.v1':
            if snapshot.get('render',{}).get('entities') is not None:self.signatures.clear()
            return snapshot
        render = snapshot.get('render',{})
        if render.get('presentation',{}).get('mode') == 'DOS_2D':return snapshot
        rows = render.get('entities')
        if rows is None:return snapshot
        signatures={};changed=[]
        for row in rows:
            identity=row['id'];signature=self.signature(row)
            if self.signatures.get(identity)!=signature:changed.append(row)
            signatures[identity]=signature
        self.signatures=signatures
        result=dict(snapshot);result['render']=dict(render)
        result['render'].pop('entities',None)
        result['render']['entities_delta']=changed
        result['render']['entity_ids']=list(signatures)
        return result
