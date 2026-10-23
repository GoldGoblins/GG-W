from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
BACKEND = PROJECT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

adapters = importlib.import_module("live_aid.adapters")
safe_tool_contract = importlib.import_module("safe_tool_contract")


class LiveAidSnapshotBindingTests(unittest.TestCase):
    def test_base_head_lock(self):
        self.assertEqual(
            adapters.BASE_HEAD,
            "e467c56bc32155045e03e8b422c60baea25019eb",
        )

    def test_reused_components_match_candidate_repo(self):
        problems = adapters.verify_components(REPO)
        self.assertEqual(problems, [])

    def test_authority_is_not_added_by_adapter_contract(self):
        self.assertEqual(adapters.debug_runner_contract()["network"], "none")
        self.assertTrue(
            adapters.code_gate_contract()["gate_pass_is_profile_bound_only"]
        )


    def test_safe_tool_probe_matches_existing_contract(self):
        from live_aid.forensic_resolver import ProbeRequest

        probe = ProbeRequest(
            kind="SAFE_TOOL_SEARCH",
            authority="GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
            profile="SEARCH",
            arguments={"literal": "main"},
            reason="test",
        )
        request = adapters.safe_tool_request(
            probe,
            "tool-" + ("a" * 32),
        )
        validated = safe_tool_contract.validate_request(request)
        self.assertEqual(validated, request)


if __name__ == "__main__":
    unittest.main()
