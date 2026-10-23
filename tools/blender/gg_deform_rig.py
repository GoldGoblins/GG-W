"""Deform-only goblin skeleton sized to moving joints, not a textbook bone count.

Rigify's generated rig adds control and mechanism bones and blows past the
engine cap of 128 joints. This list is the deformation skeleton only:
spine, neck, jaw, eyes, ears, clavicles, arms, three joints per finger,
legs, two joints per toe, and a five-bone tail. Positions are gameplay
coordinates (x, height, depth) on a figure whose tallest point is 1.
Negative depth is the front. Blender conversion is (x, depth, height).
"""

from __future__ import annotations

SCHEMA = "gg.deform.anatomy.v1"
ENGINE_JOINT_CAP = 128

_FINGERS = ("thumb", "index", "middle", "ring", "pinky")
_TOES = ("big", "index", "middle", "ring", "pinky")


def _bone(name: str, head: tuple[float, float, float], tail: tuple[float, float, float], parent: str | None, connect: bool) -> dict:
    return {
        "name": name,
        "head": (round(head[0], 5), round(head[1], 5), round(head[2], 5)),
        "tail": (round(tail[0], 5), round(tail[1], 5), round(tail[2], 5)),
        "parent": parent,
        "connect": bool(connect and parent),
    }


def _chain(names: list[str], points: list[tuple[float, float, float]], parent: str | None) -> list[dict]:
    if len(points) != len(names) + 1:
        raise ValueError("a chain needs one more point than bones")
    bones = []
    previous = parent
    for index, name in enumerate(names):
        bones.append(_bone(name, points[index], points[index + 1], previous, connect=index > 0))
        previous = name
    return bones


def _finger(side: str, finger: str, spread: float) -> list[dict]:
    sign = 1.0 if side == "L" else -1.0
    start = ((0.30 + spread * 0.018) * sign, 0.24, -0.045 - spread * 0.004)
    if finger == "thumb":
        start = (0.27 * sign, 0.27, -0.05)
    step = (0.012 * sign, -0.034, -0.012)
    points = [start]
    for _ in range(3):
        last = points[-1]
        points.append((last[0] + step[0], last[1] + step[1], last[2] + step[2]))
    names = [f"{finger}.{part}.{side}" for part in ("01", "02", "03")]
    return _chain(names, points, f"hand.{side}")


def _toe(side: str, toe: str, spread: float) -> list[dict]:
    sign = 1.0 if side == "L" else -1.0
    start = ((0.055 + spread * 0.012) * sign, 0.012, -0.10)
    step = (0.004 * sign, -0.002, -0.018)
    points = [start]
    for _ in range(2):
        last = points[-1]
        points.append((last[0] + step[0], last[1] + step[1], last[2] + step[2]))
    names = [f"toe.{toe}.{part}.{side}" for part in ("01", "02")]
    return _chain(names, points, f"ball.{side}")


def _side(side: str) -> list[dict]:
    sign = 1.0 if side == "L" else -1.0
    bones: list[dict] = []
    bones.append(_bone(
        f"eye.{side}",
        (0.07 * sign, 0.93, -0.05),
        (0.07 * sign, 0.93, -0.08),
        "head",
        False,
    ))
    bones.extend(_chain(
        [f"ear.0{index}.{side}" for index in (1, 2, 3)],
        [
            (0.10 * sign, 0.90, 0.02),
            (0.18 * sign, 0.96, 0.03),
            (0.26 * sign, 0.99, 0.04),
            (0.34 * sign, 1.00, 0.04),
        ],
        "head",
    ))
    bones.append(_bone(
        f"clavicle.{side}",
        (0.03 * sign, 0.72, 0.0),
        (0.14 * sign, 0.73, 0.0),
        "chest",
        False,
    ))
    bones.extend(_chain(
        [f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}"],
        [
            (0.14 * sign, 0.73, 0.0),
            (0.24 * sign, 0.52, 0.02),
            (0.31 * sign, 0.34, 0.0),
            (0.33 * sign, 0.24, -0.03),
        ],
        f"clavicle.{side}",
    ))
    for spread, finger in enumerate(_FINGERS):
        bones.extend(_finger(side, finger, float(spread if finger != "thumb" else 0)))
    bones.extend(_chain(
        [f"thigh.{side}", f"shin.{side}", f"foot.{side}", f"ball.{side}"],
        [
            (0.07 * sign, 0.15, 0.0),
            (0.08 * sign, 0.08, 0.01),
            (0.07 * sign, 0.03, 0.0),
            (0.07 * sign, 0.015, -0.06),
            (0.07 * sign, 0.008, -0.10),
        ],
        "hips",
    ))
    for spread, toe in enumerate(_TOES):
        bones.extend(_toe(side, toe, float(spread - 2)))
    return bones


def _center() -> list[dict]:
    bones: list[dict] = []
    bones.extend(_chain(
        ["root", "hips"],
        [(0.0, 0.0, 0.0), (0.0, 0.06, 0.0), (0.0, 0.16, 0.0)],
        None,
    ))
    bones.extend(_chain(
        ["spine.01", "spine.02", "spine.03", "spine.04"],
        [
            (0.0, 0.16, 0.01),
            (0.0, 0.30, 0.02),
            (0.0, 0.44, 0.02),
            (0.0, 0.56, 0.01),
            (0.0, 0.66, 0.0),
        ],
        "hips",
    ))
    bones.append(_bone("chest", (0.0, 0.66, 0.0), (0.0, 0.74, 0.0), "spine.04", True))
    bones.extend(_chain(
        ["neck.01", "neck.02"],
        [(0.0, 0.74, 0.0), (0.0, 0.80, 0.01), (0.0, 0.86, 0.02)],
        "chest",
    ))
    bones.append(_bone("head", (0.0, 0.86, 0.02), (0.0, 0.98, 0.02), "neck.02", True))
    bones.append(_bone("jaw", (0.0, 0.88, -0.02), (0.0, 0.86, -0.10), "head", False))
    bones.extend(_chain(
        ["tail.01", "tail.02", "tail.03", "tail.04", "tail.05"],
        [
            (0.0, 0.13, 0.05),
            (0.0, 0.11, 0.12),
            (0.0, 0.09, 0.18),
            (0.0, 0.08, 0.24),
            (0.0, 0.09, 0.30),
            (0.0, 0.12, 0.36),
        ],
        "hips",
    ))
    return bones


def deform_bones() -> list[dict]:
    """One deformation bone per moving joint. No control or mechanism bones."""
    return _center() + _side("L") + _side("R")


def anatomy_names() -> set[str]:
    return {bone["name"] for bone in deform_bones()}


def validate_deform_bones(bones: list[dict] | None = None) -> dict:
    """Parent, symmetry and cap checks. Raises ValueError when the spec is unfit."""
    rows = list(bones if bones is not None else deform_bones())
    names = [row["name"] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("duplicate deform bone name")
    if len(rows) > ENGINE_JOINT_CAP:
        raise ValueError(f"deform rig has {len(rows)} joints, cap is {ENGINE_JOINT_CAP}")
    by_name = {row["name"]: row for row in rows}
    for row in rows:
        parent = row["parent"]
        if parent is not None and parent not in by_name:
            raise ValueError(f"{row['name']} parent {parent} is missing")
        if parent == row["name"]:
            raise ValueError(f"{row['name']} parents itself")
        head, tail = row["head"], row["tail"]
        if head == tail:
            raise ValueError(f"{row['name']} has zero length")
        for point in (head, tail):
            x_coord, vertical, depth = point
            if not (-0.6 <= x_coord <= 0.6 and -0.02 <= vertical <= 1.05 and -0.5 <= depth <= 0.5):
                raise ValueError(f"{row['name']} leaves the unit figure")
    seen: set[str] = set()
    for row in rows:
        stack = []
        name = row["name"]
        while name is not None:
            if name in stack:
                raise ValueError("bone cycle at " + name)
            stack.append(name)
            name = by_name[name]["parent"]
        seen.add(row["name"])
    if len(seen) != len(rows):
        raise ValueError("bone walk missed a joint")
    for row in rows:
        if not row["name"].endswith(".L"):
            continue
        mirror_name = row["name"][:-2] + ".R"
        mirror = by_name.get(mirror_name)
        if mirror is None:
            raise ValueError("missing mirror " + mirror_name)
        for key in ("head", "tail"):
            left, right = row[key], mirror[key]
            if abs(left[0] + right[0]) > 1e-5 or abs(left[1] - right[1]) > 1e-5 or abs(left[2] - right[2]) > 1e-5:
                raise ValueError("asymmetric " + row["name"])
        parent = row["parent"]
        expected = parent[:-2] + ".R" if parent and parent.endswith(".L") else parent
        if mirror["parent"] != expected or mirror["connect"] != row["connect"]:
            raise ValueError("mirror parent mismatch " + row["name"])
    return {
        "schema": SCHEMA,
        "joints": len(rows),
        "cap": ENGINE_JOINT_CAP,
        "names": names,
    }
