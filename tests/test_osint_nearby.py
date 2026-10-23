"""Local receive-only observations, pause gating and source data boundaries."""
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import osint_nearby as nearby, osint_contract as contract
from backend.osint_host import OsintHost


class NearbyTests(unittest.TestCase):
    def test_wifi_escaped_names_dedup_and_no_rescan(self):
        output = r'AA\:BB\:CC\:DD\:EE\:01:Lab\: WiFi:76:2412 MHz:yes' + '\n'
        output += r'AA\:BB\:CC\:DD\:EE\:01:Lab\: WiFi:76:2412 MHz:yes' + '\n'
        with patch.object(nearby, '_run', return_value=output) as run:
            rows = nearby._wifi()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Lab: WiFi')
        self.assertEqual(rows[0]['signal'], 76)
        self.assertEqual(rows[0]['freshness'], 'AGE_UNKNOWN')
        self.assertTrue(rows[0]['connected'])
        self.assertNotIn('AA:BB:CC', json.dumps(rows))
        self.assertEqual(run.call_args.args[0][-2:], ['--rescan', 'no'])
        self.assertNotIn('lat', rows[0])

    def test_bluetooth_reads_only_existing_objects_with_signal(self):
        payload = {'data': [{'/org/bluez/test': {'org.bluez.Device1': {'Address': {'type': 's', 'data': 'AA:BB'},
            'Alias': {'type': 's', 'data': 'Test device'}, 'RSSI': {'type': 'n', 'data': -66}}},
            '/org/bluez/paired': {'org.bluez.Device1': {'Alias': {'type': 's', 'data': 'Old paired device'}}}}]}
        with patch.object(nearby, '_run', return_value=json.dumps(payload)) as run:
            rows = nearby._bluetooth()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['signal_unit'], 'dBm')
        self.assertEqual(rows[0]['classification'], 'UNCLASSIFIED')
        self.assertEqual(run.call_args.args[0][-1], 'GetManagedObjects')
        self.assertNotIn('StartDiscovery', run.call_args.args[0])

    def test_missing_service_does_not_remove_other_observations(self):
        with patch.object(nearby, '_wifi', return_value=[{'kind': 'wifi'}]), patch.object(nearby, '_bluetooth', side_effect=OSError()):
            result = nearby.collect()
        self.assertEqual(result['rows'], [{'kind': 'wifi'}])
        self.assertEqual(result['device_positions'], 'UNKNOWN')
        self.assertEqual(result['sources'][1]['status'], 'UNAVAILABLE')

    def test_paused_host_makes_no_reads_and_discards_inflight_result(self):
        host = OsintHost()
        self.addCleanup(host.shutdown)
        emitted = []
        host.nearbyUpdated.connect(emitted.append)
        with patch.object(nearby, 'collect') as collect:
            self.assertEqual(json.loads(host.nearbySnapshot())['status'], 'PAUSED')
            collect.assert_not_called()
        host._nearby_active = True
        old = host._nearby_generation
        host.setNearbyActive(False)
        future = Future(); future.set_result({'status': 'SYSTEM_CACHE', 'rows': [{'name': 'cached'}]})
        host._nearby_finished(future, old)
        self.assertEqual(emitted, [])
        self.assertEqual(json.loads(host.nearbySnapshot())['rows'], [])

    def test_route_step_distances_and_gps_validation(self):
        route = {'legs': [{'steps': [
            {'name': 'Start', 'distance': 200, 'maneuver': {'type': 'depart', 'location': [18, 59]}},
            {'name': 'Next', 'distance': 100, 'maneuver': {'type': 'turn', 'modifier': 'right', 'location': [18.01, 59]}},
            {'name': 'Finish', 'distance': 0, 'maneuver': {'type': 'arrive', 'location': [18.02, 59]}}
        ]}]}
        steps = contract._normalize_route_steps(route)
        self.assertEqual([step['at_m'] for step in steps], [0, 200, 300])
        self.assertEqual(steps[1]['modifier'], 'right')
        with patch.object(contract, '_read_map_api', side_effect=AssertionError('unexpected network')):
            with self.assertRaises(OSError): contract.geocode_place('GPS')
            with self.assertRaises(OSError): contract.geocode_place('GPS', {'lat': 91, 'lon': 0})
            with self.assertRaises(OSError): contract.geocode_place('GPS', {'lat': 59, 'lon': 18, 'timestamp': (time.time() - 130) * 1000})

    def test_route_requests_turn_instructions(self):
        route = {'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[18, 59], [18.01, 59]]}, 'distance': 800, 'duration': 60,
                            'legs': [{'steps': [{'name': 'Start', 'distance': 800, 'maneuver': {'type': 'depart', 'location': [18, 59]}}]}]}]}
        with patch.object(contract, 'geocode_place', side_effect=[{'lat': 59, 'lon': 18}, {'lat': 59, 'lon': 18.01}]), patch.object(
            contract, '_read_map_api', return_value=json.dumps(route).encode()
        ) as request:
            result = contract.plan_driving_route(['Start', 'End'])
        self.assertTrue(result['ok'])
        self.assertIn('steps=true', request.call_args.args[0])
        self.assertEqual(result['steps'][0]['at_m'], 0)


if __name__ == '__main__': unittest.main()
