"""Stable catalogue identities with small, speculative summary-page buffers.

The backend retains identity strings for one view, never full source metadata.
New admissions cannot shift an already visited offset. Every page still checks
current source health; withdrawals invalidate buffered pages immediately.
"""
from collections import OrderedDict
from copy import deepcopy
import threading
import time
import uuid

from backend.media_index import PAGE_SIZE, echo


class SnapshotInvalid(ValueError):
    pass


class BrowseSession:
    def __init__(self, index, view, cancel=None):
        self.index, self.view = index, dict(view, offset=0)
        self.revision = "view:" + uuid.uuid4().hex
        self.withdraw_revision = index.meta("inventory_withdraw_revision")
        self.origin_revision = index.meta("inventory_structure_revision")
        self.groups = index.snapshot_groups(self.view, cancel=cancel)
        self.base = index.browse(self.view, cancel=cancel)
        self._lock = threading.RLock()
        offset = int(view.get("offset") or 0)
        self._positions = {0: 0, offset: offset}
        self._pages = OrderedDict()

    def page(self, offset, cancel=None):
        with self._lock:
            if cancel is not None and cancel.is_set():
                raise SnapshotInvalid("MEDIA_SNAPSHOT_CANCELLED")
            if self.index.meta("inventory_withdraw_revision") != self.withdraw_revision:
                raise SnapshotInvalid("MEDIA_SNAPSHOT_WITHDRAWN")
            cached = self._pages.get(offset)
            now = time.time()
            if cached and cached[0] > now:
                self._pages.move_to_end(offset)
                return deepcopy(cached[1])
            if offset not in self._positions:
                raise SnapshotInvalid("MEDIA_SNAPSHOT_OFFSET")
            rows, position, more = self.index.snapshot_page(self.view, self.groups, self._positions[offset], cancel=cancel)
            if self.index.meta("inventory_withdraw_revision") != self.withdraw_revision:
                raise SnapshotInvalid("MEDIA_SNAPSHOT_WITHDRAWN")
            self._positions[offset + len(rows)] = position
            payload = dict(self.base, **echo(dict(self.view, offset=offset)))
            payload.update(items=rows, library_catalog_revision=self.revision,
                library_total=max(offset + len(rows) + int(more), len(self.groups)) if more else offset + len(rows),
                library_has_more=more, library_snapshot=True)
            payload["library_count"] = payload["library_total"]
            expires = min([now + 20] + [float(row.get("availability_catalog_until") or now + 20) for row in rows])
            self._pages[offset] = (expires, deepcopy(payload))
            while len(self._pages) > 4:
                self._pages.popitem(last=False)
            return payload

    def warm_after(self, offset, cancel):
        for _ in range(2):
            if cancel.is_set():
                return
            page = self.page(offset, cancel=cancel)
            if not page["library_has_more"] or not page["items"]:
                return
            offset += len(page["items"])
