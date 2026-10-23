"""Canonical GG character labels for original UnitClass/UnitRace getters.

Labels describe actual GG selection/progression. They assign no original class
stats, relic eligibility, pet family, power type or race policy.
"""
from functools import lru_cache
import re
from backend import game_engine_character_creation as appearance

SCHEMA='gg.engine.character-identity.v1'
_ID=re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}\Z')


@lru_cache(maxsize=1)
def _progression_labels():
    from backend.game_engine_content import starter_content
    content=starter_content()
    return {kind:{key:row['name'] for key,row in content[kind].items()} for kind in ('classes','races')}


def _row(value,labels):
    if value is None:return None
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('CHARACTER_IDENTITY_INVALID')
    name=labels.get(value)
    if name is None:return None
    if not isinstance(name,str) or not name or len(name.encode())>384:raise ValueError('CHARACTER_IDENTITY_INVALID')
    token=value.split('.',1)[-1].replace('-','_').upper()
    return dict(id=value,name=name,file=token)


def identity(snapshot):
    if not isinstance(snapshot,dict):raise ValueError('CHARACTER_IDENTITY_INVALID')
    creation=snapshot.get('character_creation',{})
    progression=snapshot.get('progression',{})
    if not isinstance(creation,dict) or not isinstance(progression,dict):raise ValueError('CHARACTER_IDENTITY_INVALID')
    active=creation.get('active',False)
    if type(active) is not bool:raise ValueError('CHARACTER_IDENTITY_INVALID')
    if active:
        selected=creation.get('selection')
        if not isinstance(selected,dict) or len(selected)>16:raise ValueError('CHARACTER_IDENTITY_INVALID')
        catalog=appearance.catalog()
        classes={row['id']:row['name'] for row in catalog.get('classes',[])}
        races={row['id']:row['name'] for row in catalog.get('races',[])}
        class_id=selected.get('class_id');race_id=selected.get('race_id')
    else:
        catalog=_progression_labels();classes=catalog['classes'];races=catalog['races']
        class_id=progression.get('class_id');race_id=progression.get('race_id',progression.get('race'))
        if isinstance(race_id,str) and race_id.upper() in ('ISLANDER','TIDEBORN','SKYKIN'):
            race_id='race.'+race_id.lower()
    return dict(schema=SCHEMA,**{'class':_row(class_id,classes),'race':_row(race_id,races)})
