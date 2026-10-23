"""Guild emblem purchase and its cloth use canonical equipment and Qt materials."""
import base64
import colorsys
import copy
import math
from functools import lru_cache
from backend import game_engine_items as items
from backend.game_engine_adapter_local_client import integer
from backend.game_engine_adapter_social import event

COUNTS=(170,17,6,17,51)
DESIGN_COST=100000
CLOTH_COST=1000
REGISTRAR='npc-wanderer-01'

def checked_design(value):
    if not isinstance(value,(list,tuple)) or len(value)!=5:raise ValueError('GUILD_EMBLEM_INVALID')
    return [integer(v,0,n-1) for v,n in zip(value,COUNTS)]

def color(index,count):
    r,g,b=colorsys.hls_to_rgb(index/count,.48,.70)
    return '#%02x%02x%02x'%tuple(round(v*255) for v in (r,g,b))

@lru_cache(maxsize=64)
def emblem_texture(design):
    """Own GG vector emblems: 17 motifs × 10 arrangements; no borrowed artwork."""
    style,ink,border,edge,background=checked_design(design)
    points=[];motif=style%17;rotation=(style//17)*36.;sides=3+motif%9
    for n in range(sides*2):
        a=math.radians(rotation+n*180/sides-90);radius=62 if n%2==0 else 24+motif*1.7
        points.append('%.2f,%.2f'%(128+radius*math.cos(a),145+radius*math.sin(a)))
    pattern=' '.join(points);stroke=4+border*3
    svg=('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="320" viewBox="0 0 256 320">'
        '<path d="M8 8H248V270L128 311L8 270Z" fill="'+color(background,51)+'" stroke="'+color(edge,17)+'" stroke-width="'+str(stroke)+'"/>'
        '<polygon points="'+pattern+'" fill="'+color(ink,17)+'"/>'
        '<circle cx="128" cy="145" r="'+str(8+motif)+'" fill="'+color(background,51)+'"/>'
        '<path d="M40 240H216" stroke="'+color(edge,17)+'" stroke-width="'+str(2+border)+'"/></svg>')
    return 'data:image/svg+xml;base64,'+base64.b64encode(svg.encode()).decode()

def cloth_view(catalog,design):
    row=items.instance_view(catalog,items.make_instance(catalog,'tabard-preview','item.guild_tabard',location='EQUIPPED',equipped_slot='TABARD'))
    row['visual'].update(base_color='#ffffff',base_color_map=emblem_texture(tuple(design)),grip_offset=[0.,-.35,.34])
    return row


class TabardsMixin:
    def _tabard_member_locked(self,master=False):
        guild=self._services['guild'];member=guild.get('members',{}).get('player')
        if not member:raise ValueError('GUILD_MEMBERSHIP_REQUIRED')
        if master and member['rank']!=0:raise ValueError('GUILD_PERMISSION_DENIED')
        return guild

    def _tabard_cloth_locked(self,guild):
        self._ensure_inventory_slots_locked()
        if len(self._item_instances)>=items.MAX_WORLD_INSTANCES:raise ValueError('ITEM_INSTANCE_CAPACITY')
        if not guild.get('id'):guild['id']=self._service_id_locked()
        key='guild-tabard-'+str(self._service_id_locked())
        item=items.make_instance(self._item_catalog,key,'item.guild_tabard',location='MAIL')
        item.update(guild_id=guild['id'],guild_emblem=copy.deepcopy(guild.get('emblem') or [0,4,0,4,10]))
        self._item_instances[key]=item;self._service_move_locked(item,'INVENTORY','player')
        return item

    def _tabard_command_locked(self,row):
        op=row['op']
        if op=='TabardOpen':
            target=self._service_person_locked(row.get('target',REGISTRAR),nearby=True)
            if target!=REGISTRAR:raise ValueError('GUILD_REGISTRAR_REQUIRED')
            guild=self._tabard_member_locked()
            self._service_generation+=1;self._service_windows['tabard']=True;self._service_windows['registrar']=False
            self._tabard_draft=copy.deepcopy(guild.get('emblem') or [0,4,0,4,10])
            return event('OPEN_TABARD_FRAME')+event('GUILD_REGISTRAR_CLOSED')
        self._service_session_locked(row,'tabard')
        if op=='TabardClose':
            self._service_windows['tabard']=False;self._tabard_draft=None
            return event('CLOSE_TABARD_FRAME')
        self._service_person_locked(REGISTRAR,nearby=True)
        guild=self._tabard_member_locked(op=='TabardSave')
        if op=='TabardPreview':
            self._tabard_draft=checked_design(row.get('design'));return []
        if op=='TabardBuy':
            self._service_money_locked(delta=-CLOTH_COST);self._service_money_locked(REGISTRAR,CLOTH_COST)
            self._tabard_cloth_locked(guild);return event('BAG_UPDATE',0)
        if op!='TabardSave':raise ValueError('GUILD_EMBLEM_COMMAND_UNKNOWN')
        design=checked_design(row.get('design'))
        if guild.get('emblem')==design:raise ValueError('GUILD_EMBLEM_UNCHANGED')
        self._service_money_locked(delta=-DESIGN_COST);self._service_money_locked(REGISTRAR,DESIGN_COST)
        if not guild.get('id'):guild['id']=self._service_id_locked()
        guild['emblem']=design;self._tabard_draft=copy.deepcopy(design)
        cloth=[i for i in self._item_instances.values() if i.get('definition_id')=='item.guild_tabard'
            and i.get('guild_id')==guild['id'] and i.get('owner_id')=='player' and i.get('location') in ('INVENTORY','EQUIPPED')]
        if not cloth:cloth=[self._tabard_cloth_locked(guild)]
        for item in cloth:item['guild_emblem']=copy.deepcopy(design)
        return event('PLAYER_GUILD_UPDATE','player')+event('TABARD_SAVE_PENDING')+event('UNIT_INVENTORY_CHANGED','player')+event('BAG_UPDATE',0)

    def _tabard_view_locked(self):
        guild=self._services['guild'];opened=bool(self._service_windows.get('tabard'))
        if opened:
            try:self._service_person_locked(REGISTRAR,nearby=True);self._tabard_member_locked()
            except ValueError:opened=False;self._service_windows['tabard']=False;self._tabard_draft=None
        design=getattr(self,'_tabard_draft',None)
        return dict(open=opened,in_guild='player' in guild.get('members',{}),emblem=copy.deepcopy(guild.get('emblem')),counts=list(COUNTS),cost=DESIGN_COST,cloth_cost=CLOTH_COST,
            can_save=guild.get('members',{}).get('player',{}).get('rank')==0,
            preview=copy.deepcopy(design),cloth=cloth_view(self._item_catalog,design) if opened and design else None)

    def _tabard_equipment_visual_locked(self,row):
        if row.get('definition_id')!='item.guild_tabard':return row
        row=copy.deepcopy(row);guild=self._services['guild'];owner=row.get('owner_id','player')
        design=guild.get('emblem') if owner in guild.get('members',{}) and guild.get('id')==row.get('guild_id') else None
        row['visual'].update(base_color='#ffffff',grip_offset=[0.,-.35,.34],
            base_color_map=emblem_texture(tuple(design)) if design else '')
        return row
