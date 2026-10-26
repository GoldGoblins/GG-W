"""Local, source-bound body atlas for fictional WEST learning cases.

This module echoes bounded case inputs and routes to cited material. It does
not infer diagnoses, prescribe treatment, simulate physiology or decide final
triage. Case inputs are returned to the caller only; they are never persisted.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re
from typing import Any

from backend.application_paths import STATE_ROOT
from backend import knowledge_atlas
from backend.platform_files import is_link

SCHEMA = "gg.west-body.v1"
MAX_MANIFEST_BYTES = 2_000_000
MAX_CASE_BYTES = 24_000
LEARNING_NOTICE = (
    "Övningsfall. Kroppen visar inmatade uppgifter och valt källmaterial. "
    "Slutlig triage kräver full bedömning enligt gällande rutin."
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)\Z")
_SEVERITIES = {"unassessed", "red", "orange", "yellow", "green", "blue"}
_INJURY_KINDS = {"injury", "pain", "wound", "burn", "fracture", "bleeding", "swelling", "trauma"}
_COLLECTION_LIMITS = {"age_groups": 24, "regions": 64, "figures": 64,
                      "topics": 300, "parameters": 48, "scenarios": 64, "sources": 64,
                      "educational_scores": 8}

# Transcribed from the visually reviewed WEST-A 2025:1, PDF page 10, printed
# page 6. Independently checked against RCP's official NEWS2 observation
# chart (December 2022). Only Scale 1 component arithmetic is implemented.
# Score activation additionally requires a version-bound local source table
# and the user's explicit eligible adult exercise context. No priority,
# disposition, alarm threshold or treatment follows from this arithmetic.
NEWS2_SCALE1_RULES = {
    "respiration": {"precision": 0, "bands": [[8, 3], [11, 1], [20, 0], [24, 2], [None, 3]]},
    "spo2": {"precision": 0, "bands": [[91, 3], [93, 2], [95, 1], [None, 0]]},
    "oxygen": {"values": {"no": 0, "yes": 2}},
    "systolic": {"precision": 0, "bands": [[90, 3], [100, 2], [110, 1], [219, 0], [None, 3]]},
    "pulse": {"precision": 0, "bands": [[40, 3], [50, 1], [90, 0], [110, 1], [130, 2], [None, 3]]},
    "consciousness": {"values": {"A": 0, "C": 3, "V": 3, "P": 3, "U": 3}},
    "temperature": {"precision": 1, "bands": [[35.0, 3], [36.0, 1], [38.0, 0], [39.0, 1], [None, 2]]},
}
_NEWS2_LABELS = {"respiration": "Andningsfrekvens", "spo2": "Syremättnad, skala 1",
                "oxygen": "Tillförd syrgas", "systolic": "Systoliskt blodtryck",
                "pulse": "Hjärtfrekvens/puls", "consciousness": "Medvetandegrad", "temperature": "Temperatur"}
_NEWS2_DEFAULT_FIELDS = {"respiration": "rr", "spo2": "spo2", "oxygen": "oxygen", "systolic": "sbp",
                        "pulse": "pulse", "consciousness": "consciousness", "temperature": "temperature"}
_NEWS2_NOTICE = (
    "Övningspoäng för NEWS2 skala 1. Slutlig triage är inte beräknad. "
    "Gäller valt vuxenfall utan graviditet/postpartum eller skala 2. "
    "Använd uppmätt hjärtfrekvens när sådan finns."
)


def _reject_constant(_value):
    raise ValueError("NON_FINITE_JSON")


def _json(raw: str, maximum: int):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > maximum:
        raise ValueError("INPUT_SIZE_LIMIT")
    return json.loads(raw, parse_constant=_reject_constant)


def _text(value, maximum=4000, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError("TEXT_INVALID")
    value = value.strip()
    if not empty and not value:
        raise ValueError("TEXT_REQUIRED")
    return value


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("IDENTIFIER_INVALID")
    return value


def _bounded(value, depth=0):
    """Retain declarative display metadata, never executable objects or markup."""
    if depth > 12:
        raise ValueError("MANIFEST_NESTING_LIMIT")
    if value is None or isinstance(value, bool):
        return value
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError("NON_FINITE_JSON")
        return value
    if isinstance(value, str):
        return _text(value, 24000, empty=True)
    if isinstance(value, list) and len(value) <= 512:
        return [_bounded(item, depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= 100:
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 100 or key in {"__proto__", "constructor", "prototype"}:
                raise ValueError("MANIFEST_KEY_INVALID")
            result[key] = _bounded(item, depth + 1)
        return result
    raise ValueError("MANIFEST_VALUE_INVALID")


def _applies(row, age_group):
    ages = row.get("age_groups", [])
    if not ages and row.get("age_group"):
        ages = [row["age_group"]]
    return not ages or age_group in ages


def _stat(path):
    try:
        info = path.stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


class BodyExplorer:
    """Cache only the source bundle, never users' entered case parameters."""

    def __init__(self, *, root=None):
        self.root = Path(root) if root is not None else STATE_ROOT / "knowledge-atlas"
        self.folder = self.root / "west-body"
        self._key = None
        self._snapshot = None
        self._assets = set()

    def _cache_key(self):
        paths = [self.folder / "manifest.json", self.root / "atlas.sqlite3", self.root / "atlas.sqlite3-wal"]
        paths.extend(sorted(self._assets))
        return tuple(_stat(path) for path in paths)

    def _asset(self, raw):
        value = _text(raw, 1000)
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or ":" in value or "\\" in value:
            raise ValueError("ASSET_PATH_INVALID")
        path = self.folder / relative
        self._assets.add(path)
        if any(is_link(parent) for parent in [path, *path.parents] if parent == self.folder or self.folder in parent.parents):
            raise ValueError("LINKED_ASSET_NOT_ALLOWED")
        if not path.resolve().is_relative_to(self.folder.resolve()) or not path.is_file():
            raise ValueError("ASSET_MISSING")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or path.stat().st_size > 32_000_000:
            raise ValueError("ASSET_FORMAT_INVALID")
        return path.resolve().as_uri()

    def _images(self, value, issues):
        if isinstance(value, list):
            return [self._images(item, issues) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: self._images(item, issues) for key, item in value.items() if key != "image_url"}
        if "image_path" in value:
            try:
                result["image_url"] = self._asset(value["image_path"])
            except (OSError, ValueError):
                result["image_url"] = ""
                result["asset_missing"] = True
                issues.append("En lokal illustration saknas eller kan inte öppnas.")
        elif value.get("image_url"):
            result["image_url"] = ""
            result["asset_missing"] = True
            issues.append("Illustrationer behöver en lokal bild i kroppsatlasens mapp.")
        return result

    def _citations(self, row, page_cache, issues):
        raw = row.get("citations", [])
        if not isinstance(raw, list) or len(raw) > 16:
            raise ValueError("CITATION_LIST_INVALID")
        result = []
        for citation in raw:
            if not isinstance(citation, dict):
                raise ValueError("CITATION_INVALID")
            source_id = _text(citation.get("source_id"), 160)
            page = citation.get("page")
            if type(page) is not int or not 1 <= page <= 1000:
                raise ValueError("CITATION_PAGE_INVALID")
            quote = _text(citation.get("quote"), 4000)
            key = (source_id, page)
            if key not in page_cache:
                page_cache[key] = knowledge_atlas.source_page(source_id, page, root=self.root)
            source = page_cache[key]
            checked = dict(citation)
            checked["valid"] = False
            checked["stale"] = True
            checked["source_title"] = str(source.get("source_title") or citation.get("source_title") or "Källmaterial")
            normalize = lambda text: " ".join(str(text).split()).casefold()
            if source.get("status") != "PAGE_TEXT":
                checked["issue"] = "Källsidan saknas i materialbiblioteket."
            elif normalize(quote) not in normalize(source.get("text", "")):
                checked["issue"] = "Hänvisningens text återfinns inte på källsidan."
            elif not citation.get("revision"):
                checked["issue"] = "Hänvisningen saknar versionsbindning och behöver granskas."
            elif citation["revision"] != source.get("revision"):
                checked["issue"] = "Källmaterialet har ändrats sedan hänvisningen skapades."
            else:
                checked["valid"] = True
                checked["stale"] = False
            if checked.get("issue"):
                issues.append(checked["issue"])
            result.append(checked)
        row["citations"] = result
        return any(not citation["valid"] for citation in result)

    def _load(self):
        manifest = self.folder / "manifest.json"
        if any(is_link(path) for path in (self.root, self.folder, manifest)):
            raise ValueError("LINKED_BUNDLE_NOT_ALLOWED")
        if not manifest.is_file():
            return {"status": "BODY_MISSING", "notice": "Kroppsatlasen har ännu inte lagts till i materialbiblioteket."}
        if manifest.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("MANIFEST_SIZE_LIMIT")
        bundle = _bounded(_json(manifest.read_text(encoding="utf-8"), MAX_MANIFEST_BYTES))
        if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
            raise ValueError("BODY_SCHEMA_INVALID")
        bundle["title"] = _text(bundle.get("title"), 200)
        identifiers = {}
        for name, maximum in _COLLECTION_LIMITS.items():
            rows = bundle.setdefault(name, [])
            if not isinstance(rows, list) or len(rows) > maximum:
                raise ValueError("BODY_COLLECTION_INVALID")
            used = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("BODY_ROW_INVALID")
                if name == "sources":
                    continue
                key = _id(row.get("id"))
                if key in used:
                    raise ValueError("BODY_DUPLICATE_ID")
                used.add(key)
                _text(row.get("label", row.get("title", key)), 200)
            identifiers[name] = used
        if not bundle["age_groups"]:
            raise ValueError("BODY_AGE_GROUPS_REQUIRED")
        for collection in ("topics", "parameters", "figures", "scenarios", "educational_scores"):
            for row in bundle[collection]:
                groups = row.get("age_groups", [row["age_group"]] if row.get("age_group") else [])
                if not isinstance(groups, list) or any(group not in identifiers["age_groups"] for group in groups):
                    raise ValueError("BODY_AGE_REFERENCE_INVALID")
        for row in bundle["topics"]:
            if any(region not in identifiers["regions"] for region in row.get("regions", [])):
                raise ValueError("BODY_REGION_REFERENCE_INVALID")
            if not isinstance(row.get("excludes_scores", []), list):
                raise ValueError("BODY_SCORE_EXCLUSION_INVALID")
        for row in bundle["regions"]:
            for axis in ("x", "y"):
                if axis in row and (type(row[axis]) not in (int, float) or not 0 <= row[axis] <= 1):
                    raise ValueError("BODY_REGION_POSITION_INVALID")
        for row in bundle["parameters"]:
            kind = row.get("kind", row.get("type", "number"))
            if kind not in {"number", "enum", "select", "boolean"}:
                raise ValueError("BODY_PARAMETER_KIND_INVALID")
            row["kind"] = kind
            if kind == "number":
                lower, upper = row.get("min", 0), row.get("max", 10000)
                if type(lower) not in (int, float) or type(upper) not in (int, float) or lower >= upper:
                    raise ValueError("BODY_PARAMETER_RANGE_INVALID")
                row["min"], row["max"] = lower, upper
            elif kind in {"enum", "select"}:
                options = row.get("options", [])
                if not isinstance(options, list) or not 1 <= len(options) <= 24:
                    raise ValueError("BODY_PARAMETER_OPTIONS_INVALID")
                for option in options:
                    _text(option.get("value") if isinstance(option, dict) else option, 100)
        issues, page_cache = [], {}
        bundle = self._images(bundle, issues)
        for topic in bundle["topics"]:
            stale = self._citations(topic, page_cache, issues)
            if not topic["citations"] and topic.get("illustrative") is not True and topic.get("provenance") != "proposal":
                stale = True
                issues.append("Ett ämne saknar källhänvisning och behöver granskas.")
            steps = topic.get("steps", [])
            if not isinstance(steps, list) or len(steps) > 80:
                raise ValueError("BODY_STEPS_INVALID")
            for index, step in enumerate(steps):
                if isinstance(step, str):
                    step = {"id": "step-" + str(index + 1), "text": step}
                    steps[index] = step
                if not isinstance(step, dict):
                    raise ValueError("BODY_STEP_INVALID")
                _text(step.get("text", step.get("label", "")), 12000)
                if step.get("citations"):
                    stale = self._citations(step, page_cache, issues) or stale
            topic["stale"] = stale
        for definition in bundle["educational_scores"]:
            stale = self._citations(definition, page_cache, issues)
            supported = definition["id"] == "news2_scale1"
            mapping = definition.get("parameter_map", _NEWS2_DEFAULT_FIELDS)
            if not isinstance(mapping, dict) or set(mapping) != set(NEWS2_SCALE1_RULES):
                supported = False
            elif any(not isinstance(field, str) or field not in identifiers["parameters"] for field in mapping.values()):
                supported = False
            if definition.get("rules", NEWS2_SCALE1_RULES) != NEWS2_SCALE1_RULES:
                supported = False
            # Validate that the cited source actually includes the table's
            # component headings. The citation must also match its revision.
            headings = (("andningsfrekvens",), ("syremättnad1",), ("tillfördsyrgas",),
                        ("systoliktblodtryck", "systolisktblodtryck"),
                        ("pulsfrekvens",), ("medvetandegrad",), ("temperatur",))
            table_found = False
            for citation in definition["citations"]:
                source = page_cache[(citation["source_id"], citation["page"])]
                normalized = "".join(str(source.get("text", "")).casefold().split())
                if citation["valid"] and all(any(variant in normalized for variant in heading) for heading in headings):
                    table_found = True
            if not supported or not table_found:
                stale = True
                issues.append("Övningspoängens regler eller källtabell behöver granskas.")
            definition["stale"] = stale
            definition["supported"] = supported and table_found
            definition["parameter_map"] = dict(mapping) if isinstance(mapping, dict) else {}
            definition["rules"] = copy.deepcopy(NEWS2_SCALE1_RULES) if supported else {}
            if not isinstance(definition.get("component_regions", {}), dict):
                raise ValueError("BODY_SCORE_REGIONS_INVALID")
        issues = list(dict.fromkeys(issues))
        bundle["learning_only"] = True
        bundle["clinical_use"] = False
        bundle["stale"] = bool(issues)
        bundle["learning_notice"] = LEARNING_NOTICE
        return {"status": "BODY_READY", "bundle": bundle, "stale": bool(issues),
                "issues": issues, "model_calls": 0, "case_storage": False}

    def snapshot(self):
        key = self._cache_key()
        if key == self._key and self._snapshot is not None:
            return copy.deepcopy(self._snapshot)
        try:
            result = self._load()
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            result = {"status": "ERROR", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                      "notice": "Kroppsatlasens material kunde inte läsas. Kontrollera det lokala underlaget."}
        self._key, self._snapshot = self._cache_key(), result
        return copy.deepcopy(result)

    def _score(self, request, bundle, age_group, values, selected_topics, errors):
        score_id = request.get("educational_score")
        if not score_id:
            return None
        definition = next((row for row in bundle["educational_scores"] if row["id"] == score_id), None)
        result = {"id": "news2_scale1", "label": "NEWS2, skala 1 (övning)",
                  "name": "NEWS2, skala 1 (övning)", "complete": False, "total": None,
                  "missing": [], "components": [], "citations": [], "notice": _NEWS2_NOTICE}
        if not definition or score_id != "news2_scale1" or definition.get("stale") or not definition.get("supported"):
            result["reason"] = "Övningspoängen saknar en verifierad och aktuell källtabell."
            return result
        result["citations"] = definition["citations"]
        ineligible_topic = any("news2_scale1" in row.get("excludes_scores", []) for row in selected_topics)
        # Illustration filters are not clinical age cutoffs. Explicitly
        # entered child ages nevertheless contradict this adult exercise
        # context and must block arithmetic even if the adult figure remains
        # selected. Missing age relies on the user's explicit adult context
        # attestation, rather than being silently interpreted as an age.
        supplied = request.get("parameters", request.get("values", {}))
        raw_age = request.get("age_years", supplied.get("age_years", values.get("age_years")))
        age_eligible = True
        if raw_age is not None and raw_age != "":
            if isinstance(raw_age, str) and _NUMBER.fullmatch(raw_age.strip()):
                raw_age = float(raw_age.strip().replace(",", "."))
            age_eligible = type(raw_age) in (int, float) and math.isfinite(raw_age) and 18 <= raw_age <= 130
            # A range/type validation failure on a declared age field must
            # not be bypassed by otherwise valid NEWS2 component values.
            if "age_years" in values and values["age_years"] is None:
                age_eligible = False
        if (age_group not in {"adult", "older"} or not _applies(definition, age_group)
                or request.get("context") != "adult_nonpregnant_scale1"
                or request.get("pregnant") is True or request.get("postpartum") is True
                or request.get("spo2_scale", 1) != 1 or ineligible_topic or not age_eligible):
            result["reason"] = "Välj ett tillämpligt vuxenövningsfall för NEWS2 skala 1; en angiven ålder behöver vara minst 18 år."
            return result
        mapping = definition["parameter_map"]
        definitions = {row["id"]: row for row in bundle["parameters"]}
        for component, rule in NEWS2_SCALE1_RULES.items():
            field = mapping[component]
            value = values.get(field)
            points, status = None, "missing"
            if value is not None:
                if "bands" in rule:
                    multiplier = 10 ** rule["precision"]
                    precise = type(value) in (int, float) and math.isclose(
                        value * multiplier, round(value * multiplier), rel_tol=0, abs_tol=1e-7)
                    if precise:
                        points = next(points for upper, points in rule["bands"] if upper is None or value <= upper)
                        status = "scored"
                    else:
                        status = "invalid_precision"
                        message = "NEWS2-övningen behöver temperatur i tiondels grader." if component == "temperature" else "NEWS2-övningen behöver denna parameter som heltal."
                        errors.append({"field": field, "message": message})
                elif isinstance(value, str) and value in rule["values"]:
                    points, status = rule["values"][value], "scored"
                else:
                    status = "invalid_choice"
                    errors.append({"field": field, "message": "Välj ett alternativ som stöds av NEWS2-övningens källtabell."})
            if points is None:
                result["missing"].append(field)
            row = {"id": field, "component": component, "label": _NEWS2_LABELS[component],
                   "value": value, "points": points, "status": status,
                   "unit": definitions[field].get("unit", "")}
            region = definition.get("component_regions", {}).get(component)
            if isinstance(region, str) and any(entry["id"] == region for entry in bundle["regions"]):
                row["region_id"] = region
            result["components"].append(row)
        result["complete"] = not result["missing"]
        if result["complete"]:
            result["total"] = sum(row["points"] for row in result["components"])
        return result

    def evaluate(self, raw: str):
        snapshot = self.snapshot()
        if snapshot.get("status") != "BODY_READY":
            return snapshot
        try:
            request = _json(raw, MAX_CASE_BYTES)
            if not isinstance(request, dict):
                raise ValueError("CASE_OBJECT_REQUIRED")
            request = _bounded(request)
        except (ValueError, TypeError, RecursionError):
            return {"status": "ERROR", "reason": "CASE_INPUT_INVALID", "notice": "Övningsfallets indata kunde inte läsas."}
        bundle = snapshot["bundle"]
        errors = []
        error = lambda field, message: errors.append({"field": field, "message": message})
        scenario_id = request.get("scenario_id", "")
        scenario = next((row for row in bundle["scenarios"] if row["id"] == scenario_id), {})
        if scenario_id and not scenario:
            error("scenario_id", "Övningsfallet saknas.")
        age_group = request.get("age_group", scenario.get("age_group", bundle["age_groups"][0]["id"]))
        if not isinstance(age_group, str) or age_group not in {row["id"] for row in bundle["age_groups"]}:
            error("age_group", "Välj en av atlasens åldersgrupper.")
            age_group = ""
        supplied = request.get("parameters", request.get("values", {}))
        if not isinstance(supplied, dict) or len(supplied) > 48:
            return {"status": "ERROR", "reason": "CASE_PARAMETERS_INVALID", "notice": "Kontrollera de inmatade parametrarna."}
        initial = scenario.get("parameters", scenario.get("values", {}))
        parameters = dict(initial) if isinstance(initial, dict) else {}
        parameters.update(supplied)
        values, missing, observed = {}, [], []
        definitions = {row["id"]: row for row in bundle["parameters"] if _applies(row, age_group)}
        for field in parameters:
            if field not in definitions:
                error(field, "Parametern finns inte för vald åldersgrupp.")
        for field, definition in definitions.items():
            value = parameters.get(field)
            if value is None or value == "":
                values[field] = None
                if definition.get("required", True):
                    missing.append(field)
                continue
            kind = definition["kind"]
            valid = True
            if kind == "number":
                if type(value) not in (int, float):
                    valid = isinstance(value, str) and bool(_NUMBER.fullmatch(value.strip()))
                    if valid:
                        value = float(value.strip().replace(",", "."))
                if type(value) not in (int, float) or not math.isfinite(value):
                    valid = False
                if valid:
                    valid = definition["min"] <= value <= definition["max"]
                if not valid:
                    error(field, "Ange ett ändligt värde inom fältets inmatningsgränser.")
            elif kind == "boolean":
                valid = type(value) is bool
                if not valid:
                    error(field, "Välj ja eller nej.")
            else:
                options = [item["value"] if isinstance(item, dict) else item for item in definition["options"]]
                valid = isinstance(value, str) and value in options
                if not valid:
                    error(field, "Välj ett av fältets alternativ.")
            values[field] = value if valid else None
            if valid:
                observed.append({"id": field, "label": definition.get("label", field),
                                 "value": value, "unit": definition.get("unit", ""), "status": "entered"})
            elif definition.get("required", True):
                missing.append(field)
        severity = request.get("severity", scenario.get("severity", "unassessed"))
        if severity == "unknown":
            severity = "unassessed"
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            error("severity", "Välj en manuell övningsnivå.")
            severity = "unassessed"
        regions = {row["id"]: row for row in bundle["regions"]}
        region_id = request.get("region_id", scenario.get("region_id", ""))
        if not isinstance(region_id, str) or (region_id and region_id not in regions):
            error("region_id", "Kroppsdelen finns inte i atlasen.")
            region_id = ""
        raw_injuries = request.get("injuries", scenario.get("injuries", []))
        injuries, markers = [], []
        if not isinstance(raw_injuries, list) or len(raw_injuries) > 24:
            error("injuries", "Välj högst 24 skadeområden.")
            raw_injuries = []
        for item in raw_injuries:
            injury = {"region_id": item, "kind": "injury"} if isinstance(item, str) else item
            if not isinstance(injury, dict) or not isinstance(injury.get("region_id"), str) or injury.get("region_id") not in regions:
                error("injuries", "Ett valt skadeområde saknas i atlasen.")
                continue
            key = injury["region_id"]
            kind = injury.get("kind", "injury")
            if not isinstance(kind, str) or kind not in _INJURY_KINDS:
                error("injuries", "Välj en av atlasens skadetyper.")
                continue
            entry = {"region_id": key, "kind": kind, "label": regions[key].get("label", key)}
            if entry not in injuries:
                injuries.append(entry)
                markers.append({**entry, "severity": severity, "x": regions[key].get("x", .5), "y": regions[key].get("y", .5)})
        topic_ids = request.get("topic_ids", [])
        if not isinstance(topic_ids, list) or len(topic_ids) > 24:
            topic_ids = []
            error("topic_ids", "Välj högst 24 ämnen.")
        topic_id = request.get("topic_id", scenario.get("topic_id", ""))
        requested_topics = [*topic_ids, *([topic_id] if topic_id else [])]
        topics = {row["id"]: row for row in bundle["topics"]}
        selected = []
        for key in requested_topics:
            if not isinstance(key, str) or key not in topics or not _applies(topics[key], age_group):
                error("topic_id", "Ämnet finns inte för vald åldersgrupp.")
            elif key not in selected:
                selected.append(key)
        selected_regions = {entry["region_id"] for entry in injuries} | ({region_id} if region_id else set())
        matched = [row for row in bundle["topics"] if _applies(row, age_group)
                   and (row["id"] in selected or selected_regions.intersection(row.get("regions", [])))]
        stale = any(row.get("stale") for row in matched)
        score = self._score(request, bundle, age_group, values, [topics[key] for key in selected], errors)
        result = {"status": "BODY_EVALUATED", "age_group": age_group, "region_id": region_id,
                "scenario_id": scenario_id, "values": values, "parameters": values, "observations": observed,
                "missing": missing, "errors": errors, "injuries": injuries, "markers": markers,
                "manual_severity": severity, "severity": severity, "selected_topics": selected,
                "matched_topics": matched, "source_stale": stale, "input_complete": not missing and not errors,
                "complete": False, "clinical_use": False, "learning_only": True,
                "notice": LEARNING_NOTICE, "model_calls": 0, "case_storage": False}
        if score is not None:
            result["score"] = score
            result["educational_score"] = score
        return result
