"""Stable original UI spell/loot identities for local GG books and chests."""
import json
from backend.game_engine_adapter_gameplay import QUALITY


class LocalViews:
    def __init__(self, identity):
        self.identity = identity
        self.craft_refs = {}
        self.craft_session = 0
        self.craft_book = ''
        self.loot_refs = {}
        self.loot_session = 0
        self.loot_source = ''
        self.loot_candidates=[]

    def update(self, snapshot):
        book = snapshot.get('crafting', {}).get('book', {})
        self.craft_refs = {}
        self.craft_session = book.get('session', 0) if book.get('open') else 0
        self.craft_book = book.get('book', '') if book.get('open') else ''
        recipes = []
        for row in book.get('rows', [])[:128] if book.get('open') else []:
            key = self.identity(row['ref'])
            self.craft_refs[key] = row['ref']
            recipes.append(dict(row, spell_id=key, product_item=self.identity(row['product']),
                                reagents=[dict(r, item_id=self.identity(r['ref'])) for r in row['reagents']]))
        loot = snapshot.get('loot', {})
        self.loot_refs = {}
        self.loot_session = loot.get('session', 0) if loot.get('open') else 0
        self.loot_source = loot.get('container_id', '') if loot.get('open') else ''
        self.loot_candidates=list(loot.get('master_candidates',[]))
        rows = []
        for index, row in enumerate(loot.get('rows', [])[:64] if loot.get('open') else [], 1):
            if row is None:
                rows.append(None)
                continue
            ref = row['definition_id']
            key = self.identity(ref)
            self.loot_refs[index] = row['instance_id']
            rows.append({'instance_id': row['instance_id'], 'item_id': key,
                         'name': row.get('name', ref), 'texture': row.get('icon'),
                         'quantity': row.get('quantity', 1), 'quality': QUALITY.get(row.get('rarity'), 1),
                         'link': f"|Hitem:{key}:0:0:0|h[{row.get('name', ref)}]|h"})
        return {'craft_book': dict(book, rows=recipes), 'loot': dict(loot, rows=rows)}

    def craft(self, spell, count=1):
        ref = self.craft_refs.get(spell)
        if not self.craft_session or not ref:
            raise ValueError('CRAFT_RECIPE_NOT_IN_SHOWN_BOOK')
        return {'method': 'gameEngineCraftBookRecipe', 'args': [self.craft_session, ref, count]}

    def loot(self, index):
        ref = self.loot_refs.get(index)
        if not self.loot_session or not ref:
            raise ValueError('LOOT_SLOT_EMPTY_OR_CHANGED')
        return {'method': 'gameEngineLootSlot', 'args': [self.loot_session, self.loot_source, ref]}

    def close_craft(self):
        if self.craft_session:
            return {'method': 'gameEngineCraftingClose', 'args': [self.craft_session]}

    def loot_confirm(self,index):
        ref=self.loot_refs.get(index)
        if not self.loot_session or not ref:raise ValueError('LOOT_SLOT_EMPTY_OR_CHANGED')
        return {'method':'gameEngineClientControl','args':[json.dumps(dict(kind='service',op='LootBindConfirm',
            loot_session=self.loot_session,source=self.loot_source,item=ref))]}

    def close_loot(self):
        if self.loot_session:
            return {'method': 'gameEngineLootClose', 'args': [self.loot_session]}

    def master_loot(self,index,candidate):
        ref=self.loot_refs.get(index)
        if not self.loot_session or not ref or type(candidate) is not int or not 1<=candidate<=len(self.loot_candidates):
            raise ValueError('LOOT_CANDIDATE_NOT_SHOWN')
        return {'method':'gameEngineClientControl','args':[json.dumps(dict(kind='service',op='LootMasterSlot',
            loot_session=self.loot_session,item=ref,target=self.loot_candidates[candidate-1]))]}
