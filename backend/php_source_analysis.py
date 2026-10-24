"""Bounded lexical PHP review. Never loads PHP, includes files or runs targets.

Locations describe syntax, not reachable execution or proven vulnerabilities.
Dynamic dispatch, aliases, traits and conditional declarations stay unresolved.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PROJECT_BYTES = 8 * 1024 * 1024
MAX_FILES = 256
MAX_TOKENS = 100_000
MAX_DEPTH = 256
MAX_ROWS = 128
LIMITATIONS = [
    'Lexical PHP source inventory; not a complete PHP AST, runtime trace or vulnerability detector.',
    'Call references are syntactic. Dynamic dispatch, aliases, includes, traits and framework routing are not resolved.',
    'Review points identify input, persistent state and error/lifetime APIs; they do not prove a data-flow or defect.',
    'PHP strings/comments and non-PHP markup are omitted; collections are bounded to 128 entries.',
]
_WORDS = re.compile(r'[A-Za-z_\x80-\uffff][\w\\\x80-\uffff]*')
_OPENING = re.compile(r'<\?(?:php\b|=)', re.IGNORECASE)
_CONTROL = {'if', 'elseif', 'while', 'for', 'foreach', 'switch', 'catch', 'isset', 'empty',
            'array', 'list', 'match', 'function', 'fn', 'echo', 'print', 'unset', 'declare',
            'include', 'include_once', 'require', 'require_once'}
_REVIEW_APIS = {'unserialize', 'session_start', 'session_decode', 'register_shutdown_function',
                'trigger_error', 'set_error_handler', 'set_exception_handler', 'ini_set',
                'exit', 'die', 'gc_collect_cycles'}
_INPUTS = {'$_GET', '$_POST', '$_FILES', '$_REQUEST', '$_COOKIE', '$_SERVER', '$_SESSION'}


@dataclass(slots=True)
class Token:
    value: str
    line: int


def tokenize(text: str, check=lambda: None) -> list[Token]:
    result = []
    index = 0
    line = 1
    php = False
    depth = 0
    while index < len(text):
        if index % 1024 == 0:
            check()
        if not php:
            opening = _OPENING.search(text, index)
            if opening is None:
                break
            end = opening.end()
            line += text[index:end].count('\n')
            index = end
            php = True
            continue
        if text.startswith('?>', index):
            php = False
            index += 2
            continue
        start = index
        char = text[index]
        if char.isspace():
            line += char == '\n'
            index += 1
            continue
        if text.startswith('//', index) or (char == '#' and not text.startswith('#[', index)):
            ends = [end for end in (text.find('\n', index), text.find('?>', index)) if end >= 0]
            if not ends:
                break
            index = min(ends)
            continue
        if text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('PHP_UNTERMINATED_COMMENT')
            index = end + 2
            line += text[start:index].count('\n')
            continue
        if char in "'\"`":
            quote = char
            index += 1
            while index < len(text):
                if index % 1024 == 0:
                    check()
                if text[index] == '\\':
                    index += 2
                elif text[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            else:
                raise ValueError('PHP_UNTERMINATED_STRING')
            line += text[start:index].count('\n')
            result.append(Token('<string>', line))
            if len(result) > MAX_TOKENS:
                raise ValueError('PHP_TOKEN_LIMIT')
            continue
        if text.startswith('<<<', index):
            head = re.match(r'<<<[ \t]*[\'\"]?([A-Za-z_]\w*)[\'\"]?[ \t]*\r?\n', text[index:])
            if not head:
                raise ValueError('PHP_UNSUPPORTED_HEREDOC')
            tail = re.search(r'(?m)^[ \t]*' + re.escape(head[1]) + r'(?=[;,\s\)\]]|$)', text[index + head.end():])
            if tail is None:
                raise ValueError('PHP_UNTERMINATED_HEREDOC')
            index += head.end() + tail.end()
            line += text[start:index].count('\n')
            result.append(Token('<string>', line))
            if len(result) > MAX_TOKENS:
                raise ValueError('PHP_TOKEN_LIMIT')
            continue
        prefix = '$' if char == '$' else ''
        word = _WORDS.match(text, index + len(prefix))
        if word:
            value = prefix + word[0]
            index = word.end()
        else:
            value = next((part for part in ('?->', '->', '::', '=>') if text.startswith(part, index)), char)
            index += len(value)
        if value in {'{', '(', '['}:
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError('PHP_NESTING_LIMIT')
        elif value in {'}', ')', ']'}:
            depth = max(0, depth - 1)
        result.append(Token(value, line))
        if len(result) > MAX_TOKENS:
            raise ValueError('PHP_TOKEN_LIMIT')
    check()
    return result


def _inventory(tokens: list[Token], relative: str, check, operation='analyze', query='') -> dict:
    functions = []
    calls = []
    review = []
    declarations = set()
    queried = operation in {'function', 'search', 'xrefs'}
    wanted = query.casefold().lstrip('\\')
    query_keys = {'functions'} if operation == 'function' else {'calls'} if operation == 'xrefs' else {'functions', 'calls', 'review_points'}
    def add(rows, key, row):
        if queried and (key not in query_keys or not
                (wanted in row['name'].casefold() if operation == 'search' else row['name'].casefold().lstrip('\\') == wanted)):
            return
        if len(rows) < MAX_ROWS:
            rows.append(row)
    for i, token in enumerate(tokens):
        if i % 1024 == 0:
            check()
        word = token.value
        lower = word.casefold().lstrip('\\')
        previous = tokens[i - 1].value if i else ''
        after = tokens[i + 1].value if i + 1 < len(tokens) else ''
        if lower == 'function':
            j = i + 1
            if j < len(tokens) and tokens[j].value == '&':
                j += 1
            if j < len(tokens) and _WORDS.fullmatch(tokens[j].value):
                declarations.add(j)
                add(functions, 'functions', {'name': tokens[j].value, 'path': relative, 'line': token.line,
                                           'kind': 'LEXICAL_FUNCTION_DECLARATION'})
        if word in _INPUTS or word == '$GLOBALS' or (lower == 'static' and after.startswith('$')) or lower == 'global':
            add(review, 'review_points', {'name': word, 'path': relative, 'line': token.line,
                                         'kind': 'INPUT_OR_SHARED_STATE_SYNTAX'})
        if after == '(' and i not in declarations and lower not in _CONTROL and (_WORDS.fullmatch(word) or word.startswith('$')):
            call = {'name': word, 'path': relative, 'line': token.line,
                    'resolution': 'DYNAMIC_OR_MEMBER' if previous in {'->', '?->', '::'} or word.startswith('$') else 'UNRESOLVED_LEXICAL_REFERENCE'}
            add(calls, 'calls', call)
            if lower in _REVIEW_APIS:
                add(review, 'review_points', {**call, 'kind': 'LIFETIME_OR_ERROR_API_SYNTAX'})
    return {'functions': functions, 'calls': calls, 'review_points': review}


def analyze(target: Path, operation: str = 'analyze', query: str = '', *, cancelled=None) -> dict:
    began = time.monotonic()
    def check():
        if cancelled and cancelled():
            raise ValueError('CANCELLED')
        if time.monotonic() - began > 15:
            raise ValueError('PHP_TIME_LIMIT')
    files = sorted(target.rglob('*.php')) if target.is_dir() else [target]
    if not files or len(files) > MAX_FILES:
        raise ValueError('PHP_PROJECT_FILE_LIMIT')
    total = 0
    output = {'files': [], 'functions': [], 'calls': [], 'review_points': []}
    root = target if target.is_dir() else target.parent
    for path in files:
        check()
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('PHP_REGULAR_SNAPSHOT_REQUIRED')
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('PHP_FILE_LIMIT')
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_PROJECT_BYTES:
            raise ValueError('PHP_PROJECT_SIZE_LIMIT')
        relative = path.relative_to(root).as_posix()
        inventory = _inventory(tokenize(data.decode('utf-8-sig'), check), relative, check, operation, query)
        output['files'].append({'path': relative, 'bytes': len(data)})
        for key, rows in inventory.items():
            output[key].extend(rows[:MAX_ROWS - len(output[key])])
    if operation == 'decompile':
        raise ValueError('PHP_SOURCE_IS_NOT_DECOMPILED')
    if operation in {'function', 'search', 'xrefs'}:
        wanted = query.casefold().lstrip('\\')
        keys = ('functions',) if operation == 'function' else ('calls',) if operation == 'xrefs' else ('functions', 'calls', 'review_points')
        matches = [row for key in keys for row in output[key] if (row['name'].casefold().lstrip('\\') == wanted if operation != 'search' else wanted in row['name'].casefold())]
        output['matches'] = matches[:MAX_ROWS]
        if operation == 'function' and not matches:
            raise ValueError('PHP_FUNCTION_NOT_FOUND')
    return {'schema': 'gg.php-source-review.v1', 'operation': operation, 'executed': False,
            'coverage': 'BOUNDED_LEXICAL_INVENTORY', 'limitations': LIMITATIONS, **output}
