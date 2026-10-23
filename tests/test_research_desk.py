"""Contract tests for the local Research Desk index and safety boundary."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend import research_desk


previous_root = research_desk.ROOT
with tempfile.TemporaryDirectory() as directory:
    research_desk.ROOT = Path(directory)
    try:
        assert research_desk.snapshot()["project_id"] == "project-gg-ai-desktop"
        task = research_desk.add_task("Viewport review", "Compare render windows")
        assert task["status"] == "TASK_CREATED"
        assert research_desk.promote_task(task["task_id"])["mode"] == "SHIP"

        source = research_desk.ingest_source(
            {"title": "Map note", "content": "Viewport and provenance", "remember": False}
        )
        assert source["status"] == "SOURCE_INGESTED"
        assert research_desk.add_evidence(
            {"title": "Bounded map", "claim": "The render window is capped."}
        )["status"] == "EVIDENCE_RECORDED"
        assert research_desk.add_method(
            {"name": "Map review", "trigger": "viewport", "steps": ["sample", "compare"]}
        )["status"] == "METHOD_RECORDED"

        skill = research_desk.add_web_skill(
            {
                "name": "Replay shape",
                "template": "page + evidence",
                "script": "await page.goto(url); // evidence",
                "verify": True,
            }
        )
        assert skill["status"] == "WEB_SKILL_VERIFIED"
        preview = research_desk.sql_preview("WITH x AS (SELECT * FROM sources) SELECT * FROM x")
        assert preview["executed"] is False
        assert preview["ctes"] == ["x"]
        plan = research_desk.adaptive_execution_plan("research compare and test")
        assert plan["free_agent_brain"] is False
        assert plan["loops"] <= 3
    finally:
        research_desk.ROOT = previous_root

print("RESEARCH_DESK_CONTRACT_TEST=PASS")
