"""Actual terminated children cannot strand task-owned world/audio fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.world.world_verifier_scratch import scratch_roots


class WorldVerifierScratch(unittest.TestCase):
    def test_faulthandler_exit_removes_owned_state_audio_and_keeps_unrelated_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            unrelated = base / 'unrelated-existing-file'
            unrelated.write_text('keep')
            with scratch_roots(audio_base=base) as (state, audio):
                child = subprocess.run([sys.executable, '-B', '-c', '''import faulthandler,sys,time
from pathlib import Path
for root in sys.argv[1:]: (Path(root)/'owned-fixture').write_text('fixture')
faulthandler.dump_traceback_later(.05,exit=True)
time.sleep(5)
''', str(state), str(audio)], capture_output=True, timeout=3)
                self.assertEqual(child.returncode, 1)
                self.assertIn(b'Timeout', child.stderr)
                self.assertTrue((state / 'owned-fixture').is_file())
                self.assertTrue((audio / 'owned-fixture').is_file())
            self.assertFalse(state.exists())
            self.assertFalse(audio.exists())
            self.assertEqual(unrelated.read_text(), 'keep')

    def test_parent_timeout_removes_owned_roots_while_propagating_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.TimeoutExpired):
                with scratch_roots(audio_base=Path(directory)) as (state, audio):
                    subprocess.run([sys.executable, '-B', '-c', '''import sys,time
from pathlib import Path
for root in sys.argv[1:]: (Path(root)/'owned-fixture').write_text('fixture')
time.sleep(5)
''', str(state), str(audio)], capture_output=True, timeout=.2)
            self.assertFalse(state.exists())
            self.assertFalse(audio.exists())


if __name__ == '__main__':
    unittest.main()
