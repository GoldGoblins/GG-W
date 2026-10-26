"""Finite first-install checks using public bundles, never another user's proof.

Only the initial audit created here may be resumed by the desktop. Existing
manual audits remain independent. Calls belong to a cancellable worker.
"""
from __future__ import annotations

import time

from backend.media_availability import decoder_tools
from backend.media_health_audit import MediaHealthAudit

MAX_SECONDS = 300.0
MAX_JOBS = 240
MISSING_DECODER = "Mediebiblioteket behöver FFmpeg och ffprobe. Installera FFmpeg och välj uppdatera."


def validate_initial(index, *, cancel, max_seconds=MAX_SECONDS, explicit=False):
    if cancel.is_set():
        return {"state": "cancelled", "notice": ""}
    # Inspect before initialization: policy migrations and another process's
    # manual/stopped/running audit are never part of this helper's authority.
    with index.connection() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_audit_runs'").fetchone()
        run = db.execute("SELECT id,status,cancel_requested,owner,lease_until FROM media_audit_runs ORDER BY id DESC LIMIT 1").fetchone() if exists else None
        marker = db.execute("SELECT value FROM meta WHERE key='starter_audit_run'").fetchone()
        checked = db.execute("SELECT 1 FROM items WHERE checked_at>0 LIMIT 1").fetchone()
    if not run and checked and not explicit:
        # An established local library may predate the standalone audit. Its
        # existing source work is not a fresh-install request to scan it all.
        return {"state": "existing", "notice": ""}
    if run:
        if not marker or str(run[0]) != marker[0]:
            return {"state": "manual", "notice": ""}
        if run[1] == "complete" and not explicit:
            return {"state": "complete", "notice": ""}
        if run[2] and not explicit:
            return {"state": "stopped", "notice": ""}
        if run[3] and run[4] > time.time():
            return {"state": "external", "notice": ""}
    if explicit:
        decoder_tools.cache_clear()
    if not all(decoder_tools().get(name) for name in ("ffmpeg", "ffprobe")):
        return {"state": "decoder_missing", "notice": MISSING_DECODER}
    if cancel.is_set():
        return {"state": "cancelled", "notice": ""}
    audit = MediaHealthAudit(index)
    run_id = int(run[0]) if run else audit.start(initial=True)
    if run_id is None:
        return {"state": "manual", "notice": ""}
    if explicit and run:
        # A new explicit request may recover a first-install provider outage,
        # with at most two new attempts per transient source in this slice.
        # Ordinary reopening never resets source attempts or extends the run.
        audit.repair(run_id, initial_retry=True)
        audit.include(run_id)
    result = audit.run(run_id, workers=2, max_seconds=min(MAX_SECONDS, max_seconds),
                       max_jobs=MAX_JOBS, cancel=cancel)
    state = "cancelled" if cancel.is_set() else str(result.get("status") or "paused")
    notice = "" if state == "complete" or cancel.is_set() else "Källkontrollen är pausad. Välj uppdatera för att kontrollera fler titlar."
    return {"state": state, "notice": notice}
