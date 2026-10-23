#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools" / "blender"))
sys.path.insert(0, str(PROJECT))

from gg_deform_rig import ENGINE_JOINT_CAP, anatomy_names, deform_bones, validate_deform_bones  # noqa: E402


def main() -> int:
    info = validate_deform_bones(deform_bones())
    if info["joints"] != 90:
        raise AssertionError("expected 90 deform joints, got " + str(info["joints"]))
    if info["joints"] > ENGINE_JOINT_CAP:
        raise AssertionError("deform rig exceeds the engine joint cap")
    names = anatomy_names()
    if sum(1 for name in names if name.startswith("spine.")) != 4:
        raise AssertionError("spine")
    if sum(1 for name in names if name.split(".")[0] in {"thumb", "index", "middle", "ring", "pinky"}) != 30:
        raise AssertionError("fingers")
    if sum(1 for name in names if name.startswith("toe.")) != 20:
        raise AssertionError("toes")
    if sum(1 for name in names if name.startswith("ear.")) != 6:
        raise AssertionError("ears")
    if sum(1 for name in names if name.startswith("tail.")) != 5:
        raise AssertionError("tail")
    for required in ("jaw", "clavicle.L", "clavicle.R", "neck.01", "neck.02", "eye.L", "eye.R"):
        if required not in names:
            raise AssertionError("missing " + required)

    from backend.blender_contract import blender_bin

    binary = blender_bin()
    if not binary:
        print("BLENDER_OBSERVE_SPEC=PASS")
        print("BLENDER_OBSERVE_SCENE=SKIP")
        return 0
    scene = PROJECT / "tests" / "blender_observe_scene.py"
    proc = subprocess.run(
        [binary, "--background", "--factory-startup", "--python", str(scene)],
        cwd=str(PROJECT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if "OBSERVE_SELFTEST=PASS" not in output:
        tail = output[-4000:]
        raise AssertionError("blender observe scene failed\n" + tail)
    print("BLENDER_OBSERVE_SPEC=PASS")
    print("BLENDER_OBSERVE_SCENE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
