from types import MethodType,SimpleNamespace
import unittest
from unittest.mock import Mock
from backend.chat_surface_host import ChatSurfaceHost


class TeardownTests(unittest.TestCase):
    def test_queued_show_never_allocates_after_window_deletion_or_shutdown(self):
        for stopping in (False,True):
            root=Mock();root.property.side_effect=RuntimeError('Internal C++ object already deleted')
            host=SimpleNamespace(_qml_root=root,_startup_chat_started=False,_shutdown_in_progress=stopping)
            host._defer_initial_tui=MethodType(ChatSurfaceHost._defer_initial_tui,host)
            # No hole/grid exists: a late access or allocation would fail here.
            ChatSurfaceHost._show_gpt_tui(host)
            if stopping:root.property.assert_not_called()

    def test_existing_ready_window_keeps_normal_startup_behavior(self):
        root=Mock();root.property.return_value=False
        host=SimpleNamespace(_qml_root=root,_startup_chat_started=False)
        self.assertFalse(ChatSurfaceHost._defer_initial_tui(host))
        root.property.return_value=True
        self.assertTrue(ChatSurfaceHost._defer_initial_tui(host))


if __name__=='__main__':unittest.main()
