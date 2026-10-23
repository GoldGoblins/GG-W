"""Real local Ghidra function and decompile jobs feeding the shared context API."""
import subprocess
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import research_jobs, research_learning
from backend import game_workflow_common as common, game_workflow_context as context


def main():
    with tempfile.TemporaryDirectory(prefix="gg-game-context-engine-") as temporary:
        root = Path(temporary)
        research_jobs.ROOT = root / "jobs"
        common.ROOT = root / "workflows"
        source, binary = root / "fixture.c", root / "fixture"
        source.write_text("__attribute__((noinline)) int gg_game_add(int value) { return value + 7; }\nint main(void) { return gg_game_add(0); }\n")
        subprocess.run(["gcc", "-O0", "-g", "-o", str(binary), str(source)], check=True, capture_output=True, timeout=20)
        for operation in ("function", "decompile"):
            state = research_learning._wait(research_jobs.start(str(binary), operation, "gg_game_add"))
            assert state["status"] == "COMPLETE", state.get("reason")
        value = context.from_job(state["job_id"])["context"]
        assert value["provenance"] == "LOCAL_ENGINE_STATIC_OBSERVATION"
        assert "gg_game_add" in value["function"]["name"]
        assert "+ 7" in value["function"]["pseudocode"]
        assert len(value["sources"]) == 2
        binary.write_bytes(binary.read_bytes() + b"modified")
        try:
            context.from_job(state["job_id"])
        except ValueError as exc:
            assert str(exc) == "ARTIFACT_CHANGED_RERUN_ANALYSIS"
        else:
            raise AssertionError("stale Ghidra job was accepted")
    print("GAME_WORKFLOWS_GHIDRA_CONTEXT=PASS")


if __name__ == "__main__":
    main()
