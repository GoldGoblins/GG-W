"""Freeze original UI row references against the physical local service ledger."""
import copy
from backend.game_engine_adapter_gameplay import QUALITY, EQUIPMENT_SLOTS, GameplayViews


class ServiceViews:
    def __init__(self, identity):
        self.identity = identity
        self.value = {}

    def update(self, snapshot):
        raw = snapshot.get('player', {}).get('client_controls', {}).get('services')
        if not isinstance(raw, dict):
            return self.value
        value = copy.deepcopy(raw)

        def item(row):
            if not isinstance(row, dict):
                return None
            ref = row.get('definition_id')
            if not ref:
                return None
            row['item_id'] = self.identity(ref)
            row['quality'] = QUALITY.get(row.get('rarity'), 1)
            row['link'] = f"|Hitem:{row['item_id']}:0:0:0|h[{row['name']}]|h"
            return row

        for row in value['mail']['rows']:
            row['attachment'] = item(row.get('attachment'))
        for listing in value['auction']['lists']:
            for row in listing['rows']:
                row['attachment'] = item(row.get('attachment'))
        if value['trade']['open']:
            value['trade']['player_rows'] = {k: item(v) for k, v in value['trade']['player_rows'].items()}
            value['trade']['target_rows'] = [item(v) for v in value['trade']['target_rows']]
        for roll in value.get('loot_rolls',[]):roll['attachment']=item(roll.get('attachment'))
        for row in value.get('inspection',{}).get('items',[]):
            item(row);row['slot']=EQUIPMENT_SLOTS.get(row.get('equipped_slot'),0);row.update(GameplayViews.item_fields(row))
        for row in value.get('skills',{}).get('rows',[]):
            row['id']=self.identity('profession.'+row['key'])
        if value.get('trainer',{}).get('kind')=='PROFESSION':
            for row in value['trainer'].get('rows',[]):row['id']=self.identity('profession.'+row['key'])
        self.value = value
        return value

    def route(self, request, inventory_sources, equipment_sources=None):
        if not isinstance(request, dict):
            raise ValueError('SERVICE_REQUEST_INVALID')
        row = copy.deepcopy(request)
        op = row.get('op')
        row['kind'] = 'service'
        row['session'] = self.value.get('session', -1)
        self.freeze_channel(row)
        if str(op).startswith('ItemBinding'):
            row['binding_generation']=self.value.get('item_binding',{}).get('generation',-1)
        if str(op).startswith('Enchant') or op == 'TradeEnchantPick':
            row['target_generation']=self.value.get('item_targeting',{}).get('generation',-1)
        if op in ('InventoryWrap','InventoryWrapCancel'):
            row['wrap_generation']=(self.value.get('inventory_cursor',{}).get('wrap') or {}).get('generation',-1)
        if op=='InventoryWrap':
            source=row.pop('paper_source',None)
            ref=inventory_sources.get(source[1]) if isinstance(source,list) and len(source)==2 and source[0]==0 else None
            if not ref or not ref[1]:raise ValueError('WRAPPING_PAPER_NOT_SHOWN')
            row['paper']=ref[1]
        if op=='SkillAbandon' and row.get('skill_id') not in [s['id'] for s in self.value.get('skills',{}).get('rows',[])]:
            raise ValueError('PROFESSION_NOT_SHOWN')
        if op=='TaxiTake':
            entries=self.value.get('travel',{}).get('nodes',[]);index=row.pop('index',0)
            if type(index) is not int or not 1<=index<=len(entries):raise ValueError('TAXI_DESTINATION_NOT_SHOWN')
            row['destination']=entries[index-1]['id']
        if op in ('PetitionOffer','PetitionRename','PetitionSign','PetitionClose','PetitionTurnIn'):
            petition=self.value.get('petition',{})
            record=(petition.get('owned') or [{}])[0] if op=='PetitionTurnIn' else petition.get('record') or {}
            for key in ('petition_owner','petition_asset','petition_terms'):
                if key in record:row[key]=record[key]
            if op in ('PetitionSign','PetitionClose') and 'petition_offer' in record:
                row['petition_offer']=record['petition_offer']
        if op == 'TradeAccept':
            row['offer_revision'] = self.value.get('trade', {}).get('offer_revision', -1)
        trade=self.value.get('trade',{})
        shared_trade=trade.get('shared_trade') is True and str(op).startswith('Trade') and op!='TradeOpen'
        if shared_trade:
            row['shared_trade']=True
            for key in ('id','owner','recipient','revision','terms'):
                row['shared_trade_'+key]=copy.deepcopy(trade.get('shared_trade_'+key))
        targeting = self.value.get('item_targeting', {})
        if op in ('EnchantBindConfirm', 'EnchantReplaceConfirm', 'EnchantCancel') and targeting.get('shared_trade') is True:
            row['shared_trade'] = True
            for key in ('id', 'owner', 'recipient', 'revision', 'terms'):
                row['shared_trade_' + key] = copy.deepcopy(targeting.get('shared_trade_' + key))
        if op in ('GuildPublicNote','GuildOfficerNote'):
            entries=(self.value.get('guild') or {}).get('roster',[]);index=row.pop('index',0)
            if type(index) is not int or not 1<=index<=len(entries):raise ValueError('GUILD_MEMBER_NOT_SHOWN')
            row['target']=entries[index-1]['id']
        if op in ('MailRead', 'MailItem', 'MailMoney', 'MailDelete', 'MailReturn', 'MailText'):
            index = row.pop('index', 0)
            entries = self.value.get('mail', {}).get('rows', [])
            if type(index) is not int or not 1 <= index <= len(entries):
                raise ValueError('MAIL_ROW_NOT_SHOWN')
            row['id'] = entries[index - 1]['id']
        if op in ('AuctionBid', 'AuctionCancel'):
            listing = row.pop('list', 2 if op == 'AuctionCancel' else 0)
            lists = self.value.get('auction', {}).get('lists', [])
            index = row.pop('index', 0)
            if type(listing) is not int or not 0 <= listing < len(lists):
                raise ValueError('AUCTION_LIST_NOT_SHOWN')
            entries = lists[listing]['rows']
            if type(index) is not int or not 1 <= index <= len(entries):
                raise ValueError('AUCTION_ROW_NOT_SHOWN')
            row['id'] = entries[index - 1]['id']
        if op in ('GroupKickRaid', 'GroupSubgroup', 'GroupSwap'):
            roster = self.value.get('group', {}).get('roster', [])
            index = row.pop('index', 0)
            if type(index) is not int or not 1 <= index <= len(roster):
                raise ValueError('GROUP_MEMBER_NOT_SHOWN')
            row['target'] = roster[index - 1]['id']
            if op == 'GroupKickRaid':row['op'] = 'GroupKick'
            if op == 'GroupSwap':
                other = row.pop('other', 0)
                if type(other) is not int or not 1 <= other <= len(roster):raise ValueError('GROUP_MEMBER_NOT_SHOWN')
                row['other_target'] = roster[other - 1]['id']
        source = row.pop('source', None)
        if source is not None:
            if not isinstance(source, (list, tuple)) or len(source) != 2:
                raise ValueError('SERVICE_BACKPACK_SOURCE_REQUIRED')
            equipped_trade_target = shared_trade and op == 'TradeSet' and row.get('slot') == 7
            if source[0]==-100 and (op in ('InventoryAutoStore','EnchantPick') or equipped_trade_target):
                row['item']=(equipment_sources or {}).get(source[1],'')
                if not row['item']:raise ValueError('SERVICE_ITEM_NOT_SHOWN')
                if op=='InventoryAutoStore' and row.pop('destination',0)!=0:raise ValueError('INVENTORY_DESTINATION_UNAVAILABLE')
            else:
                if source[0]!=0:raise ValueError('SERVICE_BACKPACK_SOURCE_REQUIRED')
                if op=='InventoryAutoStore' and row.pop('destination',0)!=0:raise ValueError('INVENTORY_DESTINATION_UNAVAILABLE')
                ref = inventory_sources.get(source[1])
                if not ref or not ref[1]:
                    raise ValueError('SERVICE_ITEM_NOT_SHOWN')
                row['item'] = ref[1]
        if shared_trade and op=='TradeSet':
            references = trade.get('gear_references' if row.get('slot') == 7 else 'inventory_references', {})
            row['shared_trade_item']=copy.deepcopy(references.get(row.get('item')))
        if shared_trade and op == 'TradeEnchant':
            row['shared_trade_scroll'] = copy.deepcopy(trade.get('scroll_references', {}).get(row.get('scroll')))
        if shared_trade and op == 'TradeEnchantPick':
            row['shared_trade_target'] = copy.deepcopy(trade.get('target_enchant_target_reference'))
            scroll = self.value.get('item_targeting', {}).get('scroll')
            row['shared_trade_scroll'] = copy.deepcopy(trade.get('scroll_references', {}).get(scroll))
        return row

    def freeze_channel(self, row):
        op = row.get('op', '')
        if not (str(op).startswith('Channel') or op == 'Chat' and row.get('chat_type') == 'CHANNEL'):
            return
        channels = self.value.get('channels', {})
        name = row.get('name', row.get('target'))
        if not isinstance(name, str):
            return
        numeric_slot = int(name) if name.isdecimal() else None
        if numeric_slot is not None:
            slot = int(name)
            slots = channels.get('slots', [])
            name = slots[slot - 1] if 1 <= slot <= len(slots) else None
        if not isinstance(name, str):
            return
        candidates = [r for r in channels.get('rows', [])
                      if r.get('name', '').casefold() == name.casefold()]
        if numeric_slot is not None:
            exact = next((r for r in candidates if r.get('slot') == numeric_slot), None)
            shown = exact or next((r for r in candidates if r.get('shared_channel') is not True), None)
        elif type(row.get('shared_channel')) is bool:
            shown = next((r for r in candidates if (r.get('shared_channel') is True) == row['shared_channel']), None)
        else:
            shown = next(iter(candidates), None)
        offer = channels.get('shared_invite') or {}
        if (shown is None and op == 'ChannelJoin' and row.get('shared_channel') is not False
                and offer.get('name', '').casefold() == name.casefold()):
            shown = offer
        if shown is not None:
            row['shared_channel'] = shown.get('shared_channel') is True
            if row['shared_channel']:
                for key in ('channel_id', 'channel_revision'):
                    row[key] = copy.deepcopy(shown[key])
            return
        if op == 'ChannelJoin' and channels.get('shared_available') is True and numeric_slot is None and row.get('shared_channel') is not False:
            from backend.game_engine_adapter_channels import ZONE_CHANNELS
            builtin = any(name.casefold() in (zone.casefold(), (zone + ' - GG Island').casefold())
                          for zone in ZONE_CHANNELS)
            if not builtin:
                row['shared_channel'] = True
