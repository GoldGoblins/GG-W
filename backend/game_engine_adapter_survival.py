"""Actual liquid contact and canonical damage behind original mirror timers.

Mirror drain/refill event shapes follow GgEngine's retained protocol. Damage
rates are an explicit GG local policy; meshes contain no server damage numbers.
Fatigue needs an original-world deep-water provider flag, which the current
streaming provider does not export. GG seas never imply it.
"""
import copy
import math
from backend import game_engine_combat as combat

BREATH_SECONDS = 60.
FATIGUE_SECONDS = 60.
DAMAGE_INTERVAL = 2.
MAX_DAMAGE_TICKS = 4
MAX_ELAPSED_SECONDS = 120.
BODY_HALF_HEIGHT = .65
HAZARD_FRACTIONS = {"MAGMA": .20, "LAVA": .20, "SLIME": .10}
LUA_TIMER_KINDS = {"BREATH": "BREATH", "FATIGUE": "EXHAUSTION"}


class SurvivalMixin:
    def _reset_survival_locked(self):
        self._survival = dict(breath_s=BREATH_SECONDS, submerged=False,
                              next_damage=0., breath_rate=0,
                              fatigue_s=FATIGUE_SECONDS, fatigued=False,
                              next_fatigue_damage=0., fatigue_rate=0,
                              fatigue_supported=False, hazard="", next_hazard_damage=0.)

    def _survival_save_locked(self):
        # Contact, event edges and damage deadlines are transient. Loading a
        # balance must not replay elapsed damage from an earlier process.
        return dict(breath_s=self._survival["breath_s"], fatigue_s=self._survival["fatigue_s"])

    def _restore_survival_locked(self, value):
        self._reset_survival_locked()
        if isinstance(value, dict):
            for key, maximum in (("breath_s", BREATH_SECONDS), ("fatigue_s", FATIGUE_SECONDS)):
                balance = value.get(key, maximum)
                if type(balance) in (int, float) and math.isfinite(balance) and 0 <= balance <= maximum:
                    self._survival[key] = float(balance)

    def _survival_timer_edge_locked(self, kind, rate):
        state = self._survival; prefix = kind.lower(); key = prefix + "_rate"
        if state[key] == rate:
            return
        state[key] = rate
        if rate:
            self._spell_event_locked("MIRROR_TIMER_START", LUA_TIMER_KINDS[kind], round(state[prefix + "_s"] * 1000),
                                      60000, rate, 0, kind.title())
        else:
            self._spell_event_locked("MIRROR_TIMER_STOP", LUA_TIMER_KINDS[kind])

    def _suspend_survival_locked(self):
        """A lazy/temporarily absent actor has no environmental health target."""
        for kind in ("BREATH", "FATIGUE"):
            self._survival_timer_edge_locked(kind, 0)
        self._survival.update(submerged=False, fatigued=False, fatigue_supported=False,
                              hazard="", next_damage=0., next_fatigue_damage=0., next_hazard_damage=0.)

    def _stop_survival_locked(self):
        for kind in ("BREATH", "FATIGUE"):
            self._survival_timer_edge_locked(kind, 0)
        self._reset_survival_locked()

    def _survival_balance_locked(self, kind, draining, elapsed, start):
        state = self._survival; prefix = kind.lower(); balance_key = prefix + "_s"
        deadline_key = "next_damage" if kind == "BREATH" else "next_fatigue_damage"
        maximum = BREATH_SECONDS if kind == "BREATH" else FATIGUE_SECONDS
        before = state[balance_key]
        if draining:
            self._survival_timer_edge_locked(kind, -1)
            state[balance_key] = max(0., before - elapsed)
            if before > 0 and state[balance_key] == 0:
                state[deadline_key] = start + before + DAMAGE_INTERVAL
            elif state[balance_key] == 0 and not state[deadline_key]:
                state[deadline_key] = start + DAMAGE_INTERVAL
        else:
            state[deadline_key] = 0.
            if before < maximum:
                self._survival_timer_edge_locked(kind, 10)
                state[balance_key] = min(maximum, before + elapsed * 10.)
            if state[balance_key] >= maximum:
                self._survival_timer_edge_locked(kind, 0)

    def _survival_damage_locked(self, deadline_key, fraction, status, budget):
        state = self._survival; actor = self._combat_state.get("actors", {}).get("player")
        if not isinstance(actor, dict):
            return budget
        now = self._sim_time
        while (budget and state[deadline_key] and state[deadline_key] <= now + 1e-8
               and actor.get("alive", True)):
            due = state[deadline_key]; state[deadline_key] = due + DAMAGE_INTERVAL; budget -= 1
            attacker = "environment:" + status.lower()
            damage = max(1., actor.get("max_health", 100) * fraction)
            dealt, absorbed = combat.deal_damage(self._combat_state, actor, damage, attacker, due)
            self._combat_state["revision"] += 1
            self._last_combat = dict(kind="ENVIRONMENT_DAMAGE", status=status, damage=dealt,
                                    absorbed=absorbed, defender_id="player", attacker_id=attacker,
                                    time_s=due, defeated=not actor.get("alive", True),
                                    policy="GG_AUTHORED_SURVIVAL_POLICY")
            self._append_event_locked("ENVIRONMENT_DAMAGE", status.title(), actor_id=attacker,
                                      target_id="player", payload=copy.deepcopy(self._last_combat))
            if not actor.get("alive", True):
                self._stop_survival_locked()
                self._tick_lifecycle_locked()  # Existing durable corpse/gear/cast lifecycle.
                return 0
        if state[deadline_key] and state[deadline_key] <= now + 1e-8:
            # Bound all hazards to four pulses total; discard a stalled update's
            # old backlog instead of replaying it on later frames.
            state[deadline_key] = now + DAMAGE_INTERVAL
        return budget

    def _tick_survival_locked(self, dt):
        if type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0:
            return
        elapsed = min(float(dt), MAX_ELAPSED_SECONDS)
        actor = self._combat_state.get("actors", {}).get("player")
        if not isinstance(actor, dict):
            self._suspend_survival_locked()
            return
        if (not actor.get("alive", True) or self._is_ghost_locked()
                or self._vehicle_kind != "NONE"):
            self._stop_survival_locked()  # Retain the existing local vehicle rider protection.
            return
        state = self._survival; start = max(0., self._sim_time - elapsed)
        sample = self._water_sample_locked(self._x[0], self._z[0])
        height = sample.get("height_m") if isinstance(sample, dict) else None
        valid = type(height) in (int, float) and math.isfinite(height)
        kind = str(sample.get("body_kind", "WATER")).upper() if isinstance(sample, dict) else "NONE"
        model = sample.get("surface_model", "") if isinstance(sample, dict) else ""
        volume = valid and model == "GG_ENGINE_FLOODED_VOLUME" and height > 1e30
        valid = valid and (abs(height) <= 1000000. or volume)
        surface = valid and (sample.get("has_surface", True) is True or volume) and kind != "NONE"
        body_contact = surface and (volume or self._y[0] - BODY_HALF_HEIGHT < height)
        submerged = surface and kind not in HAZARD_FRACTIONS and (volume or self._y[0] + BODY_HALF_HEIGHT < height)
        # The optional flag is accepted only from an original-world provider.
        # Ocean kind, visual depth and GG sea never imply fatigue.
        flag = sample.get("deep_water_fatigue") if isinstance(sample, dict) else None
        supported = (getattr(self, "_engine_world", None) is not None
                     and model == "GG_ENGINE_WET_GRID" and type(flag) is bool)
        fatigued = bool(supported and flag and body_contact and kind not in HAZARD_FRACTIONS)
        state.update(submerged=bool(submerged), fatigued=fatigued, fatigue_supported=supported)
        self._survival_balance_locked("BREATH", submerged, elapsed, start)
        self._survival_balance_locked("FATIGUE", fatigued, elapsed, start)
        hazard = kind if body_contact and kind in HAZARD_FRACTIONS else ""
        if hazard != state["hazard"]:
            state.update(hazard=hazard, next_hazard_damage=start + DAMAGE_INTERVAL if hazard else 0.)
        budget = MAX_DAMAGE_TICKS
        if submerged and state["breath_s"] <= 0:
            budget = self._survival_damage_locked("next_damage", .10, "DROWNING", budget)
        if self._combat_state.get("actors", {}).get("player", {}).get("alive", False) and fatigued and state["fatigue_s"] <= 0:
            budget = self._survival_damage_locked("next_fatigue_damage", .10, "FATIGUE", budget)
        if self._combat_state.get("actors", {}).get("player", {}).get("alive", False) and hazard:
            self._survival_damage_locked("next_hazard_damage", HAZARD_FRACTIONS[hazard],
                                          "LAVA" if hazard in ("MAGMA", "LAVA") else "SLIME", budget)

    def _survival_view_locked(self):
        state = self._survival; timers = []
        for kind in ("BREATH", "FATIGUE"):
            prefix = kind.lower()
            if state[prefix + "_rate"]:
                timers.append(dict(kind=LUA_TIMER_KINDS[kind], remaining_ms=round(state[prefix + "_s"] * 1000),
                                   max_ms=60000, scale=state[prefix + "_rate"], label=kind.title()))
        return dict(breath_s=round(state["breath_s"], 3), max_breath_s=BREATH_SECONDS,
                    submerged=state["submerged"], drowning=state["submerged"] and state["breath_s"] <= 0.,
                    fatigue_s=round(state["fatigue_s"], 3), max_fatigue_s=FATIGUE_SECONDS,
                    fatigued=state["fatigued"], fatigue_supported=state["fatigue_supported"],
                    hazard=state["hazard"], mirror_timers=timers, policy="GG_AUTHORED_SURVIVAL_POLICY")
