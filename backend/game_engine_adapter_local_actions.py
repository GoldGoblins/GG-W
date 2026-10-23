"""Original UI crafting/loot actions over the authoritative local GG inventory."""
from __future__ import annotations

import math

from backend import game_engine_items as items


class LocalActionsMixin:
    def _clear_local_ui_sessions_locked(self):
        self._clear_service_windows_locked()
        self._engine_loot={};self._engine_craft_book={};self._engine_craft_repeat={};self._engine_craft_error=''
        self._engine_quest_panel={};self._engine_gossip_hidden=False
        self._open_merchant_id='';self._open_stash_container_id=''
        self._dialogue_state['active']={}
        self._ui_snapshot_base=None

    def _local_action_error_locked(self, error):
        result = self.snapshot_locked()
        result['error'] = error
        return result

    def _craft_inventory_error_locked(self, candidate):
        """Predict the existing instance reconciliation before spending ingredients."""
        owned = [r for r in self._item_instances.values() if isinstance(r, dict)
                 and self._item_owned_state(r.get('location'), r.get('owner_id'))]
        slots = sum(r.get('location') == 'INVENTORY' for r in owned)
        created = 0
        consumed = 0
        for key, raw in candidate.items():
            expected = max(0, int(raw))
            rows = [r for r in owned if r.get('definition_id') == key]
            current = sum(max(1, int(r.get('quantity', 1))) for r in rows)
            if expected!=current and any(self._item_binding_locked(row) for row in rows):return 'ITEM_PENDING_CONFIRMATION'
            if expected < current:
                remaining = current - expected
                for row in reversed(rows):
                    if row.get('location') != 'INVENTORY':
                        continue
                    quantity = max(1, int(row.get('quantity', 1)))
                    removed = min(quantity, remaining)
                    if removed == quantity:
                        slots -= 1
                        consumed += 1
                    remaining -= removed
                    if remaining == 0:
                        break
                if remaining:
                    return 'CRAFT_INGREDIENT_NOT_IN_BAGS'
            elif expected > current:
                definition = items.definition(self._item_catalog, key)
                if not definition:
                    return 'CRAFT_OUTPUT_UNKNOWN'
                limit = max(1, int(definition.get('stack_limit', 1)))
                count = math.ceil((expected - current) / limit)
                slots += count
                created += count
        if slots > items.MAX_INVENTORY_SLOTS:
            return 'ITEM_INVENTORY_FULL'
        destroyed = sum(isinstance(r, dict) and r.get('location') == 'DESTROYED'
                        for r in self._item_instances.values())
        if len(self._item_instances) - destroyed - consumed + created > items.MAX_WORLD_INSTANCES:
            return 'ITEM_INSTANCE_CAPACITY'
        return ''

    def _station_reachable_locked(self, key):
        row = self._gear_tables.get('workstations', {}).get(key)
        if not isinstance(row, dict):
            return False
        position = row.get('position', {})
        x, z = float(position.get('x', 0)), float(position.get('z', 0))
        return math.dist((self._x[0], self._y[0], self._z[0]),
                         (x, self._terrain_height_locked(x, z) + .65, z)) <= items.INTERACTION_RADIUS_M

    def _craft_book_view_locked(self):
        book = getattr(self, '_engine_craft_book', {})
        if not book:
            return {'open': False}
        station = book['station_id']
        if station and not self._station_reachable_locked(station):
            self._engine_craft_book = {}
            self._engine_craft_repeat = {}
            return {'open': False}
        rows = []
        for family, table in (('CONTENT', self._content.get('recipes', {})),
                              ('GEAR', self._gear_tables.get('recipes', {}))):
            for key, recipe in table.items():
                if not self._profession_known_locked(recipe.get('profession', 'SURVIVAL')):continue
                if recipe.get('station_id', '') != station and family == 'GEAR':
                    continue
                if family == 'CONTENT' and station:
                    continue
                inputs, outputs = recipe.get('inputs', {}), recipe.get('output', {})
                if not outputs or len(inputs) > 8 or len(outputs) > 4:
                    continue
                available = min((max(0, int(self._inventory.get(k, 0))) // int(n)
                                 for k, n in inputs.items() if int(n) > 0), default=1)
                reagents = []
                for ref, count in inputs.items():
                    definition = items.definition(self._item_catalog, ref) or {}
                    reagents.append({'ref': ref, 'name': definition.get('name', ref),
                                     'icon': definition.get('icon'), 'need': int(count),
                                     'have': max(0, int(self._inventory.get(ref, 0)))})
                product, quantity = next(iter(outputs.items()))
                definition = items.definition(self._item_catalog, product) or {}
                rows.append({'ref': key, 'name': recipe.get('name', key), 'family': family,
                             'available': available, 'product': product, 'quantity': int(quantity),
                             'icon': definition.get('icon'), 'reagents': reagents,
                             'description': ' · '.join(f"{n} × {(items.definition(self._item_catalog, k) or {}).get('name', k)}" for k, n in outputs.items())})
        repeat = getattr(self, '_engine_craft_repeat', {})
        return dict(book, open=True, name='GG Crafting', rows=rows[:128],
                    repeat_count=repeat.get('remaining', 0), error=getattr(self, '_engine_craft_error', ''))

    def open_crafting(self, book='TRADE_SKILL', station_id=''):
        with self._lock:
            if book not in ('TRADE_SKILL', 'CRAFT'):
                return self._local_action_error_locked('CRAFT_BOOK_UNKNOWN')
            if station_id and not self._station_reachable_locked(station_id):
                return self._local_action_error_locked('CRAFT_STATION_OUT_OF_REACH')
            self._engine_craft_generation = getattr(self, '_engine_craft_generation', 0) + 1
            self._engine_craft_repeat = {}
            self._engine_craft_error = ''
            self._engine_craft_book = {'book': book, 'station_id': station_id,
                                       'session': self._engine_craft_generation}
            return self.snapshot_locked()

    def close_crafting(self, session):
        with self._lock:
            if getattr(self, '_engine_craft_book', {}).get('session') != session:
                return self._local_action_error_locked('CRAFT_BOOK_CHANGED_OR_CLOSED')
            self._engine_craft_book = {}
            self._engine_craft_repeat = {}
            return self.snapshot_locked()

    def craft_book_recipe(self, session, recipe_id, count=1):
        with self._lock:
            view = self._craft_book_view_locked()
            if not view.get('open') or view.get('session') != session:
                return self._local_action_error_locked('CRAFT_BOOK_CHANGED_OR_CLOSED')
            row = next((r for r in view['rows'] if r['ref'] == recipe_id), None)
            if not row:
                return self._local_action_error_locked('CRAFT_RECIPE_NOT_IN_BOOK')
            if type(count) is not int or not 1 <= count <= 65535:
                return self._local_action_error_locked('CRAFT_REPEAT_CAPACITY')
            if getattr(self, '_engine_craft_repeat', {}):
                return self._local_action_error_locked('CRAFT_ALREADY_RUNNING')
            count = min(count, max(1, row['available']))
            self._engine_craft_error = ''
            result = (self.craft_recipe(recipe_id) if row['family'] == 'CONTENT'
                      else self.craft_gear(recipe_id, view['station_id']))
            if not result.get('error') and count > 1:
                self._engine_craft_repeat = {'session': session, 'ref': recipe_id,
                                              'remaining': count - 1, 'wait_s': .1}
            result['craft_batch'] = {'completed': int(not result.get('error')), 'requested': count}
            result['crafting']['book'] = self._craft_book_view_locked()
            return result

    def stop_crafting(self):
        with self._lock:
            self._engine_craft_repeat = {}
            return self.snapshot_locked()

    def _tick_crafting_locked(self, dt):
        """A bounded repeat advances one real transaction per 100 ms of play."""
        repeat = getattr(self, '_engine_craft_repeat', {})
        if not repeat:
            return
        repeat['wait_s'] -= dt
        if repeat['wait_s'] > 1e-9:
            return
        view = self._craft_book_view_locked()
        row = next((r for r in view.get('rows', []) if r['ref'] == repeat['ref']), None)
        if not view.get('open') or view.get('session') != repeat['session'] or not row:
            self._engine_craft_repeat = {}
            return
        result = (self.craft_recipe(row['ref']) if row['family'] == 'CONTENT'
                  else self.craft_gear(row['ref'], view['station_id']))
        if result.get('error'):
            self._engine_craft_error = result['error']
            self._engine_craft_repeat = {}
        else:
            repeat['remaining'] -= 1
            repeat['wait_s'] = .1
            if repeat['remaining'] <= 0:
                self._engine_craft_repeat = {}

    def _loot_source_locked(self):
        session = getattr(self, '_engine_loot', {})
        if not session:
            return None
        row, _ = self._nearest_item_locked(session['container_id'], container_only=True)
        if row is None or row.get('container_state') != 'OPEN':
            self._engine_loot = {}
            return None
        p = row.get('position', {})
        if math.dist((self._x[0], self._y[0], self._z[0]),
                     tuple(float(p.get(k, 0)) for k in ('x', 'y', 'z'))) > items.INTERACTION_RADIUS_M:
            self._engine_loot = {}
            return None
        return row

    def _open_loot_locked(self, container):
        source = str(container['instance_id'])
        self._engine_loot_generation = getattr(self, '_engine_loot_generation', 0) + 1
        self._engine_loot = {'container_id': source, 'session': self._engine_loot_generation,
                              'ids': tuple(r['instance_id'] for r in self._item_instances.values()
                                           if r.get('location') == 'CONTAINER' and r.get('container_id') == source)[:items.MAX_CONTAINER_ITEMS]}

    def _loot_view_locked(self):
        source = self._loot_source_locked()
        if source is None:
            return {'open': False}
        session = self._engine_loot
        rows = []
        for key in session['ids']:
            row = self._item_instances.get(key)
            if not self._loot_item_at_source_locked(row, source):
                rows.append(None)
            else:
                rows.append(items.instance_view(self._item_catalog, row, sim_time=self._sim_time))
        group=self._services['group']
        candidates=[self._service_unit_locked(v)['name'] for v in ['player']+group['members']] if group['loot_method']=='master' else []
        pending=session.get('pending_bind')
        if pending and pending['expires']<=self._service_now_locked():session.pop('pending_bind');pending=None
        return {'open': True, 'container_id': session['container_id'], 'session': session['session'], 'rows': rows,
                'master_candidates':candidates,'pending_bind':dict(item=pending['item'],name=(self._item_instance_locked(pending['item']) or {}).get('name','Item')) if pending else None}

    def loot_slot(self, session, container_id, instance_id):
        with self._lock:
            try:events=self._service_command_locked(dict(op='LootPickup',loot_session=session,source=container_id,item=instance_id))
            except (ValueError,TypeError,KeyError,OverflowError) as exc:return self._local_action_error_locked(str(exc))
            result=self.snapshot_locked();result['client_events']=events;return result

    def _loot_pickup_command_locked(self,command):
        source=self._loot_source_locked();shown=self._engine_loot;identity=command.get('item')
        if not source or (shown.get('session'),shown.get('container_id'))!=(command.get('loot_session'),command.get('source')):
            raise ValueError('LOOT_SOURCE_CHANGED_OR_CLOSED')
        item=self._item_instance_locked(identity)
        if not item or identity not in shown['ids'] or not self._loot_item_at_source_locked(item,source):
            raise ValueError('LOOT_SLOT_EMPTY_OR_CHANGED')
        definition=items.definition(self._item_catalog,item['definition_id']) or {}
        if command['op'] in ('LootBindConfirm','LootBindCancel'):
            pending=shown.get('pending_bind')
            if (not pending or pending['item']!=identity or pending['expires']<=self._service_now_locked()
                    or pending['definition']!=item['definition_id'] or pending['quantity']!=item['quantity']):
                raise ValueError('LOOT_BIND_CHANGED_OR_CLOSED')
            shown.pop('pending_bind')
            if command['op']=='LootBindCancel':return []
        else:
            if any(r['item']==identity for r in self._services['loot_rolls']) or self._services['group']['members'] and self._services['group']['loot_method']!='freeforall':
                return self._group_loot_route_locked(item,source) or []
            if definition.get('bonding')==1 and not item.get('bound_to'):
                shown['pending_bind']=dict(item=identity,definition=item['definition_id'],quantity=item['quantity'],expires=self._service_now_locked()+120.)
                return [dict(event='LOOT_BIND_CONFIRM',args=[shown['ids'].index(identity)+1])]
        ok,result=self._move_item_locked(item,'INVENTORY',owner_id='player')
        if not ok:raise ValueError(result['error'])
        self._refresh_loot_container_locked(source)
        self._append_event_locked('CONTAINER_LOOT',f"Looted {item.get('name',identity)}.",actor_id='player',subject_id=source['instance_id'],payload={'count':1,'item_ids':[identity]})
        self._record_quest_event_locked(dict(kind='PICKUP',target_id=identity,definition_id=item['definition_id'],rarity=item.get('rarity','COMMON'),amount=item['quantity']))
        return [dict(event='LOOT_SLOT_CLEARED',args=[shown['ids'].index(identity)+1]),dict(event='BAG_UPDATE',args=[0])]

    def close_loot(self, session):
        with self._lock:
            if getattr(self, '_engine_loot', {}).get('session') != session:
                return self._local_action_error_locked('LOOT_SOURCE_CHANGED_OR_CLOSED')
            source = self._item_instances.get(self._engine_loot['container_id'])
            if source and source.get('kind') == 'CONTAINER' and not source.get('contents'):
                source['container_state'] = 'LOOTED'
            self._engine_loot = {}
            return self.snapshot_locked()
