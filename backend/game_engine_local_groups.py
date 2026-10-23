"""Original loot settings and present-world eligibility for saved groups.

A saved identity is not a world actor. The local client has one actual player
body; offline roster entries never receive votes, loot or candidate slots.
"""
from __future__ import annotations

LOOT_METHODS = ('freeforall', 'roundrobin', 'master', 'group', 'needbeforegreed')


def world_loot_context(key, group, character, *, present):
    if group is None or character not in group['members']:
        return None
    return dict(shared_id=key, character=character, members=list(group['members']),
                loot_method=group['loot_method'], threshold=group['threshold'],
                master='player' if group['master'] == character else group['master'],
                eligible=['player'] if present else [], raid=group['raid'],
                subgroups=dict(group['subgroups']))


def master_candidates(context, name):
    if not context or context['loot_method'] != 'master' or not context['eligible']:
        return []
    if context['raid']:
        # The original dropdown uses eight five-slot subgroup blocks. Keep the
        # unoccupied slots empty rather than packing offline roster names.
        slots = [None] * 40
        slots[(context['subgroups'][context['character']] - 1) * 5] = name
        return slots
    return [name] + [None] * 4
