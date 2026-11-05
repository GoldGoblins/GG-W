"""Actual offscreen QML financial projection; no live app or image capture."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]


def fixture(path):
    sys.path.insert(0,str(ROOT))
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    body=json.loads(path.read_text(encoding='utf-8'));app=QApplication([])
    engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('initialJSON',json.dumps({'parallel_dag':body,'ui_operation':{}}))
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {id:testWindow;width:1100;height:760;visible:true;property var packet:JSON.parse(initialJSON)
GGParallelDagDashboard {id:dashboard;anchors.fill:parent;state:testWindow.packet}}
'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(path.parent/'financial-fixture.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];root=window.findChild(QQuickItem,'parallelDagDashboard')
    def js(expression):
        exp=QQmlExpression(qmlContext(root),root,expression);result=exp.evaluate()
        assert not exp.hasError(),exp.error().toString()
        value=result[0] if isinstance(result,tuple) else result
        return value.toVariant() if hasattr(value,'toVariant') else value
    def items(item):
        yield item
        for child in item.childItems():yield from items(child)
    def named(name):
        value=next((item for item in items(root) if item.objectName()==name),None)
        assert value is not None,name
        return value
    try:
        QTest.qWait(80)
        assert root.property('financialSource') and root.property('sdkSource') and root.property('membershipOnly')
        assert not root.property('canStartOwn') and not root.property('canStartDefaultStress')
        assert js('metricAt(0).value')==body['certified_blocks']
        assert js('metricAt(1).value')==body['certified_transactions']
        assert js('metricAt(2).value')==body['rejected_transactions']
        assert named('dagCanonicalFinality').property('value')=='SDK-certifierat tillstånd'
        assert named('dagFinancialApplied').property('value')==body['certified_transactions']
        own=body['own_financial_accounts']
        if own:
            value=named('dagFinancialAccount').property('value')
            if own[0].get('exists') is False:
                assert value=='Verifierad frånvaro' and 'nonce' not in value and 'atomer' not in value,value
                assert 'Kontot finns inte i verifierat tillstånd' in js('financialAccountDetail(ownFinancialAccounts[0])')
            else:assert str(own[0]['balance_atomic']) in value and str(own[0]['nonce']) in value,value
        else:assert named('dagFinancialAccount').property('value')=='Väntar på certifierat kontotillstånd'
        tree=body['dag_proofs'].get('account_tree')
        assert named('dagFinancialAccountCount').isVisible() is bool(tree)
        if tree:assert named('dagFinancialAccountCount').property('value')==tree['count']
        profiles=body.get('financial_account_profiles',{})
        if profiles.get('selected_profile'):
            selected=next(row for row in profiles['profiles'] if row['profile']==profiles['selected_profile'])
            if selected['public_key']==body['dag_proofs'].get('selected_account'):assert named('dagFinancialAccount').property('name')=='Konto · '+selected['label']
        assert js('producerName(0)').startswith(body['lan']['producer_identities'][0]['display_name'])
        eligible=body['lan']['participation'].get('eligible_network_producers',body['producer_count'])
        assert root.property('eligibleProducerCount')==eligible
        assert js('proofRows.length')==len(body['dag_proofs'].get('proven_blocks',[]))
        assert not named('dagBlockRelationsGraph').isVisible()
        assert named('dagSparseProofScope').isVisible()
        assert not warnings,sorted(set(warnings))
        print(json.dumps({'status':'PASS','actual_QML':True,'signed_owner_projection':True,
            'exact_account_and_counters':True,'receipt_block_rows':js('proofRows.length'),
            'no_fabricated_parent_graph':True,'active_app_touched':False,'images_captured':False,'warnings':len(warnings)}))
    finally:
        window.close();engine.deleteLater();app.processEvents()


class FinancialDashboardUI(unittest.TestCase):
    def public_view(self):
        # Presentation-only values; this test does not authenticate a certificate.
        body={'mode':'FINANCIAL_SDK_CERTIFIED_VIEW','state':'CERTIFIED','producer_count':6,
            'certified_blocks':'9007199254740993','certified_transactions':'9223372036854775807','rejected_transactions':'7',
            'own_financial_accounts':[{'address':'a'*64,'balance_atomic':'250000000000','nonce':'18446744073709551615'}],
            'lan':{'state':'READY','producer_identities':[{'index':0,'display_name':'Linux · 1','local':True}],
                'participation':{'producer':True,'local_producer_count':2,'eligible_network_producers':4}},
            'lan_setup':{'active':True},'observation':{'read_only':True},
            'dag_proofs':{'state':'CERTIFIED','canonical_finality':True,'proven_blocks':[]},'block_graph':{'blocks':[],'edges':[]}}
        return body

    def check_view(self,body):
        with tempfile.TemporaryDirectory(prefix='gg-financial-qml-') as directory:
            path=Path(directory)/'public-view.json';path.write_text(json.dumps(body),encoding='utf-8')
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                GG_DESKTOP_STATE_ROOT=str(Path(directory)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(directory)/'data'))
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',str(path)],
                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout.strip())

    def test_exact_financial_view_in_actual_offscreen_QML(self):
        self.check_view(self.public_view())

    def test_general_account_absence_is_distinct_from_an_existing_zero_balance(self):
        for exists in (True,False):
            with self.subTest(exists=exists):
                body=self.public_view();body['own_financial_accounts']=[{'address':'a'*64,'balance_atomic':'0',
                    'nonce':'1' if exists else '0','exists':exists,'certificate_height':42}]
                body['dag_proofs']['account_tree']={'count':'5004'}
                self.check_view(body)

    def test_missing_account_proof_shows_waiting_instead_of_a_fabricated_zero(self):
        body=self.public_view();body['own_financial_accounts']=[]
        self.check_view(body)

    def test_selected_protected_account_label_matches_the_actual_requested_address(self):
        body=self.public_view();body['dag_proofs']['selected_account']='a'*64
        body['financial_account_profiles']={'selected_profile':'Alice','profiles':[{'profile':'Alice','label':'Public wallet','public_key':'a'*64}]}
        self.check_view(body)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
