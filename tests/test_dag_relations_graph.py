"""Actual signed fork/merge topology in native retained QML; no user state."""
from copy import deepcopy
import hashlib,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def fixture(directory):
    from PySide6.QtCore import QObject,QUrl
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QSGRendererInterface
    from PySide6.QtTest import QSignalSpy,QTest
    from PySide6.QtWidgets import QApplication
    sys.path.insert(0,str(ROOT))
    from backend.gg_parallel_dag import ParallelDag
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    if os.name=='nt':QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts/consola.ttf'))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    source=directory/'fixture.qml'
    source.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
 width:706;height:192;visible:true;color:'#111111'
 flags:Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus
 x:-10000;y:-10000
 BlockRelationsGraph {objectName:'graph';inspectGeometry:true;pointMode:false;x:8;y:8;width:parent.width-16;height:176}
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(source)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];graph=window.findChild(QQuickItem,'graph');assert graph
    native=os.environ.get('GG_DAG_NATIVE')=='1'
    if native:assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
    def js(code):
        expression=QQmlExpression(qmlContext(graph),graph,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        value=value[0] if isinstance(value,tuple) else value
        return value.toVariant() if hasattr(value,'toVariant') else value
    def settle():
        QTest.qWait(50);app.processEvents();deadline=time.monotonic()+2
        while graph.property('animationRunning') and time.monotonic()<deadline:QTest.qWait(50);app.processEvents()
        QTest.qWait(50);app.processEvents()
        assert not graph.property('animationRunning')
        assert not graph.property('geometryError')
        assert not warnings,warnings
    def push(data):graph.setProperty('graph',data);settle()
    def descendants(item):
        for child in item.childItems():
            yield child;yield from descendants(child)
    def save(name):
        target=os.environ.get('GG_DAG_GRAPH_EVIDENCE')
        if target:
            output=Path(target);output.mkdir(parents=True,exist_ok=True)
            assert window.grabWindow().save(str(output/(name+('-native' if native else '-software')+'.png')))
    # No fixture asserts signature verification from a made-up hash. These
    # Public observations come from two actual disposable signed waves and
    # their real genesis anchor. A larger history must not hide the anchor.
    dag=ParallelDag();dag.start()
    try:
        dag.build_wave(24,4);observed=dag.build_wave(24,4)['block_graph']
    finally:dag.stop()
    assert len(observed['blocks'])==49 and len(observed['edges'])==192
    push(observed)
    assert graph.property('dagMode') and graph.property('retainedCount')==49
    cards=[item for item in descendants(graph) if item.objectName()=='relationBlock']
    assert 24<len(cards)<=49 and graph.property('shownCount')==len(cards)
    positions={(round(card.x(),2),round(card.y(),2)) for card in cards}
    assert len(positions)==len(cards),'same producer/rank proposals must remain separate visible cards'
    assert {card.property('proposerIndex') for card in cards if not card.property('genesis')}=={0,1,2,3}
    references={row['hash']:row for row in observed['blocks']}
    rendered=js('JSON.stringify(_edges)');rendered=json.loads(rendered)
    card_hashes={card.property('blockHash') for card in cards}
    assert graph.property('edgeCount')==sum(edge['from'] in card_hashes and edge['to'] in card_hashes for edge in observed['edges'])
    for edge in rendered:
        assert edge['from'] in references[edge['to']]['parent_hashes']
        assert references[edge['from']]['rank']<references[edge['to']]['rank']
    assert all(not card.property('verified') and (card.property('genesis') or card.property('signatureChecked')) for card in cards)
    save('dag-actual-48-parents')
    graph.setProperty('pointMode',True);settle()
    points=[item for item in descendants(graph) if item.objectName()=='relationBlock']
    assert len(points)==49 and graph.property('edgeCount')==192
    assert all(item.width()==10 and item.height()==10 for item in points)
    assert len({(round(item.x(),2),round(item.y(),2)) for item in points})==49
    assert not graph.property('geometryError')
    save('dag-point-map-48-real-parents')
    graph.setProperty('pointMode',False);settle()
    # Equal ranks are not unique block identifiers. Height-only selection must
    # not silently pick one of 24 real parallel siblings.
    assert not js('selectMeasurement({block_height:2})')
    assert js('selectMeasurement({block_hash:'+json.dumps(observed['blocks'][-1]['hash'])+',block_height:2})')
    chosen=js('selectedBlock');assert len(chosen['parent_hashes'])==7
    generation=graph.property('_nodeGeneration')
    graph.setProperty('graph',deepcopy(observed));QTest.qWait(80)
    assert graph.property('_nodeGeneration')==generation
    swaps=QSignalSpy(window.frameSwapped);QTest.qWait(250);assert swaps.count()==0
    # Width adaptation keeps whole real rank/producer groups and never invents
    # a chain among siblings. Shown/retained counts disclose any reduced view.
    for width in (360,430,706,1200):
        window.setWidth(width);settle()
        assert 0<graph.property('shownCount')<=49
        assert graph.property('edgeCount')<=343
    window.setWidth(706);settle()
    # Deliberately malformed public topology tests below exercise edge guards;
    # they are tagged synthetic, not a claim of valid cryptographic admission.
    def key(name):return hashlib.sha256(('synthetic-dag-topology-'+name).encode()).hexdigest()
    def node(name,rank,producer,parents,sequence=1):
        return dict(hash=key(name),height=rank,rank=rank,parent_hashes=[key(p) for p in parents],
          proposer_index=producer,producer_sequence=sequence,timestamp=1700000000+rank,
          transaction_count=0,signature_verified=rank>0,certificate_verified=True,
          state='GENESIS' if rank==0 else 'ADMITTED_UNFINALIZED')
    nodes=[node('g',0,-1,[]),node('a',1,0,['g']),node('b',1,1,['g']),node('c',1,2,['g']),
           node('d',2,3,['a','b']),node('e',3,0,['d','c'],2)]
    fork=dict(schema='gg.block-graph.v1',topology='MULTIPARENT_DAG',source='SYNTHETIC_ADVERSARIAL_TOPOLOGY',
      blocks=nodes,edges=[{'from':parent,'to':child['hash']} for child in nodes for parent in child['parent_hashes']],
      finality='EXPLICIT_CHECKPOINT_REQUIRED',metrics={'canonical_finalized':0})
    push(fork);assert graph.property('shownCount')==5 and graph.property('edgeCount')==4
    js('selectBlock('+json.dumps(key('a'))+')');assert graph.property('highlightedCount')==3
    js('selectBlock('+json.dumps(key('c'))+')');assert graph.property('highlightedCount')==2
    assert not js('selectedBlock.certificate_verified'),'DAG admission is never an SDK finality certificate'
    save('dag-fork-merge')
    wrong=deepcopy(fork)
    wrong['edges']+= [{'from':key('c'),'to':key('d')}, {'from':key('d'),'to':key('a')},
                     {'from':key('a'),'to':key('b')},wrong['edges'][-1],{'from':key('unknown'),'to':key('e')}]
    push(wrong);assert graph.property('edgeCount')==4,'unlisted, reverse, same-rank, repeated and unknown edges must not render'
    wrong=deepcopy(fork);wrong['blocks'][1]['parent_hashes']=[key('d')]
    wrong['edges'].append({'from':key('d'),'to':key('a')})
    push(wrong);assert graph.property('edgeCount')==4,'a declared cycle is rejected by strict rank ordering'
    for invalid in ([key('g')]*2,[key('a')],[key(str(i)) for i in range(8)]):
        bad=deepcopy(fork);bad['blocks'][1]['parent_hashes']=invalid
        push(bad);assert graph.property('retainedCount')==5,'invalid parent sets must not become admitted nodes'
    bad=deepcopy(fork);bad['blocks'][1]['signature_verified']=False
    push(bad);assert graph.property('retainedCount')==5
    bad=deepcopy(fork);bad['topology']='UNRECOGNIZED_DAG'
    push(bad);assert not graph.property('supportedTopology') and graph.property('shownCount')==0
    # Seven successor hops over the complete retained graph, including merges,
    # remain a hard traversal bound even when the viewport shows fewer ranks.
    steps=[node('g',0,-1,[])]+[node('s'+str(i),i,0,['g' if i==1 else 's'+str(i-1)],i) for i in range(1,10)]
    hops=dict(fork,blocks=steps,edges=[{'from':p,'to':r['hash']} for r in steps for p in r['parent_hashes']])
    push(hops);js('selectBlock('+json.dumps(key('s1'))+')')
    assert graph.property('highlightedCount')==8
    assert not js('!!_reachable['+json.dumps(key('s9'))+']')
    push({});assert not graph.property('dagMode') and graph.property('shownCount')==0
    print(json.dumps({'status':'PASS','native':native,'actual_signed_blocks':48,'real_genesis_anchors':1,'actual_parent_edges':192,
       'same_rank_producer_collisions_visible':True,'fork_merge_nonadjacent_parent':True,
       'adversarial_edge_guards':True,'idle_swaps':0,'warnings':0,'finality_claimed':False}))
    window.close();engine.deleteLater();app.processEvents()


class DagRelationsGraphTests(unittest.TestCase):
    def run_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-dag-render-') as temporary:
            env=os.environ.copy();env['QT_QUICK_CONTROLS_STYLE']='Basic'
            if native:
                env.pop('QT_QUICK_BACKEND',None);env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_DAG_NATIVE='1')
            else:
                env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software');env.pop('GG_DAG_NATIVE',None)
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=ROOT,
              env=env,capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
    def test_software_actual_signed_forks_and_merges(self):self.run_fixture()
    @unittest.skipUnless(os.name=='nt','Direct3D11 requires Windows')
    def test_native_actual_signed_forks_and_merges(self):self.run_fixture(True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
