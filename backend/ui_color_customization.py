"""Bounded, local presentation colors. Never stores displayed text or keys.

The caller supplies a stable *presentation* key, not a wallet address or chat
message. Partial formats follow UTF-16 positions in the stable UI field,
matching Qt's text cursor API; legacy digest anchors remain readable. Private/chat surfaces must opt
out at the UI boundary; this module additionally refuses known private keys.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
import unicodedata

from PySide6.QtCore import QEvent, QObject, Property, Signal, Slot, Qt
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from shiboken6 import getCppPointer, isValid, wrapInstance

from backend.application_paths import PROJECT_ROOT, STATE_ROOT
from backend.platform_files import atomic_replace, secure_open, NOFOLLOW, sync_directory

SCHEMA = 'gg.ui-colors.v1'
MAX_ENTRIES = 1024
MAX_RANGES = 32
MAX_TEXT_UNITS = 16384
MAX_FILE_BYTES = 512 * 1024
MAX_EPOCH_MS = 253402300799999
MAX_HIT_ITEMS = 8192
MAX_HIT_DEPTH = 64
KEY = re.compile(r'^[A-Za-z][A-Za-z0-9_.:/-]{0,255}$')
PRIVATE_KEY = re.compile(r'(^|[./:_-])(chat(?:body|message)?|password|secret|mnemonic|seed|recovery|private)([./:_-]|$)', re.I)
DIGEST = re.compile(r'^[0-9a-f]{64}$')


def canonical_colors():
    raw = json.loads((PROJECT_ROOT / 'config/gg-palette.json').read_text(encoding='utf-8'))
    return frozenset(str(value).lower() for value in raw['colors'][:64])


def valid_key(value):
    return isinstance(value, str) and KEY.fullmatch(value) is not None and PRIVATE_KEY.search(value) is None


def text_digest(text):
    return hashlib.sha256(b'GG-UI-TEXT-v1\0' + text.encode('utf-8')).hexdigest()


def utf16_boundaries(text):
    """Return valid UTF-16 cursor positions and their Python character offsets."""
    positions = {0: 0}
    cursor = 0
    for index, character in enumerate(text):
        cursor += 2 if ord(character) > 0xffff else 1
        positions[cursor] = index + 1
    return positions


def word_range(text, position):
    """A Unicode word, or one non-space symbol, using Qt UTF-16 positions."""
    if not isinstance(text, str) or type(position) is not int:
        return (-1, -1)
    bounds = utf16_boundaries(text)
    if not text or max(bounds) > MAX_TEXT_UNITS or not 0 <= position <= max(bounds):
        return (-1, -1)
    cursor = max(value for value in bounds if value <= position)
    index = min(bounds[cursor], len(text) - 1)
    if text[index].isspace():
        return (-1, -1)
    def member(char):
        return char.isalnum() or char == '_' or unicodedata.category(char).startswith('M')
    start, end = index, index + 1
    if member(text[index]):
        while start > 0 and member(text[start - 1]):
            start -= 1
        while end < len(text) and member(text[end]):
            end += 1
    reverse = {value: key for key, value in bounds.items()}
    return reverse[start], reverse[end]


def normalize_registry(raw, colors=None):
    colors = canonical_colors() if colors is None else colors
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key, value in list(raw.items())[:MAX_ENTRIES]:
        if not valid_key(key) or not isinstance(value, dict):
            continue
        entry = {}
        if value.get('scale') in {'solid', 'risk', 'progress'}:
            entry['scale'] = value['scale']
        if value.get('scale') == 'deadline':
            start, end = value.get('deadline_start'), value.get('deadline_end')
            if type(start) is int and type(end) is int and 0 <= start < end <= MAX_EPOCH_MS:
                entry.update(scale='deadline', deadline_start=start, deadline_end=end)
        base = value.get('color')
        if isinstance(base, str) and base.lower() in colors:
            entry['color'] = base.lower()
        digest = value.get('text_digest')
        ranges = value.get('ranges')
        slot_anchor = value.get('anchor') == 'slot'
        if (slot_anchor or isinstance(digest, str) and DIGEST.fullmatch(digest)) and isinstance(ranges, list):
            spans = []
            for span in ranges[:MAX_RANGES]:
                if not isinstance(span, dict) or set(span) != {'start', 'end', 'color'}:
                    continue
                start, end, color = span['start'], span['end'], span['color']
                if type(start) is int and type(end) is int and 0 <= start < end <= MAX_TEXT_UNITS and isinstance(color, str) and color.lower() in colors:
                    spans.append({'start': start, 'end': end, 'color': color.lower()})
            if spans:
                entry['ranges'] = spans
                if slot_anchor:
                    entry['anchor'] = 'slot'
                else:
                    entry['text_digest'] = digest
        if entry:
            clean[key] = entry
    return clean


class ColorRegistry:
    """Presentation-only store; all mutations persist atomically before publish."""
    def __init__(self, path=None, *, colors=None):
        self.path = Path(path) if path is not None else Path(STATE_ROOT) / 'ui-colors-v1.json'
        self.colors = canonical_colors() if colors is None else frozenset(colors)
        self.entries = {}
        try:
            fd = secure_open(self.path, os.O_RDONLY | NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                blob = stream.read(MAX_FILE_BYTES + 1)
            if len(blob) <= MAX_FILE_BYTES:
                raw = json.loads(blob)
                if isinstance(raw, dict) and raw.get('schema') == SCHEMA:
                    self.entries = normalize_registry(raw.get('entries'), self.colors)
        except (OSError, ValueError, TypeError, UnicodeError):
            pass

    def _commit(self, entries):
        blob = (json.dumps({'schema': SCHEMA, 'entries': entries}, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
        if len(entries) > MAX_ENTRIES or len(blob) > MAX_FILE_BYTES:
            raise ValueError('UI_COLOR_STORAGE_LIMIT')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.tmp-' + secrets.token_hex(8))
        fd = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace(temporary, self.path)
            sync_directory(self.path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()
        self.entries = entries

    def _validate(self, key, color):
        if not valid_key(key):
            raise ValueError('UI_COLOR_PRESENTATION_KEY_REQUIRED')
        if not isinstance(color, str) or color.lower() not in self.colors:
            raise ValueError('UI_COLOR_CANONICAL_SWATCH_REQUIRED')
        return color.lower()

    def set_color(self, key, color):
        color = self._validate(key, color)
        entries = deepcopy(self.entries)
        entries.setdefault(key, {}).update(color=color, scale='solid')
        self._commit(entries)

    def set_scale(self, key, mode):
        if not valid_key(key) or mode not in {'solid', 'risk', 'progress'}:
            raise ValueError('UI_COLOR_SCALE_REQUIRED')
        entries = deepcopy(self.entries)
        entries.setdefault(key, {})['scale'] = mode
        self._commit(entries)

    def set_deadline(self, key, start, end):
        if not valid_key(key) or type(start) is not int or type(end) is not int or not 0 <= start < end <= MAX_EPOCH_MS:
            raise ValueError('UI_COLOR_DEADLINE_REQUIRED')
        entries = deepcopy(self.entries)
        entries.setdefault(key, {}).update(scale='deadline', deadline_start=start, deadline_end=end)
        self._commit(entries)

    def set_range(self, key, text, start, end, color):
        color = self._validate(key, color)
        if not isinstance(text, str) or len(text) > MAX_TEXT_UNITS or type(start) is not int or type(end) is not int:
            raise ValueError('UI_COLOR_TEXT_RANGE_REQUIRED')
        boundaries = utf16_boundaries(text)
        if max(boundaries) > MAX_TEXT_UNITS or start not in boundaries or end not in boundaries or start >= end:
            raise ValueError('UI_COLOR_TEXT_RANGE_REQUIRED')
        digest = text_digest(text)
        entries = deepcopy(self.entries)
        entry = entries.setdefault(key, {})
        previous = entry.get('ranges', []) if entry.get('anchor') == 'slot' or entry.get('text_digest') == digest else []
        previous = [span for span in previous if span['start'] in boundaries and span['end'] in boundaries]
        # Last explicit selection wins; preserve non-overlapping portions.
        spans = []
        for span in previous:
            if span['end'] <= start or span['start'] >= end:
                spans.append(dict(span))
            else:
                if span['start'] < start:
                    spans.append(dict(span, end=start))
                if span['end'] > end:
                    spans.append(dict(span, start=end))
        spans.append({'start': start, 'end': end, 'color': color})
        spans.sort(key=lambda span: (span['start'], span['end']))
        merged = []
        for span in spans:
            if merged and merged[-1]['end'] == span['start'] and merged[-1]['color'] == span['color']:
                merged[-1]['end'] = span['end']
            else:
                merged.append(span)
        if len(merged) > MAX_RANGES:
            raise ValueError('UI_COLOR_RANGE_LIMIT')
        entry.update(anchor='slot', ranges=merged)
        entry.pop('text_digest', None)
        self._commit(entries)

    def reset(self, key):
        if not valid_key(key):
            raise ValueError('UI_COLOR_PRESENTATION_KEY_REQUIRED')
        if key in self.entries:
            entries = deepcopy(self.entries)
            del entries[key]
            self._commit(entries)

    def style(self, key, text=''):
        value = self.entries.get(key, {}) if valid_key(key) else {}
        output = {'color': value.get('color', ''), 'scale': value.get('scale', 'solid'), 'ranges': []}
        if output['scale'] == 'deadline':
            output.update(deadline_start=value['deadline_start'], deadline_end=value['deadline_end'])
        if isinstance(text, str) and len(text) <= MAX_TEXT_UNITS and value.get('ranges') and (value.get('anchor') == 'slot' or value.get('text_digest') == text_digest(text)):
            boundaries = utf16_boundaries(text)
            output['ranges'] = [dict(span) for span in value.get('ranges', []) if span['start'] in boundaries and span['end'] in boundaries]
        return output


def rich_text(text, style):
    """Escape all input; only validated numeric spans/canonical hex reach HTML."""
    if not isinstance(text, str):
        text = str(text)
    boundaries = utf16_boundaries(text)
    # Qt StyledText collapses ordinary whitespace like HTML. Keep run width
    # while retaining one normal breakable space in interior runs.
    escaped = [html.escape(char) for char in text]
    index = 0
    while index < len(text):
        if text[index] != ' ':
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] == ' ':
            end += 1
        interior = index > 0 and end < len(text) and text[index-1] not in '\r\n' and text[end] not in '\r\n'
        for at in range(index, end):
            escaped[at] = ' ' if interior and at == end-1 else '&nbsp;'
        index = end
    spans = style.get('ranges', [])
    fragments, cursor = [], 0
    for span in sorted(spans, key=lambda row: row['start']):
        if span['start'] not in boundaries or span['end'] not in boundaries:
            continue
        start, end = boundaries[span['start']], boundaries[span['end']]
        if start < cursor or end <= start or not re.fullmatch(r'#[0-9a-f]{6}', str(span.get('color', ''))):
            continue
        fragments.append(''.join(escaped[cursor:start]))
        fragments.append('<font color="' + span['color'] + '">' + ''.join(escaped[start:end]) + '</font>')
        cursor = end
    fragments.append(''.join(escaped[cursor:]))
    return ''.join(fragments).replace('\n', '<br/>')


def scale_color(mode, fraction, fallback):
    """One cheap RGB interpolation per value update; no shader or animation."""
    if mode not in {'risk', 'progress'} or type(fraction) not in {int, float} or not math.isfinite(fraction):
        return fallback
    fraction = min(1.0, max(0.0, fraction))
    points = ((0.0, '#005fff'), (0.01, '#00afff'), (0.25, '#00ff87'), (0.5, '#ffd700'), (0.75, '#ff8700'), (1.0, '#ff0000')) if mode == 'risk' else (
        (0.0, '#d78787'), (0.25, '#ff8700'), (0.6, '#87ff00'), (0.95, '#00ff87'), (0.99, '#87d7ff'), (1.0, '#afd7ff'))
    for (left, a), (right, b) in zip(points, points[1:]):
        if fraction <= right:
            amount = (fraction - left) / (right - left)
            channels = [round(int(a[index:index+2], 16) + amount * (int(b[index:index+2], 16) - int(a[index:index+2], 16))) for index in (1, 3, 5)]
            return '#' + ''.join(format(channel, '02x') for channel in channels)
    return points[-1][1]


class UiColorController(QObject):
    stylesChanged = Signal()
    errorChanged = Signal()

    def __init__(self, parent=None, *, path=None, colors=None):
        super().__init__(parent)
        self.registry = ColorRegistry(path, colors=colors)
        self._revision = 0
        self._error = ''
        self._window_filters = {}

    @Slot(QObject, result=bool)
    def installWindow(self, window):
        """Disabled Qt controls suppress child pointer handlers. This fallback
        inspects their display text only on an explicit right-button press.
        It never changes a control's enabled state or invokes its action.
        """
        if not isinstance(window, QQuickWindow) and isinstance(window, QObject) and window.inherits('QQuickWindow'):
            window = wrapInstance(getCppPointer(window)[0], QQuickWindow)
        if not isinstance(window, QQuickWindow):
            return False
        identity = int(getCppPointer(window)[0])
        if identity in self._window_filters:
            return True
        listener = _DisabledTextColorFilter(self, window)
        window.installEventFilter(listener)
        self._window_filters[identity] = listener
        window.destroyed.connect(lambda *_: self._window_filters.pop(identity, None))
        return True

    @Property(int, notify=stylesChanged)
    def revision(self):
        return self._revision

    @Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @Property(float, notify=stylesChanged)
    def latestDeadlineTime(self):
        return float(max((entry.get('deadline_end', 0) for entry in self.registry.entries.values() if entry.get('scale') == 'deadline'), default=0))

    def _mutation(self, operation):
        try:
            operation()
        except (ValueError, OSError) as failure:
            self._error = str(failure) if isinstance(failure, ValueError) else 'UI_COLOR_SAVE_FAILED'
            self.errorChanged.emit()
            return False
        self._revision += 1
        self._error = ''
        self.stylesChanged.emit()
        self.errorChanged.emit()
        return True

    @Slot(str, str, result=str)
    def colorFor(self, key, fallback):
        return self.registry.style(key).get('color') or fallback

    @Slot(str, str, 'QVariant', result=str)
    def colorForValue(self, key, fallback, fraction):
        style = self.registry.style(key)
        return scale_color(style.get('scale'), fraction, style.get('color') or fallback)

    @Slot(str, str, result=str)
    def scaleFor(self, key, fallback):
        entry = self.registry.entries.get(key, {}) if valid_key(key) else {}
        return entry.get('scale') or fallback

    @Slot(str, str, 'QVariant', result=str)
    def deadlineColor(self, key, fallback, now):
        style = self.registry.style(key)
        if style.get('scale') != 'deadline' or type(now) not in {int, float} or not math.isfinite(now):
            return style.get('color') or fallback
        fraction = (now - style['deadline_start']) / (style['deadline_end'] - style['deadline_start'])
        return scale_color('risk', fraction, style.get('color') or fallback)

    @Slot(str, str, result=str)
    def styleFor(self, key, text):
        return json.dumps(self.registry.style(key, text), separators=(',', ':'))

    @Slot(str, result=bool)
    def hasRangeStyle(self, key):
        """Cheap revision-scoped hint; actual text/ranges still validate on use."""
        return bool(self.registry.entries.get(key, {}).get('ranges')) if valid_key(key) else False

    @Slot(str, str, result=str)
    def richText(self, key, text):
        return rich_text(text, self.registry.style(key, text))

    @Slot(str, int, result=str)
    def wordRange(self, text, position):
        return json.dumps(word_range(text, position))

    @Slot(str, str, result=bool)
    def setColor(self, key, color):
        return self._mutation(lambda: self.registry.set_color(key, color))

    @Slot(str, str, int, int, str, result=bool)
    def setRangeColor(self, key, text, start, end, color):
        return self._mutation(lambda: self.registry.set_range(key, text, start, end, color))

    @Slot(str, str, result=bool)
    def setScale(self, key, mode):
        return self._mutation(lambda: self.registry.set_scale(key, mode))

    @Slot(str, 'QVariant', 'QVariant', result=bool)
    def setDeadline(self, key, start, end):
        def save():
            if type(start) not in {int, float} or type(end) not in {int, float} or not math.isfinite(start) or not math.isfinite(end) or start != int(start) or end != int(end):
                raise ValueError('UI_COLOR_DEADLINE_REQUIRED')
            self.registry.set_deadline(key, int(start), int(end))
        return self._mutation(save)

    @Slot(str, result=bool)
    def reset(self, key):
        return self._mutation(lambda: self.registry.reset(key))


class _DisabledTextColorFilter(QObject):
    """Bounded interaction-time fallback, not a polling/global recolor pass."""
    def __init__(self, controller, window):
        super().__init__(window)
        self.controller = controller

    @staticmethod
    def _item(value):
        if isinstance(value, QQuickItem):
            return value
        if isinstance(value, QObject) and isValid(value):
            return wrapInstance(getCppPointer(value)[0], QQuickItem)
        return None

    def _disabled_text_at(self, root, scene_position):
        remaining = MAX_HIT_ITEMS
        blocked_popup = object()
        def visit(item, depth):
            nonlocal remaining
            remaining -= 1
            if remaining < 0 or depth > MAX_HIT_DEPTH or not isValid(item) or not item.isVisible() or item.opacity() <= 0:
                return None
            local = item.mapFromScene(scene_position)
            inside = item.contains(local)
            if item.clip() and not inside:
                return None
            popup_here = inside and item.inherits('QQuickPopupItem')
            children = list(item.childItems())
            # z ties retain QQuickItem sibling paint order, last child on top.
            ordered = sorted(enumerate(children), key=lambda row: (row[1].z(), row[0]), reverse=True)
            for _, child in ordered:
                match = visit(child, depth + 1)
                if match is not None:
                    return match
            if (inside and not item.isEnabled()
                    and item.property('customizationAllowed') is True
                    and isinstance(item.property('effectiveColorKey'), str)
                    and item.metaObject().indexOfMethod('openColorMenu(QVariant,QVariant)') >= 0):
                return item, local
            if popup_here:
                # A native menu/combobox/popup above the page is a hit-test
                # boundary. Never recolor a disabled caption behind it.
                return blocked_popup
            return None
        result = visit(root, 0)
        return None if result is blocked_popup else result

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.MouseButtonPress or event.button() != Qt.MouseButton.RightButton or not isinstance(watched, QQuickWindow):
            return False
        try:
            match = self._disabled_text_at(watched.contentItem(), event.position())
            if match is None:
                return False
            item, local = match
            x, y = float(local.x()), float(local.y())
            if not math.isfinite(x) or not math.isfinite(y):
                return False
            context = qmlContext(item)
            if context is None:
                return False
            # Only finite numbers enter this owned-source expression. Neither
            # displayed text, an object name nor a selected string is code.
            expression = QQmlExpression(context, item, f'openColorMenu({x!r},{y!r})')
            expression.evaluate()
            if expression.hasError():
                return False
            event.accept()
            return True
        except (RuntimeError, TypeError, AttributeError):
            # A delegate may disappear during an event; normal Qt handling
            # remains the safe fallback and no disabled action is enabled.
            return False
