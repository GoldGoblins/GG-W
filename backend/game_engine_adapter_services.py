"""Local game services over GG's canonical items, economy, people and fauna.

This is the local authority, not a second inventory/renderer or a pretend
remote realm. Escrow keeps the original item instance in the world registry.
UI commands are finite, session-bound, and publish together under the host lock.
"""
from __future__ import annotations

import copy
import math
import time
from backend import game_engine_items as items
from backend import game_engine_trade as trade
from backend import game_engine_economy as economy
from backend import game_engine_combat as combat
from backend import game_engine_enchants as enchants
from backend.game_engine_adapter_local_client import integer, text
from backend.game_engine_adapter_social import SocialServicesMixin, defaults as social_defaults
from backend.game_engine_adapter_pet_training import PetTrainingMixin, SPELLS as PET_SPELLS
from backend.game_engine_adapter_lifecycle import LifecycleMixin, defaults as lifecycle_defaults
from backend.game_engine_adapter_channels import ChannelsMixin, defaults as channel_defaults
from backend.game_engine_adapter_inventory import InventoryServicesMixin
from backend.game_engine_adapter_inspection import InspectionMixin
from backend.game_engine_adapter_item_info import ItemInfoMixin
from backend.game_engine_adapter_travel import TravelMixin, defaults as travel_defaults
from backend.game_engine_adapter_party_quests import PartyQuestsMixin
from backend.game_engine_adapter_support import SupportMixin
from backend.game_engine_adapter_skills import SkillsMixin
from backend.game_engine_adapter_petitions import PetitionsMixin
from backend.game_engine_adapter_tabards import TabardsMixin
from backend.game_engine_adapter_item_binding import ItemBindingMixin
from backend.game_engine_adapter_wrapping import WrappingMixin
from backend.game_engine_adapter_item_targeting import ItemTargetingMixin
from backend.game_engine_adapter_dressup import DressupMixin
from backend.game_engine_adapter_item_sets import ItemSetsMixin
from backend.game_engine_adapter_opening_cinematic import OpeningCinematicMixin
from backend.game_engine_adapter_battlefields import BattlefieldsMixin,defaults as battlefield_defaults
from backend.game_engine_adapter_instance_sessions import InstanceSessionsMixin,defaults as instance_defaults
from backend.game_engine_adapter_private_world import SESSION_ROLLBACK_ATTRIBUTES
from backend.game_engine_adapter_gameplay import identity as spell_identity

MAX_MAIL = 128
MAX_AUCTIONS = 64
MAX_COPPER = 2_000_000_000
PET_STRIKE = 0x800101
LOOT_METHODS = ('freeforall', 'roundrobin', 'master', 'group', 'needbeforegreed')


def defaults():
    return dict(version=1, next_id=1, revision=0, mail=[], auctions=[],
                group=dict(members=[], raid=False, leader='player', assistants=[],
                           subgroups={}, loot_method='freeforall', threshold=2,
                           master='player', marks={}, ready={}),
                pets=[], active_pet=0, current_pet=0, stable_slots=0, clock=0., market_at=0., party_quests={}, support_note=None, petition_offer=None, **social_defaults(), **lifecycle_defaults(), **channel_defaults(), **travel_defaults(), **battlefield_defaults(), **instance_defaults())


def events(name, *args):
    return [{'event': name, 'args': list(args)}]


class ServicesMixin(SocialServicesMixin, PetTrainingMixin, LifecycleMixin, ChannelsMixin, InventoryServicesMixin, InspectionMixin, ItemInfoMixin, TravelMixin, PartyQuestsMixin, SupportMixin, SkillsMixin, PetitionsMixin, TabardsMixin, ItemBindingMixin, WrappingMixin, ItemTargetingMixin, DressupMixin, ItemSetsMixin, OpeningCinematicMixin, BattlefieldsMixin, InstanceSessionsMixin):
    def _reset_services_locked(self):
        self._services = defaults()
        self._battlefield_map=0;self._battlefield_positions_at=0.;self._inspect_honor_owner=None;self._battlefield_cancelled_return=None
        self._clear_service_windows_locked()

    def _clear_service_windows_locked(self):
        self._service_generation = getattr(self, '_service_generation', 0) + 1
        self._service_windows = dict(mail=False, auction=False, stable=False, trade=False, trainer=False,registrar=False,petition=None,tabard=False)
        self._service_trade = {}
        self._service_text = None
        self._tabard_draft = None
        self._clear_item_binding_locked()
        self._clear_wrapping_locked()
        self._clear_item_targeting_locked()
        self._clear_dressup_locked()
        self._stop_opening_cinematic_locked()
        self._opening_cinematic=None
        self._inspect_honor_owner=None
        self._auction_query = dict(name='', page=0)
        self._auction_pages = [0, 0, 0]
        self._auction_sorts = [[] for _ in range(3)]
        self._service_next_tick = 0.

    def _restore_services_locked(self, raw):
        if not isinstance(raw, dict):
            return
        # Shape validation precedes copying. Never accept executable data,
        # unknown versions, duplicate claims, unbounded records or NaNs.
        try:
            import json
            if len(json.dumps(raw, allow_nan=False)) > 1024 * 1024:
                return
            if raw.get('version') != 1:
                return
            integer(raw['next_id'], 1, 2**31 - 1)
            integer(raw['revision'], 0, 2**31 - 1)
            if not isinstance(raw['mail'], list) or len(raw['mail']) > MAX_MAIL:
                return
            if not isinstance(raw['auctions'], list) or len(raw['auctions']) > MAX_AUCTIONS:
                return
            seen = set()
            for row in raw['mail'] + raw['auctions']:
                key = integer(row['id'], 1, raw['next_id'] - 1)
                if key in seen:
                    return
                seen.add(key)
                if not isinstance(row.get('item', ''), str) or len(row.get('item', '')) > 96:
                    return
            group = raw['group']
            if (not isinstance(group, dict) or not isinstance(group['members'], list)
                    or len(group['members']) > (39 if group['raid'] else 4)
                    or len(set(group['members'])) != len(group['members'])
                    or any(not isinstance(v, str) or len(v) > 64 for v in group['members'])):
                return
            pets = raw['pets']
            if not isinstance(pets, list) or len(pets) > 3:
                return
            from backend.game_engine_nature_catalog import ANIMALS
            for pet in pets:
                integer(pet['number'], 1, 2**31 - 1)
                if pet['species'] not in ANIMALS or len(pet['slots']) != 10:
                    return
                if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in pet['slots']):
                    return
                if len(pet['name']) > 32 or len(pet['id']) > 96:
                    return
            integer(raw['stable_slots'], 0, 2)
            self._services = copy.deepcopy(raw)
            self._services.setdefault('current_pet', self._services['active_pet'])
            self._services.setdefault('market_at', 0.)
            try:self._restore_social_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(social_defaults())
            try:self._restore_lifecycle_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(lifecycle_defaults())
            try:self._restore_battlefields_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(battlefield_defaults())
            try:self._restore_instance_sessions_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(instance_defaults())
            try:self._restore_channels_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(channel_defaults())
            try:self._restore_travel_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services.update(travel_defaults())
            try:self._restore_party_quests_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services['party_quests']={}
            try:self._restore_support_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services['support_note']=None
            try:self._restore_petitions_locked()
            except (KeyError,TypeError,ValueError,OverflowError):self._services['petition_offer']=None
            for pet in self._services['pets']:
                try:self._pet_training_defaults_locked(pet)
                except (KeyError,TypeError,ValueError,OverflowError):
                    for key in ('learned','happiness','loyalty','loyalty_progress','training_spent','pending_spell','resistances'):pet.pop(key,None)
                    self._pet_training_defaults_locked(pet)
        except (KeyError, TypeError, ValueError, OverflowError):
            self._services = defaults()
            return

    def _service_id_locked(self):
        value = self._services['next_id']
        if value >= 2**31 - 1:
            raise ValueError('SERVICE_ID_CAPACITY')
        self._services['next_id'] += 1
        return value

    def _service_now_locked(self):
        value = max(float(self._services['clock']), time.time())
        self._services['clock'] = value
        return value

    def _service_money_locked(self, owner='player', delta=0):
        if owner == 'player':
            wallet = self._economy_state['wallet']
        else:
            vendor_id = next((key for key, v in self._vendor_catalog.items() if v.get('npc_id') == owner), '')
            wallet = self._economy_state.get('vendors', {}).get(vendor_id)
            if not isinstance(wallet, dict):
                raise ValueError('SERVICE_RECIPIENT_HAS_NO_WALLET')
        current = int(wallet.get('gold', 0)) * 10000 + int(wallet.get('copper', 0))
        value = current + delta
        if not 0 <= value <= economy.MAX_CURRENCY * 10000 + 9999:
            raise ValueError('SERVICE_INSUFFICIENT_MONEY' if value < 0 else 'SERVICE_WALLET_FULL')
        if delta:
            wallet['gold'], wallet['copper'] = divmod(value, 10000)
            if not wallet['copper']:wallet.pop('copper')
            wallet['revision'] = int(wallet.get('revision', 0)) + 1
        return value

    def _service_person_locked(self, value, *, nearby=False):
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError('SERVICE_PERSON_REQUIRED')
        if value in ('player', getattr(self, '_local_character_name', 'Gold Goblin')):
            return 'player'
        token = value.casefold()
        if token == 'target':
            value = self._combat_target_id
        elif token.startswith('party') and token[5:].isdigit():
            n = int(token[5:]) - 1
            group = self._services['group']['members']
            value = group[n] if 0 <= n < len(group) else ''
        elif token.startswith('raid') and token[4:].isdigit():
            roster = ['player'] + self._services['group']['members']
            n = int(token[4:]) - 1
            value = roster[n] if self._services['group']['raid'] and 0 <= n < len(roster) else ''
        matches = [p['id'] for p in self._local_people_locked()
                   if p['id'] == value or p['name'].casefold() == value.casefold()]
        if len(matches) != 1:
            raise ValueError('SERVICE_PERSON_UNKNOWN_OR_AMBIGUOUS')
        identity = matches[0]
        if self._instance_private_locked() and identity not in self._expedition_record_locked()['participants']:
            raise ValueError('INSTANCE_ENCOUNTER_SERVICE_UNAVAILABLE')
        if nearby and identity != 'player':
            index = self._npc_index_for_id_locked(identity)
            if (index is None or not self._alive[index]
                    or not self._combat_state.get('actors',{}).get(identity,{}).get('alive',True)
                    or math.dist((self._x[0], self._y[0], self._z[0]),
                                 (self._x[index], self._y[index], self._z[index])) > items.INTERACTION_RADIUS_M
                    or not self._npc_line_of_sight_locked(index)):
                raise ValueError('SERVICE_PERSON_OUT_OF_REACH')
        return identity

    def _service_item_locked(self, value, owner='player', location='INVENTORY'):
        row = self._item_instance_locked(value)
        definition = items.definition(self._item_catalog, row.get('definition_id')) if row else None
        ok, result = trade.validate_offer(row, definition, owner_id=owner, location=location)
        if not ok:
            raise ValueError(result.get('error', 'SERVICE_ITEM_INVALID'))
        return row

    def _service_move_locked(self, row, location, owner):
        ok, result = self._move_item_locked(row, location, owner_id=owner)
        if not ok:
            raise ValueError(result.get('error', 'SERVICE_ITEM_MOVE_FAILED'))

    def _service_mail_locked(self, sender, recipient, subject, body='', *, item='', money=0,
                             cod=0, returned=False, invoice=None):
        if len(self._services['mail']) >= MAX_MAIL:
            raise ValueError('MAILBOX_CAPACITY')
        row = dict(id=self._service_id_locked(), sender=sender, recipient=recipient,
                   subject=subject[:128], body=body[:4096], item=item, money=money,
                   cod=cod, read=False, returned=returned, permanent=False,
                   expires=self._service_now_locked() + 30 * 86400, invoice=invoice)
        self._services['mail'].append(row)
        if item:
            instance = self._item_instance_locked(item)
            if not instance:
                raise ValueError('MAIL_ATTACHMENT_MISSING')
            self._service_move_locked(instance, 'MAIL', recipient)
        return row

    def _service_session_locked(self, row, window):
        if (not self._service_windows[window]
                or row.get('session') != self._service_generation):
            raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')

    def _inbox_locked(self):
        return [r for r in self._services['mail'] if r['recipient'] == 'player']

    def _mail_command_locked(self, row):
        op = row['op']
        if op == 'MailOpen':
            self._service_generation += 1
            self._service_windows['mail'] = True
            return events('MAIL_SHOW')
        self._service_session_locked(row, 'mail')
        if op == 'MailClose':
            self._service_windows['mail'] = False
            return events('MAIL_CLOSED')
        if op == 'MailCheck':
            return events('MAIL_INBOX_UPDATE')
        if op == 'MailSend':
            target = self._service_person_locked(text(row.get('target'), 48))
            if target != 'player' and not any(v.get('npc_id') == target for v in self._vendor_catalog.values()):
                raise ValueError('MAIL_LOCAL_RECIPIENT_UNAVAILABLE')
            subject = text(row.get('subject'), 128)
            body = row.get('body', '')
            if not isinstance(body, str) or len(body) > 4096 or '\x00' in body:
                raise ValueError('MAIL_BODY_INVALID')
            money = integer(row.get('money', 0), 0, MAX_COPPER)
            cod = integer(row.get('cod', 0), 0, MAX_COPPER)
            item = row.get('item', '')
            if item:
                self._service_item_locked(item)
            if cod and (money or not item):
                raise ValueError('MAIL_COD_REQUIRES_ATTACHMENT_WITHOUT_MONEY')
            self._service_money_locked(delta=-(money + 30))
            self._service_mail_locked('player', target, subject, body, item=item, money=money, cod=cod)
            return events('MAIL_SEND_SUCCESS') + events('MAIL_INBOX_UPDATE')
        mail = next((m for m in self._inbox_locked() if m['id'] == row.get('id')), None)
        if not mail:
            raise ValueError('MAIL_CHANGED_OR_REMOVED')
        if op == 'MailRead':
            mail['read'] = True
        elif op == 'MailItem':
            if not mail['item']:
                raise ValueError('MAIL_HAS_NO_ATTACHMENT')
            item = self._service_item_locked(mail['item'], 'player', 'MAIL')
            if mail['cod']:
                self._service_money_locked(delta=-mail['cod'])
                self._service_mail_locked('player', mail['sender'], 'Postförskott', money=mail['cod'])
            self._service_move_locked(item, 'INVENTORY', 'player')
            mail['item'] = '';mail['cod'] = 0;mail['read'] = True
        elif op == 'MailMoney':
            if not mail['money']:
                raise ValueError('MAIL_HAS_NO_MONEY')
            self._service_money_locked(delta=mail['money']);mail['money'] = 0
        elif op == 'MailDelete':
            if mail['item'] or mail['money']:
                raise ValueError('MAIL_MUST_COLLECT_ASSETS_FIRST')
            self._services['mail'].remove(mail)
        elif op == 'MailReturn':
            if mail['returned'] or mail['sender'] == 'Auction House':
                raise ValueError('MAIL_CANNOT_RETURN')
            mail['sender'], mail['recipient'] = mail['recipient'], mail['sender']
            mail['returned'] = True;mail['read'] = False;mail['cod'] = 0
            mail['expires'] = self._service_now_locked() + 30 * 86400
            if mail['item']:
                self._service_move_locked(self._item_instance_locked(mail['item']), 'MAIL', mail['recipient'])
        elif op == 'MailText':
            if mail['permanent'] or not mail['body']:
                raise ValueError('MAIL_TEXT_ALREADY_SAVED_OR_EMPTY')
            self._ensure_inventory_slots_locked()
            if len(self._item_instances) >= items.MAX_WORLD_INSTANCES:
                raise ValueError('ITEM_INSTANCE_CAPACITY')
            definition_id = 'item.gg_letter'
            self._item_catalog.setdefault('items', {}).setdefault(definition_id,
                dict(id=definition_id, name='Letter', kind='ITEM', rarity='COMMON',
                     stack_limit=1, tags=['NO_TRADE'], equip_slots=[]))
            key = f"letter-{self._service_id_locked()}"
            instance = items.make_instance(self._item_catalog, key, definition_id, location='MAIL')
            self._service_move_locked(instance, 'INVENTORY', 'player')
            instance['letter'] = dict(subject=mail['subject'], body=mail['body'], sender=mail['sender'])
            self._item_instances[key] = instance;mail['permanent'] = True
        else:
            raise ValueError('MAIL_COMMAND_UNKNOWN')
        return events('MAIL_INBOX_UPDATE')

    def _auction_finish_locked(self, auction, *, cancel=False):
        item = self._service_item_locked(auction['item'], auction['owner'], 'AUCTION')
        sold = bool(auction['bidder']) and not cancel
        need = 2 if sold or auction['bidder'] else 1
        if len(self._services['mail']) + need > MAX_MAIL:
            raise ValueError('MAILBOX_CAPACITY')
        if cancel and auction['bidder']:
            self._service_mail_locked('Auction House', auction['bidder'], 'Återbetalat bud', money=auction['bid'])
        if sold:
            self._service_mail_locked('Auction House', auction['bidder'], 'Vunnen auktion', item=item['instance_id'])
            # Only the commission is a currency sink. The seller's posted
            # deposit is returned on success; failed sales forfeit it.
            amount = auction['bid'] - auction['bid'] // 20 + auction['deposit']
            self._service_mail_locked('Auction House', auction['owner'], 'Såld på auktion', money=amount,
                invoice=dict(item_name=item['name'], player_name=auction['bidder'],
                             bid=auction['bid'], buyout=auction['buyout'], deposit=auction['deposit'],
                             consignment=auction['bid'] // 20, seller=True))
        else:
            self._service_mail_locked('Auction House', auction['owner'], 'Återlämnat föremål', item=item['instance_id'])
        self._services['auctions'].remove(auction)

    def _auction_post_locked(self, item_id, owner, min_bid, buyout, duration):
        if len(self._services['auctions']) >= MAX_AUCTIONS:
            raise ValueError('AUCTION_CAPACITY')
        item = self._service_item_locked(item_id, owner, 'INVENTORY' if owner == 'player' else 'POCKET')
        min_bid = integer(min_bid, 1, MAX_COPPER - 1)
        buyout = integer(buyout, 0, MAX_COPPER - 1)
        duration = integer(duration, 120, 1440)
        if duration not in (120, 480, 1440) or buyout and buyout < min_bid:
            raise ValueError('AUCTION_PRICE_OR_DURATION_INVALID')
        deposit = max(1, min_bid // 20) * (duration // 120)
        self._service_money_locked(owner, -deposit)
        self._service_move_locked(item, 'AUCTION', owner)
        if owner != 'player':
            person = self._individual_state['individuals'][owner]
            if not self._npc_remove_inventory_ref_locked(person, item['definition_id']):
                raise ValueError('AUCTION_NPC_STOCK_CHANGED')
        auction = dict(id=self._service_id_locked(), owner=owner, item=item_id,
                       min_bid=min_bid, buyout=buyout, bid=0, bidder='', deposit=deposit,
                       expires=self._service_now_locked() + duration * 60)
        self._services['auctions'].append(auction)
        if owner=='player':self._services['market_at']=self._service_now_locked()+30
        return auction

    def _seed_local_auctions_locked(self):
        # A real NPC can list at most one of its existing pocket items. No
        # synthetic market stock, infinite buyers or a second NPC wallet.
        for vendor_id, vendor in self._vendor_catalog.items():
            identity = vendor.get('npc_id', '')
            if any(a['owner'] == identity for a in self._services['auctions']):
                continue
            candidates = [i for i in self._item_instances.values()
                          if i.get('owner_id') == identity and i.get('location') == 'POCKET']
            for item in candidates[:16]:
                definition = items.definition(self._item_catalog, item['definition_id'])
                if not trade.tradeable_definition(definition)[0]:
                    continue
                prices = economy.dynamic_prices(vendor, self._economy_state.get('vendors', {}).get(vendor_id), item['definition_id'])
                if not prices:
                    continue
                price = max(1, int(prices.get('buy', 1))) * 10000 * int(item.get('quantity', 1))
                if self._service_money_locked(identity) < max(1, price // 20):
                    continue
                self._auction_post_locked(item['instance_id'], identity, price, price * 2, 120)
                break

    def _auction_command_locked(self, row):
        op = row['op']
        if op == 'AuctionOpen':
            self._seed_local_auctions_locked();self._service_generation += 1;self._service_windows['auction'] = True
            return events('AUCTION_HOUSE_SHOW') + events('AUCTION_ITEM_LIST_UPDATE')
        self._service_session_locked(row, 'auction')
        if op == 'AuctionClose':
            self._service_windows['auction'] = False
            return events('AUCTION_HOUSE_CLOSED')
        if op == 'AuctionQuery':
            query = row.get('query', {})
            if not isinstance(query, dict):
                raise ValueError('AUCTION_QUERY_INVALID')
            name = query.get('name', '')
            if not isinstance(name, str) or len(name) > 128:
                raise ValueError('AUCTION_QUERY_INVALID')
            for key in ('min_level','max_level'):
                integer(query.get(key,0),0,10000)
            for key,limit in (('class',15),('sub_class',64),('quality',6),('inv_type',28)):
                if query.get(key) is not None:integer(query[key],0,limit)
            if type(query.get('usable_only',False)) is not bool:
                raise ValueError('AUCTION_QUERY_INVALID')
            self._auction_pages[0] = integer(query.get('page', 0), 0, 10000)
            self._auction_query = dict(query)
        elif op == 'AuctionPage':
            self._auction_pages[integer(row.get('list'), 1, 2)] = integer(row.get('page', 0), 0, 10000)
        elif op == 'AuctionSort':
            index = integer(row.get('list'), 0, 2);key = row.get('key')
            if key not in ('level', 'quality', 'bid', 'duration', 'buyout', 'status', 'name', 'seller'):
                raise ValueError('AUCTION_SORT_INVALID')
            previous = self._auction_sorts[index]
            descending = not previous[0][1] if previous and previous[0][0] == key else False
            self._auction_sorts[index] = [(key, descending)] + [v for v in previous if v[0] != key][:7]
        elif op == 'AuctionStart':
            self._auction_post_locked(row.get('item'), 'player', row.get('min_bid'), row.get('buyout', 0), row.get('duration'))
        elif op in ('AuctionBid', 'AuctionCancel'):
            auction = next((a for a in self._services['auctions'] if a['id'] == row.get('id')), None)
            if not auction or auction['expires'] <= self._service_now_locked():
                raise ValueError('AUCTION_CHANGED_OR_EXPIRED')
            if op == 'AuctionCancel':
                if auction['owner'] != 'player':
                    raise ValueError('AUCTION_NOT_YOURS')
                self._auction_finish_locked(auction, cancel=True)
            else:
                self._auction_bid_locked(auction, 'player', integer(row.get('amount'), 1, MAX_COPPER - 1))
        else:
            raise ValueError('AUCTION_COMMAND_UNKNOWN')
        return events('AUCTION_ITEM_LIST_UPDATE') + events('AUCTION_OWNED_LIST_UPDATE') + events('AUCTION_BIDDER_LIST_UPDATE')

    def _auction_bid_locked(self, auction, bidder, amount):
        if auction['owner'] == bidder:
            raise ValueError('AUCTION_CANNOT_BID_OWN')
        current = auction['bid'] or auction['min_bid']
        minimum = auction['bid'] + max(1, current // 20) if auction['bid'] else current
        if auction['buyout'] and amount >= auction['buyout']:
            amount = auction['buyout']
        elif amount < minimum:
            raise ValueError('AUCTION_BID_TOO_LOW')
        # Replacing our own bid consumes only the difference, with the held
        # first bid remaining in escrow. Other bids refund via real mail.
        delta = amount - auction['bid'] if auction['bidder'] == bidder else amount
        self._service_money_locked(bidder, -delta)
        if auction['bidder'] and auction['bidder'] != bidder:
            self._service_mail_locked('Auction House', auction['bidder'], 'Överbjuden', money=auction['bid'])
        auction['bidder'] = bidder;auction['bid'] = amount
        if auction['buyout'] and amount == auction['buyout']:
            self._auction_finish_locked(auction)

    def _trade_command_locked(self, row):
        op = row['op']
        if op == 'TradeOpen':
            identity = self._service_person_locked(row.get('target', 'target'), nearby=True)
            if identity == 'player':
                raise ValueError('TRADE_CANNOT_TRADE_SELF')
            stock = [i for i in self._item_instances.values() if i.get('owner_id') == identity
                     and i.get('location') == 'POCKET' and trade.tradeable_definition(items.definition(self._item_catalog, i['definition_id']))[0]]
            if not stock:
                raise ValueError('TRADE_TARGET_HAS_NO_TRADEABLE_ITEMS')
            self._service_generation += 1
            self._service_trade = dict(target=identity, slots={}, target_items=[stock[0]['instance_id']], money=0, offer_revision=0)
            self._service_windows['trade'] = True
            return events('TRADE_SHOW')
        self._service_session_locked(row, 'trade')
        offer = self._service_trade
        identity = self._service_person_locked(offer['target'], nearby=True)
        if op in ('TradeClose', 'TradeCancel'):
            self._service_windows['trade'] = False;self._service_trade = {}
            return events('TRADE_CLOSED')
        if op in ('TradeBegin', 'TradeUnaccept'):
            return events('TRADE_REQUEST_CANCEL') if op == 'TradeUnaccept' else []
        if op == 'TradeConfirmChanged':
            raise ValueError('TRADE_OFFER_CHANGED_ACCEPT_AGAIN')
        if op == 'TradeSet':
            slot = integer(row.get('slot'), 1, 7)
            if slot==7:
                from backend.game_engine_adapter_trade_enchant import select_item
                select_item(self,offer,row.get('item'));offer['offer_revision']+=1
                return events('TRADE_PLAYER_ITEM_CHANGED',7)+events('TRADE_ACCEPT_UPDATE',0,0)
            item = self._service_item_locked(row.get('item'))
            if item['instance_id']==offer.get('enchant_item'):raise ValueError('TRADE_ITEM_ALREADY_OFFERED')
            if item['instance_id'] in [v for k, v in offer['slots'].items() if int(k) != slot]:
                raise ValueError('TRADE_ITEM_ALREADY_OFFERED')
            offer['slots'][str(slot)] = item['instance_id']
            offer['offer_revision'] += 1
            return events('TRADE_PLAYER_ITEM_CHANGED', slot) + events('TRADE_ACCEPT_UPDATE', 0, 0)
        if op == 'TradeClear':
            slot = integer(row.get('slot'), 1, 7)
            if slot==7:
                for key in ('enchant_item','enchant_id','enchant_scroll'):offer.pop(key,None)
            else:offer['slots'].pop(str(slot), None)
            offer['offer_revision'] += 1
            return events('TRADE_PLAYER_ITEM_CHANGED', slot) + events('TRADE_ACCEPT_UPDATE', 0, 0)
        if op == 'TradeMoney':
            offer['money'] = integer(row.get('money'), 0, min(MAX_COPPER, self._service_money_locked()))
            offer['offer_revision'] += 1
            return events('TRADE_MONEY_CHANGED') + events('TRADE_ACCEPT_UPDATE', 0, 0)
        if op == 'TradeTarget':
            item = self._service_item_locked(row.get('item'), identity, 'POCKET')
            offer['target_items'] = [item['instance_id']]
            offer['offer_revision'] += 1
            return events('TRADE_TARGET_ITEM_CHANGED', 1)
        if op=='TradeEnchant':
            from backend.game_engine_adapter_trade_enchant import select_enchant
            select_enchant(self,offer,row.get('enchant_id'));offer['offer_revision']+=1
            return events('TRADE_PLAYER_ITEM_CHANGED',7)+events('TRADE_ACCEPT_UPDATE',0,0)
        if op != 'TradeAccept':
            raise ValueError('TRADE_COMMAND_UNKNOWN')
        if row.get('offer_revision') != offer['offer_revision']:
            raise ValueError('TRADE_OFFER_CHANGED_ACCEPT_AGAIN')
        give = [self._service_item_locked(v) for v in offer['slots'].values()]
        receive = [self._service_item_locked(v, identity, 'POCKET') for v in offer['target_items']]
        if not give and not offer['money'] and not offer.get('enchant_item'):
            raise ValueError('TRADE_EMPTY_PLAYER_OFFER')
        if offer.get('enchant_item'):
            from backend.game_engine_adapter_trade_enchant import apply
            apply(self,offer)
        if len(give) == len(receive) == 1 and not offer['money']:
            # Reuse the original GG atomic transaction, identity memory,
            # equipment choice and power update for the existing barter path.
            result = self.trade_items(identity, give[0]['instance_id'], receive[0]['instance_id'])
            if result.get('error'):
                raise ValueError(result['error'])
        else:
            person = self._individual_state['individuals'][identity]
            refs = person['inventory']
            from backend import game_engine_npc_identity as identity_contract
            if len(refs) - len(receive) + len(give) > identity_contract.MAX_CARRIED_ITEMS:
                raise ValueError('TRADE_TARGET_INVENTORY_FULL')
            if offer['money']:
                self._service_money_locked(delta=-offer['money'])
                self._service_money_locked(identity, offer['money'])
            for item in receive:
                if not self._npc_remove_inventory_ref_locked(person, item['definition_id']):
                    raise ValueError('TRADE_TARGET_STOCK_CHANGED')
            for item in give:
                self._service_move_locked(item, 'POCKET', identity)
                if not self._npc_add_inventory_ref_locked(person, item['definition_id']):
                    raise ValueError('TRADE_TARGET_INVENTORY_FULL')
            for item in receive:
                self._service_move_locked(item, 'INVENTORY', 'player')
            self._last_trade = dict(schema=trade.SCHEMA, action='TRADE', npc_id=identity,
                                   policy='ATOMIC_CANONICAL_MULTI_INSTANCE_TRANSFER',
                                   give=[i['instance_id'] for i in give], receive=[i['instance_id'] for i in receive])
        self._service_windows['trade'] = False;self._service_trade = {}
        return events('TRADE_ACCEPT_UPDATE', 1, 1) + events('TRADE_CLOSED')

    def _group_command_locked(self, row):
        op = row['op'];group = self._services['group'];roster = ['player'] + group['members']
        if op in ('GroupRequestInvite','GroupAccept','GroupDecline'):return self._group_invitation_locked(row)
        if op in ('GroupInvite', 'GroupKick', 'GroupRaid', 'GroupLeader', 'GroupAssistant',
                  'GroupSubgroup', 'GroupSwap', 'GroupLoot', 'GroupThreshold', 'GroupReady') and group['leader'] != 'player':
            raise ValueError('GROUP_LEADER_REQUIRED')
        if op == 'GroupInvite':
            identity = self._service_person_locked(row.get('target', 'target'))
            if identity == 'player' or identity in group['members']:
                raise ValueError('GROUP_ALREADY_MEMBER')
            if len(group['members']) >= (39 if group['raid'] else 4):
                raise ValueError('GROUP_FULL')
            group['members'].append(identity)
            occupied = [1] + [group['subgroups'].get(v, 1) for v in group['members'][:-1]]
            group['subgroups'][identity] = next(n for n in range(1, 9) if occupied.count(n) < 5)
        elif op == 'GroupLeave':
            self._services['group'] = defaults()['group']
        elif op == 'GroupKick':
            identity = self._service_person_locked(row.get('target', ''))
            if identity not in group['members']:
                raise ValueError('GROUP_NOT_MEMBER')
            group['members'].remove(identity);group['subgroups'].pop(identity, None)
        elif op == 'GroupLeader':
            identity = self._service_person_locked(row.get('target', ''))
            if identity not in roster:
                raise ValueError('GROUP_NOT_MEMBER')
            group['leader'] = identity
        elif op == 'GroupRaid':
            if not group['members']:
                raise ValueError('GROUP_REQUIRED')
            group['raid'] = True
        elif op == 'GroupAssistant':
            identity = self._service_person_locked(row.get('target', ''))
            if not group['raid'] or identity not in group['members'] or type(row.get('grant')) is not bool:
                raise ValueError('GROUP_RAID_MEMBER_REQUIRED')
            if row['grant'] and identity not in group['assistants']:
                group['assistants'].append(identity)
            elif not row['grant'] and identity in group['assistants']:
                group['assistants'].remove(identity)
        elif op in ('GroupSubgroup', 'GroupSwap'):
            if not group['raid']:
                raise ValueError('GROUP_RAID_REQUIRED')
            identity = row.get('target') or roster[integer(row.get('index'), 1, len(roster)) - 1]
            if identity not in roster:raise ValueError('GROUP_MEMBER_CHANGED')
            if op == 'GroupSwap':
                other = row.get('other_target') or roster[integer(row.get('other'), 1, len(roster)) - 1]
                if other not in roster:raise ValueError('GROUP_MEMBER_CHANGED')
                first = group['subgroups'].get(identity, 1);second = group['subgroups'].get(other, 1)
                group['subgroups'][identity] = second;group['subgroups'][other] = first
            else:
                subgroup = integer(row.get('subgroup'), 1, 8)
                if sum(group['subgroups'].get(v, 1) == subgroup for v in roster if v != identity) >= 5:
                    raise ValueError('GROUP_SUBGROUP_FULL')
                group['subgroups'][identity] = subgroup
        elif op == 'GroupLoot':
            method = row.get('method')
            if method not in LOOT_METHODS or not group['members']:
                raise ValueError('GROUP_LOOT_METHOD_INVALID')
            threshold = integer(row.get('threshold') or group['threshold'], 2, 4)
            master = self._service_person_locked(row.get('master') or 'player')
            if master not in roster:
                raise ValueError('GROUP_MASTER_NOT_MEMBER')
            group.update(loot_method=method, threshold=threshold, master=master)
        elif op == 'GroupThreshold':
            group['threshold'] = integer(row.get('threshold'), 2, 4)
        elif op == 'GroupMark':
            identity = self._service_person_locked(row.get('target', 'target'))
            group['marks'][identity] = integer(row.get('index'), 0, 8)
        elif op == 'GroupReady':
            if not group['members']:
                raise ValueError('GROUP_REQUIRED')
            group['ready'] = {v: bool(self._combat_state.get('actors', {}).get(v, {}).get('alive', True)) for v in roster}
            return events('READY_CHECK', getattr(self, '_local_character_name', 'Gold Goblin'), 30) + events('READY_CHECK_FINISHED')
        elif op == 'GroupReadyAnswer':
            if not group['ready'] or type(row.get('ready')) is not bool:
                raise ValueError('GROUP_NO_READY_CHECK')
            group['ready']['player'] = row['ready']
            return events('READY_CHECK_CONFIRM', 'player', row['ready'])
        elif op == 'GroupRaidInfo':
            return events('UPDATE_INSTANCE_INFO')
        elif op == 'GroupReadyLine':
            message = text(row.get('text'), 512)
            return events('CHAT_MSG_SYSTEM', message)
        else:
            raise ValueError('GROUP_COMMAND_UNKNOWN')
        return events('PARTY_MEMBERS_CHANGED') + events('RAID_ROSTER_UPDATE')

    def _active_pet_locked(self):
        return next((p for p in self._services['pets'] if p['number'] == self._services['active_pet']), None)

    def _pet_command_locked(self, row):
        from backend.game_engine_nature_catalog import SPECIES, ANIMALS
        op = row['op'];pet = self._active_pet_locked()
        if op == 'PetTame':
            if pet or len(self._services['pets']) >= 1 + self._services['stable_slots']:
                raise ValueError('PET_STABLE_OR_DISMISS_CURRENT_FIRST')
            self._refresh_nature_locked()
            animal = next((r for r in self._nature.rows if r['id'] == row.get('id')), None)
            if (not animal or SPECIES[animal['species']]['domain'] != 'LAND'
                    or animal.get('dead') or math.dist((self._x[0], self._y[0] - .65, self._z[0]),
                                                     (animal['x'], animal['y'], animal['z'])) > 3.75):
                raise ValueError('PET_LIVE_LAND_ANIMAL_IN_REACH_REQUIRED')
            if any(p['id'] == animal['id'] for p in self._services['pets']):
                raise ValueError('PET_ALREADY_OWNED')
            pet = copy.deepcopy(animal)
            pet.update(number=self._service_id_locked(), name=SPECIES[animal['species']]['name'],
                       level=int(self._progression.get('level', 1)), reaction=1, command=1,
                       renamed=False, xp=0, autocast=False, target='',
                       slots=[(7 << 24) | i for i in (2, 1, 0)] + [(128<<24)|PET_STRIKE]+[0]*3 + [(6 << 24) | i for i in (2, 1, 0)])
            self._services['pets'].append(pet);self._services['active_pet'] = pet['number'];self._services['current_pet']=pet['number']
            self._pet_training_defaults_locked(pet)
            profile = self._pet_profile_locked(pet)
            actor = combat.ensure_actor(self._combat_state, profile['id'], profile)
            actor['health'] = min(actor['max_health'], max(1., float(animal.get('health', actor['max_health']))))
            actor['alive'] = True
        elif op.startswith('Stable'):
            return self._stable_command_locked(row)
        elif not pet:
            raise ValueError('PET_ACTIVE_COMPANION_REQUIRED')
        elif op == 'PetRename':
            name = text(row.get('name'), 32)
            if pet['renamed']:
                raise ValueError('PET_ALREADY_RENAMED')
            pet['name'] = name;pet['renamed'] = True
        elif op in ('PetAbandon', 'PetDismiss'):
            self._services['active_pet'] = 0
            if op == 'PetAbandon':
                self._services['pets'].remove(pet);self._nature.states.pop(pet['id'], None)
                self._combat_state.get('actors', {}).pop('pet:'+str(pet['number']), None)
                self._services['current_pet']=0;self._nature._stamp=None
            pet = None
        elif op in ('PetAction', 'PetOrder', 'PetStop'):
            word = pet['slots'][integer(row.get('slot'), 1, 10) - 1] if op == 'PetAction' else integer(row.get('word', 7 << 24 | 1), 0, 0xffffffff)
            kind, value = word >> 24, word & 0xffffff
            if kind == 7 and value in (0, 1, 2):
                pet['command'] = value
                if value == 2:
                    self._pet_begin_attack_locked(pet)
                else:
                    pet['target'] = ''
            elif kind == 6 and value in (0, 1, 2):
                pet['reaction'] = value
                if value==0:pet['target']=''
            elif str(value) in pet['learned'] and kind in (1,128,192):
                if PET_SPELLS[value].get('passive'):raise ValueError('PET_SPELL_PASSIVE')
                pet['pending_spell']=value
                self._pet_begin_attack_locked(pet)
            else:
                raise ValueError('PET_ACTION_NOT_LEARNED')
        elif op == 'PetSlots':
            changes = row.get('slots')
            if not isinstance(changes, list) or len(changes) > 10:
                raise ValueError('PET_BAR_INVALID')
            allowed = {0} | {(kind << 24) | i for kind in (6, 7) for i in (0, 1, 2)} | {(kind<<24)|int(spell) for spell in pet['learned'] for kind in (1,128,192)}
            result = list(pet['slots'])
            for slot, word in changes:
                slot = integer(slot, 0, 9);word = integer(word, 0, 0xffffffff)
                if word not in allowed:
                    raise ValueError('PET_ACTION_NOT_LEARNED')
                result[slot] = word
            pet['slots'] = result
        elif op=='PetSpell':
            if str(row.get('spell_id')) not in pet['learned']:raise ValueError('PET_SPELL_NOT_LEARNED')
            if PET_SPELLS[row['spell_id']].get('passive'):raise ValueError('PET_SPELL_PASSIVE')
            pet['pending_spell']=row['spell_id']
            self._pet_begin_attack_locked(pet)
        elif op=='PetAutocast':
            spell=row.get('spell_id')
            if row.get('slot') is not None:spell=pet['slots'][integer(row['slot'],1,10)-1]&0xffffff
            if str(spell) not in pet['learned']:raise ValueError('PET_SPELL_NOT_LEARNED')
            if PET_SPELLS[spell].get('passive'):raise ValueError('PET_SPELL_PASSIVE')
            pet['learned'][str(spell)]=not pet['learned'][str(spell)]
            if spell==PET_STRIKE:pet['autocast']=pet['learned'][str(spell)]
        elif op=='PetRevive':
            self._service_session_locked(row,'stable')
            actor=combat.ensure_actor(self._combat_state,'pet:'+str(pet['number']),self._pet_profile_locked(pet))
            if actor.get('alive',True):raise ValueError('PET_ALREADY_ALIVE')
            self._service_money_locked(delta=-100000)
            actor.update(alive=True,health=actor['max_health'],engaged_target='',respawn_at=0.)
            pet.update(command=1,target='',x=self._x[0]+1,z=self._z[0]+1)
        else:
            raise ValueError('PET_COMMAND_UNKNOWN')
        self._publish_companions_locked()
        return events('UNIT_PET', 'player') + events('PET_BAR_UPDATE') + events('PET_UI_UPDATE')

    def _stable_command_locked(self, row):
        op = row['op']
        if op == 'StableOpen':
            self._service_generation += 1
            self._service_windows['stable'] = True
            return events('PET_STABLE_SHOW')
        self._service_session_locked(row, 'stable')
        active = self._active_pet_locked()
        if op == 'StableClose':
            self._service_windows['stable'] = False
            return events('PET_STABLE_CLOSED')
        if op == 'StableBuy':
            count = self._services['stable_slots']
            if count >= 2:
                raise ValueError('PET_STABLE_FULLY_BOUGHT')
            self._service_money_locked(delta=-10000 * (count + 1));self._services['stable_slots'] += 1
        elif op == 'StableStore':
            if not active or len(self._services['pets']) - 1 >= self._services['stable_slots']:
                raise ValueError('PET_STABLE_NO_FREE_SLOT')
            self._services['active_pet'] = 0
            self._services['current_pet'] = 0
        elif op in ('StableTake', 'StableSwap'):
            chosen = next((p for p in self._services['pets'] if p['number'] == row.get('number')), None)
            if not chosen or chosen == active or op == 'StableTake' and active:
                raise ValueError('PET_STABLE_SELECTION_INVALID')
            self._services['active_pet'] = chosen['number']
            self._services['current_pet'] = chosen['number']
            chosen.update(x=self._x[0] + 1, z=self._z[0] + 1, target='', command=1)
        else:
            raise ValueError('PET_STABLE_COMMAND_UNKNOWN')
        self._publish_companions_locked()
        return events('PET_STABLE_UPDATE') + events('UNIT_PET', 'player') + events('PET_BAR_UPDATE')

    def _assert_service_custody_locked(self):
        claims = {}
        for row in self._services['mail']:
            if row['item']:
                if row['item'] in claims:
                    raise ValueError('SERVICE_DUPLICATE_ATTACHMENT')
                claims[row['item']] = ('MAIL', row['recipient'])
        for row in self._services['auctions']:
            if row['item'] in claims:
                raise ValueError('SERVICE_DUPLICATE_ATTACHMENT')
            claims[row['item']] = ('AUCTION', row['owner'])
        for key, (location, owner) in claims.items():
            item = self._item_instance_locked(key)
            if not item or (item.get('location'), item.get('owner_id')) != (location, owner):
                raise ValueError('SERVICE_ESCROW_DESYNCHRONIZED')

    def _item_text_command_locked(self, row):
        op = row['op']
        if op == 'ItemTextOpen':
            item = self._item_instance_locked(row.get('item'))
            if not item or (item.get('owner_id'), item.get('location')) != ('player', 'INVENTORY'):
                raise ValueError('ITEM_NOT_IN_INVENTORY')
            letter = item.get('letter')
            if not isinstance(letter, dict):raise ValueError('ITEM_HAS_NO_TEXT')
            self._service_text = dict(item=letter['subject'], text=letter['body'],
                                     creator=letter['sender'], page=1, has_next=False)
            return events('ITEM_TEXT_BEGIN') + events('ITEM_TEXT_READY')
        if op == 'ItemTextClose':
            self._service_text = None
            return events('ITEM_TEXT_CLOSED')
        if op == 'ItemTextPage' and self._service_text:
            integer(row.get('delta'), -1, 1)
            return events('ITEM_TEXT_READY')
        raise ValueError('ITEM_TEXT_SESSION_CLOSED')

    def _service_command_locked(self, row):
        # A committed cross-character intent must never enter the older
        # in-memory rollback wrapper: recovery owns that durable transaction.
        shared = getattr(self, '_shared_service_command_locked', None)
        if shared is not None:
            result = shared(row)
            if result is not None:
                return result
        attrs = ('_services', '_item_instances', '_inventory', '_economy_state',
                 '_individual_state', '_combat_state', '_service_trade', '_service_windows',
                 '_auction_query', '_auction_pages', '_auction_sorts', '_last_trade',
                 '_event_journal', '_persistence_revision', '_service_text', '_quest_state', '_profession_state')
        attrs += ('_service_generation',)
        if hasattr(self,'_spell_state'):attrs += ('_spell_state',)
        attrs += ('_item_pending_equips','_item_pending_use','_item_binding_generation','_gift_wrap','_gift_wrap_generation','_tabard_draft')
        attrs += ('_item_target','_item_target_generation')
        attrs += ('_dressup',)
        attrs += ('_battlefield_map','_battlefield_positions_at','_inspect_honor_owner')
        if row.get('op','').startswith('Instance'):
            attrs += SESSION_ROLLBACK_ATTRIBUTES + ('_faction_state',)
        if row.get('op','').startswith('Loot'):attrs += ('_engine_loot',)
        attrs += ('_opening_cinematic','_camera_distance','_camera_pitch','_camera_yaw','_camera_yaw_offset','_camera_view_revision')
        if row.get('op','').startswith('Cinematic'):
            attrs += ('_legacy_held','_legacy_autorun','_legacy_jump','_follow_id','_actions','_input','_vx','_vz')
        if row.get('op','').startswith('Trade'):
            attrs += ('_npc_interaction_count','_npc_last_interaction','_last_item_interaction')
        if row.get('op','').startswith(('Inventory','Petition')):attrs += ('_item_counter',)
        if row.get('op','').startswith('Tabard'):attrs += ('_item_counter',)
        if row.get('op','').startswith('ItemBinding'):
            attrs += ('_last_item_interaction','_action_item_cooldowns','_resource')
        if row.get('op')=='SkillAbandon':attrs += ('_engine_craft_repeat', '_engine_craft_error')
        if row.get('op','').startswith(('Death','Duel','Binder','Taxi','Summon','Stuck','Battlefield','Instance')):
            attrs += ('_x','_y','_z','_vx','_vy','_vz','_legacy_held','_legacy_autorun','_follow_id',
                      '_jump_held','_grapple_anchor','_grapple_projectile','_input','_actions',
                      '_character_actions','_character_action_serial','_engine_loot','_engine_craft_book','_engine_craft_repeat',
                      '_engine_craft_error','_engine_quest_panel','_engine_gossip_hidden','_open_merchant_id',
                      '_open_stash_container_id','_dialogue_state')
            attrs += ('_movement_mode','_vehicle_kind','_boat_entity_index','_jump_count',
                      '_double_jump_pose_remaining_s','_stand_state','_grounded')
            attrs += ('_npc_state','_npc_reason')
        backup = {key: copy.deepcopy(getattr(self, key)) for key in attrs}
        nature_states = copy.deepcopy(self._nature.states)
        previous_atomic=getattr(self,'_service_atomic_active',False)
        self._service_atomic_active=True
        try:
            self._assert_service_custody_locked()
            op = row.get('op', '')
            if not isinstance(op, str):
                raise ValueError('SERVICE_COMMAND_INVALID')
            if op.startswith('Enchant') and op!='EnchantCancel':
                if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
                if self._services['taxi_flight']:raise ValueError('TAXI_IN_PROGRESS')
            if (not self._combat_state.get('actors',{}).get('player',{}).get('alive',True)
                    and op.startswith(('Trade','Auction','Mail','Loot','Trainer','Stable','PetFeed','PetUnlearn','PetAction','PetOrder','PetSpell','PetTame','PetRevive','Binder','Inventory','Skill','Petition','Tabard'))
                    and not op.endswith('Close')):raise ValueError('PLAYER_DEFEATED')
            if self._services['taxi_flight'] and op.startswith(('Trade','Auction','Mail','Loot','Trainer','Stable','PetTame','PetAction','PetOrder','PetSpell','PetRevive','Binder')) and not op.endswith('Close'):raise ValueError('TAXI_IN_PROGRESS')
            if self._services['taxi_flight'] and op=='InventoryDropOnUnit':raise ValueError('TAXI_IN_PROGRESS')
            if self._services['taxi_flight'] and op in ('InventoryWrapOpen','InventoryWrap','InventoryUnwrap'):raise ValueError('TAXI_IN_PROGRESS')
            if self._services['taxi_flight'] and op.startswith(('Petition','Tabard')) and not op.endswith('Close'):raise ValueError('TAXI_IN_PROGRESS')
            if op.startswith('ItemBinding') and not op.endswith(('Cancel','Answer')):
                if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
                if self._services['taxi_flight']:raise ValueError('TAXI_IN_PROGRESS')
            if op=='ItemBindingEquipAnswer' and row.get('accept'):
                if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
                if self._services['taxi_flight']:raise ValueError('TAXI_IN_PROGRESS')
            if op.startswith('Support'):
                result = self._support_command_locked(row)
            elif op.startswith('Battlefield') or op=='InspectHonor':
                result = self._battlefield_command_locked(row)
            elif op.startswith(('Instance','MeetingStone')):
                count=row.get('requests',1)
                if type(count) is not int or not 1<=count<=16:raise ValueError('INSTANCE_REQUEST_CAPACITY')
                result = self._instance_command_locked(row)
            elif op.startswith('Cinematic'):
                count=row.get('requests',1)
                if type(count) is not int or not 1<=count<=16:raise ValueError('CINEMATIC_REQUEST_CAPACITY')
                result=self._opening_cinematic_command_locked(row)
            elif op.startswith('Petition'):
                result = self._petition_command_locked(row)
            elif op.startswith('Tabard'):
                result = self._tabard_command_locked(row)
            elif op.startswith('QuestShare'):
                result = self._party_quest_command_locked(row)
            elif op.startswith(('Taxi','Summon','Stuck')):
                result = self._travel_command_locked(row)
            elif op=='ItemInfo':
                result = self._item_info_command_locked(row)
            elif op=='ItemSetInfo':
                result = self._item_set_info_locked(row)
            elif op=='SpellTooltipRequest':
                spell=integer(row.get('id'),1,2**32-1)
                if type(row.get('pet')) is not bool:raise ValueError('SPELL_CASTER_INVALID')
                known=(self._active_pet_locked() is not None and spell in PET_SPELLS) if row['pet'] else (any(spell_identity(key)==spell for key in self._content.get('abilities',{})) or any(spell_identity('profession.'+key)==spell for key in self._gear_tables.get('professions',{})))
                if not known:raise ValueError('SPELL_TEMPLATE_NOT_LOCAL')
                # Known views are supplied with this canonical snapshot; this
                # read neither learns nor casts the requested spell.
                result=[]
            elif op.startswith('ItemBinding'):
                result = self._item_binding_command_locked(row)
            elif op.startswith('Enchant'):
                result = self._enchant_cursor_command_locked(row)
            elif op.startswith('Dressup'):
                result = self._dressup_command_locked(row)
            elif op in ('Inspect','InspectClear'):
                result = self._inspection_command_locked(row)
            elif op=='AuraCancel':
                result = self._aura_command_locked(row)
            elif op.startswith('InventoryWrap') or op=='InventoryUnwrap':
                result = self._wrapping_command_locked(row)
            elif op.startswith('Inventory'):
                result = self._inventory_service_command_locked(row)
            elif op.startswith('Channel'):
                result = self._channel_command_locked(row)
            elif op.startswith('Death'):
                result = self._death_command_locked(row)
            elif op.startswith('Binder'):
                result = self._bind_command_locked(row)
            elif op.startswith('Duel'):
                result = self._duel_command_locked(row)
            elif op.startswith('Guild'):
                result = self._guild_command_locked(row)
            elif op.startswith('Loot'):
                if op in ('LootPickup','LootBindConfirm','LootBindCancel'):result=self._loot_pickup_command_locked(row)
                elif op in ('LootStart','LootMasterSlot'):
                    source=self._loot_source_locked();shown=self._engine_loot
                    item=self._item_instance_locked(row.get('item'))
                    if (not source or shown.get('session')!=row.get('loot_session') or not item
                            or item['instance_id'] not in shown['ids']
                            or not self._loot_item_at_source_locked(item,source)):raise ValueError('LOOT_SOURCE_CHANGED_OR_CLOSED')
                    if op=='LootMasterSlot':
                        roll=next((r for r in self._services['loot_rolls'] if r['item']==item['instance_id']),None)
                        if roll is None:
                            self._group_loot_route_locked(item,source)
                            roll=next((r for r in self._services['loot_rolls'] if r['item']==item['instance_id']),None)
                        if not roll:raise ValueError('LOOT_MASTER_ITEM_REQUIRED')
                        result=self._loot_roll_command_locked(dict(op='LootMasterGive',id=roll['id'],
                            target=self._service_person_locked(row.get('target'))))
                    else:result=self._group_loot_route_locked(item,source) or []
                else:result=self._loot_roll_command_locked(row)
            elif op=='SkillAbandon':
                result = self._skill_command_locked(row)
            elif op.startswith('Trainer') and (row.get('mode')=='PROFESSION' if op=='TrainerOpen' else self._services.get('trainer_kind')=='PROFESSION'):
                result = self._profession_trainer_command_locked(row)
            elif op.startswith('Trainer') or op in ('PetFeed','PetUnlearn'):
                result = self._pet_training_command_locked(row)
            elif op.startswith('Mail'):
                result = self._mail_command_locked(row)
            elif op.startswith('Auction'):
                result = self._auction_command_locked(row)
            elif op.startswith('Trade'):
                result = self._trade_command_locked(row)
            elif op.startswith('Group'):
                result = self._group_command_locked(row)
            elif op.startswith(('Pet', 'Stable')):
                result = self._pet_command_locked(row)
            elif op.startswith('ItemText'):
                result = self._item_text_command_locked(row)
            else:
                raise ValueError('SERVICE_COMMAND_UNKNOWN')
            self._assert_service_custody_locked()
            # Reading a catalogue advances the in-memory monotonic clock, but
            # does not rewrite the complete character save. Real mutations
            # still checkpoint that clock with the rest of their transaction.
            service_keys=set(self._services)-{'clock'};old_keys=set(backup['_services'])-{'clock'}
            durable=(service_keys!=old_keys or any(self._services[k]!=backup['_services'][k] for k in service_keys)
                     or any(getattr(self,key)!=backup[key] for key in
                            ('_item_instances','_inventory','_economy_state','_individual_state','_combat_state','_quest_state','_profession_state')))
            self._services['revision'] += 1
            self._append_event_locked('LOCAL_SERVICE', op, actor_id='player',
                                      payload={'revision': self._services['revision']})
            if durable:
                self.save_state(snapshot=False)
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as error:
            for key, value in backup.items():
                setattr(self, key, value)
            self._nature.states = nature_states;self._nature._stamp = None
            self._companion_visual_stamp = None
            self._refresh_nature_locked()
            self._ui_snapshot_base = None;self._render_snapshot_cache = None
            if isinstance(error, OSError):
                raise ValueError('SERVICE_SAVE_FAILED') from error
            raise
        finally:self._service_atomic_active=previous_atomic
        if op in ('PetAbandon','PetDismiss','StableStore','StableTake','StableSwap','PetRevive','PetTame'):
            from backend.game_engine_adapter_pet_world import cancel
            cancel(self,op)
        self._ui_snapshot_base = None;self._render_snapshot_cache = None
        return result

    def _settle_services_locked(self):
        if not hasattr(self, '_services') or getattr(self,'_service_atomic_active',False):
            return
        now = self._service_now_locked()
        if now < self._service_next_tick:
            return
        self._service_next_tick = now + 1
        self._tick_battlefields_locked()
        self._tick_instance_sessions_locked()
        attrs = ('_services', '_item_instances', '_inventory', '_economy_state',
                 '_individual_state', '_event_journal', '_persistence_revision', '_quest_state')
        backup = {key: copy.deepcopy(getattr(self, key)) for key in attrs}
        try:
            self._settle_service_assets_locked(now)
            self._settle_group_loot_locked(now)
            self._settle_petitions_locked(now)
            self._assert_service_custody_locked()
            if self._services['revision'] != backup['_services']['revision']:
                self.save_state(snapshot=False)
                self._ui_snapshot_base = None;self._render_snapshot_cache = None
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            for key, value in backup.items():
                setattr(self, key, value)
            self._append_event_locked('LOCAL_SERVICE_RETRY', 'Local settlement will retry after saving is available.', actor_id='player')

    def _settle_service_assets_locked(self, now):
        for auction in list(self._services['auctions']):
            if auction['expires'] > now:
                continue
            # A full mailbox postpones settlement. Escrow remains intact.
            backup = copy.deepcopy((self._services, self._item_instances, self._inventory))
            try:
                self._auction_finish_locked(auction);self._services['revision'] += 1
            except ValueError:
                self._services, self._item_instances, self._inventory = backup
                break
        for mail in self._services['mail']:
            if mail['expires'] <= now and not mail['returned'] and mail['sender'] != 'Auction House':
                mail['sender'], mail['recipient'] = mail['recipient'], mail['sender']
                mail['returned'] = True;mail['cod'] = 0;mail['read'] = False
                if mail['item']:
                    self._service_move_locked(self._item_instance_locked(mail['item']), 'MAIL', mail['recipient'])
                self._services['revision'] += 1
        for mail in list(self._services['mail']):
            identity = mail['recipient']
            if identity == 'player':
                continue
            person = self._individual_state.get('individuals', {}).get(identity)
            if not isinstance(person, dict):
                continue
            backup = copy.deepcopy((self._services, self._item_instances, self._inventory,
                                    self._economy_state, self._individual_state))
            try:
                if mail['cod']:
                    self._service_money_locked(identity, -mail['cod'])
                    self._service_mail_locked(identity, mail['sender'], 'Postförskott', money=mail['cod'])
                if mail['item']:
                    item = self._service_item_locked(mail['item'], identity, 'MAIL')
                    if not self._npc_add_inventory_ref_locked(person, item['definition_id']):
                        raise ValueError('MAIL_RECIPIENT_POCKET_FULL')
                    self._service_move_locked(item, 'POCKET', identity)
                if mail['money']:
                    self._service_money_locked(identity, mail['money'])
                self._services['mail'].remove(mail);self._services['revision'] += 1
            except ValueError:
                (self._services, self._item_instances, self._inventory,
                 self._economy_state, self._individual_state) = backup
                break
        if now>=self._services['market_at'] and any(a['owner']=='player' for a in self._services['auctions']):
            self._services['market_at']=now+30
            for auction in list(self._services['auctions']):
                if auction['owner']!='player' or auction['expires']<=now:continue
                item=self._item_instance_locked(auction['item'])
                if not item:continue
                for vendor_id,vendor in self._vendor_catalog.items():
                    identity=vendor.get('npc_id','');person=self._individual_state.get('individuals',{}).get(identity,{})
                    if len(person.get('inventory',[]))>=16:continue
                    held=sum(int(i.get('quantity',1)) for i in self._item_instances.values() if i.get('owner_id')==identity and i.get('location')=='POCKET' and i.get('definition_id')==item['definition_id'])
                    preference=economy.preference_for(vendor,item['definition_id'])
                    if held+int(item.get('quantity',1))>max(2,int(preference.get('target_stock',0))):continue
                    quote=economy.dynamic_prices(vendor,self._economy_state['vendors'][vendor_id],item['definition_id'],held)
                    if not quote:continue
                    budget=int(quote['sell'])*10000*int(item.get('quantity',1))
                    minimum=auction['min_bid'] if not auction['bid'] else auction['bid']+max(1,auction['bid']//20)
                    amount=auction['buyout'] if auction['buyout'] and auction['buyout']<=budget else minimum
                    if amount>budget or auction['bidder']==identity or self._service_money_locked(identity)<amount:continue
                    backup=copy.deepcopy((self._services,self._item_instances,self._inventory,self._economy_state,self._individual_state))
                    try:self._auction_bid_locked(auction,identity,amount);self._services['revision']+=1
                    except ValueError:(self._services,self._item_instances,self._inventory,self._economy_state,self._individual_state)=backup
                    return

    def _service_unit_locked(self, identity):
        if identity == 'player':
            return dict(id='player', guid=1, name=getattr(self, '_local_character_name', 'Gold Goblin'),
                        level=int(self._progression.get('level', 1)), health=self._combat_state.get('actors', {}).get('player', {}).get('health', 100),
                        max_health=self._combat_state.get('actors', {}).get('player', {}).get('max_health', 100), online=True)
        index = self._npc_index_for_id_locked(identity)
        person = self._individual_state.get('individuals', {}).get(identity, {})
        actor = self._combat_state.get('actors', {}).get(identity, {})
        target=actor.get('engaged_target','');target_index=self._npc_index_for_id_locked(target)
        return dict(id=identity, guid=index + 1 if index is not None else 0,
                    name=person.get('name', identity), level=int(person.get('progression', {}).get('level', 1)),
                    x=self._x[index] if index is not None else 0.,y=self._y[index] if index is not None else 0.,z=self._z[index] if index is not None else 0.,
                    health=actor.get('health', 0), max_health=actor.get('max_health', 1),
                    online=index is not None and self._alive[index], class_name=str(person.get('progression', {}).get('class_id', '')),
                    distance_sq=sum((values[0]-values[index])**2 for values in (self._x,self._y,self._z)) if index is not None else 1e12,
                    target_guid=1 if target=='player' else 0xfffffff0 if target.startswith('pet:') else target_index+1 if target_index is not None else 0,
                    inspectable=identity in self._services['group']['members'] or identity in self._services['guild'].get('members',{}))

    def _service_item_view_locked(self, key):
        item = self._item_instance_locked(key)
        return items.instance_view(self._item_catalog, item, sim_time=self._sim_time) if item else None

    def _services_view_locked(self):
        self._settle_services_locked()
        inbox = []
        for mail in self._inbox_locked():
            value = dict(mail)
            value['sender_name'] = (self._service_unit_locked(mail['sender'])['name']
                                    if mail['sender'] != 'Auction House' else mail['sender'])
            value['attachment'] = self._service_item_view_locked(mail['item']) if mail['item'] else None
            value['days_left'] = max(0, (mail['expires'] - self._services['clock']) / 86400)
            inbox.append(value)
        auction_lists = []
        live = []
        for auction in self._services['auctions']:
            value = dict(auction);value['attachment'] = self._service_item_view_locked(auction['item'])
            value['owner_name'] = self._service_unit_locked(auction['owner'])['name']
            remaining = auction['expires'] - self._services['clock']
            value['time_left'] = 1 if remaining < 1800 else 2 if remaining < 7200 else 3 if remaining < 43200 else 4
            live.append(value)
        for n in range(3):
            selected = live if n == 0 else [a for a in live if a['bidder' if n == 1 else 'owner'] == 'player']
            if n == 0:
                query = self._auction_query;needle = str(query.get('name', '')).casefold()
                selected = [a for a in selected if a['attachment'] and needle in a['attachment']['name'].casefold()]
                from backend.game_engine_adapter_gameplay import QUALITY
                selected = [a for a in selected if (not query.get('min_level') or a['attachment'].get('level', 1) >= query['min_level'])
                            and (not query.get('max_level') or a['attachment'].get('level', 1) <= query['max_level'])
                            and (query.get('quality') is None or QUALITY.get(a['attachment'].get('rarity'), 1) >= query['quality'])]
                from backend.game_engine_adapter_gameplay import EQUIPMENT_SLOTS
                def matches(a):
                    item=a['attachment'];kind=item.get('kind','ITEM')
                    item_class=2 if kind=='WEAPON' else 4 if kind in ('ARMOR','ACCESSORY') else 0 if kind=='CONSUMABLE' else 7
                    if query.get('class') is not None and query['class']!=item_class:return False
                    if query.get('inv_type') is not None and query['inv_type'] not in [EQUIPMENT_SLOTS.get(s) for s in item.get('equip_slots',[])]:return False
                    if query.get('usable_only') and item.get('level',1)>self._progression.get('level',1):return False
                    # GG's catalog has no original DBC weapon/armor subtypes.
                    # A specific original subtype cannot match an invented one.
                    return query.get('sub_class') is None
                selected=[a for a in selected if matches(a)]
            for key, descending in reversed(self._auction_sorts[n]):
                def sort_key(a):
                    item = a['attachment'] or {}
                    from backend.game_engine_adapter_gameplay import QUALITY
                    return {'level': item.get('level', 1), 'quality': QUALITY.get(item.get('rarity'), 1),
                            'name': item.get('name', '').casefold(), 'bid': a['bid'] or a['min_bid'],
                            'buyout': a['buyout'], 'duration': a['expires'], 'seller': a['owner_name'].casefold(),
                            'status': int(a['bidder'] == 'player')}[key]
                selected = sorted(selected, key=sort_key, reverse=descending)
            offset = self._auction_pages[n] * 50
            auction_lists.append(dict(rows=selected[offset:offset + 50], total=len(selected), sort=self._auction_sorts[n]))
        offer = dict(self._service_trade)
        if offer:
            offer['player_rows'] = {k: self._service_item_view_locked(v) for k, v in offer['slots'].items()}
            offer['target_rows'] = [self._service_item_view_locked(v) for v in offer['target_items']]
            if offer.get('enchant_item'):
                offer['player_rows']['7']=self._service_item_view_locked(offer['enchant_item'])
                if offer['player_rows']['7']:offer['player_rows']['7']['enchantment']=enchants.definition(offer.get('enchant_id','')).get('name','')
            offer['enchant_scrolls']=[dict(id=i['instance_id'],enchant_id=i['scroll_enchant_id'],name=enchants.definition(i['scroll_enchant_id']).get('name',i['name']))
                for i in self._item_instances.values() if i.get('owner_id')=='player' and i.get('location')=='INVENTORY' and i.get('scroll_enchant_id')][:32]
            offer['target_name'] = self._service_unit_locked(offer['target'])['name']
            offer['stock'] = [self._service_item_view_locked(i['instance_id']) for i in self._item_instances.values()
                              if i.get('owner_id') == offer['target'] and i.get('location') == 'POCKET'
                              and trade.tradeable_definition(items.definition(self._item_catalog, i['definition_id']))[0]][:16]
        group = copy.deepcopy(self._services['group'])
        group['roster'] = [self._service_unit_locked(v) for v in ['player'] + group['members']]
        group['mark_guids'] = {str(self._service_unit_locked(v)['guid']): mark for v,mark in group['marks'].items()}
        for member in group['roster']:member['raid_target'] = group['marks'].get(member['id'], 0)
        pet = copy.deepcopy(self._active_pet_locked())
        if pet:
            pet.update(self._pet_training_view_locked(pet))
            actor = self._combat_state.get('actors', {}).get('pet:' + str(pet['number']), {})
            pet.update(health=actor.get('health', 100), max_health=actor.get('max_health', 100), guid=0x40000000 + pet['number'])
        active = self._services['active_pet']
        from backend.game_engine_nature_catalog import SPECIES, ANIMALS
        nearby = [dict(id=a['id'], name=SPECIES[a['species']]['name'], species=a['species'],
                       distance=round(math.hypot(a['x']-self._x[0], a['z']-self._z[0]), 1))
                  for a in self._nature.rows if SPECIES[a['species']]['domain']=='LAND'
                  and a['species'] in ANIMALS
                  and not a.get('dead') and not any(p['id']==a['id'] for p in self._services['pets'])
                  and math.hypot(a['x']-self._x[0], a['z']-self._z[0])<8][:12]
        value = dict(version=1, revision=self._services['revision'], session=self._service_generation,
                    mode='LOCAL_WORLD', money=self._service_money_locked(),
                    mail=dict(open=self._service_windows['mail'], rows=inbox, unread=sum(not m['read'] for m in inbox)),
                    auction=dict(open=self._service_windows['auction'], lists=auction_lists),
                    trade=dict(open=self._service_windows['trade'], **offer), group=group, pet=pet, text=self._service_text,
                    guild=self._guild_view_locked(), loot_rolls=self._loot_roll_view_locked(), trainer=self._trainer_view_locked(),
                    item_binding=self._item_binding_view_locked(),
                    item_targeting=self._item_targeting_view_locked(),
                    dressup=self._dressup_view_locked(),
                    pet_spell_templates=[dict(row) for row in PET_SPELLS.values()] if self._active_pet_locked() else [],
                    inventory_cursor=self._wrapping_view_locked(),
                    lifecycle=self._lifecycle_view_locked(),
                    channels=self._channels_view_locked(),
                    inspection=self._inspection_view_locked(),auras=self._auras_view_locked(),
                    item_templates=self._item_templates_view_locked(),
                    item_requirements=self._item_requirements_view_locked(),
                    item_sets=self._item_sets_view_locked(),
                    cinematic=self._opening_cinematic_view_locked(),
                    battlefields=self._battlefields_view_locked(),
                    instance_sessions=self._instance_sessions_view_locked(),
                    travel=self._taxi_view_locked(),
                    party_quests=self._party_quests_view_locked(),
                    support_note=self._support_view_locked(),skills=self._skills_view_locked(),
                    petition=self._petition_view_locked(),
                    tabard=self._tabard_view_locked(),
                    guild_invite=copy.deepcopy(self._services['guild_invite']),group_invite=copy.deepcopy(self._services['group_invite']),
                    people=[self._service_unit_locked(v) for v in self._individual_state.get('individuals',{}) if self._npc_index_for_id_locked(v) is not None][:64],
                    stable=dict(open=self._service_windows['stable'], bought=self._services['stable_slots'],
                                price=10000 * (self._services['stable_slots'] + 1),
                                pets=[{key:p[key] for key in ('number','name','level','species')} for p in self._services['pets']], active=active,current=self._services['current_pet']), nearby_animals=nearby)
        shared = getattr(self, '_shared_services_view_locked', None)
        return shared(value) if shared is not None else value

    def _group_steering_locked(self, index, decision):
        if self._npc_ids[index] not in self._services['group']['members']:
            return decision
        slot = self._services['group']['members'].index(self._npc_ids[index])
        angle = (slot % 8) * math.tau / 8
        x = self._x[0] + math.sin(angle) * (2.5 + slot // 8)
        z = self._z[0] + math.cos(angle) * (2.5 + slot // 8)
        target=self._combat_state.get('actors',{}).get('player',{}).get('engaged_target')
        if target and target not in self._services['group']['members']:
            enemy=self._npc_index_for_id_locked(target)
            if enemy is not None and self._alive[enemy]:
                x=self._x[enemy]+math.sin(angle)*1.5;z=self._z[enemy]+math.cos(angle)*1.5
        distance = math.hypot(x - self._x[index], z - self._z[index])
        return decision._replace(state='FOLLOW', target_x=x, target_z=z, target_distance=distance,
                                 desired_speed=3.5 if distance > 1 else 0., reason='GROUP_FOLLOW')

    def _publish_companions_locked(self):
        if not hasattr(self, '_nature') or not hasattr(self, '_services'):
            return
        from backend.game_engine_nature import parts_for, visual_key
        owned = {p['id'] for p in self._services['pets']}
        previous=getattr(self,'_companion_render_ids',set())
        if not owned and not previous:return
        pet=self._active_pet_locked()
        if pet:
            from backend.game_engine_adapter_pet_world import pending
            if pending(self,pet):pet=None
        actor=self._combat_state.get('actors',{}).get('pet:'+str((pet or {}).get('number',0)),{})
        stamp=(id(self._nature.groups),tuple(sorted(owned)),tuple((pet or {}).get(k) for k in ('number','x','y','z','yaw','vx','vz')),actor.get('alive',True),int(self._sim_time*60))
        if stamp==getattr(self,'_companion_visual_stamp',None):return
        for key, rows in self._nature.groups.items():
            self._nature.groups[key] = [r for r in rows if r['id'] not in owned|previous]
        self._nature.rows = [r for r in self._nature.rows if r['id'] not in owned|previous]
        self._companion_render_ids=set(owned)
        for identity in owned:
            self._nature.states.setdefault(identity, {})['hidden_until'] = 1e12
        if not pet:
            self._nature.revision+=1
            if self._nature._stamp:self._nature._stamp=(*self._nature._stamp[:4],self._nature.revision)
            self._companion_visual_stamp=stamp
            return
        actor = self._combat_state.get('actors', {}).get('pet:' + str(pet['number']), {})
        row = dict(pet, dead=not actor.get('alive', True),
                   idle=math.hypot(pet.get('vx', 0), pet.get('vz', 0)) < .1)
        self._nature.rows.append(row)
        for part in parts_for(pet['species']):
            visual = self._nature._render(row)
            if part in ('motion_a', 'motion_b') and not row['idle']:
                visual['pitch'] = math.sin(self._sim_time * 7) * (18 if part == 'motion_a' else -18)
            self._nature.groups.setdefault(visual_key(pet, part), []).append(visual)
        self._nature.revision += 1
        if self._nature._stamp:self._nature._stamp=(*self._nature._stamp[:4],self._nature.revision)
        self._companion_visual_stamp=stamp

    def _pet_profile_locked(self,pet):
        from backend.game_engine_nature_catalog import SPECIES
        hp=SPECIES[pet['species']]['health']
        happiness=pet.get('happiness',600000)
        factor=.75 if happiness<333333 else 1.25 if happiness>=666666 else 1.
        guard=4 if str(0x800103) in pet.get('learned',{}) else 1
        return combat.profile(dict(level=pet['level'],derived_stats={'health':hp,'damage':max(1,hp*.12)*factor,'armor':guard}),
                              actor_id='pet:'+str(pet['number']),kind='PET')

    def _pet_begin_attack_locked(self,pet):
        target=self._combat_target_id
        if target=='player' or target in self._services['group']['members'] or not self._npc_index_for_id_locked(target):
            raise ValueError('PET_HOSTILE_TARGET_REQUIRED')
        pet.update(target=target,command=2)

    def _service_combat_fx_locked(self,result,x,y,z):
        for i in range(4):
            angle=i*math.pi/2
            self._spawn_particle_locked(x,y+.3,z,math.sin(angle)*1.2,1.5,math.cos(angle)*1.2,.3,'#e8bb70')

    def _tick_group_combat_locked(self):
        if self._tick%3:return
        target=self._combat_state.get('actors',{}).get('player',{}).get('engaged_target')
        if not target or target=='player' or target in self._services['group']['members']:return
        enemy=self._npc_index_for_id_locked(target)
        if enemy is None or not self._alive[enemy]:return
        defender=self._npc_combat_profile_locked(target,self._individual_state['individuals'].get(target,{}))
        for identity in self._services['group']['members']:
            index=self._npc_index_for_id_locked(identity)
            if index is None or not self._alive[index]:continue
            profile=self._npc_combat_profile_locked(identity,self._individual_state['individuals'].get(identity,{}))
            if math.hypot(self._x[index]-self._x[enemy],self._z[index]-self._z[enemy])>profile['attack_range_m'] or not self._npc_line_of_sight_locked(enemy):continue
            result=combat.resolve_attack(self._combat_state,attacker_id=identity,defender_id=target,attacker_profile=profile,
                defender_profile=defender,sim_time=self._sim_time,seed=self._tick+index*31,action_id='group_assist')
            if result.get('ok'):
                self._last_combat=result;self._start_character_action_locked(identity,'UnarmedAttack')
                self._service_combat_fx_locked(result,self._x[enemy],self._y[enemy],self._z[enemy])
                self._append_event_locked('GROUP_ATTACK',identity,actor_id=identity,target_id=target,payload=result)
            if result.get('defeated'):
                self._handle_npc_defeat_locked(target,enemy,result);break
            elif result.get('ok'):
                reply=combat.resolve_attack(self._combat_state,attacker_id=target,defender_id=identity,attacker_profile=defender,
                    defender_profile=profile,sim_time=self._sim_time,seed=self._tick+enemy*17,action_id='group_retaliate')
                if reply.get('ok'):
                    self._start_character_action_locked(identity,'Death' if reply.get('defeated') else 'HitReact')
                    self._append_event_locked('GROUP_HIT',identity,actor_id=target,target_id=identity,payload=reply)

    def _tick_services_locked(self, dt):
        shared = getattr(self, '_tick_shared_custody_locked', None)
        if shared is not None:
            shared()
        self._tick_opening_cinematic_locked(dt)
        self._tick_travel_locked(dt)
        self._settle_services_locked()
        self._tick_group_combat_locked()
        pet = self._active_pet_locked()
        if not pet:
            return
        self._tick_pet_training_locked(pet,dt)
        from backend.game_engine_adapter_pet_world import pending
        if pending(self,pet):
            self._publish_companions_locked();return
        pet_profile = self._pet_profile_locked(pet)
        actor = combat.ensure_actor(self._combat_state, pet_profile['id'], pet_profile)
        self._pet_physics_locked(pet,actor,dt)
        target = pet['target']
        if not target and pet['reaction'] and pet['autocast']:
            threat=next((a for a,state in self._combat_state.get('actors',{}).items() if state.get('engaged_target') in ('player',pet_profile['id']) and a not in self._services['group']['members']),None)
            if threat and self._npc_index_for_id_locked(threat) is not None:pet['target']=target=threat
        index = self._npc_index_for_id_locked(target) if target else None
        if index is None or not self._alive[index] or target in self._services['group']['members']:
            pet['target'] = '';index = None
        if actor.get('alive', True) and (pet['command'] == 1 or index is not None):
            x = self._x[index] if index is not None else self._x[0] + 1.5
            z = self._z[index] if index is not None else self._z[0] + 1.5
            goal_x,goal_z=x,z
            x,z=self._pet_waypoint_locked(pet,x,z)
            dx, dz = x - pet['x'], z - pet['z'];distance = math.hypot(dx, dz)
            remaining=math.hypot(goal_x-pet['x'],goal_z-pet['z'])-(1.8 if index is not None else 1.5)
            if abs(x-goal_x)+abs(z-goal_z)>.01:remaining=distance
            speed = min(4., max(0., min(distance,remaining) / max(.001, dt)))
            pet['vx'] = dx / distance * speed if distance else 0.
            pet['vz'] = dz / distance * speed if distance else 0.
            old_x,old_z=pet['x'],pet['z']
            pet['x'],pet['y'],pet['z']=self._pet_move_locked(pet,old_x+pet['vx']*dt,old_z+pet['vz']*dt)
            pet['vx']=(pet['x']-old_x)/max(.001,dt);pet['vz']=(pet['z']-old_z)/max(.001,dt)
            if speed:
                pet['yaw'] = math.degrees(math.atan2(dx, dz))
            reach=math.dist((pet['x'],pet['y'],pet['z']),(self._x[index],self._y[index],self._z[index])) if index is not None else float('inf')
            if (index is not None and reach <= pet_profile['attack_range_m']
                    and self._line_of_sight_locked((pet['x'],pet['y']+.35,pet['z']),
                        (self._x[index],self._y[index]+.5,self._z[index]),ignore_index=index)):
                if pet.get('pending_spell')==0x800102 or pet.get('learned',{}).get(str(0x800102)):
                    pet_profile=dict(pet_profile);pet_profile['damage']=pet_profile.get('damage',1)*1.2
                person = self._individual_state['individuals'].get(target, {})
                result = combat.resolve_attack(self._combat_state, attacker_id=pet_profile['id'], defender_id=target,
                    attacker_profile=pet_profile, defender_profile=self._npc_combat_profile_locked(target, person),
                    sim_time=self._sim_time, seed=self._tick + pet['number'], action_id='pet_attack')
                if result.get('ok'):
                    self._last_combat = result
                    pet['pending_spell']=PET_STRIKE
                    self._service_combat_fx_locked(result,self._x[index],self._y[index],self._z[index])
                    self._append_event_locked('PET_ATTACK', pet['name'], actor_id=pet_profile['id'], target_id=target, payload=result)
                if result.get('defeated'):
                    self._handle_npc_defeat_locked(target, index, result);pet['target'] = '';pet['command'] = 1;pet['xp'] += 10
                elif result.get('ok'):
                    person=self._individual_state['individuals'].get(target,{})
                    enemy_profile=self._npc_combat_profile_locked(target,person)
                    reply=combat.resolve_attack(self._combat_state,attacker_id=target,defender_id=pet_profile['id'],
                        attacker_profile=enemy_profile,defender_profile=pet_profile,sim_time=self._sim_time,seed=self._tick+index*17,action_id='pet_retaliate')
                    if reply.get('ok'):
                        self._last_combat=reply;self._append_event_locked('PET_HIT',pet['name'],actor_id=target,target_id=pet_profile['id'],payload=reply)
        else:
            pet['vx'] = pet['vz'] = 0.
        self._publish_companions_locked()
