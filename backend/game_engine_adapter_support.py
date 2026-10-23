"""A saved local issue note using the original Help window's ticket verbs.

There is no remote GM queue. Status is disabled and no assignment is invented;
the local category and exact submitted text are still editable and persistent.
"""
import copy
import math
from backend.game_engine_adapter_local_client import text,integer


class SupportMixin:
    def _restore_support_locked(self):
        row=self._services.setdefault('support_note',None)
        if row is None:return
        if not isinstance(row,dict):raise ValueError('SUPPORT_NOTE_INVALID')
        integer(row['category'],1,1);text(row['text'],1999)
        if any(type(row[k]) not in (float,int) or not math.isfinite(row[k]) or row[k]<0 for k in ('created','updated')):raise ValueError('SUPPORT_NOTE_CLOCK_INVALID')

    def _support_command_locked(self,row):
        op=row['op'];note=self._services['support_note'];now=self._service_now_locked()
        if op=='SupportStatus':return [{'event':'UPDATE_GM_STATUS','args':[-1]}]
        if op=='SupportDelete':self._services['support_note']=None
        elif op=='SupportWrite':
            category=integer(row.get('category'),1,1);message=text(row.get('text'),1999)
            if not message.strip():raise ValueError('SUPPORT_NOTE_TEXT_REQUIRED')
            if (row.get('new') is True)==bool(note):raise ValueError('SUPPORT_NOTE_ALREADY_EXISTS' if note else 'SUPPORT_NOTE_NOT_FOUND')
            self._services['support_note']=dict(category=category,text=message,created=note['created'] if note else now,updated=now)
        elif op!='SupportAsk':raise ValueError('SUPPORT_COMMAND_UNKNOWN')
        note=self._services['support_note']
        args=[0] if not note else [note['category'],note['text'],max(0.,now-note['created'])/86400.,-1.,max(0.,now-note['updated'])/86400.,0,0]
        return [{'event':'UPDATE_TICKET','args':args}]

    def _support_view_locked(self):return copy.deepcopy(self._services['support_note'])
