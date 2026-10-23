"""Authored item-set thresholds shared by actual combat and original tooltips."""
import math
from backend import game_engine_items as items
from backend.game_engine_adapter_gameplay import identity

DEFAULT_SETS={'saltwake_voyager':dict(name='Saltwake Voyager',
    members=['item.tideguard_jacket','item.drift_cloak','item.saltpath_boots'],
    bonuses=[dict(count=2,stats={'armor':3},text='+3 armor.'),
             dict(count=3,stats={'health':12},text='+12 health.')])}


def set_rows(tables,catalog):
    source=tables.get('item_sets',DEFAULT_SETS)
    if not isinstance(source,dict) or len(source)>64:raise ValueError('ITEM_SET_CAPACITY')
    rows=[];claims=set();seen=set()
    for ref,raw in source.items():
        if not isinstance(ref,str) or not 1<=len(ref)<=96 or not isinstance(raw,dict):raise ValueError('ITEM_SET_INVALID')
        name=raw.get('name');members=raw.get('members');bonuses=raw.get('bonuses',[])
        if (not isinstance(name,str) or not 1<=len(name)<=96 or not isinstance(members,list) or not 1<=len(members)<=17
                or any(not isinstance(m,str) or not items.definition(catalog,m) for m in members)
                or len(set(members))!=len(members) or not isinstance(bonuses,list) or len(bonuses)>8):
            # A foreign pack lacking every member does not inherit the GG set.
            if source is DEFAULT_SETS:continue
            raise ValueError('ITEM_SET_INVALID')
        key=identity('itemset.'+ref)
        if key in seen or claims.intersection(members):raise ValueError('ITEM_SET_DUPLICATE')
        seen.add(key);claims.update(members);checked=[]
        for bonus in bonuses:
            if not isinstance(bonus,dict):raise ValueError('ITEM_SET_BONUS_INVALID')
            count=bonus.get('count');stats=bonus.get('stats');text=bonus.get('text')
            if (type(count) is not int or not 1<=count<=len(members) or not isinstance(stats,dict) or not 1<=len(stats)<=16
                    or any(not isinstance(s,str) or not 1<=len(s)<=48 or type(v) not in (int,float) or not math.isfinite(v) or abs(v)>10000 for s,v in stats.items())
                    or not isinstance(text,str) or not 1<=len(text)<=512):raise ValueError('ITEM_SET_BONUS_INVALID')
            checked.append(dict(count=count,stats=dict(stats),text=text))
        profession=raw.get('profession','');rank=raw.get('profession_rank',0)
        if (not isinstance(profession,str) or profession and profession not in tables.get('professions',{})
                or type(rank) is not int or not 0<=rank<=100):raise ValueError('ITEM_SET_SKILL_INVALID')
        rows.append(dict(id=key,ref=ref,name=name,members=list(members),bonuses=checked,
                         profession=profession,profession_rank=rank))
    return rows


def active_stats(rows,equipped,professions):
    worn={i.get('definition_id') for i in equipped if float(i.get('condition',1.))>0.}
    stats={}
    for row in rows:
        skill=professions.get(row['profession'],{})
        if row['profession'] and (not skill or not skill.get('trained',True) or skill.get('level',0)<row['profession_rank']):continue
        count=len(worn.intersection(row['members']))
        for bonus in row['bonuses']:
            if count>=bonus['count']:
                for stat,value in bonus['stats'].items():stats[stat]=stats.get(stat,0)+value
    return stats


class ItemSetsMixin:
    def _item_sets_locked(self):
        cached=getattr(self,'_engine_item_sets',None)
        if cached is None or cached[0] is not self._gear_tables or cached[1] is not self._item_catalog:
            cached=(self._gear_tables,self._item_catalog,set_rows(self._gear_tables,self._item_catalog));self._engine_item_sets=cached
        return cached[2]

    def _item_set_stats_locked(self,equipped,professions=None):return active_stats(self._item_sets_locked(),equipped,self._profession_state if professions is None else professions)

    def _item_sets_view_locked(self):
        return [dict(id=row['id'],name=row['name'],members=[[identity(ref),(items.definition(self._item_catalog,ref) or {})['name']] for ref in row['members']],
                     bonuses=[[bonus['count'],bonus['text']] for bonus in row['bonuses']],
                     required_skill=identity('profession.'+row['profession']) if row['profession'] else 0,
                     required_skill_rank=row['profession_rank'],
                     required_skill_name=self._gear_tables['professions'].get(row['profession'],{}).get('name')) for row in self._item_sets_locked()]

    def _item_set_info_locked(self,row):
        key=row.get('id')
        if type(key) is not int or not any(r['id']==key for r in self._item_sets_locked()):raise ValueError('ITEM_SET_NOT_LOCAL')
        return []
