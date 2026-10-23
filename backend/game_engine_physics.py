"""Bounded energy bookkeeping for the local GAME ENGINE.

This module takes the useful engineering part of the proposed TSEU idea:
tagged energy sectors can be summed and converted to a mass-equivalent with
``E / c_game**2``.  It is deliberately *not* a claim that the preview has a
general-relativistic mass integral, a unified field theory or a gravity solver.
The game uses an explicit dimensionless ``c_game`` so the accounting stays
stable and cheap; charge remains a separate Noether-like gameplay channel.

The log/exp helpers are kept here because they are useful for arbitrary
positive roots, inverse powers and dimension-agnostic norms.  The p=2 norm
keeps a direct ``sqrt`` fast path for the fixed-step hot path.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


SCHEMA = "gg.game-engine.physics.v1"
MODEL = "TSEU_INSPIRED_BOOKKEEPING"
DEFAULT_GAME_LIGHT_SPEED = 64.0
MAX_SECTORS = 16
MAX_VECTOR_DIMENSIONS = 16


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _require_finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _positive_degree(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("root degree must be a positive integer") from exc
    if not math.isfinite(number) or number < 1.0 or number != math.floor(number):
        raise ValueError("root degree must be a positive integer")
    return int(number)


def real_nth_root(value: Any, degree: Any) -> float:
    """Return the real n-th root using the positive-domain log/exp identity.

    Positive values follow ``exp(log(x) / n)``.  A negative value is accepted
    only for an odd integer degree, where the real signed root exists.  Zero
    is handled explicitly because ``log(0)`` is undefined.
    """
    number = _require_finite(value, "root value")
    root_degree = _positive_degree(degree)
    if number == 0.0:
        return 0.0
    if number < 0.0 and root_degree % 2 == 0:
        raise ValueError("even root of a negative value is not real")
    magnitude = abs(number)
    if root_degree == 1:
        result = magnitude
    else:
        result = math.exp(math.log(magnitude) / float(root_degree))
    return math.copysign(result, number)


def log_power(base: Any, exponent: Any) -> float:
    """Compute ``base**exponent`` as ``exp(log(base) * exponent)``.

    The real-valued form is intentionally restricted to a positive base.
    Callers that need integer powers in a hot loop should use ordinary
    multiplication or ``pow`` instead.
    """
    safe_base = _require_finite(base, "log-power base")
    safe_exponent = _require_finite(exponent, "log-power exponent")
    if safe_base <= 0.0:
        raise ValueError("log-power base must be positive")
    if safe_exponent == 0.0 or safe_base == 1.0:
        return 1.0
    return math.exp(math.log(safe_base) * safe_exponent)


def log_base(value: Any, base: Any) -> float:
    """Return ``log_base(value)`` through ``ln(value) / ln(base)``."""
    safe_value = _require_finite(value, "logarithm value")
    safe_base = _require_finite(base, "logarithm base")
    if safe_value <= 0.0:
        raise ValueError("logarithm value must be positive")
    if safe_base <= 0.0 or safe_base == 1.0:
        raise ValueError("logarithm base must be positive and not one")
    return math.log(safe_value) / math.log(safe_base)


def lp_norm(values: Iterable[Any], degree: Any = 2) -> float:
    """Return a bounded real L-p norm for any small positive integer degree."""
    root_degree = _positive_degree(degree)
    numbers: list[float] = []
    for value in values:
        if len(numbers) >= MAX_VECTOR_DIMENSIONS:
            raise ValueError("vector dimension exceeds the bounded physics limit")
        numbers.append(abs(_finite(value)))
    if not numbers:
        return 0.0
    maximum = max(numbers)
    if maximum == 0.0:
        return 0.0
    normalized_power = sum(
        (number / maximum) ** root_degree
        for number in numbers
    )
    root = (
        math.sqrt(normalized_power)
        if root_degree == 2
        else real_nth_root(normalized_power, root_degree)
    )
    return maximum * root


def mass_from_total_energy(
    total_energy: Any,
    *,
    c_game: Any = DEFAULT_GAME_LIGHT_SPEED,
) -> float:
    """Convert game-energy into a mass-equivalent with an explicit c value."""
    energy = _require_finite(total_energy, "total energy")
    light_speed = _require_finite(c_game, "c_game")
    if light_speed <= 0.0:
        raise ValueError("c_game must be positive")
    return energy / (light_speed * light_speed)


def _sector_name(value: Any) -> str:
    raw = str(value or "").strip().upper()
    safe = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in raw
    )
    return safe[:32]


def build_energy_ledger(
    sectors: Mapping[str, Any] | None,
    *,
    charge: Any = 0.0,
    c_game: Any = DEFAULT_GAME_LIGHT_SPEED,
) -> dict[str, Any]:
    """Sum a bounded, extensible set of tagged energy sectors.

    Unknown sector names are retained up to ``MAX_SECTORS`` so a future field
    can be added without changing this function's shape.  Negative terms are
    allowed because binding/potential contributions may be signed; the local
    gameplay mass used as a source is clamped at zero in the returned view.
    """
    if not isinstance(sectors, Mapping):
        sectors = {}
    values: dict[str, float] = {}
    for raw_name, raw_value in sectors.items():
        name = _sector_name(raw_name)
        if not name:
            continue
        if name not in values and len(values) >= MAX_SECTORS:
            break
        values[name] = values.get(name, 0.0) + _finite(raw_value)
    total_energy = sum(values.values())
    mass_equivalent = mass_from_total_energy(total_energy, c_game=c_game)
    safe_charge = _finite(charge)
    return {
        "schema": SCHEMA,
        "model": MODEL,
        "components": {
            key: round(value, 6)
            for key, value in sorted(values.items())
        },
        "component_count": len(values),
        "total_energy": round(total_energy, 6),
        "mass_equivalent": round(mass_equivalent, 6),
        "simulation_mass": round(max(0.0, mass_equivalent), 6),
        "c_game": round(_finite(c_game, DEFAULT_GAME_LIGHT_SPEED), 6),
        "charge": round(safe_charge, 6),
        "charge_channel": "SEPARATE_U1_LIKE_GAMEPLAY_VALUE",
        "gravity_status": "NOT_CONNECTED",
        "gravity_source": "ENERGY_LEDGER_ONLY",
        "vacuum_policy": "EXCLUDED_UNLESS_EXPLICIT",
    }


def build_runtime_view(
    *,
    speed: Any,
    movement_mode: str,
    active_entities: Any,
    active_particles: Any,
    resource: Any,
) -> dict[str, Any]:
    """Build the player-facing energy view without changing movement physics."""
    safe_speed = max(0.0, _finite(speed))
    c_game = DEFAULT_GAME_LIGHT_SPEED
    base_mass = 1.0
    rest_energy = base_mass * c_game * c_game
    kinetic_energy = 0.5 * base_mass * safe_speed * safe_speed
    ledger = build_energy_ledger(
        {
            "REST": rest_energy,
            "KINETIC": kinetic_energy,
        },
        c_game=c_game,
    )
    ledger.update(
        {
            "scope": "LOCAL_GAME_SIMULATION_NOT_GENERAL_RELATIVITY",
            "definition": "MASS_EQUIVALENT = SUM_TAGGED_ENERGY / C_GAME_SQUARED",
            "t00_note": "BOOKKEEPING_TOTAL; NO_COORDINATE_INVARIANT_GR_MASS_CLAIM",
            "movement_mode": str(movement_mode or "GROUND"),
            "speed": round(safe_speed, 6),
            "resource": round(max(0.0, _finite(resource)), 6),
            "active_entities": max(0, int(_finite(active_entities))),
            "active_particles": max(0, int(_finite(active_particles))),
            "norm": "EUCLIDEAN_L2_FAST_PATH",
        }
    )
    return ledger
