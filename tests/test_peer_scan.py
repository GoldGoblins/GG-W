import unittest
from backend import gg_peer_scan as scan


class PeerScanModelTests(unittest.TestCase):
    def test_refused_record_does_not_advance_validated_prefix_until_real_payload_arrives(self):
        state=scan.initial();a,b,c='a'*64,'b'*64,'c'*64
        scan.advance(state,scan.event('OBSERVED',1,a),{a,c})
        scan.advance(state,scan.event('OBSERVED',2,b,'REFUSED',scan.REASONS['REFUSED']),{a,c})
        scan.advance(state,scan.event('OBSERVED',3,c),{a,c})
        self.assertEqual((state['position'],state['prefix']),(3,1))
        with self.assertRaisesRegex(ValueError,'RESOLUTION'):scan.advance(state,scan.event('VALIDATED',2,b),{a,c})
        scan.advance(state,scan.event('VALIDATED',2,b),{a,b,c})
        self.assertEqual((state['position'],state['prefix']),(3,3));self.assertEqual(state['pending'],{})

    def test_bad_position_or_false_admission_is_rejected_without_manufacturing_a_prefix(self):
        state=scan.initial(7)
        for value in (scan.event('OBSERVED',9,'a'*64),scan.event('OBSERVED',8,'a'*64)):
            with self.assertRaises(ValueError):scan.advance(state,value,set())
        self.assertEqual(scan.summary(state)['validated_prefix'],7)

    def test_cli_rejects_inconsistent_or_incomplete_validation_claims(self):
        from backend.terminal_cli import _foreground_peer_sync
        base={'state':'SCANNED_WITH_REFUSALS','received_records':3,'remote_records':3,'pending_records':0,
            'validated_prefix':1,'declined_records':1,'unresolved_records':1}
        for change in ({'validated_prefix':4},{'unresolved_records':False},{'state':'CAUGHT_UP'},{'declined_records':0},{'unresolved_records':0},
                {'state':'CAUGHT_UP','pending_records':1,'remote_records':4},{'state':'CATCHING_UP'}):
            row=_foreground_peer_sync({'peer_status':[{'label':'Linux','sync':{**base,**change}}]})[0]
            self.assertEqual(row['state'],'UNOBSERVED');self.assertIsNone(row['received_records'])
