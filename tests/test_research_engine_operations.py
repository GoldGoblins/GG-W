"""Real pinned-provider checks for native overview, search and cross-references."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import research_learning, research_jobs


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='gg-research-operations-') as raw:
        root = Path(raw)
        marker = root / 'executed'
        binary = research_learning.build_native_fixture(root, marker)
        original = binary.read_bytes()
        expected_format = 'pe' if os.name == 'nt' else 'elf'

        def complete(state):
            details = {key: state.get(key) for key in ('status', 'phase', 'reason', 'engine_error', 'diagnostic')}
            assert state['status'] == 'COMPLETE', json.dumps(details, ensure_ascii=False)
            assert not marker.exists(), 'Selected target was executed'
            assert binary.read_bytes() == original, 'Selected target was modified'
            assert not (research_jobs._dir(state['job_id']) / 'scratch').exists()
            results.append({'operation': state['operation'], 'status': 'PASS',
                            'target_not_executed': True, 'scratch_removed': True})
            return state['report']['content']

        def address_value(value):
            # Ghidra may include the address space for either native format.
            return int(str(value).rsplit(':', 1)[-1], 16)

        with patch.object(research_jobs, 'ROOT', root / 'jobs'):
            function = research_learning._wait(research_jobs.start(str(binary), 'function', 'gg_stack_next'))
            function_result = complete(function)['normalized_result']
            assert function_result['procedure']['name'] == 'gg_stack_next'
            address = function_result['procedure']['address']
            caller = next(item for item in function_result['callers'] if item['name'] == 'main')
            main_ranges = caller['body']['ranges']
            assert main_ranges, 'Known caller has no recorded function body'
            for operation, query in [('analyze', ''), ('search', 'gg_stack_next'), ('xrefs', address)]:
                state = research_learning._wait(research_jobs.start(str(binary), operation, query))
                content = complete(state)
                result = content.get('normalized_result')
                assert result, content
                if operation == 'analyze':
                    assert result.get('procedure_count', 0) > 0
                    assert any(segment.get('name') == '.text' for segment in result.get('segments', []))
                    assert content['subject']['format'] == expected_format
                elif operation == 'search':
                    assert 'gg_stack_next' in json.dumps(result), result
                else:
                    assert isinstance(result, list) and result
                    assert any(address_value(span['start']) <= address_value(reference) <= address_value(span['end'])
                               for reference in result for span in main_ranges), result
    print(json.dumps({'status': 'PASS', 'results': results}, indent=2))


if __name__ == '__main__':
    main()
