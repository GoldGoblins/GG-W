"""Validate Windows scope rejection without creating an AppContainer or ACLs."""
from pathlib import Path, PureWindowsPath
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import windows_research_sandbox as sandbox


class _WindowsScopePath(PureWindowsPath):
    """Model existing local directories without accessing another drive."""

    @classmethod
    def home(cls):
        return cls('C:/Users/scope-test')

    def resolve(self, strict=False):
        return self

    def is_symlink(self):
        return False

    def is_junction(self):
        return False

    def is_dir(self):
        return True


class WindowsResearchSandboxScopeTests(unittest.TestCase):
    def reject_scope(self, *, tools, scratch):
        with (
            patch.object(sandbox, 'Path', _WindowsScopePath),
            patch.object(sandbox.os, 'name', 'nt'),
            patch.object(sandbox, 'available', return_value=True),
            patch.object(sandbox, '_run_native') as native,
        ):
            with self.assertRaisesRegex(ValueError, '^SANDBOX_SCOPE_INVALID$'):
                sandbox.run([str(tools / 'runtime/node.exe'), '-e', 'process.exit(0)'],
                            scratch=scratch, tools=tools, timeout=1, max_output_bytes=1024)
            native.assert_not_called()

    def test_tools_cannot_be_another_drive_root(self):
        self.reject_scope(tools=PureWindowsPath('R:/'),
                          scratch=PureWindowsPath('C:/research-job/scratch'))

    def test_scratch_cannot_be_another_drive_root(self):
        self.reject_scope(tools=PureWindowsPath('C:/research-tools'),
                          scratch=PureWindowsPath('R:/'))


if __name__ == '__main__':
    unittest.main()
