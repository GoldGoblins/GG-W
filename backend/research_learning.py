"""Known-answer engine exercises and narrowly scoped, tested method memory.

Passing a transport/schema check never validates an arbitrary user conclusion.
Only the specific workflow exercised by a known-answer fixture is promoted.
"""
from pathlib import Path
import json
import subprocess
import tempfile
import time

from backend import research_desk, research_jobs


def _wait(state):
    deadline = time.monotonic() + research_jobs.TIMEOUT + 25
    while state.get('status') in research_jobs.BUSY and time.monotonic() < deadline:
        time.sleep(0.2)
        state = research_jobs.status(state['job_id'])
    return state


def verify_method(method_id: str) -> dict:
    # An arbitrary lesson requires an independent test designed for its claim.
    # This endpoint does not promote on command or on a successful import.
    with research_desk._LOCK, research_desk._db() as db:
        row = db.execute('SELECT status,proof FROM methods WHERE id=?', (method_id,)).fetchone()
    if row is None:
        return {'status': 'METHOD_NOT_FOUND'}
    try:
        proof = json.loads(row['proof']) if str(row['proof']).startswith('{') else {}
    except ValueError:
        proof = {}
    if not isinstance(proof, dict):
        proof = {}
    tested = row['status'] == 'VERIFIED' and proof.get('test_schema') == 'gg.research-known-answer.v1'
    return {'status': 'TESTED_WORKFLOW' if tested else 'INDEPENDENT_TEST_REQUIRED',
            'detail': 'Verification applies to the recorded fixture and workflow.' if tested else
                      'Define an independent test for this conclusion; a successful analysis alone is insufficient.'}


def _record(name: str, trigger: str, steps: list[str], state: dict, checks: dict) -> dict:
    report = state['report']
    proof = {'test_schema': 'gg.research-known-answer.v1', 'checks': checks,
             'operation': report['operation'], 'engine': report['engine'],
             'tested_at': research_desk._now(), 'scope': 'Known-answer fixture workflow only; not arbitrary target behavior.'}
    source = research_desk.ingest_source({'title': name + ' known-answer test', 'kind': 'LOCAL_ENGINE_TEST',
        'origin': 'gg-research:self-test', 'content': json.dumps({'proof': proof, 'report': report}, ensure_ascii=False), 'remember': False})
    evidence = research_desk.add_evidence({'title': name, 'claim': 'The recorded workflow passed the listed known-answer checks.',
        'kind': 'ENGINE_VERIFICATION', 'source_url': 'gg-research:self-test', 'provenance': 'KNOWN_ANSWER_TEST',
        'confidence': 1.0, 'details': {'checks': checks, 'source_id': source['source_id'], 'engine': report['engine'],
                                    'scope': proof['scope']}})
    command = 'python3 projects/gg-ai-desktop/gg-research ' + report['operation'] + ' TARGET'
    if report['operation'] != 'analyze':
        command += ' FUNCTION'
    command += ' --wait'
    method = research_desk.add_method({'name': name, 'trigger': trigger + ' undersök analysera bibliotek binär funktion kod',
        'steps': [steps[0], command, *steps[1:]],
        'proof': json.dumps(proof), 'source_id': source['source_id'], 'status': 'VERIFIED'})
    with research_desk._LOCK, research_desk._db() as db:
        db.execute("UPDATE methods SET status='RETIRED' WHERE name=? AND id<>?", (name, method['method_id']))
    return {'name': name, 'method_id': method['method_id'], 'evidence_id': evidence['evidence_id'],
            'checks': checks, 'status': 'PASS'}


def self_test() -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix='gg-research-known-answer-') as raw:
        root = Path(raw)
        js = root / 'application'
        js.mkdir()
        marker = root / 'target-executed'
        (js / 'package.json').write_text('{"name":"gg-known-answer","version":"1.0.0","type":"module","main":"main.js"}')
        (js / 'math.js').write_text('export function ggStackNext(value) { return value + 7; }\n')
        (js / 'main.js').write_text("import { ggStackNext } from './math.js';\nimport fs from 'node:fs';\n" +
            f"fs.writeFileSync({json.dumps(str(marker))}, 'executed');\n" +
            'export function ggPortfolio(value) { return ggStackNext(value); }\n')
        native_source = root / 'fixture.c'
        native_source.write_text('#include <stdio.h>\n__attribute__((noinline)) int gg_stack_next(int value) { return value + 7; }\n' +
            'int main(void) { FILE *f=fopen(' + json.dumps(str(marker)) + ',"w"); if(f) fclose(f); return gg_stack_next(0); }\n')
        binary = root / 'fixture'
        subprocess.run(['gcc', '-O0', '-g', '-fno-inline', '-o', str(binary), str(native_source)],
                       check=True, timeout=20, capture_output=True)
        cases = [('JavaScript dependency inspection', js, 'analyze', '', ['ggStackNext', 'ggPortfolio', 'math.js'],
                  ['Select an explicit JavaScript project.', 'Run local REA application analysis.',
                   'Inspect source locations, imports and exports.', 'Test behavioral claims independently.']),
                 ('Native function inspection', binary, 'function', 'gg_stack_next', ['gg_stack_next'],
                  ['Select a native executable.', 'Query a known function with REA and Ghidra.',
                   'Use its references and locations to inspect the implementation.', 'Separate observed structure from runtime claims.']),
                 ('Native pseudocode inspection', binary, 'decompile', 'gg_stack_next', ['gg_stack_next'],
                  ['Select a native executable.', 'Decompile the selected function with REA and Ghidra.',
                   'Check the arithmetic against a known-answer fixture.', 'Validate new target behavior independently.'])]
        for name, path, operation, query, expected, steps in cases:
            state = _wait(research_jobs.start(str(path), operation, query))
            if state.get('status') != 'COMPLETE':
                results.append({'name': name, 'status': 'FAIL', 'reason': state.get('reason', state.get('status')),
                                'engine_error': state.get('engine_error', {}), 'diagnostic': state.get('diagnostic', '')})
                continue
            text = json.dumps(state['report']['content'])
            checks = {'known_symbols_present': all(symbol in text for symbol in expected),
                      'target_not_executed': not marker.exists(),
                      'scratch_removed': not (research_jobs._dir(state['job_id']) / 'scratch').exists(),
                      'local_engine_provenance': state['report']['provenance'] == 'LOCAL_ENGINE_STATIC_OBSERVATION'}
            if operation == 'analyze':
                graph = state['report']['content'].get('normalized_result', {}).get('graph', {})
                checks['known_import_resolved'] = any(edge.get('relation') == 'imports' and
                    edge.get('properties', {}).get('resolved_path') == 'math.js' and
                    edge.get('properties', {}).get('imported_name') == 'ggStackNext' for edge in graph.get('edges', []))
                checks['known_export_observed'] = any(edge.get('relation') == 'exposes' and
                    edge.get('properties', {}).get('exported_name') == 'ggPortfolio' for edge in graph.get('edges', []))
            if operation == 'decompile':
                import re
                pseudocode = state['report']['content'].get('normalized_result')
                checks['known_arithmetic_present'] = isinstance(pseudocode, str) and bool(re.search(r'return\s+value\s*\+\s*7\s*;', pseudocode))
            if operation == 'function':
                normalized = state['report']['content'].get('normalized_result') or {}
                checks['known_function_body_present'] = normalized.get('procedure', {}).get('name') == 'gg_stack_next' and bool(normalized.get('procedure', {}).get('body', {}).get('available'))
                checks['known_caller_present'] = any(caller.get('name') == 'main' for caller in normalized.get('callers', []))
            if all(checks.values()):
                results.append(_record(name, 'research reverse engineering REA Ghidra ' + operation, steps, state, checks))
            else:
                results.append({'name': name, 'status': 'FAIL', 'checks': checks})
    result = {'schema': 'gg.research-learning-test.v1', 'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
              'results': results, 'tested_at': research_desk._now(),
              'scope': 'These tests verify the listed workflows on synthetic fixtures.'}
    from backend import research_lab
    research_jobs._write(research_lab.TOOLS_ROOT / 'verification.json', result)
    return result
