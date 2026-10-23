"""Contract tests for the code-owned workbench contribution registry."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend import workbench_registry


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "registry.json"
    initial = workbench_registry.default_state()
    workbench_registry.save_state(initial, path)

    loaded = workbench_registry.load_state(path)
    assert loaded["schema"] == workbench_registry.SCHEMA
    manifest_rows = workbench_registry.rows(loaded)
    assert manifest_rows
    assert all(row["enabled"] is True for row in manifest_rows)
    assert any(row["required"] is True for row in manifest_rows)

    optional = next(row for row in manifest_rows if not row["required"])
    disabled = workbench_registry.set_enabled(
        str(optional["id"]), False, path
    )
    disabled_rows = workbench_registry.rows(disabled)
    disabled_row = next(
        row for row in disabled_rows if row["id"] == optional["id"]
    )
    assert disabled_row["enabled"] is False
    assert workbench_registry.is_enabled(str(optional["hostKind"]), disabled) is False

    profile_path = Path(directory) / "profile-registry.json"
    workbench_registry.save_state(workbench_registry.default_state(), profile_path)
    profile_state = workbench_registry.set_enabled(
        str(optional["id"]),
        False,
        profile_path,
        theme_id="obsidian-ledger",
        profile_id="research",
    )
    assert next(
        row for row in workbench_registry.rows(
            profile_state, "obsidian-ledger", "research"
        ) if row["id"] == optional["id"]
    )["enabled"] is False
    assert next(
        row for row in workbench_registry.rows(
            profile_state, "obsidian-ledger", "standard"
        ) if row["id"] == optional["id"]
    )["enabled"] is True

    copied_theme = workbench_registry.copy_theme(
        "obsidian-ledger", "night-theme", profile_path
    )
    assert workbench_registry.is_enabled(
        str(optional["hostKind"]),
        copied_theme,
        theme_id="night-theme",
        profile_id="research",
    ) is False

    required = next(row for row in manifest_rows if row["required"])
    required_state = workbench_registry.set_enabled(
        str(required["id"]), False, path
    )
    assert required_state["enabled"][required["id"]] is True

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["enabled"]["untrusted.arbitrary.extension"] = True
    normalized = workbench_registry.normalize_state(raw)
    assert "untrusted.arbitrary.extension" not in normalized["enabled"]

    try:
        workbench_registry.set_enabled("untrusted.arbitrary.extension", True, path)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown contribution was accepted")

print("Workbench registry manifest/state contract PASS")
