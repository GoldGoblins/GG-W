"""Bounded per-character addon choices; the original Lua core owns the verbs."""
from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from backend.game_engine_legacy import schema_matches

SCHEMA = 'gg.engine.addons.v1'


def _local_profile_ids(characters, active_id):
    # A directory scan would also include retired/orphan UI profiles. The
    # character service's locked, validated roster is the local realm evidence.
    from backend.game_engine_local_characters import LocalCharacters
    if (not isinstance(characters, LocalCharacters)
            or not characters._registry_valid or characters._closed
            or characters.phase not in ('CHARACTERS', 'WORLD')):
        raise ValueError('Invalid local addon character session')
    lock = characters._session_lock
    try:
        if lock is None or lock.closed:
            raise ValueError('Local addon character session is not locked')
        held = os.fstat(lock.fileno())
        path = characters.root/'.session.lock'
        actual = path.lstat()
        if (not stat.S_ISREG(held.st_mode) or not stat.S_ISREG(actual.st_mode)
                or (held.st_dev, held.st_ino) != (actual.st_dev, actual.st_ino)):
            raise ValueError('Invalid local addon character lock')
    except (AttributeError, OSError, TypeError) as exc:
        raise ValueError('Invalid local addon character lock') from exc
    rows = characters.rows
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10:
        raise ValueError('Invalid local addon character roster')
    ids = []
    for row in rows:
        identity = row.get('id') if isinstance(row, dict) else None
        try:
            valid = isinstance(identity, str) and uuid.UUID(identity).hex == identity
        except (ValueError, AttributeError):
            valid = False
        if not valid or identity in ids:
            raise ValueError('Invalid local addon character roster')
        # Reuse the store's profile boundary rather than interpreting a name as
        # a path. This also rejects a roster pointing through an escaping link.
        saved = characters.store.path(identity)
        if saved.is_symlink() or not saved.is_file():
            raise ValueError('Local addon character save is absent')
        ids.append(identity)
    if active_id not in ids:
        raise ValueError('Local addon character is absent from the roster')
    return ids


def bind_local_roster(ui, account_root, active_id, characters):
    """Bind a UI boot to one actual locked local realm; never enumerate disk."""
    ui._addon_roster_context = None
    _local_profile_ids(characters, active_id)
    account = Path(account_root).resolve()
    ui._addon_roster_context = (account, active_id, characters)


def _profile_root(account, identity):
    root = account/'characters'/identity
    if ((account/'characters').is_symlink() or root.is_symlink()
            or not root.resolve().is_relative_to(account)):
        raise ValueError('Invalid local addon profile scope')
    return root


def enable_rows(value):
    if not isinstance(value, dict) or not schema_matches(value.get('schema'), SCHEMA):
        raise ValueError('Invalid saved addon schema')
    rows = value.get('rows')
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError('Invalid saved addon rows')
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('Invalid saved addon entry')
        name, enabled = row
        if (not isinstance(name, str) or not name or len(name) > 256
                or name in ('.', '..') or any(c in name for c in '/\\\r\n\0')
                or type(enabled) is not bool):
            raise ValueError('Invalid saved addon choice')
    return rows


def _load_rows(ui, root):
    path = root/'addons.json'
    value = ui._saved_json(path, root)
    if value is None:
        return []
    try:
        rows = enable_rows(value)
    except ValueError as exc:
        ui.held_saves.add(path)
        ui.errors = (ui.errors + [str(exc)])[-32:]
        return []
    return rows


def load_enabled(ui, addons):
    root = ui.character_saved_root
    context = getattr(ui, '_addon_roster_context', None)
    if root is None:
        if context is not None:
            raise ValueError('Local addon profile scope changed')
        return []
    inherited = {}
    if context is not None:
        account, active_id, characters = context
        if (ui.saved_root != account
                or root != _profile_root(account, active_id)):
            raise ValueError('Local addon profile scope changed')
        ids = _local_profile_ids(characters, active_id)
        choices = {}
        rows = []
        for identity in ids:
            own = _load_rows(ui, _profile_root(account, identity))
            if identity == active_id:
                rows = own
            # A duplicate line has its last value, exactly as EnableHash does.
            explicit = {_fold(name): enabled for name, enabled in own}
            for name, enabled in explicit.items():
                choices.setdefault(name, set()).add(enabled)
        # Original 0x51e470 counts explicit rows only. Missing/contested rows
        # take the TOC DefaultState; inheritance itself creates no explicit row.
        inherited = {name: next(iter(values)) for name, values in choices.items()
                     if len(values) == 1}
    else:
        rows = _load_rows(ui, root)
    fold = _fold if context is not None else str.casefold
    explicit = {fold(name): enabled for name, enabled in rows}
    for info, _ in addons.values():
        name = fold(info['name'])
        info['enabled'] = explicit.get(name, inherited.get(name, info.get('enabled', True)))
    return rows


def _fold(name):
    # Match the retained native EnableHash's ASCII case-insensitive keys.
    return name.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                      'abcdefghijklmnopqrstuvwxyz'))


def save_enabled(ui, rows):
    if rows is not None:
        # The native writer clears its dirty flag when drained. Retain these
        # rows in Python until the atomic disk write succeeds, including retry.
        ui._pending_addon_rows = enable_rows({'schema': SCHEMA, 'rows': rows})
    if ui._pending_addon_rows is None or ui.character_saved_root is None:
        return
    path = ui.character_saved_root/'addons.json'
    if path in ui.held_saves:
        raise ValueError('Saved addon choices need repair before changes can be saved')
    ui._write_saved(path, json.dumps({'schema': SCHEMA, 'rows': ui._pending_addon_rows},
                                    ensure_ascii=False))
    ui._pending_addon_rows = None
