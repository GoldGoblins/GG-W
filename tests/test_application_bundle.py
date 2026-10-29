"""Relocation, source isolation and meaningful negative export checks."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
spec = importlib.util.spec_from_file_location("gg_application_catalog", PROJECT / "packaging/catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class BundleTests(unittest.TestCase):
    def test_private_data_and_game_content_are_outside_source(self):
        for name in (".env", "config/auth.json", "sessions/history.jsonl", "native/engine/target/release/data.json", "qml/assets/authored/hero.glb", "qml/game/Main.qml", "private.key", "weights.gguf", "state.sqlite", ".runtime/test-state/example.json", ".venv/Lib/settings.json"):
            self.assertFalse(catalog.permitted(name), name)
        self.assertTrue(catalog.permitted("backend/chat_sessions.py"))
        self.assertFalse(catalog.permitted(".venv-windows/Lib/site-packages/installed.py"))
        self.assertTrue(catalog.permitted("knowledge/web-gpts/GG-idekompassen/README.md"))
        self.assertTrue(catalog.permitted("native/engine/.cargo/config.toml"))

    def test_export_refuses_existing_or_source_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "ALREADY_EXISTS"):
                catalog.export_sources(Path(tmp))
        with self.assertRaisesRegex(ValueError, "OUTSIDE_SOURCE"):
            catalog.export_sources(PROJECT / "dist/test")

    def test_secret_values_are_rejected_without_being_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
            (root / "example.py").write_text('key = "' + secret + '"\n')
            with patch.object(catalog, "selected_paths", return_value=["example.py"]):
                with self.assertRaisesRegex(ValueError, "CREDENTIAL_PATTERN") as caught:
                    catalog.make_catalog(root)
            self.assertNotIn(secret, str(caught.exception))

    def test_external_file_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            outside = Path(tmp) / "outside.py"
            outside.write_text("value = 1\n")
            if os.name == 'nt':
                from backend.application_paths import expose_directory
                outside_directory = Path(tmp) / 'external-skills'
                outside_directory.mkdir()
                expose_directory(root / '.agents/skills', outside_directory)
                selected = ['.agents/skills']
                expected = 'INVALID_APPLICATION_LINK'
            else:
                (root / "module.py").symlink_to(outside)
                selected = ['module.py']
                expected = 'EXTERNAL'
            with patch.object(catalog, "selected_paths", return_value=selected):
                with self.assertRaisesRegex(ValueError, expected):
                    catalog.make_catalog(root)

    def test_tampered_catalog_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "example.py").write_text("value = 1\n")
            with patch.object(catalog, "selected_paths", return_value=["example.py"]):
                catalog.write_catalog(root)
                (root / "example.py").write_text("value = 2\n")
                with self.assertRaisesRegex(ValueError, "STALE"):
                    catalog.verify_catalog(root)

    def test_client_skill_registration_preserves_user_skills(self):
        from backend.application_paths import prepare_codex_skills
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            custom = home / "skills/user-owned/SKILL.md"
            custom.parent.mkdir(parents=True)
            custom.write_text("user instructions\n")
            prepare_codex_skills(home)
            prepare_codex_skills(home)
            self.assertEqual(custom.read_text(), "user instructions\n")
            self.assertTrue((home / "skills/gg-live-eyes/SKILL.md").is_file())
            self.assertTrue((home / "skills/gg-blender-reference-workflow/SKILL.md").is_file())

    def test_source_contract_authority_is_unchanged(self):
        manifest = json.loads((PROJECT / "SOURCE-MANIFEST.json").read_text())
        self.assertEqual(manifest["authority"]["general_action_authority"], "NONE")
        self.assertEqual(manifest["authority"]["network_authority"], "NONE")
        self.assertEqual(manifest["autonomy_bootstrap"]["authority_file_mutation"], "FORBIDDEN")

    def test_absent_project_data_is_empty_and_invalid_data_still_fails(self):
        from backend import game_engine_settlement as settlement
        with tempfile.TemporaryDirectory() as tmp, patch.object(settlement, "SOURCE", Path(tmp) / "map.json"):
            settlement.catalog.cache_clear()
            try:
                result = settlement.catalog()
                self.assertEqual(result["routines"], [])
                self.assertEqual(result["roads"], [])
                self.assertEqual(result["fences"], [])
                self.assertIsNone(settlement.build_geometry('SETTLEMENT_ROADS'))
                self.assertIsNone(settlement.build_geometry('SETTLEMENT_FENCES'))
                settlement.SOURCE.write_text('{"schema":"invalid"}')
                settlement.catalog.cache_clear()
                with self.assertRaisesRegex(ValueError, "invalid settlement"):
                    settlement.catalog()
            finally:
                settlement.catalog.cache_clear()

    def test_export_runs_with_new_home_and_without_shared_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exported = root / "program"
            catalog.export_sources(exported)
            env = os.environ.copy()
            for key in ("GG_WORKSPACE", "GG_GPT_KNOWLEDGE_ROOT", "GG_DESKTOP_STATE_ROOT", "GG_DESKTOP_DATA_ROOT", "GG_USER_CODEX_HOME", "PYTHONPATH"):
                env.pop(key, None)
            env.update(HOME=str(root / "new-user"), XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"), XDG_CACHE_HOME=str(root / "cache"), QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", PYTHONDONTWRITEBYTECODE="1")
            if os.name == 'nt':
                env['USERPROFILE'] = str(root / 'new-user')
                env['GG_USER_HOME'] = str(root / 'new-user')
                env['CODEX_HOME'] = str(root / 'new-user/.codex')
            code = '''from pathlib import Path
from backend.application_paths import PROJECT_ROOT, WORKSPACE_ROOT, STATE_ROOT, SUPPORT_ROOT
from backend.omni_gpt_profiles import discover_profiles, build_context
from backend.orchestrator_policy_adapter import _load_orchestrator
from backend.orchestrator_mandate_adapter import _repo_root
from backend.live_aid.qml_preflight_runner import QML_GATE
assert WORKSPACE_ROOT == PROJECT_ROOT
assert STATE_ROOT.is_relative_to(Path.home().parent)
assert len(discover_profiles()) == 7
assert all(p.path.is_relative_to(PROJECT_ROOT) for p in discover_profiles())
assert "[PROFILE idekompassen" in build_context("Jag har en idé")
assert callable(_load_orchestrator().validate_task)
assert _repo_root() == SUPPORT_ROOT
assert (SUPPORT_ROOT / "cognitive-core/gg_mandate_approval.py").is_file()
assert QML_GATE.is_file() and QML_GATE.is_relative_to(SUPPORT_ROOT)
import main
from backend.game_engine_host import _RUNTIME
_RUNTIME._world_population.tick(0)
_RUNTIME.snapshot()
print("RELOCATED_APP_IMPORT=PASS")
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
from startup import FirstFrameBootstrap, run_event_loop
app = QApplication(['GG exported application test'])
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile(str(PROJECT_ROOT / 'qml/Main.qml')))
assert engine.rootObjects(), 'RELOCATED_QML_ROOT_MISSING'
window = engine.rootObjects()[0]
bootstrap = FirstFrameBootstrap(window, app, engine)
def check_startup():
    if window.property('startupFailed'):
        print(window.property('shellLoadLog'))
        app.exit(2)
    elif window.property('startupReady') and not window.property('shellLoading'):
        print('RELOCATED_QML_STARTUP=PASS')
        app.exit(0)
timer = QTimer()
timer.setInterval(250)
timer.timeout.connect(check_startup)
timer.start()
QTimer.singleShot(30000, lambda: app.exit(3))
bootstrap.start()
assert run_event_loop(app, engine) == 0, 'RELOCATED_QML_STARTUP_FAILED'
'''
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=exported, env=env, text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr[-1800:])
            self.assertIn("RELOCATED_APP_IMPORT=PASS", result.stdout)
            self.assertIn('RELOCATED_QML_STARTUP=PASS', result.stdout)
            result = subprocess.run([sys.executable, "-B", "gg-setup", "--prepare"], cwd=exported, env=env, text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr[-1000:])
            report = json.loads(result.stdout)
            self.assertEqual(report["gpt_packages"], 7)
            self.assertEqual(set(report["gg_skills"]), {
                "gg-blender-reference-workflow", "gg-knowledge-atlas",
                "gg-live-eyes", "selfdev-t", "visible-web",
            })
            self.assertTrue((root / "state/goldgoblins/gg-ai-desktop/codex-gpt-tui/skills/gg-live-eyes/SKILL.md").is_file())
            self.assertFalse((root / "new-user/.codex/auth.json").exists())


if __name__ == "__main__":
    unittest.main()
