"""Read pre-rename engine data without rewriting a user's saved content."""


def schema_matches(value, current):
    if isinstance(value, str) and value.startswith('gg.benilla'):
        value = 'gg.engine' + value[len('gg.benilla'):]
    return value == current


def manifest_path(value):
    old = 'game/worlds/benilla-demo'
    if isinstance(value, str) and (value == old or value.startswith(old+'/')):
        return 'game/worlds/engine-demo' + value[len(old):]
    return value
