"""Real pinned-provider checks for native overview, search and cross-references."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import research_learning, research_jobs


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='gg-research-operations-') as raw:
        root = Path(raw)
        source = root / 'fixture.c'
        binary = root / 'fixture'
        marker = root / 'executed'
        source.write_text('#include <stdio.h>\n__attribute__((noinline)) int gg_stack_next(int value) { return value+7; }\n' +
            'int main(void) { FILE *f=fopen(' + json.dumps(str(marker)) + ',"w"); if(f) fclose(f); return gg_stack_next(0); }\n')
        subprocess.run(['gcc', '-O0', '-g', '-o', str(binary), str(source)], check=True, capture_output=True, timeout=20)
        function = research_learning._wait(research_jobs.start(str(binary), 'function', 'gg_stack_next'))
        assert function['status'] == 'COMPLETE', function
        address = function['report']['content']['normalized_result']['procedure']['address']
        main = next(caller for caller in function['report']['content']['normalized_result']['callers'] if caller['name'] == 'main')
        main_ranges = main['body']['ranges']
        for operation, query in [('analyze', ''), ('search', 'gg_stack_next'), ('xrefs', address)]:
            state = research_learning._wait(research_jobs.start(str(binary), operation, query))
            assert state['status'] == 'COMPLETE', state
            result = state['report']['content'].get('normalized_result')
            assert result, state['report']['content']
            if operation == 'analyze':
                assert result.get('procedure_count', 0) > 0
                assert any(segment.get('name') == '.text' for segment in result.get('segments', []))
                assert state['report']['content']['subject']['format'] == 'elf'
            elif operation == 'search':
                assert 'gg_stack_next' in json.dumps(result), result
            else:
                assert isinstance(result, list) and result
                assert any(int(span['start'], 16) <= int(reference, 16) <= int(span['end'], 16)
                           for reference in result for span in main_ranges), result
            assert not marker.exists(), 'Selected target was executed'
            assert not (research_jobs._dir(state['job_id']) / 'scratch').exists()
            results.append({'operation': operation, 'status': 'PASS', 'target_not_executed': True, 'scratch_removed': True})
    print(json.dumps({'status': 'PASS', 'results': results}, indent=2))


if __name__ == '__main__':
    main()
