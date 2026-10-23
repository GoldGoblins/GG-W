"""Read-only selected/page metadata from an explicitly mounted native asset reader.

This object owns no worker or archive and grants no gameplay actions. A UI loader should
use its own bounded NativeFormats worker rather than cold-loading on the render thread.
"""
from __future__ import annotations

import json

SCHEMA = 'gg.engine.game-data.v1'
MAX_RESPONSE = 1024 * 1024


class GameplayData:
    def __init__(self, reader):
        self.reader = reader

    def _query(self, operation, **fields):
        # Catalog loading is a bounded cold operation; it never raises blob/export limits.
        result = self.reader.request(operation, timeout=3, **fields)
        if not isinstance(result, dict) or result.get('schema') != SCHEMA:
            raise ValueError('Invalid gameplay metadata schema')
        if result.get('execution_authority') is not False or result.get('source') != 'MOUNTED_DBC':
            raise ValueError('Invalid gameplay metadata authority')
        if 'blob_base64' in result or result.get('blob_bytes', 0):
            raise ValueError('Gameplay metadata cannot contain an asset blob')
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()) > MAX_RESPONSE:
            raise ValueError('Gameplay metadata response capacity exceeded')
        return result

    @staticmethod
    def _selection(ids, offset, limit):
        if ids is not None:
            if offset is not None or limit is not None:
                raise ValueError('Gameplay selection and page are mutually exclusive')
            return {'ids': ids}
        return {key: value for key, value in (('offset', offset), ('limit', limit)) if value is not None}

    def classes(self, ids=None, *, offset=None, limit=None):
        return self._query('game_data_classes', **self._selection(ids, offset, limit))

    def triggers(self,ids=None,*,offset=None,limit=None):
        return self._query('game_data_triggers',**self._selection(ids,offset,limit))

    def skills(self, ids=None, *, kind='lines', race_id, class_id, level, offset=None, limit=None):
        return self._query('game_data_skills', kind=kind, race_id=race_id, class_id=class_id,
                           level=level, **self._selection(ids, offset, limit))

    def talents(self, *, race_id, class_id, tab_id=None, ids=None, offset=None, limit=None):
        fields = {'race_id': race_id, 'class_id': class_id, **self._selection(ids, offset, limit)}
        if tab_id is not None:
            fields['tab_id'] = tab_id
        return self._query('game_data_talents', **fields)

    def spells(self, ids=None, *, offset=None, limit=None, joins=False, level=None):
        fields=self._selection(ids, offset, limit)
        if joins:fields['joins']=joins
        if level is not None:fields['level']=level
        return self._query('game_data_spells', **fields)
