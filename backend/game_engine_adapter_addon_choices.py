"""Original per-character/all tri-state choices over the actual local roster."""
from __future__ import annotations
import copy,json
from backend.game_engine_adapter_addon_state import SCHEMA,_local_profile_ids,_profile_root,_load_rows,_fold


class AddonChoices:
    def __init__(self,ui):
        context=getattr(ui,'_addon_roster_context',None)
        if context is None:raise ValueError('A local character roster is required')
        self.ui=ui;self.context=context;self.account,self.active,self.characters=context
        self.identities=tuple(_local_profile_ids(self.characters,self.active))
        self.defaults=dict(ui.addon_defaults);self.selected=self.active;self.saved={};self.baselines={};self.pending={}
        for identity in self.identities:
            root=_profile_root(self.account,identity);path=root/'addons.json'
            self.saved[identity]=copy.deepcopy(_load_rows(ui,root))
            if path in ui.held_saves:raise ValueError('Saved addon choices need repair before changes can be saved')
            self.baselines[identity]=path.read_bytes() if path.exists() else None

    def guard(self):
        if (getattr(self.ui,'closed',False) or self.characters.phase!='WORLD' or self.characters.active_id!=self.active
                or getattr(self.ui,'_addon_roster_context',None)!=self.context or self.ui.saved_root!=self.account
                or self.ui.character_saved_root!=_profile_root(self.account,self.active)
                or tuple(_local_profile_ids(self.characters,self.active))!=self.identities):
            raise ValueError('Local addon selection scope changed')

    def select(self,identity):
        self.guard()
        if identity and identity not in self.identities:raise ValueError('Unknown addon character')
        self.selected=identity

    def columns(self):
        columns={};votes={}
        for identity in self.identities:
            own={_fold(name):enabled for name,enabled in self.pending.get(identity,self.saved[identity])}
            columns[identity]=own
            for name,enabled in own.items():votes.setdefault(name,set()).add(enabled)
        inherited={name:next(iter(values)) for name,values in votes.items() if len(values)==1}
        return {identity:{name:own.get(_fold(name),inherited.get(_fold(name),default)) for name,default in self.defaults.items()}
                for identity,own in columns.items()}

    def view(self,rows):
        self.guard();columns=self.columns();identities=[self.selected] if self.selected else list(self.identities)
        result=[]
        for row in rows:
            values=[columns[identity].get(row['id'],True) for identity in identities]
            enabled=all(values);mixed=any(values) and not enabled
            result.append(dict(row,enabled=enabled,mixed=mixed))
        return dict(rows=result,selected=self.selected,editing=True,dirty=bool(self.pending),
            characters=[dict(id='',name='Alla karaktärer')]+[dict(id=row['id'],name=row['name']) for row in self.characters.rows])

    def set(self,name,enabled):
        self.guard()
        if type(enabled) is not bool or name not in self.defaults:raise ValueError('Unknown addon choice')
        for identity in ([self.selected] if self.selected else self.identities):
            rows=copy.deepcopy(self.pending.get(identity,self.saved[identity]))
            rows=[row for row in rows if _fold(row[0])!=_fold(name)];rows.append([name,enabled])
            if len(rows)>256:raise ValueError('Addon choice capacity exceeded')
            self.pending[identity]=rows

    def save(self):
        self.guard()
        # Every file uses the existing atomic writer. On an I/O failure the
        # remaining changes stay pending; a retry never replays a saved file.
        for identity in list(self.pending):
            path=_profile_root(self.account,identity)/'addons.json'
            if path in self.ui.held_saves:raise ValueError('Held addon choices cannot be overwritten')
            actual=path.read_bytes() if path.exists() else None
            if actual!=self.baselines[identity]:raise ValueError('Addon choices changed while the list was open')
            source=json.dumps(dict(schema=SCHEMA,rows=self.pending[identity]),ensure_ascii=False)
            self.ui._write_saved(path,source)
            self.saved[identity]=self.pending.pop(identity);self.baselines[identity]=source.encode()
