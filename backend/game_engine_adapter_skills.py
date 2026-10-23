"""Original skill/trainer actions use the existing durable GG profession rows."""
import copy
from backend.game_engine_adapter_gameplay import identity
from backend.game_engine_adapter_local_client import integer

TRAINING_COST = 1000


class SkillsMixin:
    def _profession_known_locked(self, key):
        row = self._profession_state.get(key)
        return isinstance(row, dict) and row.get('trained', True) is True

    def _skills_view_locked(self):
        rows = []
        for key, definition in self._gear_tables.get('professions', {}).items():
            if not self._profession_known_locked(key):continue
            row = self._profession_state[key]
            maximum = max(1, min(100, int(row.get('max_level', 100))))
            rows.append(dict(key=key, id=identity('profession.'+key), name=definition.get('name', key),
                             level=max(1, min(maximum, int(row.get('level', 1)))), max_level=maximum,
                             xp=max(0, int(row.get('xp', 0))), abandonable=True))
        return dict(rows=rows[:40])

    def _skill_command_locked(self, row):
        if row.get('session') != self._service_generation:raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')
        skill_id = integer(row.get('skill_id'), 1, 0xffffffff)
        key = next((key for key in self._gear_tables.get('professions', {})
                    if identity('profession.'+key) == skill_id), '')
        if not key or not self._profession_known_locked(key):raise ValueError('PROFESSION_NOT_KNOWN')
        # Preserve a durable untrained row. Content-pack rebuilds merge these
        # same rows instead of silently teaching the starting profession again.
        self._profession_state[key].update(trained=False, level=0, xp=0, specializations=[])
        pending = self._engine_craft_repeat
        recipe = self._gear_tables.get('recipes', {}).get(pending.get('ref'), {})
        profession = recipe.get('profession', 'SURVIVAL')
        if pending and profession == key:self._engine_craft_repeat = {}
        self._engine_craft_error = ''
        return [{'event': name, 'args': []} for name in ('SKILL_LINES_CHANGED', 'TRADE_SKILL_UPDATE', 'CRAFT_UPDATE')]

    def _profession_trainer_command_locked(self, row):
        op = row['op']
        if op == 'TrainerOpen':
            target = self._service_person_locked(row.get('target', 'target'), nearby=True)
            # Mira is the authored local general crafting instructor. Other
            # NPCs do not acquire every profession merely by being selectable.
            if target != 'npc-wanderer-01':raise ValueError('PROFESSION_TRAINER_REQUIRED')
            self._service_generation += 1
            self._service_windows['trainer'] = True
            self._services.update(trainer_target=target, trainer_kind='PROFESSION')
            return [{'event': 'TRAINER_SHOW', 'args': []}]
        self._service_session_locked(row, 'trainer')
        if op == 'TrainerClose':
            self._service_windows['trainer'] = False
            return [{'event': 'TRAINER_CLOSED', 'args': []}]
        if op != 'TrainerBuy':raise ValueError('PROFESSION_TRAINER_COMMAND_UNKNOWN')
        target = self._service_person_locked(self._services.get('trainer_target'), nearby=True)
        if target != 'npc-wanderer-01':raise ValueError('PROFESSION_TRAINER_REQUIRED')
        spell_id = integer(row.get('spell_id'), 1, 0xffffffff)
        key = next((key for key in self._gear_tables.get('professions', {})
                    if identity('profession.'+key) == spell_id), '')
        if not key or self._profession_known_locked(key):raise ValueError('PROFESSION_ALREADY_KNOWN_OR_UNKNOWN')
        self._service_money_locked(delta=-TRAINING_COST)
        self._service_money_locked(owner=target, delta=TRAINING_COST)
        self._profession_state[key] = copy.deepcopy(self._gear_tables['professions'][key])
        self._profession_state[key].update(trained=True, level=1, xp=0, specializations=[])
        return [{'event': name, 'args': []} for name in ('SKILL_LINES_CHANGED', 'TRAINER_UPDATE', 'TRADE_SKILL_UPDATE')]

    def _profession_trainer_view_locked(self):
        if not self._service_windows.get('trainer'):return dict(open=False, rows=[])
        money = self._service_money_locked()
        rows = [dict(id=identity('profession.'+key), name=definition.get('name', key), key=key,
                     level=1, points=0, cost=TRAINING_COST,
                     description='Learn '+str(definition.get('name',key))+' at level 1.',
                     icon='Interface\\Icons\\INV_Misc_Book_09',
                     category='used' if self._profession_known_locked(key) else
                     'available' if money >= TRAINING_COST else 'unavailable')
                for key, definition in self._gear_tables.get('professions', {}).items()]
        return dict(open=True, rows=rows[:40], kind='PROFESSION',
                    target=self._services.get('trainer_target', ''))
