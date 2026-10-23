from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

from capability_registry import (  # noqa: E402
    CapabilityRegistry,
    CapabilityRegistryError,
)


SEEDS = (
    PROJECT
    / "config"
    / "capability-seeds-v1.json"
)

MANIFEST = (
    PROJECT
    / "SOURCE-MANIFEST.json"
)


def load_seed_data() -> dict:
    return json.loads(
        SEEDS.read_text(
            encoding="utf-8"
        )
    )


def load_manifest() -> dict:
    return json.loads(
        MANIFEST.read_text(
            encoding="utf-8"
        )
    )


def real_registry(
    seed_data: dict | None = None,
) -> CapabilityRegistry:
    return CapabilityRegistry.from_data(
        repo_root=REPO,
        project_root=PROJECT,
        seed_data=(
            load_seed_data()
            if seed_data is None
            else seed_data
        ),
        manifest=load_manifest(),
    )


class CapabilityRegistryTests(
    unittest.TestCase
):
    def test_real_seed_graph_binds_current_source(
        self,
    ) -> None:
        registry = real_registry()
        summary = registry.summary()

        self.assertEqual(
            summary["capability_count"],
            35,
        )

        self.assertEqual(
            registry.get(
                "verify.qml.gate"
            ).content_sha256,
            (
                "71d2e1f25dcc66ab9fc61806ffaa6a6c414734ded47e7e1398cc3a84ec3d6e72"
            ),
        )

        self.assertEqual(
            registry.get(
                "workflow.qml.post_draft_repair"
            ).depends_on,
            (
                "verify.qml.preflight",
                "repair.qml.local_model",
            ),
        )

    def test_qml_repair_search_is_local_and_bounded(
        self,
    ) -> None:
        registry = real_registry()

        results = {
            record.human_id
            for record
            in registry.search(
                "qml repair",
                limit=8,
            )
        }

        self.assertIn(
            "repair.qml.local_model",
            results,
        )

        self.assertIn(
            "workflow.qml.post_draft_repair",
            results,
        )

        working_set = registry.active_working_set(
            "qml repair",
            limit=8,
            depth=2,
        )

        ids = {
            record.human_id
            for record in working_set
        }

        self.assertLessEqual(
            len(ids),
            8,
        )

        self.assertIn(
            "repair.qml.local_model",
            ids,
        )

        self.assertIn(
            "verify.qml.preflight",
            ids,
        )

        self.assertIn(
            "workflow.qml.post_draft_repair",
            ids,
        )

    def test_semantic_metadata_does_not_change_execution_revision(
        self,
    ) -> None:
        original_data = load_seed_data()
        changed_data = copy.deepcopy(
            original_data
        )

        target = next(
            item
            for item
            in changed_data["capabilities"]
            if item["human_id"]
            == "analyze.source.qml"
        )

        target["description"] += (
            " Additional retrieval wording."
        )

        target["tags"].append(
            "nearby"
        )

        original = real_registry(
            original_data
        ).get(
            "analyze.source.qml"
        )

        changed = real_registry(
            changed_data
        ).get(
            "analyze.source.qml"
        )

        self.assertEqual(
            original.execution_revision_sha256,
            changed.execution_revision_sha256,
        )

        self.assertNotEqual(
            original.metadata_sha256,
            changed.metadata_sha256,
        )

    def test_hard_dependency_changes_execution_revision(
        self,
    ) -> None:
        original_data = load_seed_data()
        changed_data = copy.deepcopy(
            original_data
        )

        target = next(
            item
            for item
            in changed_data["capabilities"]
            if item["human_id"]
            == "verify.qml.preflight"
        )

        target["depends_on"].append(
            "analyze.source.qml"
        )

        original = real_registry(
            original_data
        ).get(
            "verify.qml.preflight"
        )

        changed = real_registry(
            changed_data
        ).get(
            "verify.qml.preflight"
        )

        self.assertNotEqual(
            original.dependency_root_sha256,
            changed.dependency_root_sha256,
        )

        self.assertNotEqual(
            original.execution_revision_sha256,
            changed.execution_revision_sha256,
        )

    def test_hard_dependency_cycle_is_rejected(
        self,
    ) -> None:
        data = load_seed_data()

        python_item = next(
            item
            for item
            in data["capabilities"]
            if item["human_id"]
            == "analyze.source.python"
        )

        json_item = next(
            item
            for item
            in data["capabilities"]
            if item["human_id"]
            == "analyze.source.json"
        )

        python_item["depends_on"] = [
            "analyze.source.json"
        ]

        json_item["depends_on"] = [
            "analyze.source.python"
        ]

        with self.assertRaises(
            CapabilityRegistryError
        ):
            real_registry(data)

    def test_source_identity_drift_is_rejected(
        self,
    ) -> None:
        data = load_seed_data()

        target = next(
            item
            for item
            in data["capabilities"]
            if item["human_id"]
            == "analyze.source.shell"
        )

        target["content_sha256"] = (
            "0" * 64
        )

        with self.assertRaises(
            CapabilityRegistryError
        ):
            real_registry(data)

    def test_python_source_is_parsed_not_imported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            project = repo / "project"

            project.mkdir()

            source = repo / "danger.py"

            source.write_text(
                (
                    'raise RuntimeError("MUST_NOT_IMPORT")\n'
                    "\n"
                    "def safe_symbol():\n"
                    "    return 1\n"
                ),
                encoding="utf-8",
            )

            content_sha = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()

            seed_data = {
                "schema":
                    "gg.capability-seeds.v1",
                "capabilities": [
                    {
                        "human_id":
                            "test.static.parse",
                        "description":
                            "Static parse fixture.",
                        "kind":
                            "ANALYZER",
                        "source_path":
                            "danger.py",
                        "manifest_key":
                            None,
                        "content_sha256":
                            content_sha,
                        "entrypoint_kind":
                            "python_symbol",
                        "entrypoint":
                            "safe_symbol",
                        "contract": {
                            "effect_class":
                                "IN_MEMORY_ONLY",
                            "risk_floor":
                                "GREEN",
                            "persistent_write":
                                "NONE",
                            "network":
                                "NONE",
                            "sudo":
                                "NO",
                            "execution_authority":
                                "NONE",
                            "model_inference":
                                False,
                        },
                        "depends_on": [],
                        "tags": [
                            "static"
                        ],
                        "relations": [],
                    }
                ],
            }

            registry = (
                CapabilityRegistry.from_data(
                    repo_root=repo,
                    project_root=project,
                    seed_data=seed_data,
                    manifest={
                        "files": {}
                    },
                )
            )

            self.assertEqual(
                registry.get(
                    "test.static.parse"
                ).entrypoint,
                "safe_symbol",
            )


if __name__ == "__main__":
    unittest.main()
