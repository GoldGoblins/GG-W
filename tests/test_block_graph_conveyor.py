"""Small software-only guards for real-record layout, dynamic lanes and kicks.

Input identities are explicitly synthetic public topology fixtures. No node,
signature verification, network rate or native rendering benchmark is claimed.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def fixture(directory):
    from PySide6.QtCore import QUrl,QPointF,QEventLoop,QTimer,Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    app=QGuiApplication([]);engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS as GG
ApplicationWindow {
 id:shell;width:970;height:620;visible:true
 property string packet:''
 onPacketChanged:if(packet)dashboard.state=JSON.parse(packet)
 GG.GGParallelDagDashboard {id:dashboard;objectName:'conveyorDashboard';anchors.fill:parent}
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(directory/'conveyor.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];dashboard=window.findChild(QQuickItem,'conveyorDashboard')
    graph=dashboard.findChild(QQuickItem,'dagBlockRelationsGraph');assert graph is not None
    def js(code):
        expression=QQmlExpression(qmlContext(graph),graph,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        value=value[0] if isinstance(value,tuple) else value
        return value.toVariant() if hasattr(value,'toVariant') else value
    def descendants(item):
        for child in item.childItems():yield child;yield from descendants(child)
    def digest(count,index):return hashlib.sha256(('synthetic-conveyor-'+str(count)+'-'+str(index)).encode()).hexdigest()
    def data(count,tip=127):
        rows=[]
        for index in range(max(0,tip-127),tip+1):
            parents=[] if index==0 else sorted({max(0,index-1),max(0,index-3),max(0,index-7)})
            rows.append({'hash':digest(count,index),'height':index,'rank':index,
                'parent_hashes':[digest(count,parent) for parent in parents],
                'proposer_index':-1 if index==0 else (index-1)%count,'producer_sequence':0 if index==0 else (index-1)//count,
                'admission_index':index,'timestamp':1700000000+index,'transaction_count':0,
                'state':'GENESIS' if index==0 else 'ADMITTED_UNFINALIZED','signature_verified':index>0})
        known={row['hash'] for row in rows}
        graph_data={'topology':'MULTIPARENT_DAG','producer_count':count,'source':'SYNTHETIC_PUBLIC_TOPOLOGY_FIXTURE',
                    'blocks':rows,'edges':[{'from':parent,'to':row['hash']} for row in rows for parent in row['parent_hashes'] if parent in known],
                    'tip_height':tip,'metrics':{'proposal_bps':64,'bps':64},'history_limit':128}
        body={'state':'RUNNING','producer_count':count,'worker_count':count,'chain_id':'synthetic-'+str(count),
            'block_graph':graph_data,'live':{'mode':'ASYNC_INDEPENDENT_PRODUCERS','enabled':True,'state':'RUNNING',
                'blocks':8,'transactions_per_block':0,'interval_ms':125,'target_proposal_bps':64},
            'producers':[{'index':i,'proposals':20+i,'transactions':i,'observed_proposal_bps':3+i/2,'configured_interval_ms':100+i*13} for i in range(count)]}
        return {'parallel_dag':body,'ui_operation':{}}
    def publish(body):
        window.setProperty('packet',json.dumps(body));app.processEvents();app.processEvents()
    def wait(milliseconds):
        loop=QEventLoop();timer=QTimer();timer.setSingleShot(True);timer.setTimerType(Qt.PreciseTimer)
        timer.timeout.connect(loop.quit);timer.start(milliseconds);loop.exec();app.processEvents()
    try:
        payload=data(8);publish(payload);wait(50)
        assert graph.property('producerCount')==dashboard.property('producerCount')==8
        assert graph.property('shownCount')==128
        assert dashboard.property('asynchronous') and len(dashboard.property('producerRows').toVariant())==8
        points={item.property('blockHash'):item for item in descendants(graph) if item.objectName()=='relationBlock'}
        assert len(points)==128
        expected={row['hash']:row for row in payload['parallel_dag']['block_graph']['blocks']}
        assert set(points)==set(expected)
        assert {item.property('proposerIndex') for item in points.values() if not item.property('genesis')}==set(range(8))
        before={identifier:(item,item.x()) for identifier,item in points.items()}
        # New headers translate the shared parent; retained point local x
        # stays fixed rather than dirtying every retained edge's geometry.
        publish(data(8,129));wait(25)
        current={item.property('blockHash'):item for item in descendants(graph) if item.objectName()=='relationBlock'}
        stable=[identifier for identifier in before if identifier in current and expected[identifier]['admission_index']<100]
        assert len(stable)>80
        assert all(current[identifier] is before[identifier][0] and abs(current[identifier].x()-before[identifier][1])<.001 for identifier in stable)
        tail=sorted((item.mapToItem(graph,QPointF(5,5)).x() for item in current.values() if item.property('index')<104))
        pitch=graph.property('pointPitch')
        assert max(b-a for a,b in zip(tail,tail[1:]))<=3*pitch
        head=[item for item in current.values() if item.property('index')>=104]
        assert any(abs(item.property('arrivalYOffset'))>1 for item in head),'Real new points need local endpoint movement'
        assert all(abs(item.property('arrivalOffset'))<=min(12,2*pitch)+.01 for item in head)
        assert all(0<=item.mapToItem(graph,QPointF(5,5)).x()<=graph.width() for item in current.values())
        links=json.loads(js('JSON.stringify(_edges)'))
        actual_rows={row['hash']:row for row in data(8,129)['parallel_dag']['block_graph']['blocks']}
        assert all(link['from'] in actual_rows[link['to']]['parent_hashes'] for link in links)
        # A much later actual ordinal rebases the local coordinates; the
        # source keys remain exact and physical positions stay in the plot.
        publish(data(8,5000));wait(5)
        assert graph.property('_coordinateTip')<=4096 and graph.property('shownCount')==128
        publish(data(16));wait(5)
        assert graph.property('producerCount')==16 and graph.property('shownCount')==128
        assert set(js('_rows.map(function(row){return row.proposer_index}).filter(function(index){return index>=0})'))==set(range(16))
        assert len({str(js('proposerColor('+str(index)+')')) for index in range(8)})==8
        bad=data(16);bad['parallel_dag']['block_graph']['producer_count']=17;publish(bad)
        assert not graph.property('supportedTopology') and graph.property('shownCount')==0
        assert not warnings,warnings
        print(json.dumps({'status':'PASS','software_only':True,'source':'Synthetic public topology fixture',
            'actual_supplied_keys_preserved':128,'dynamic_producer_counts':[8,16],
            'retained_points_keep_local_geometry':len(stable),'local_new_head_endpoints_move':True,
            'strict_tail_occupancy':True,'ordinal_rebase_verified':True,'node_started':False,'warnings':0}))
    finally:
        window.close();engine.deleteLater();app.processEvents()


class BlockGraphConveyorTests(unittest.TestCase):
    def test_dynamic_producer_lanes_and_true_retained_conveyor(self):
        with tempfile.TemporaryDirectory(prefix='gg-conveyor-guard-') as temporary:
            target=Path(temporary)
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                     GG_DESKTOP_STATE_ROOT=str(target/'state'),GG_DESKTOP_DATA_ROOT=str(target/'data'))
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                   cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=12)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
