"""Original five-field designer, real payment/cloth and shared render material."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_tabards import COUNTS,DESIGN_COST,CLOTH_COST,emblem_texture
from backend import game_engine_items as items
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage
import base64


class Tabards(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def start(self):
        self.move_near_npc();self.service('GuildCreate',name='Emblem Guild');self.publish()
        self.call('GetTabardInfo()');self.assertTrue(self.view()['tabard']['open'])

    def test_original_model_variations_save_money_cloth_equipment_and_restart(self):
        self.start();before=self.view()['money'];vendor=self.runtime._service_money_locked('npc-wanderer-01')
        self.call('T=CreateFrame("TabardModel","GGTabardTest"); T:InitializeTabardColors(); T:CycleVariation(1,1); T:Save()')
        design=self.runtime._services['guild']['emblem'];self.assertEqual(len(design),5)
        self.assertEqual(self.view()['money'],before-DESIGN_COST);self.assertEqual(self.runtime._service_money_locked('npc-wanderer-01'),vendor+DESIGN_COST)
        cloth=next(i for i in self.runtime._item_instances.values() if i['definition_id']=='item.guild_tabard')
        self.assertEqual(self.runtime._inventory['item.guild_tabard'],1)
        self.assertNotIn('error',self.runtime.equip_item(cloth['instance_id']))
        equipment=self.runtime.snapshot()['items']['equipment']
        worn=next(i for i in equipment if i['definition_id']=='item.guild_tabard')
        self.assertEqual(worn['equipped_slot'],'TABARD');self.assertEqual(worn['visual']['base_color_map'],emblem_texture(tuple(design)))
        self.call('T:Save()');self.assertEqual(self.view()['money'],before-DESIGN_COST)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._services['guild']['emblem'],design);self.assertEqual(self.runtime._item_instances[cloth['instance_id']]['guild_emblem'],design)
        self.assertEqual(self.runtime._item_instances[cloth['instance_id']]['location'],'EQUIPPED')
        self.assertFalse(self.view()['tabard']['open'])

    def test_invalid_fields_permission_money_and_failed_save_restore_every_asset(self):
        self.start();before=copy.deepcopy((self.runtime._services,self.runtime._economy_state,self.runtime._inventory,self.runtime._item_instances,self.runtime._tabard_draft))
        for design in ([170,0,0,0,0],[0,17,0,0,0],[0,0,6,0,0],[0,0,0,17,0],[0,0,0,0,51],[False,0,0,0,0],[0]*4):
            self.assertIn('error',self.service('TabardSave',design=design))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.service('TabardSave',design=[1,2,3,4,5])['error'],'SERVICE_SAVE_FAILED')
        current=copy.deepcopy(self.runtime._services);current['clock']=before[0]['clock']
        self.assertEqual(before,(current,self.runtime._economy_state,self.runtime._inventory,self.runtime._item_instances,self.runtime._tabard_draft))
        guild=self.runtime._services['guild'];guild['members']['player']['rank']=1;guild['members']['npc-wanderer-01']=dict(rank=0,note='',officer_note='')
        self.assertEqual(self.service('TabardSave',design=[1,2,3,4,5])['error'],'GUILD_PERMISSION_DENIED')

    def test_preview_is_not_a_purchase_and_leave_removes_emblem_from_same_cloth(self):
        self.start();before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.assertNotIn('error',self.service('TabardPreview',design=[4,5,1,7,14]))
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.assertNotIn('error',self.service('TabardSave',design=[4,5,1,7,14]));cloth=next(i for i in self.runtime._item_instances.values() if i['definition_id']=='item.guild_tabard')
        self.runtime.equip_item(cloth['instance_id']);self.service('GuildDisband')
        worn=next(i for i in self.runtime.snapshot()['items']['equipment'] if i['definition_id']=='item.guild_tabard')
        self.assertEqual(worn['instance_id'],cloth['instance_id']);self.assertEqual(worn['visual']['base_color_map'],'')

    def test_cloth_buy_range_closed_session_and_full_backpack_do_not_charge(self):
        self.start();before=self.view()['money']
        self.assertNotIn('error',self.service('TabardBuy'));self.assertEqual(self.view()['money'],before-CLOTH_COST)
        self.runtime._x[0]+=100;before=self.view()['money']
        self.assertEqual(self.service('TabardBuy')['error'],'SERVICE_WINDOW_CHANGED_OR_CLOSED');self.assertEqual(self.view()['money'],before)
        self.move_near_npc();self.service('TabardOpen');old=self.view()['session'];self.service('TabardClose');self.service('TabardOpen')
        self.assertEqual(self.control('service','TabardBuy',session=old)['error'],'SERVICE_WINDOW_CHANGED_OR_CLOSED')
        with self.runtime._lock:
            carried=sum(i['location']=='INVENTORY' and i['owner_id']=='player' for i in self.runtime._item_instances.values())
            for n in range(items.MAX_INVENTORY_SLOTS-carried):
                item=items.make_instance(self.runtime._item_catalog,'full-tabard-'+str(n),'item.field_ration',location='MAIL')
                self.runtime._item_instances[item['instance_id']]=item;self.runtime._service_move_locked(item,'INVENTORY','player')
        self.assertEqual(self.service('TabardBuy')['error'],'ITEM_INVENTORY_FULL')
        self.assertEqual(self.view()['money'],before)

    def test_own_emblem_rasterizes_and_all_field_boundaries_change_actual_image(self):
        previous=emblem_texture((0,0,0,0,0))
        for index,count in enumerate(COUNTS):
            design=[0]*5;design[index]=count-1;uri=emblem_texture(tuple(design))
            self.assertNotEqual(uri,previous)
            image=QImage.fromData(QByteArray(base64.b64decode(uri.split(',',1)[1])))
            self.assertFalse(image.isNull());self.assertEqual((image.width(),image.height()),(256,320))
        invalid=items.make_instance(self.runtime._item_catalog,'bad','item.guild_tabard');invalid.update(guild_id=1,guild_emblem=[-1]*5)
        self.assertNotIn('guild_emblem',items.normalize_instance(self.runtime._item_catalog,invalid))

if __name__=='__main__':unittest.main()
