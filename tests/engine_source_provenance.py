"""Check retained upstream evidence and the exact adapted local source."""
from pathlib import Path
import hashlib
import json
from backend.application_paths import DATA_ROOT

UPSTREAM = DATA_ROOT/'game-engine/engine-reference-upstream'


def assert_source_integrity(test, root):
    receipt = json.loads((root/'upstream-provenance.json').read_text())
    adaptations = json.loads((root/'local-adaptations.json').read_text())['files']
    paths = receipt['source_paths']
    test.assertEqual(set(paths), set(receipt['source_files']))
    changed = set()
    for original, expected in receipt['source_files'].items():
        actual = hashlib.sha256((root/paths[original]).read_bytes()).hexdigest()
        if actual == expected:
            test.assertNotIn(original, adaptations)
            continue
        changed.add(original)
        change = adaptations[original]
        test.assertEqual(change['path'], paths[original])
        test.assertEqual(change['original_sha256'], expected, original)
        test.assertEqual(change['adapted_sha256'], actual, original)
        test.assertEqual(hashlib.sha256((UPSTREAM/original).read_bytes()).hexdigest(), expected, original)
    test.assertEqual(changed, set(adaptations))
    return receipt, adaptations
