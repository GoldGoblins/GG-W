"""Bounded public gallery previews, exact cache identity and cancellation."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import omni_assets as assets,omni_rpc,crypto_explorer as markets,marketplace_discovery as discovery


def collection(index=0):
    return {'id':'gallery-'+str(index),'name':'Gallery '+str(index),'symbol':'SAME',
            'asset_platform_id':'ethereum','contract_address':'0x'+str(index+1).zfill(40)}


class GalleryPreviews(unittest.TestCase):
    def setUp(self):
        discovery.stop_previews()
        self.wait_stopped()
        self.temp=tempfile.TemporaryDirectory(prefix='gg-mp-gallery-')
        self.root=patch.object(assets,'ROOT',Path(self.temp.name));self.root.start()
        self.provider=patch.object(markets,'PROVIDERS',{key:dict(value,spacing=0) for key,value in markets.PROVIDERS.items()});self.provider.start()
        assets.bootstrap()
        with patch.object(omni_rpc,'_json',return_value=[collection(i) for i in range(8)]):discovery.refresh()

    def tearDown(self):
        discovery.stop_previews();self.wait_stopped()
        self.provider.stop();self.root.stop();self.temp.cleanup()

    def wait_stopped(self):
        for _ in range(200):
            with discovery._PREVIEW_LOCK:
                thread=discovery._preview_thread
            if thread is None or not thread.is_alive():return
            thread.join(.01)
        self.fail('bounded preview worker did not stop')

    def ids(self,count=6):return ['coingecko:gallery-'+str(i) for i in range(count)]

    def detail(self,url):
        index=int(url.rsplit('-',1)[1]);return collection(index) | {
            'description':'Actual mocked source detail '+str(index),'floor_price':{'usd':index+1},
            'image':{'small':'https://coin-images.coingecko.com/nft_contracts/images/gallery-'+str(index)+'.png'}}

    def test_snapshot_merges_only_exact_identity_and_preserves_stale_state(self):
        original=discovery.snapshot()['rows'][0]
        detail=original | {'image_url':'file:///fixture/image.png','description':'Cached source detail','floor_usd':12}
        for field in discovery._IDENTITY_FIELDS:
            bad=dict(detail);bad[field]='wrong-'+str(detail[field])
            discovery._save('detail:'+original['id'],bad)
            row=discovery.snapshot()['rows'][0]
            self.assertEqual(row['image_url'],'',field);self.assertNotIn('detail_state',row,field)
        discovery._save('detail:'+original['id'],detail,time.time()-301,'MP_DISCOVERY_DETAIL_UNAVAILABLE')
        with patch.object(omni_rpc,'_json') as request:
            row=discovery.snapshot()['rows'][0]
            self.assertFalse(request.called)
        self.assertEqual(row['image_url'],detail['image_url']);self.assertEqual(row['floor_usd'],12)
        self.assertEqual(row['detail_state'],'STALE');self.assertEqual(row['detail_error'],'MP_DISCOVERY_DETAIL_UNAVAILABLE')

    def test_six_real_results_fill_gallery_without_changing_selected_account_or_reference(self):
        discovery._pref('selected',self.ids(8)[7])
        with patch.object(omni_rpc,'_json',side_effect=self.detail) as request,patch.object(discovery,'_image',side_effect=lambda url:'file:///fixture/'+url.rsplit('/',1)[1]):
            discovery.action(json.dumps({'action':'previews','ids':self.ids()}));self.wait_stopped()
        state=discovery.snapshot();job=state['preview_job']
        self.assertEqual((job['state'],job['total'],job['completed'],job['failed'],job['images']),('done',6,6,0,6))
        self.assertEqual(request.call_count,6);self.assertFalse(job['worker_active'])
        self.assertEqual(discovery._pref('selected'),'coingecko:gallery-7')
        self.assertEqual(sum(bool(r['image_url']) for r in state['rows']),6)
        with patch.object(omni_rpc,'_json') as request:
            discovery.previews(self.ids());self.wait_stopped();self.assertFalse(request.called)
        self.assertEqual(discovery.preview_status()['completed'],6)

    def test_invalid_oversized_duplicate_or_nonpage_request_never_starts_network(self):
        invalid=[[],self.ids(7),[self.ids(1)[0]]*2,'gallery',None,[123],['coingecko:not-in-this-page']]
        with patch.object(omni_rpc,'_json') as request:
            for value in invalid:
                with self.assertRaises(ValueError):discovery.previews(value)
            self.assertFalse(request.called)

    def test_partial_failure_counts_completed_source_attempts_not_promised_images(self):
        def response(url):
            if url.endswith('-1'):raise OSError('mock offline')
            value=self.detail(url)
            if url.endswith('-2'):value['contract_address']='0x'+'f'*40
            return value
        with patch.object(omni_rpc,'_json',side_effect=response),patch.object(discovery,'_image',return_value='file:///fixture/image.png'):
            discovery.previews(self.ids(3));self.wait_stopped()
        job=discovery.preview_status()
        self.assertEqual((job['state'],job['completed'],job['failed'],job['images']),('partial',3,2,1))
        self.assertEqual(sum(bool(r['image_url']) for r in discovery.snapshot()['rows']),1)

    def test_stop_discards_late_detail_and_cannot_start_second_worker(self):
        entered=threading.Event();release=threading.Event()
        def response(url):
            entered.set();release.wait(3);return self.detail(url)
        with patch.object(omni_rpc,'_json',side_effect=response) as request,patch.object(discovery,'_image') as image:
            try:
                discovery.previews(self.ids(2));self.assertTrue(entered.wait(1))
                running=discovery.preview_status();self.assertEqual((running['completed'],running['images']),(0,0))
                discovery.previews(self.ids(2));self.assertEqual(request.call_count,1)
                discovery.action('{"action":"stop_previews"}')
                self.assertEqual(discovery.preview_status()['state'],'cancelled')
                with self.assertRaisesRegex(ValueError,'MP_PREVIEW_BUSY'):discovery.previews(self.ids(1))
            finally:release.set();self.wait_stopped()
            self.assertEqual(request.call_count,1);self.assertFalse(image.called)
        self.assertIsNone(discovery._cached('detail:'+self.ids(1)[0]));self.assertEqual(discovery.preview_status()['completed'],0)

    def test_cancel_after_image_fetch_discards_late_cache_publish(self):
        entered=threading.Event();release=threading.Event()
        def image(url):entered.set();release.wait(3);return 'file:///fixture/late.png'
        with patch.object(omni_rpc,'_json',side_effect=self.detail),patch.object(discovery,'_image',side_effect=image):
            try:
                discovery.previews(self.ids(1));self.assertTrue(entered.wait(1));discovery.stop_previews()
            finally:release.set();self.wait_stopped()
        self.assertIsNone(discovery._cached('detail:'+self.ids(1)[0]));self.assertEqual(discovery.preview_status()['images'],0)

    def test_page_change_cancels_bound_job_and_does_not_save_old_page_details(self):
        entered=threading.Event();release=threading.Event()
        def response(url):entered.set();release.wait(3);return self.detail(url)
        with patch.object(omni_rpc,'_json',side_effect=response),patch.object(discovery,'_image') as image:
            try:
                discovery.previews(self.ids(1));self.assertTrue(entered.wait(1))
                # A cached page switch can finish immediately while the old
                # request still owns the provider lane.
                discovery._save('coingecko:page:2',discovery.collections([collection(7)],'coingecko'))
                switch=threading.Thread(target=lambda:discovery.refresh('coingecko',2));switch.start()
                for _ in range(100):
                    if discovery.preview_status()['state']=='cancelled':break
                    time.sleep(.005)
                self.assertEqual(discovery.preview_status()['state'],'cancelled')
            finally:release.set();switch.join(2);self.wait_stopped()
            self.assertFalse(image.called)
        self.assertIsNone(discovery._cached('detail:'+self.ids(1)[0]));self.assertEqual(discovery.snapshot()['page'],2)
        self.assertIsNone(discovery.snapshot()['selected'])

    def test_provider_drift_discards_response_and_image_error_can_recover(self):
        entered=threading.Event();release=threading.Event()
        def response(url):entered.set();release.wait(3);return self.detail(url)
        with patch.object(omni_rpc,'_json',side_effect=response),patch.object(discovery,'_image') as image:
            try:
                discovery.previews(self.ids(1));self.assertTrue(entered.wait(1))
                discovery._pref('provider','kat')
            finally:release.set();self.wait_stopped()
            self.assertFalse(image.called)
        self.assertEqual(discovery.preview_status()['state'],'cancelled')
        self.assertIsNone(discovery._cached('detail:'+self.ids(1)[0]))
        discovery._pref('provider','coingecko')
        first=discovery.snapshot()['rows'][0]
        discovery._save('detail:'+first['id'],first | {'image_error':'MP_COLLECTION_IMAGE_UNAVAILABLE'},time.time()-301)
        with patch.object(omni_rpc,'_json',side_effect=self.detail),patch.object(discovery,'_image',return_value='file:///fixture/recovered.png'):
            discovery.previews(self.ids(1));self.wait_stopped()
        recovered=discovery.snapshot()['rows'][0]
        self.assertNotIn('image_error',recovered);self.assertEqual(recovered['image_url'],'file:///fixture/recovered.png')
        self.assertEqual(discovery.preview_status()['failed'],0)

    def test_replaced_page_identity_cancels_even_when_provider_and_page_number_match(self):
        entered=threading.Event();release=threading.Event()
        def response(url):entered.set();release.wait(3);return self.detail(url)
        with patch.object(omni_rpc,'_json',side_effect=response),patch.object(discovery,'_image') as image:
            try:
                discovery.previews(self.ids(1));self.assertTrue(entered.wait(1))
                new=collection();new['contract_address']='0x'+'f'*40
                discovery._save('coingecko:page:1',discovery.collections([new],'coingecko'),time.time()+1)
            finally:release.set();self.wait_stopped()
            self.assertFalse(image.called)
        self.assertIsNone(discovery._cached('detail:'+self.ids(1)[0]));self.assertEqual(discovery.preview_status()['state'],'cancelled')
        self.assertEqual(discovery.snapshot()['rows'][0]['collection'],'0x'+'f'*40)

    def test_stop_while_waiting_for_provider_budget_does_not_launch_later_request(self):
        providers={key:dict(value,spacing=1) for key,value in markets.PROVIDERS.items()}
        with patch.object(markets,'PROVIDERS',providers),patch.dict(markets._last_request,{'coingecko':time.time()}),patch.object(discovery.time,'sleep',side_effect=lambda seconds:discovery.stop_previews()),patch.object(omni_rpc,'_json') as request:
            discovery.previews(self.ids(1));self.wait_stopped()
            self.assertFalse(request.called)
        self.assertEqual(discovery.preview_status()['state'],'cancelled');self.assertEqual(discovery.preview_status()['completed'],0)


if __name__=='__main__':unittest.main()
