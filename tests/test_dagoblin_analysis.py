"""Exact dimensional and adversarial-input tests for the offline planner."""

from fractions import Fraction as F
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support.dagoblin import analyze as a


class WireAndUnitsTests(unittest.TestCase):
    def wire(self, **changes):
        args = dict(blocks_per_second=300, transactions_per_block=1000,
                    payload_bytes=186, signature_bytes=64)
        args.update(changes)
        return a.wire_budget(**args)

    def test_required_examples_are_exact(self):
        examples = a.examples()
        medium = examples["300_blocks_1000_tx_250_bytes"]["per_full_receiver"]
        fast = examples["3000_blocks_1000_tx_250_bytes"]["per_full_receiver"]
        self.assertEqual(medium["bytes_per_second"], 75_000_000)
        self.assertEqual(fast["bytes_per_second"], 750_000_000)
        self.assertEqual(fast["decimal_Gbit_per_second"], 6)
        self.assertEqual(examples["100k_classical_transactions"]["per_full_receiver"]["decimal_MB_per_second"], 32)
        self.assertEqual(examples["100k_hybrid_ml_dsa_65_transactions"]["per_full_receiver"]["decimal_MB_per_second"], F(3629, 10))

    def test_bit_byte_and_decimal_binary_units_do_not_alias(self):
        self.assertEqual(a.link_bytes_per_second(1, "Gbit/s"), 125_000_000)
        self.assertEqual(a.link_bytes_per_second(1, "Gib/s") / 1024**2, 128)
        self.assertEqual(a.link_bytes_per_second(1, "Gibit/s"), a.link_bytes_per_second(1, "Gib/s"))
        self.assertEqual(a.link_bytes_per_second(1, "GiB/s") / 1024**2, 1024)
        self.assertEqual(a.link_bytes_per_second(1, "GiB/s"), a.link_bytes_per_second(1, "Gib/s") * 8)
        self.assertNotEqual(a.link_bytes_per_second(1, "MB/s"), a.link_bytes_per_second(1, "MiB/s"))
        for ambiguous in ("gb/s", "1gb", "gigabit", "GBps", ""):
            with self.subTest(unit=ambiguous), self.assertRaises(ValueError):
                a.link_bytes_per_second(1, ambiguous)

    def test_explicit_wire_components_parents_and_replication(self):
        result = self.wire(witness_bytes=10, public_key_bytes=32, public_keys_cached=False,
                           header_bytes=80, parent_count=7, replication=3)
        self.assertEqual(result["transaction_bytes"]["total"], 292)
        self.assertEqual(result["serialized_block_bytes"], 292_304)
        self.assertEqual(result["per_full_receiver"]["bytes_per_second"], 87_691_200)
        self.assertEqual(result["all_copies"]["bytes_per_second"], 3 * 87_691_200)
        self.assertEqual(result["unique_transactions_per_second"], 300_000)

    def test_public_key_cache_is_separate_from_steady_state(self):
        cached = self.wire(public_key_bytes=1952, cached_key_count=42)
        uncached = self.wire(public_key_bytes=1952, public_keys_cached=False)
        self.assertEqual(cached["one_time_public_key_cache_fill_bytes"], 1952 * 42)
        self.assertEqual(cached["transaction_bytes"]["public_key_on_wire"], 0)
        self.assertEqual(uncached["transaction_bytes"]["public_key_on_wire"], 1952)
        self.assertEqual(uncached["per_full_receiver"]["bytes_per_second"] - cached["per_full_receiver"]["bytes_per_second"], 1952 * 300_000)

    def test_ml_dsa_parameters_are_nist_table_sizes_not_implementations(self):
        self.assertEqual([(v["signature_bytes"], v["public_key_bytes"]) for v in a.ML_DSA_PARAMETERS.values()],
                         [(2420, 1312), (3309, 1952), (4627, 2592)])
        with self.assertRaises(TypeError):
            a.ML_DSA_PARAMETERS["ML-DSA-65"]["signature_bytes"] = 64

    def test_wire_monotonicity_and_zero_offered_rate(self):
        baseline = self.wire()["all_copies"]["bytes_per_second"]
        for change in ({"blocks_per_second": 301}, {"transactions_per_block": 1001},
                       {"witness_bytes": 1}, {"signature_bytes": 65},
                       {"parent_count": 1}, {"header_bytes": 1}, {"replication": 2}):
            with self.subTest(change=change):
                self.assertGreater(self.wire(**change)["all_copies"]["bytes_per_second"], baseline)
        self.assertEqual(self.wire(blocks_per_second=0)["per_full_receiver"]["bytes_per_second"], 0)

    def test_exact_rationals_and_no_planned_throughput_ceiling(self):
        result = self.wire(blocks_per_second="1/3")
        self.assertEqual(result["unique_transactions_per_second"], F(1000, 3))
        large = self.wire(blocks_per_second=10**50)
        self.assertEqual(large["unique_transactions_per_second"], 10**53)
        self.assertEqual(large["status"], "SERIALIZED_WIRE_LOWER_BOUND")
        self.assertFalse(large["achieved_benchmark"])

    def test_rejects_nonexact_nonphysical_and_fractional_counts(self):
        for value in (True, False, 0.1, float("nan"), float("inf"), "1.5", "1e9", "1/0", "-1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.wire(blocks_per_second=value)
        for changes in ({"transactions_per_block": "3/2"}, {"transactions_per_block": 0},
                        {"signature_bytes": -1}, {"parent_count": "1/2"},
                        {"public_keys_cached": 1}, {"replication": 0},
                        {"payload_bytes": 0, "signature_bytes": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.wire(**changes)


class BufferBatchAndPollingTests(unittest.TestCase):
    def test_buffer_exactness_ceiling_error_is_less_than_a_byte(self):
        result = a.retained_buffer(bytes_per_second="10/3", window_seconds="7/5", copies=3, overhead_factor="3/2")
        exact, whole = result["retained_bytes_exact"], result["required_whole_bytes"]
        self.assertEqual(exact, 21)
        self.assertEqual(whole, 21)
        for divisor in range(2, 12):
            result = a.retained_buffer(bytes_per_second=F(1, divisor), window_seconds=1)
            error = result["required_whole_bytes"] - result["retained_bytes_exact"]
            self.assertGreaterEqual(error, 0)
            self.assertLess(error, 1)

    def test_buffer_time_and_copies_increase_cost(self):
        base = a.retained_buffer(bytes_per_second=75_000_000, window_seconds=2)
        twice = a.retained_buffer(bytes_per_second=75_000_000, window_seconds=4)
        self.assertEqual(base["required_whole_bytes"], 150_000_000)
        self.assertEqual(twice["required_whole_bytes"], 2 * base["required_whole_bytes"])
        with self.assertRaises(ValueError):
            a.retained_buffer(bytes_per_second=1, window_seconds=0)
        with self.assertRaises(ValueError):
            a.retained_buffer(bytes_per_second=1, window_seconds=1, overhead_factor="1/2")

    def test_checkpoint_cost_amortizes_exactly_not_free_security(self):
        one = a.checkpoint_batch_cost(batch_transactions=1, checkpoint_bytes=3309, verification_seconds="1/100")
        many = a.checkpoint_batch_cost(batch_transactions=1000, checkpoint_bytes=3309, verification_seconds="1/100")
        self.assertEqual(many["bytes_per_transaction"] * 1000, one["bytes_per_transaction"])
        self.assertEqual(many["verification_seconds_per_transaction"], F(1, 100_000))
        with self.assertRaises(ValueError):
            a.checkpoint_batch_cost(batch_transactions=0, checkpoint_bytes=1, verification_seconds=1)

    def test_eleven_peers_cost_and_shared_hub_risk(self):
        result = a.peer_polling_cost(request_bytes=64, response_bytes=1024, peers=11,
                                    interval_seconds="1/2", shared_latest_hub=True,
                                    independent_fault_domains=1)
        self.assertEqual(result["exchanges_per_second"], 22)
        self.assertEqual(result["total_bytes_per_second"], 23_936)
        self.assertEqual(result["risk"], "SHARED_HUB_AVAILABILITY_AND_VIEW_CONCENTRATION")
        self.assertEqual(result["independent_fault_domains"], 1)
        self.assertEqual(a.peer_polling_cost(request_bytes=1, response_bytes=1)["risk"], "FAULT_INDEPENDENCE_NOT_PROVEN")
        with self.assertRaises(ValueError):
            a.peer_polling_cost(request_bytes=1, response_bytes=1, peers=11, independent_fault_domains=12)


class CapacityTests(unittest.TestCase):
    def plan(self, **changes):
        args = dict(transactions_per_block=1000, payload_bytes=186, signature_bytes=64,
                    link={"value": 6, "unit": "Gbit/s"})
        args.update(changes)
        return a.capacity_bounds(**args)

    def test_full_receiver_link_bound_and_status(self):
        result = self.plan()
        self.assertEqual(result["scenario_blocks_per_second"], 3000)
        self.assertEqual(result["scenario_unique_transactions_per_second"], 3_000_000)
        self.assertEqual(result["byte_model_upper_bound_unique_transactions_per_second"], 3_000_000)
        self.assertEqual(result["resource_limits"]["network"]["status"], "UNDER_STATED_BYTE_MODEL")
        self.assertEqual(result["bottlenecks"], ["network"])
        self.assertEqual(result["status"], "CONDITIONAL_CAPACITY_SCENARIO")
        self.assertFalse(result["achieved_benchmark"])
        self.assertIn("cpu_verify", result["unspecified_resource_stages"])
        self.assertTrue(any("BFT quorum" in text for text in result["unmodelled_constraints"]))

    def test_link_parent_header_fanout_safety_and_utilization(self):
        result = self.plan(header_bytes=100, parent_count=7, utilization="4/5",
                           safety_factor=2, fanout=3, copies=2)
        self.assertEqual(result["serialized_block_bytes_including_amortized_checkpoint"], 250_324)
        self.assertEqual(result["scenario_blocks_per_second"], F(50_000_000, 250_324))
        baseline = self.plan()["scenario_unique_transactions_per_second"]
        self.assertLess(result["scenario_unique_transactions_per_second"], baseline)

    def test_measured_signature_time_worker_and_batch_scaling(self):
        slow = self.plan(link=None, cpu_sign={"p95_seconds": 10, "workers": 1})
        self.assertEqual(slow["scenario_unique_transactions_per_second"], F(1, 10))
        self.assertIsNone(slow["byte_model_upper_bound_unique_transactions_per_second"])
        self.assertEqual(slow["resource_limits"]["cpu_sign"]["status"], "SERVICE_TIME_SCENARIO_ESTIMATE")
        self.assertNotIn("upper_bound_unique_transactions_per_second", slow)
        doubled = self.plan(link=None, cpu_sign={"p95_seconds": 10, "workers": 2})
        batched = self.plan(link=None, cpu_sign={"p95_seconds": 10, "workers": 2, "transactions_per_batch": 100})
        self.assertEqual(doubled["scenario_unique_transactions_per_second"], F(1, 5))
        self.assertEqual(batched["scenario_unique_transactions_per_second"], 20)
        nanos = self.plan(link=None, cpu_verify={"p95_nanoseconds": 1000, "workers": 2,
                                               "operations_per_batch": 4})
        self.assertEqual(nanos["scenario_unique_transactions_per_second"], 500_000)

    def test_minimum_identifies_actual_declared_resource_bottleneck(self):
        args = dict(cpu_verify={"p95_seconds": "1/10000", "workers": 8},
                    storage={"bytes_per_second": 10**7, "write_amplification": 2},
                    memory={"budget_bytes": 10**8, "window_seconds": 2})
        result = self.plan(**args)
        self.assertEqual(result["bottlenecks"], ["storage"])
        self.assertEqual(result["scenario_unique_transactions_per_second"], 20_000)
        self.assertEqual(result["resource_limits"]["memory"]["unique_transactions_per_second"], 200_000)

    def test_memory_reservation_window_copies_and_whole_block_budget(self):
        result = self.plan(link=None, memory={"budget_bytes": 1_000_001,
                           "reserved_bytes": 1, "window_seconds": 2, "copies": 2,
                           "overhead_factor": 2})
        self.assertEqual(result["resource_limits"]["memory"]["whole_block_slots"], 1)
        self.assertEqual(result["scenario_unique_transactions_per_second"], 500)
        too_small = self.plan(link=None, memory={"budget_bytes": 249_999, "window_seconds": 1})
        self.assertEqual(too_small["scenario_blocks_per_second"], 0)

    def test_checkpoint_wire_and_verification_are_amortized_constraints(self):
        result = self.plan(checkpoint={"batch_transactions": 1000, "checkpoint_bytes": 3309,
                           "verification_seconds": 10, "verification_workers": 1})
        self.assertEqual(result["serialized_block_bytes_including_amortized_checkpoint"], 253_309)
        self.assertEqual(result["bottlenecks"], ["checkpoint_verify"])
        self.assertEqual(result["scenario_unique_transactions_per_second"], 100)
        larger = self.plan(checkpoint={"batch_transactions": 10_000, "checkpoint_bytes": 3309,
                           "verification_seconds": 10, "verification_workers": 1})
        self.assertEqual(larger["scenario_unique_transactions_per_second"], 1000)
        self.assertLess(larger["serialized_block_bytes_including_amortized_checkpoint"], 253_309)

    def test_gpu_requires_measured_relevant_work_and_does_not_erase_cpu(self):
        gpu = dict(p95_seconds="1/1000", workers=100, scope="signature_verification")
        result = self.plan(cpu_verify={"p95_seconds": 1, "workers": 1}, gpu=gpu)
        self.assertEqual(result["bottlenecks"], ["cpu_verify"])
        self.assertEqual(result["resource_limits"]["gpu"]["unique_transactions_per_second"], 100_000)
        self.assertEqual(result["resource_limits"]["gpu"]["status"], "SERVICE_TIME_SCENARIO_ESTIMATE")
        for scope in (None, "rendering", "magic_consensus"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.plan(gpu=dict(gpu, scope=scope))

    def test_p95_scenario_does_not_claim_a_safe_rate_or_mathematical_bound(self):
        result = self.plan(cpu_verify={"p95_seconds": 1, "workers": 1})
        self.assertEqual(result["scenario_unique_transactions_per_second"], 1)
        self.assertEqual(result["byte_model_upper_bound_unique_transactions_per_second"], 3_000_000)
        self.assertIn("unmodelled tail", result["resource_limits"]["cpu_verify"]["condition"])
        self.assertTrue(any("sustained end-to-end load" in note for note in result["assumptions"]))
        # 95/100 calls taking 1 second permits 5 unbounded-tail calls. Both
        # distributions share a 1-second p95 but have very different throughput.
        fast_mean = F(95 * 1 + 5 * 2, 100)
        slow_mean = F(95 * 1 + 5 * 10**9, 100)
        self.assertNotEqual(1 / fast_mean, 1 / slow_mean)

    def test_monotonic_resource_improvements_and_cost_increases(self):
        basic = self.plan()["scenario_unique_transactions_per_second"]
        self.assertEqual(self.plan(link={"value": 12, "unit": "Gbit/s"})["scenario_unique_transactions_per_second"], basic * 2)
        for change in ({"signature_bytes": 128}, {"witness_bytes": 1}, {"fanout": 2},
                       {"utilization": "1/2"}, {"safety_factor": 2}):
            with self.subTest(change=change):
                self.assertLess(self.plan(**change)["scenario_unique_transactions_per_second"], basic)

    def test_invalid_resource_input_fails_closed(self):
        invalid = (
            {"link": None}, {"utilization": 0}, {"utilization": 2},
            {"safety_factor": "1/2"}, {"fanout": 0}, {"copies": False},
            {"cpu_verify": {"p95_seconds": 0}},
            {"cpu_sign": {"p95_seconds": 1, "p95_nanoseconds": 1}},
            {"cpu_sign": {"p95_seconds": 1, "workers": "3/2"}},
            {"cpu_sign": {"p95_seconds": 1, "imagined_speedup": 100}},
            {"storage": {"bytes_per_second": 1, "write_amplification": "1/2"}},
            {"memory": {"budget_bytes": 1, "reserved_bytes": 1, "window_seconds": 1}},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.plan(**change)


class ComparisonAndCliTests(unittest.TestCase):
    def contract(self):
        return {field: {"evidence": field + "-same"} for field in a.COMPARISON_FIELDS}

    def test_each_unequal_or_unknown_contract_blocks_comparison(self):
        baseline = self.contract()
        for field in a.COMPARISON_FIELDS:
            for value in (None, "UNKNOWN", {}, {"evidence": "different"}):
                candidate = dict(baseline, **{field: value})
                with self.subTest(field=field, value=value):
                    result = a.comparison_eligibility(baseline=baseline, candidate=candidate)
                    self.assertEqual(result["status"], "INCOMPARABLE")
                    self.assertIsNone(result["speedup"])
            missing = dict(baseline)
            missing.pop(field)
            self.assertEqual(a.comparison_eligibility(baseline=baseline, candidate=missing)["status"], "INCOMPARABLE")

    def test_equal_metadata_only_permits_measurement_and_types_are_not_aliased(self):
        baseline = self.contract()
        self.assertEqual(a.comparison_eligibility(baseline=baseline, candidate=dict(baseline))["status"],
                         "ELIGIBLE_FOR_CONTROLLED_COMPARISON")
        self.assertEqual(a.comparison_eligibility(baseline=dict(baseline, workload=True),
                                                candidate=dict(baseline, workload=1))["status"], "INCOMPARABLE")
        self.assertEqual(a.comparison_eligibility(baseline=dict(baseline, workload={"x": "UNKNOWN"}),
                                                candidate=baseline)["unknown_fields"], ["workload"])

    def cli(self, *args, input_text=None):
        return subprocess.run([sys.executable, str(Path(a.__file__)), *args], input=input_text,
                              text=True, capture_output=True, timeout=5, check=False)

    def test_cli_defaults_to_exact_json_examples_without_state_writes(self):
        result = self.cli("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ANALYTICAL_EXAMPLES_NOT_BENCHMARKS")
        self.assertEqual(output["100k_hybrid_ml_dsa_65_transactions"]["per_full_receiver"]["decimal_MB_per_second"], "3629/10")
        self.assertEqual(result.stderr, "")

    def test_cli_custom_file_and_stdin_are_equivalent(self):
        request = {"operation": "capacity_bounds", "parameters": {
            "transactions_per_block": 1000, "payload_bytes": 186, "signature_bytes": 64,
            "link": {"value": 1, "unit": "Gib/s"}, "utilization": "3/4",
        }}
        encoded = json.dumps(request)
        stdin = self.cli("--input", "-", input_text=encoded)
        with tempfile.TemporaryDirectory(prefix="gg-dagoblin-plan-") as temp:
            path = Path(temp) / "plan.json"
            path.write_text(encoded, encoding="utf-8")
            file = self.cli("--input", str(path))
            self.assertEqual(set(Path(temp).iterdir()), {path})
        self.assertEqual(stdin.returncode, 0, stdin.stderr)
        self.assertEqual(file.returncode, 0, file.stderr)
        self.assertEqual(stdin.stdout, file.stdout)
        output = json.loads(stdin.stdout)
        self.assertEqual(output["scenario_unique_transactions_per_second"], "50331648/125")

    def test_cli_malformed_duplicate_unknown_or_oversize_input(self):
        for text in ("{", "[]", '{"operation":"__import__","parameters":{}}',
                     '{"operation":"link_bytes_per_second","parameters":{"value":1.5,"unit":"B/s"}}',
                     '{"operation":"link_bytes_per_second","parameters":{"value":NaN,"unit":"B/s"}}',
                     '{"operation":"link_bytes_per_second","parameters":{"value":1,"value":2,"unit":"B/s"}}',
                     '{"operation":"wire_budget","parameters":{"private_input_marker":1}}',
                     " " * (a.MAX_INPUT_BYTES + 1)):
            with self.subTest(size=len(text)):
                result = self.cli("--input", "-", input_text=text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["status"], "INVALID_INPUT")
                self.assertNotIn("private_input_marker", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_request_dispatch_only_permits_explicit_pure_operations(self):
        self.assertEqual(a.run_request({"operation": "link_bytes_per_second",
                                       "parameters": {"value": 1, "unit": "B/s"}}), 1)
        with self.assertRaises(ValueError):
            a.run_request({"operation": "capacity_bounds", "parameters": {}, "extra": True})
        with self.assertRaises(ValueError):
            a.run_request({"operation": "capacity_bounds", "parameters": {}})


if __name__ == "__main__":
    unittest.main()
