"""Read supported literal WordPress settings without executing PHP config.

Comments and quoted text cannot create settings. Dynamic or conditional database
bindings fail closed; callers report an unsupported configuration, not success.
"""
from dataclasses import dataclass
import re

_IDENTIFIER = re.compile(r'\$?[A-Za-z_][A-Za-z0-9_]*')
_DATABASE = {'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST'}


@dataclass(frozen=True)
class Literal:
    value: str
    start: int
    end: int


def _tokens(text):
    if len(text) > 262144:
        raise ValueError('SITE_DATABASE_CONFIG_INVALID')
    opening = re.match(r'\ufeff?\s*<\?php\b', text, re.IGNORECASE)
    if not opening:
        raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
    i = opening.end()
    count = 0
    while i < len(text):
        if text.startswith('?>', i):
            if text[i + 2:].strip():
                raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
            break
        if text[i].isspace():
            i += 1
            continue
        if text.startswith('//', i) or text[i] == '#':
            ends = [n for n in (text.find('\n', i), text.find('?>', i)) if n >= 0]
            if not ends:
                break
            i = min(ends)
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('SITE_DATABASE_CONFIG_INVALID')
            i = end + 2
            continue
        count += 1
        if count > 32768:
            raise ValueError('SITE_DATABASE_CONFIG_INVALID')
        start = i
        char = text[i]
        if char in "'\"":
            value = []
            i += 1
            while i < len(text) and text[i] != char:
                if text[i] == '$' and char == '"':
                    raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
                if text[i] == '\\' and i + 1 < len(text):
                    following = text[i + 1]
                    if following in ('\\', char) or (char == '"' and following == '$'):
                        value.append(following)
                        i += 2
                        continue
                    if char == '"':
                        translations = {'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', 'f': '\f', 'e': '\x1b'}
                        if following in translations:
                            value.append(translations[following])
                            i += 2
                            continue
                        if following in '01234567xXuU':
                            raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
                value.append(text[i])
                i += 1
            if i == len(text):
                raise ValueError('SITE_DATABASE_CONFIG_INVALID')
            i += 1
            yield ('string', ''.join(value), start, i)
            continue
        match = _IDENTIFIER.match(text, i)
        if match:
            i = match.end()
            yield ('word', match[0], start, i)
        else:
            i += 1
            yield ('symbol', char, start, i)


def settings(text: str) -> dict[str, Literal]:
    tokens = list(_tokens(text))
    found = {}
    def invalid():
        raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
    def values(at, end):
        return [token[1] for token in tokens[at:end]]
    def definition(at):
        # Closed grammar: no variable calls, client code, extra arguments or
        # nested calls can execute before the literal bindings we rely on.
        if (at + 6 >= len(tokens) or tokens[at][0] != 'word' or tokens[at][1].casefold() != 'define'
                or values(at + 1, at + 2) != ['('] or tokens[at + 2][0] != 'string' or tokens[at + 3][1] != ','):
            invalid()
        end = at + 4
        while end < len(tokens) and tokens[end][:2] != ('symbol', ';'):
            end += 1
        if end >= len(tokens) or tokens[end - 1][:2] != ('symbol', ')'):
            invalid()
        expression = tokens[at + 4:end - 1]
        if not expression or any(not (kind == 'string' or (kind == 'word' and value.casefold() in {'true', 'false', 'null', '__dir__', '__file__', 'directory_separator'}) or (kind == 'symbol' and value in '.+-0123456789')) for kind, value, _, _ in expression):
            invalid()
        name = tokens[at + 2][1]
        if name in _DATABASE:
            if name in found or len(expression) != 1 or expression[0][0] != 'string':
                invalid()
            literal = expression[0]
            found[name] = Literal(literal[1], literal[2], literal[3])
        return end + 1, name
    i = 0
    while i < len(tokens):
        kind, value, _, _ = tokens[i]
        if kind == 'word' and value.casefold() == 'define':
            i, _ = definition(i)
        elif kind == 'word' and value == '$table_prefix':
            if ('table_prefix' in found or i + 3 >= len(tokens) or tokens[i + 1][1] != '='
                    or tokens[i + 2][0] != 'string' or tokens[i + 3][1] != ';'):
                invalid()
            literal = tokens[i + 2]
            found['table_prefix'] = Literal(literal[1], literal[2], literal[3])
            i += 4
        elif value == ';' and kind == 'symbol':
            i += 1
        elif (_DATABASE | {'table_prefix'}).issubset(found) and values(i, i + 9) == ['if', '(', '!', 'defined', '(', 'ABSPATH', ')', ')', '{']:
            i, name = definition(i + 9)
            if name != 'ABSPATH' or i >= len(tokens) or tokens[i][1] != '}':
                invalid()
            i += 1
        elif ((_DATABASE | {'table_prefix'}).issubset(found) and kind == 'word'
                and value.casefold() in {'require', 'require_once'}
                and values(i + 1, i + 5) == ['ABSPATH', '.', 'wp-settings.php', ';']):
            i += 5
            if i != len(tokens):
                invalid()
        else:
            invalid()
    return found


def replace_host(text: str, host: str) -> str:
    before = settings(text)
    if 'DB_HOST' not in before or not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', host):
        raise ValueError('SITE_DATABASE_LITERAL_CONFIG_REQUIRED')
    binding = before['DB_HOST']
    changed = text[:binding.start] + "'" + host + "'" + text[binding.end:]
    after = settings(changed)
    if after['DB_HOST'].value != host or any(after[key].value != value.value for key, value in before.items() if key != 'DB_HOST'):
        raise ValueError('SITE_DATABASE_CONFIG_POSTCONDITION_FAILED')
    return changed
