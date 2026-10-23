"""Party quest invitations and nearby shared kill credit over real GG people.

The player keeps the existing quest ledger. Companions keep separate progress;
sharing never copies a reward, completed objective or the player's inventory.
"""
import copy
import math
from backend import game_engine_quests as quests


class PartyQuestsMixin:
    def _restore_party_quests_locked(self):
        raw=self._services.setdefault('party_quests',{})
        if not isinstance(raw,dict) or len(raw)>64:raise ValueError('PARTY_QUEST_SAVE_INVALID')
        self._services['party_quests']={person:quests.normalize_state(state,self._quest_catalog)
            for person,state in raw.items() if person in self._individual_state.get('individuals',{})}

    def _party_quest_member_locked(self,person):
        if person not in self._services['group']['members']:raise ValueError('QUEST_GROUP_MEMBER_REQUIRED')
        index=self._npc_index_for_id_locked(person)
        if index is None or not self._alive[index] or math.hypot(self._x[index]-self._x[0],self._z[index]-self._z[0])>10:
            raise ValueError('QUEST_GROUP_MEMBER_OUT_OF_RANGE')
        return index

    def _party_quest_command_locked(self,row):
        if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
        op=row['op'];now=self._service_now_locked()
        if op=='QuestShareDecline':self._service_windows['quest_invite']=None;return []
        if op=='QuestShareConfirm':
            invitation=self._service_windows.get('quest_invite')
            if not invitation or invitation['expires']<=now:raise ValueError('QUEST_INVITATION_EXPIRED')
            person=invitation['person'];key=invitation['quest'];self._party_quest_member_locked(person)
            if key not in self._services['party_quests'].get(person,{}).get('active',{}):raise ValueError('QUEST_SHARER_NO_LONGER_HAS_QUEST')
            ok,result=quests.accept(self._quest_state,self._quest_catalog,key,self._sim_time)
            if not ok:raise ValueError(result['error'])
            self._service_windows['quest_invite']=None
            return [{'event':'QUEST_LOG_UPDATE','args':[]}]
        key=row.get('quest');definition=self._quest_catalog.get(key)
        if not definition or definition.get('shareable',True) is not True:raise ValueError('QUEST_NOT_SHAREABLE')
        if op=='QuestShareOffer':
            person=self._service_person_locked(row.get('target'));self._party_quest_member_locked(person)
            if key not in self._services['party_quests'].get(person,{}).get('active',{}):raise ValueError('QUEST_SHARER_NO_LONGER_HAS_QUEST')
            probe=copy.deepcopy(self._quest_state);ok,result=quests.accept(probe,self._quest_catalog,key,self._sim_time)
            if not ok:raise ValueError(result['error'])
            self._service_windows['quest_invite']=dict(person=person,quest=key,expires=now+60.)
            return [{'event':'QUEST_ACCEPT_CONFIRM','args':[self._service_unit_locked(person)['name'],definition['name']]}]
        if op!='QuestShare':raise ValueError('PARTY_QUEST_COMMAND_UNKNOWN')
        if key not in self._quest_state.get('active',{}):raise ValueError('QUEST_NOT_ACTIVE')
        if not self._services['group']['members']:raise ValueError('QUEST_GROUP_REQUIRED')
        messages=[]
        for person in self._services['group']['members']:
            name=self._service_unit_locked(person)['name']
            try:
                self._party_quest_member_locked(person)
                state=self._services['party_quests'].setdefault(person,quests.normalize_state({},self._quest_catalog))
                ok,result=quests.accept(state,self._quest_catalog,key,self._sim_time)
                verdict='Accepted' if ok else result['error']
            except ValueError as exc:verdict=str(exc)
            messages.append({'event':'CHAT_MSG_SYSTEM','args':[name+': '+verdict]})
        return messages

    def _party_quest_credit_locked(self,event):
        # Loot and crafting require the companion's own item transactions.
        # Shared kill credit is earned in the same nearby living group.
        if event.get('kind')!='DEFEAT' or self._player_defeated_locked():return
        for person in self._services['group']['members']:
            state=self._services['party_quests'].get(person)
            if not state:continue
            index=self._npc_index_for_id_locked(person)
            if index is None or not self._alive[index] or math.hypot(self._x[index]-self._x[0],self._z[index]-self._z[0])>30:continue
            quests.record_event(state,self._quest_catalog,event,self._sim_time)

    def _party_quests_view_locked(self):
        return {person:quests.view(state,self._quest_catalog)['active']
            for person,state in self._services['party_quests'].items() if person in self._services['group']['members']}
