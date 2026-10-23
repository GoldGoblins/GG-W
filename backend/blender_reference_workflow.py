"""Persistent, task-bounded reference -> model -> observe -> repair workflow.

The acting model supplies visual judgments. This journal never treats a hash,
mesh count or self-assigned score as proof of artistic quality. Image generation
uses the available image tool outside this module; no provider key is needed.
"""
from __future__ import annotations

from contextlib import contextmanager
from backend.application_paths import STATE_ROOT
from backend.platform_support import file_locks as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable
import uuid

SCHEMA = "gg.blender-reference-workflow.v1"
PROJECT = Path(__file__).resolve().parents[1]
SKILL = PROJECT / "skills/gg-blender-reference-workflow/SKILL.md"
ROOT = STATE_ROOT / "blender-modeling"
VIEWS = ("front", "side", "back", "three_quarter")
PREFERRED_IMAGE_MODEL = "gpt-image-2.5-sunburst"
OPERATIONS = ("create", "references", "setup", "capture", "review", "export", "finish", "status", "lessons")
TERMINAL = {"COMPLETE", "LIMIT_REACHED"}


def matches(text: str) -> bool:
    return bool(re.search(r"blender|\bmesh\b|\bsculpt\w*|skulpter\w*|\b3[dD][ -]?(?:modell|model|figur|character)|modellera|modeling workflow|modelling workflow",
                          text, re.IGNORECASE))


def render_context(text: str, budget: int = 1000) -> str:
    if not matches(text):
        return ""
    lines = ["[GG BLENDER WORKFLOW]", "Read " + SKILL.as_posix(),
             "One text or image starts the task. Generate coherent references with the image tool; prefer "
             + PREFERRED_IMAGE_MODEL + "; record the actual reported model honestly.",
             "Use gg-model for isolated Blender workspace, frozen references, fixed-camera clay/silhouette/material "
             "captures, saved checkpoints and evidence-bound reviews. Inspect every reference and render yourself; "
             "correct the largest mismatch, recapture and compare. Reuse tested lessons. "
             "Do not require user grading each round. This workflow changes procedures, not model weights. "
             "Current task authority and tool gates still apply; no background or cross-task action.",
             "[/GG BLENDER WORKFLOW]"]
    closer = lines.pop()
    body = "\n".join(lines)
    cap = max(0, int(budget))
    return body[:max(0, cap - len(closer) - 1)].rstrip() + "\n" + closer if cap >= len(closer) + 1 else ""


def _text(value, name: str, maximum: int = 2000) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ValueError("Missing or oversized " + name)
    return result


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _artifact(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Missing artifact: " + str(path))
    return {"path": str(path), "sha256": _digest(path)}


def _verify(row: dict) -> None:
    if _digest(Path(row["path"])) != row["sha256"]:
        raise ValueError("Artifact changed; capture/review again")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _blender(operation: str, payload: dict) -> dict:
    from backend.blender_contract import sidecar_call
    folder = str(PROJECT / "tools/blender")
    # Python source goes straight to the local sidecar, never through a shell.
    code = ("import sys, importlib, json\n"
            + "sys.path.insert(0, " + repr(folder) + ")\n"
            + "import gg_blender_reference\nimportlib.reload(gg_blender_reference)\n"
            + "print(json.dumps(gg_blender_reference.dispatch(" + repr(operation) + ", json.loads("
            + repr(json.dumps(payload, allow_nan=False)) + "))))")
    reply = sidecar_call("exec", code=code)
    if not reply.get("ok"):
        raise RuntimeError(str(reply.get("error", "Blender failed")) + ": " + str(reply.get("message", ""))[:400])
    try:
        return json.loads(reply["stdout"].strip().splitlines()[-1])
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("Blender returned no complete workflow result") from exc


def _job(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(name or "")):
        raise ValueError("Invalid modeling job")
    path = root / "jobs" / name
    if not (path / "job.json").is_file():
        raise ValueError("Modeling job not found")
    return path


def _next(state: dict) -> str:
    return {"NEEDS_REFERENCES": "Generate or derive coherent views, inspect them, then freeze references.",
            "REFERENCES_READY": "Set up the isolated live Blender workspace.",
            "MODELING": "Build or correct geometry in the job collection, then capture.",
            "NEEDS_REVIEW": "Inspect frozen references and all captured views; submit comparisons and specific fixes.",
            "ACCEPTED": "Export the reviewed model; perform requested engine/rig/animation checks, then finish.",
            "LIMIT_REACHED": "Keep reviewed checkpoints and report unresolved mismatches honestly.",
            "COMPLETE": "Deliver saved files and reuse applicable evidence on the next task."}[state["phase"]]


def _lessons(root: Path, query: str = "") -> list[dict]:
    path = root / "lessons.json"
    records = json.loads(path.read_text()) if path.is_file() else []
    words = set(re.findall(r"[\w]+", query.lower()))
    scored = [(len(words & set(re.findall(r"[\w]+", (row["trigger"] + " " + row["technique"]).lower()))), row)
              for row in records]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row for score, row in scored if score or not words][:5]


def _learn(root: Path, state: dict, payload: dict) -> None:
    additions = payload.get("lessons", [])
    if not additions:
        return
    path = root / "lessons.json"
    with _lock(root / "lessons.lock"):
        records = json.loads(path.read_text()) if path.is_file() else []
        for supplied in additions[:8]:
            before_number = int(supplied.get("before", 0))
            after_number = int(supplied.get("after", 0))
            captures = state["captures"]
            if not (1 <= before_number < after_number <= len(captures)):
                raise ValueError("A lesson needs captured before/after evidence")
            before, after = captures[before_number - 1], captures[after_number - 1]
            for capture in (before, after):
                _verify(capture["checkpoint"])
                _verify(capture["mesh_report_artifact"])
                for image in capture["images"].values():
                    _verify(image)
            if (before["fingerprint"] == after["fingerprint"] or
                    not before.get("review", {}).get("issues") or after.get("review", {}).get("verdict") != "PASS"):
                raise ValueError("A lesson needs a diagnosed issue and a corrected reviewed result")
            trigger = _text(supplied.get("trigger"), "lesson trigger", 400)
            technique = _text(supplied.get("technique"), "lesson technique", 1200)
            limits = _text(supplied.get("limits"), "lesson limits", 800)
            key = hashlib.sha256((trigger + "\n" + technique).encode()).hexdigest()
            row = next((entry for entry in records if entry["key"] == key), None)
            if row is None:
                row = {"key": key, "trigger": trigger, "technique": technique, "limits": limits,
                       "status": "OBSERVED_ON_ONE_TASK", "evidence": []}
                records.append(row)
            if not any(entry["job"] == state["job"] for entry in row["evidence"]):
                row["evidence"].append({"job": state["job"], "brief": state["brief"],
                    "references": [state["references"][view]["sha256"] for view in VIEWS],
                    "before": before["checkpoint"], "after": after["checkpoint"],
                    "review": after["review"], "variant": str(supplied.get("variant", ""))[:400]})
            variants = {tuple(entry["references"]) for entry in row["evidence"] if entry["variant"]}
            if len(variants) >= 2:
                row["status"] = "REPEATED_ON_REPORTED_REFERENCE_VARIANTS"
        _write(path, records)


def execute(operation: str, payload: dict, *, root: Path | None = None,
            blender: Callable | None = None) -> dict:
    """One finite action. Authorization remains with the active chat/tool runtime."""
    if operation not in OPERATIONS or not isinstance(payload, dict):
        raise ValueError("Unknown workflow operation or non-object payload")
    root = Path(root or ROOT)
    call = blender or _blender
    if operation == "lessons":
        return {"lessons": _lessons(root, str(payload.get("query", ""))),
                "limit": "Observed procedures, not changed weights or a mastery guarantee."}
    if operation == "create":
        brief = _text(payload.get("brief"), "brief", 8000)
        rounds = int(payload.get("max_rounds", 6))
        if not 1 <= rounds <= 12:
            raise ValueError("max_rounds must be between 1 and 12")
        name = uuid.uuid4().hex[:12]
        directory = root / "jobs" / name
        criteria = payload.get("criteria", ["silhouette", "proportions", "features", "materials", "technical"])
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= 12:
            raise ValueError("Provide 1-12 brief-specific criteria")
        criteria = [_text(item, "criterion", 120) for item in criteria]
        if len(set(criteria)) != len(criteria):
            raise ValueError("Criteria must be distinct")
        state = {"schema": SCHEMA, "job": name, "brief": brief, "phase": "NEEDS_REFERENCES",
                 "criteria": criteria, "max_rounds": rounds,
                 "requested_image_model": str(payload.get("image_model") or PREFERRED_IMAGE_MODEL),
                 "reported_image_model": None, "references": {}, "captures": [], "exports": {}}
        initial = payload.get("image")
        if initial:
            image = Path(initial).expanduser().resolve()
            if image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("Input must be an image")
            target = directory / ("input" + image.suffix.lower())
            target.parent.mkdir(parents=True)
            shutil.copyfile(image, target)
            state["input"] = _artifact(target)
        _write(directory / "job.json", state)
        return {**state, "directory": str(directory), "next": _next(state), "lessons": _lessons(root, brief)}
    directory = _job(root, str(payload.get("job", "")))
    with _lock(directory / "job.lock"):
        state = json.loads((directory / "job.json").read_text())
        if operation == "status":
            return {**state, "directory": str(directory), "next": _next(state)}
        if state["phase"] in TERMINAL:
            raise ValueError("This job has finished")
        for row in state["references"].values():
            _verify(row)
        if operation == "references":
            if state["phase"] != "NEEDS_REFERENCES":
                raise ValueError("Accepted references stay fixed; start a new job for a changed target")
            review = _text(payload.get("consistency_review"), "reference consistency review")
            refs = payload.get("views", {})
            if set(refs) != set(VIEWS):
                raise ValueError("Freeze front, side, back and three_quarter references")
            rows = {}
            copies = {}
            for view in VIEWS:
                row = refs[view]
                path = Path(row["path"]).expanduser().resolve()
                if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError("Reference must be an image")
                region = row.get("region", [0, 0, 1, 1])
                if (len(region) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in region)
                        or region[0] >= region[2] or region[1] >= region[3]):
                    raise ValueError("Reference region must be [u0,v0,u1,v1], bottom-left origin, within 0..1")
                if path not in copies:
                    target = directory / "references" / (view + path.suffix.lower())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    copies[path] = _artifact(target)
                rows[view] = {**copies[path], "region": region,
                              "inferred": bool(row.get("inferred", False)),
                              "source": _text(row.get("source"), "reference source", 80)}
            state.update(references=rows, consistency_review=review, phase="REFERENCES_READY",
                         reported_image_model=payload.get("reported_image_model"))
        elif operation == "setup":
            if state["phase"] != "REFERENCES_READY":
                raise ValueError("Freeze references before workspace setup")
            state["workspace"] = call("setup", {"job": state["job"], "references": state["references"]})
            state["phase"] = "MODELING"
        elif operation == "capture":
            if state["phase"] != "MODELING" and not (state["phase"] == "NEEDS_REVIEW" and payload.get("discard_unreviewed") is True):
                raise ValueError("Review the existing capture before making another")
            previous = state["captures"]
            if len(previous) >= state["max_rounds"]:
                raise ValueError("Iteration limit reached")
            changes = _text(payload.get("changes"), "changes since previous capture")
            result = call("capture", {"job": state["job"], "directory": str(directory / (("round-%02d-" % (len(previous) + 1)) + uuid.uuid4().hex[:8])),
                         "framing": state.get("framing"), "size": int(payload.get("size", 640))})
            for style in ("clay", "silhouette", "appearance"):
                if not set(VIEWS).issubset(result["views"][style]):
                    raise ValueError("Capture needs every reference view")
            images = {style + "/" + view: _artifact(Path(row["path"]))
                      for style, views in result["views"].items() for view, row in views.items() if view in VIEWS}
            current = {"round": len(previous) + 1, "changes": changes, "fingerprint": result["fingerprint"],
                       "checkpoint": _artifact(Path(result["checkpoint"])), "images": images,
                       "mesh_reports": result["mesh_reports"], "review": None}
            current["mesh_report_artifact"] = _artifact(Path(result["mesh_reports"]["path"]))
            state["framing"] = result["framing"]
            state["captures"].append(current)
            state["phase"] = "NEEDS_REVIEW"
        elif operation == "review":
            if state["phase"] != "NEEDS_REVIEW":
                raise ValueError("Capture the current model before reviewing")
            latest = state["captures"][-1]
            _verify(latest["checkpoint"])
            _verify(latest["mesh_report_artifact"])
            for row in latest["images"].values():
                _verify(row)
            if call("fingerprint", {"job": state["job"]})["fingerprint"] != latest["fingerprint"]:
                raise ValueError("Model changed after capture; review that checkpoint or recapture")
            if set(payload.get("viewed", [])) != set(latest["images"]):
                raise ValueError("Inspect every captured image before reviewing")
            comparisons = payload.get("comparisons", {})
            if set(comparisons) != set(VIEWS):
                raise ValueError("Compare all four views against the frozen references")
            for view, checks in comparisons.items():
                if set(checks) != set(state["criteria"]):
                    raise ValueError("Review every brief-specific criterion in " + view)
                for criterion, observation in checks.items():
                    _text(observation, "comparison " + criterion, 2000)
            technical = _text(payload.get("technical_review"), "technical review", 4000)
            issues = payload.get("issues", [])
            if not isinstance(issues, list) or len(issues) > 32:
                raise ValueError("Review issues must be a bounded list")
            for issue in issues:
                if issue.get("view") not in (*VIEWS, "technical") or issue.get("severity") not in ("minor", "major", "blocker"):
                    raise ValueError("Each issue needs a view and severity")
                _text(issue.get("observation"), "observed mismatch")
                _text(issue.get("change"), "specific corrective edit")
            verdict = payload.get("verdict")
            if verdict not in {"PASS", "REPAIR"} or (verdict == "PASS" and issues) or (verdict == "REPAIR" and not issues):
                raise ValueError("PASS needs no unresolved issues; REPAIR needs specific observed issues")
            latest["review"] = {"verdict": verdict, "comparisons": comparisons, "technical_review": technical,
                                 "issues": issues, "judgment": "MODEL_VISUAL_ASSESSMENT_NOT_EXTERNAL_CERTIFICATION"}
            unchanged = len(state["captures"]) >= 2 and latest["fingerprint"] == state["captures"][-2]["fingerprint"]
            state["phase"] = ("ACCEPTED" if verdict == "PASS" else "LIMIT_REACHED"
                              if len(state["captures"]) >= state["max_rounds"] or unchanged else "MODELING")
        elif operation == "export":
            if state["phase"] != "ACCEPTED":
                raise ValueError("Review must pass before final export")
            latest = state["captures"][-1]
            _verify(latest["checkpoint"])
            _verify(latest["mesh_report_artifact"])
            for row in latest["images"].values():
                _verify(row)
            result = call("export", {"job": state["job"], "directory": str(directory / ("delivery-" + uuid.uuid4().hex[:8])),
                                     "expected": latest["fingerprint"]})
            state["exports"] = {kind: _artifact(Path(result[kind])) for kind in ("blend", "glb")}
        elif operation == "finish":
            if state["phase"] != "ACCEPTED" or not state["exports"]:
                raise ValueError("Export the accepted model first")
            for row in state["exports"].values():
                _verify(row)
            state["delivery_checks"] = _text(payload.get("delivery_checks"), "delivery checks", 4000)
            _learn(root, state, payload)
            state["phase"] = "COMPLETE"
        _write(directory / "job.json", state)
        return {**state, "directory": str(directory), "next": _next(state)}
