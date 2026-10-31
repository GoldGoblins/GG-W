"""Exercise real QML Slider.moved signals and every relative-capacity label."""
import unittest

from tests.test_lan_transport_ui import LanTransportUiTests as _PopupTests


class ResourceSliderUiTests(unittest.TestCase):
    def check_offscreen(self, assertions):
        # Repeater delegates belong to the visual item tree. Traverse that
        # actual tree rather than assuming QObject ownership matches it.
        _PopupTests.check_offscreen(self, r'''
def find(name):
    pending=[root]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    raise AssertionError((name,warnings))
''' + assertions)

    def test_every_slider_recomputes_all_labels_and_changes_bottleneck_both_ways(self):
        self.check_offscreen(r'''
from PySide6.QtCore import QMetaObject
names=['cpu','gpu','ram','network']
body=snapshot()
body['dag_resources']={'budget':dict.fromkeys(['overall']+names,100),
    'hardware':{'gpu_compute_supported':True},
    'test':{'state':'COMPLETE','profile':{'active_resources':names,
        'capacities_tps':dict.fromkeys(names,10000)}}}
def preview():return json.loads(js('JSON.stringify(resourcePreview)'))
def move(name,percent):
    slider=find('lanResource_'+name)
    assert slider.isEnabled(),name
    slider.setProperty('value',percent)
    assert QMetaObject.invokeMethod(slider,'moved'),name
    app.processEvents()
    return preview()
for limiting in names:
    for percent in (10,30,60,30,10):
        put(body);js('draftBudget=null')
        p=move(limiting,percent)
        assert p['tps']==percent*100,(limiting,p)
        assert p['bottlenecks']==[limiting],p
        for other in names:
            assert p['resources'][other]['relative']==percent,(limiting,other,p)
            assert ('Relativt behov: %.1f %%'%percent) in text('lanResourceRelative_'+other)
        assert '%.1f TX/s'%(percent*100) in text('lanResourceEstimate')
for first in names:
    for second in names:
        if first==second:continue
        put(body);js('draftBudget=null')
        move(first,20)
        assert move(second,10)['bottlenecks']==[second]
        assert set(move(second,20)['bottlenecks'])=={first,second}
        assert move(second,40)['bottlenecks']==[first]
for limiting in names:
    put(body);js('draftBudget=null');move(limiting,10)
    for overall in (100,50,10,0,50,100):
        p=move('overall',overall)
        assert p['tps']==overall*10,p
        for other in names:
            assert p['resources'][other]['relative']==overall/10,p
assert js('draftBudget.overall')==100
# Unequal hardware capacities must be converted to TX/s before comparing
# ceilings. Comparing raw slider percentages would fail these interactions.
capacities=dict(zip(names,[6000,12000,24000,10000]))
body['dag_resources']['test']['profile']['capacities_tps']=capacities
for limiting in names:
    for percent in (1,5,10,20,10,1):
        put(body);js('draftBudget=null')
        p=move(limiting,percent);target=capacities[limiting]*percent/100
        assert p['tps']==target,(limiting,p)
        assert p['bottlenecks']==[limiting],p
        for other in names:
            expected=target/capacities[other]*100
            assert abs(p['resources'][other]['relative']-expected)<1e-9,(limiting,other,p)
            displayed=float(text('lanResourceRelative_'+other).split(': ')[1].split(' %')[0])
            assert abs(displayed-expected)<=.050000001,(limiting,other,displayed,expected)
''')

    def test_unsupported_gpu_and_unmeasured_resources_do_not_invent_capacity(self):
        self.check_offscreen(r'''
body=snapshot();body['dag_resources']={'budget':dict.fromkeys(['overall','cpu','gpu','ram','network'],100),
    'hardware':{'gpu_compute_supported':False},'test':{'state':'UNMEASURED'}}
put(body)
assert not find('lanResource_gpu').isEnabled()
assert text('lanResourceRelative_gpu')=='Används inte av denna DAG-backend'
assert 'okänt' in text('lanResourceEstimate')
assert 'okänt' in text('lanResourceRelative_cpu')
assert js('resourcePreview.tps') is None
js('changeBudget("cpu",0)')
assert js('resourcePreview.tps')==0
assert 'Relativt behov: 0.0 %' in text('lanResourceRelative_network')
''')

    def test_ram_space_ceiling_can_stop_all_work_even_when_copy_bandwidth_is_fast(self):
        self.check_offscreen(r'''
from PySide6.QtCore import QMetaObject
body=snapshot();body['dag_stress']['state']='IDLE'
body['dag_stress']['limits']['max_tx_per_block']=50000
body['dag_resources']={'budget':dict.fromkeys(['overall','cpu','gpu','ram','network'],100),
    'hardware':{'gpu_compute_supported':False,'memory_total_bytes':10000000,'memory_available_bytes':10000000},
    'memory_committed_bytes':0,
    'test':{'state':'COMPLETE','profile':{'active_resources':['cpu','ram','network'],
        'wire_bytes_per_transaction':100,'capacities_tps':{'cpu':1000,'ram':100000,'network':10000}}}}
put(body);find('lanDagStressTransactions').setProperty('text','1000')
assert js('resourcePreview.tps')==1000
assert find('lanDagStressStart').isEnabled()
slider=find('lanResource_ram');slider.setProperty('value',10)
assert QMetaObject.invokeMethod(slider,'moved')
assert js('resourcePreview.state')=='MEMORY_LIMIT'
assert js('resourcePreview.tps')==0
assert 'RAM-budgeten räcker inte' in text('lanResourceEstimate')
assert 'flaskhals' in text('lanResourceRelative_ram')
assert 'Relativt behov: 0.0 %' in text('lanResourceRelative_cpu')
assert not find('lanDagStressStart').isEnabled()
slider.setProperty('value',50);QMetaObject.invokeMethod(slider,'moved')
assert js('resourcePreview.tps')==1000
assert find('lanDagStressStart').isEnabled()
''')


if __name__=='__main__':unittest.main()
