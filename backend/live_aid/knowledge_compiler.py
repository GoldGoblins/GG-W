"""Typed deterministic generic-to-machine knowledge specialization.

This layer reuses the existing content-addressed Fact representation but does
not mutate FactStore, promote canonical policy, execute tools, invoke a model,
access the network, or grant action authority.

Specialized knowledge is a rebuildable derivation.  Its bundle root binds the
generic input, current machine profile, policy identity, exact specializer
source identity and specialized result identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import Fact, SCHEMA_FACT, digest_json


BINDING_SCHEMA = (
    "gg.knowledge-binding.v1"
)
MACHINE_PROFILE_SCHEMA = (
    "gg.machine-profile.v1"
)
SPECIALIZATION_REQUEST_SCHEMA = (
    "gg.knowledge-specialization-request.v1"
)
SPECIALIZATION_RESULT_SCHEMA = (
    "gg.knowledge-specialization-result.v1"
)
SPECIALIZATION_BUNDLE_SCHEMA = (
    "gg.knowledge-specialization-bundle.v1"
)

GENERIC = "GENERIC"
MACHINE = "MACHINE"

PLANES = frozenset(
    (
        GENERIC,
        MACHINE,
    )
)

STRATEGY_UNIQUE_ATTESTED_ALIAS = (
    "UNIQUE_ATTESTED_ALIAS_V1"
)

STATUSES = frozenset(
    (
        "COMPILED",
        "UNSUPPORTED",
        "AMBIGUOUS",
    )
)

_ALLOWED_KINDS_KEY = (
    "machine.registry.allowed_kinds"
)
_ROLE_EXAMPLES_KEY = (
    "machine.registry.role_examples"
)
_REJECTED_ALIASES_KEY = (
    "machine.registry.rejected_aliases"
)
_ACCEPTED_ALIASES_KEY = (
    "machine.registry.accepted_aliases"
)


class KnowledgeCompilerError(
    RuntimeError
):
    """Knowledge specialization contract violation."""


def _valid_sha256(
    value: object,
) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character
            in "0123456789abcdef"
            for character in value
        )
    )


def _require_sha256(
    value: object,
    label: str,
) -> str:
    if not _valid_sha256(value):
        raise KnowledgeCompilerError(
            label
            + "_SHA256_INVALID"
        )

    return value


def _require_fact_id(
    value: object,
) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("fact-")
        or len(value) != 69
        or any(
            character
            not in "0123456789abcdef"
            for character
            in value[5:]
        )
    ):
        raise KnowledgeCompilerError(
            "FACT_ID_FORMAT_INVALID"
        )

    return value


def _require_text(
    value: object,
    label: str,
    *,
    maximum: int = 512,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise KnowledgeCompilerError(
            label
            + "_TEXT_INVALID"
        )

    return value


def _string_set(
    value: object,
    label: str,
    *,
    allow_empty: bool,
) -> frozenset[str]:
    if not isinstance(value, list):
        raise KnowledgeCompilerError(
            label
            + "_LIST_INVALID"
        )

    result: set[str] = set()

    for item in value:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 128
        ):
            raise KnowledgeCompilerError(
                label
                + "_ITEM_INVALID"
            )

        result.add(item)

    if (
        not allow_empty
        and not result
    ):
        raise KnowledgeCompilerError(
            label
            + "_EMPTY"
        )

    return frozenset(result)


@dataclass(frozen=True)
class KnowledgeBinding:
    plane: str
    fact_id: str
    fact_payload: dict[str, Any]

    @classmethod
    def from_fact(
        cls,
        fact: Fact,
        *,
        plane: str,
    ) -> "KnowledgeBinding":
        if not isinstance(fact, Fact):
            raise KnowledgeCompilerError(
                "FACT_TYPE_INVALID"
            )

        binding = cls(
            plane=plane,
            fact_id=fact.fact_id,
            fact_payload=fact.as_dict(),
        )

        binding.validate()

        return binding

    def validate(
        self,
    ) -> None:
        if self.plane not in PLANES:
            raise KnowledgeCompilerError(
                "KNOWLEDGE_PLANE_INVALID"
            )

        _require_fact_id(
            self.fact_id
        )

        if not isinstance(
            self.fact_payload,
            dict,
        ):
            raise KnowledgeCompilerError(
                "FACT_PAYLOAD_INVALID"
            )

        if (
            self.fact_payload.get(
                "schema"
            )
            != SCHEMA_FACT
        ):
            raise KnowledgeCompilerError(
                "FACT_SCHEMA_INVALID"
            )

        if (
            "fact-"
            + digest_json(
                self.fact_payload
            )
            != self.fact_id
        ):
            raise KnowledgeCompilerError(
                "FACT_ID_BINDING_MISMATCH"
            )

        _require_text(
            self.fact_payload.get("key"),
            "FACT_KEY",
            maximum=256,
        )

        if not isinstance(
            self.fact_payload.get("value"),
            dict,
        ):
            raise KnowledgeCompilerError(
                "FACT_VALUE_INVALID"
            )

    @property
    def key(
        self,
    ) -> str:
        self.validate()
        return self.fact_payload["key"]

    @property
    def value(
        self,
    ) -> dict[str, Any]:
        self.validate()
        return dict(
            self.fact_payload["value"]
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        self.validate()

        return {
            "schema":
                BINDING_SCHEMA,
            "plane":
                self.plane,
            "fact_id":
                self.fact_id,
            "fact_payload":
                dict(
                    self.fact_payload
                ),
        }

    def binding_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class MachineProfile:
    profile_id: str
    state_base_revision: str
    bindings: tuple[
        KnowledgeBinding,
        ...
    ]

    def validate(
        self,
    ) -> None:
        _require_text(
            self.profile_id,
            "PROFILE_ID",
            maximum=256,
        )

        _require_text(
            self.state_base_revision,
            "STATE_BASE_REVISION",
            maximum=256,
        )

        if not self.bindings:
            raise KnowledgeCompilerError(
                "MACHINE_PROFILE_EMPTY"
            )

        fact_ids: list[str] = []

        for binding in self.bindings:
            if not isinstance(
                binding,
                KnowledgeBinding,
            ):
                raise KnowledgeCompilerError(
                    "MACHINE_BINDING_TYPE_INVALID"
                )

            binding.validate()

            if binding.plane != MACHINE:
                raise KnowledgeCompilerError(
                    "NON_MACHINE_FACT_IN_PROFILE"
                )

            fact_ids.append(
                binding.fact_id
            )

        if len(set(fact_ids)) != len(
            fact_ids
        ):
            raise KnowledgeCompilerError(
                "MACHINE_PROFILE_DUPLICATE_FACT"
            )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        self.validate()

        ordered = sorted(
            (
                binding.as_dict()
                for binding
                in self.bindings
            ),
            key=lambda item: item[
                "fact_id"
            ],
        )

        return {
            "schema":
                MACHINE_PROFILE_SCHEMA,
            "profile_id":
                self.profile_id,
            "state_base_revision":
                self.state_base_revision,
            "bindings":
                ordered,
        }

    def profile_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SpecializationRequest:
    generic: KnowledgeBinding
    machine_profile: MachineProfile
    policy_sha256: str
    specializer_content_sha256: str
    strategy: str = (
        STRATEGY_UNIQUE_ATTESTED_ALIAS
    )

    def validate(
        self,
    ) -> None:
        if not isinstance(
            self.generic,
            KnowledgeBinding,
        ):
            raise KnowledgeCompilerError(
                "GENERIC_BINDING_TYPE_INVALID"
            )

        self.generic.validate()

        if self.generic.plane != GENERIC:
            raise KnowledgeCompilerError(
                "GENERIC_PLANE_REQUIRED"
            )

        if not isinstance(
            self.machine_profile,
            MachineProfile,
        ):
            raise KnowledgeCompilerError(
                "MACHINE_PROFILE_TYPE_INVALID"
            )

        self.machine_profile.validate()

        _require_sha256(
            self.policy_sha256,
            "POLICY",
        )

        _require_sha256(
            self.specializer_content_sha256,
            "SPECIALIZER_CONTENT",
        )

        if (
            self.strategy
            != STRATEGY_UNIQUE_ATTESTED_ALIAS
        ):
            raise KnowledgeCompilerError(
                "SPECIALIZATION_STRATEGY_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        self.validate()

        return {
            "schema":
                SPECIALIZATION_REQUEST_SCHEMA,
            "generic_binding_sha256":
                self.generic.binding_sha256(),
            "machine_profile_sha256":
                self.machine_profile
                .profile_sha256(),
            "policy_sha256":
                self.policy_sha256,
            "specializer_content_sha256":
                self.specializer_content_sha256,
            "strategy":
                self.strategy,
        }

    def request_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SpecializationResult:
    status: str
    semantic_role: str
    specialized_value: str
    request_sha256: str
    generic_identity_sha256: str
    machine_profile_sha256: str
    policy_sha256: str
    specializer_content_sha256: str
    specialized_result_sha256: str
    bundle_root_sha256: str
    input_fact_ids: tuple[str, ...]
    limitation: str
    action_authority: str = "NONE"
    promotion_authority: str = "NONE"
    canonical_policy_change: bool = False
    persistent_write: str = "NONE"
    model_inference: bool = False

    @property
    def compiled(
        self,
    ) -> bool:
        return (
            self.status == "COMPILED"
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                SPECIALIZATION_RESULT_SCHEMA,
            "status":
                self.status,
            "semantic_role":
                self.semantic_role,
            "specialized_value":
                self.specialized_value,
            "request_sha256":
                self.request_sha256,
            "generic_identity_sha256":
                self.generic_identity_sha256,
            "machine_profile_sha256":
                self.machine_profile_sha256,
            "policy_sha256":
                self.policy_sha256,
            "specializer_content_sha256":
                self.specializer_content_sha256,
            "specialized_result_sha256":
                self.specialized_result_sha256,
            "bundle_root_sha256":
                self.bundle_root_sha256,
            "input_fact_ids":
                list(
                    self.input_fact_ids
                ),
            "limitation":
                self.limitation,
            "action_authority":
                self.action_authority,
            "promotion_authority":
                self.promotion_authority,
            "canonical_policy_change":
                self.canonical_policy_change,
            "persistent_write":
                self.persistent_write,
            "model_inference":
                self.model_inference,
        }


def _machine_fact(
    profile: MachineProfile,
    key: str,
) -> KnowledgeBinding:
    matches = [
        binding
        for binding in profile.bindings
        if binding.key == key
    ]

    if len(matches) != 1:
        raise KnowledgeCompilerError(
            "MACHINE_FACT_CARDINALITY:"
            + key
            + ":"
            + str(len(matches))
        )

    return matches[0]


def _role_values(
    binding: KnowledgeBinding,
    *,
    expected_role: str,
    label: str,
    allow_empty: bool,
) -> frozenset[str]:
    value = binding.value

    role = value.get(
        "semantic_role"
    )

    if role != expected_role:
        raise KnowledgeCompilerError(
            label
            + "_ROLE_MISMATCH"
        )

    return _string_set(
        value.get("values"),
        label,
        allow_empty=allow_empty,
    )


def _result_core(
    *,
    status: str,
    semantic_role: str,
    specialized_value: str,
    request: SpecializationRequest,
    input_fact_ids: tuple[str, ...],
    limitation: str,
) -> dict[str, Any]:
    return {
        "schema":
            SPECIALIZATION_RESULT_SCHEMA,
        "status":
            status,
        "semantic_role":
            semantic_role,
        "specialized_value":
            specialized_value,
        "request_sha256":
            request.request_sha256(),
        "generic_identity_sha256":
            request.generic
            .binding_sha256(),
        "machine_profile_sha256":
            request.machine_profile
            .profile_sha256(),
        "policy_sha256":
            request.policy_sha256,
        "specializer_content_sha256":
            request.specializer_content_sha256,
        "input_fact_ids":
            list(
                input_fact_ids
            ),
        "limitation":
            limitation,
        "action_authority":
            "NONE",
        "promotion_authority":
            "NONE",
        "canonical_policy_change":
            False,
        "persistent_write":
            "NONE",
        "model_inference":
            False,
    }


def compile_specialization(
    request: SpecializationRequest,
) -> SpecializationResult:
    request.validate()

    generic_value = (
        request.generic.value
    )

    semantic_role = (
        generic_value.get(
            "semantic_role"
        )
    )

    _require_text(
        semantic_role,
        "GENERIC_SEMANTIC_ROLE",
        maximum=128,
    )

    aliases = _string_set(
        generic_value.get(
            "candidate_aliases"
        ),
        "GENERIC_ALIAS",
        allow_empty=False,
    )

    allowed_binding = _machine_fact(
        request.machine_profile,
        _ALLOWED_KINDS_KEY,
    )

    allowed = _string_set(
        allowed_binding.value.get(
            "values"
        ),
        "MACHINE_ALLOWED_KIND",
        allow_empty=False,
    )

    examples_binding = _machine_fact(
        request.machine_profile,
        _ROLE_EXAMPLES_KEY,
    )

    examples = _role_values(
        examples_binding,
        expected_role=semantic_role,
        label="MACHINE_ROLE_EXAMPLE",
        allow_empty=False,
    )

    rejected_binding = _machine_fact(
        request.machine_profile,
        _REJECTED_ALIASES_KEY,
    )

    rejected = _role_values(
        rejected_binding,
        expected_role=semantic_role,
        label="MACHINE_REJECTED_ALIAS",
        allow_empty=True,
    )

    accepted_binding = _machine_fact(
        request.machine_profile,
        _ACCEPTED_ALIASES_KEY,
    )

    accepted = _role_values(
        accepted_binding,
        expected_role=semantic_role,
        label="MACHINE_ACCEPTED_ALIAS",
        allow_empty=False,
    )

    viable = sorted(
        (
            aliases
            & allowed
            & examples
            & accepted
        )
        - rejected
    )

    if len(viable) == 1:
        status = "COMPILED"
        specialized_value = viable[0]

    elif not viable:
        status = "UNSUPPORTED"
        specialized_value = ""

    else:
        status = "AMBIGUOUS"
        specialized_value = ""

    if status not in STATUSES:
        raise KnowledgeCompilerError(
            "SPECIALIZATION_STATUS_INVALID"
        )

    input_fact_ids = tuple(
        sorted(
            (
                request.generic.fact_id,
                *(
                    binding.fact_id
                    for binding
                    in request.machine_profile
                    .bindings
                ),
            )
        )
    )

    limitation = (
        "Derived only from the bound generic aliases "
        "and machine-attested allowed, role-example, "
        "rejected and accepted values. This result is "
        "rebuildable derived knowledge, not canonical "
        "policy and not action authority."
    )

    core = _result_core(
        status=status,
        semantic_role=semantic_role,
        specialized_value=(
            specialized_value
        ),
        request=request,
        input_fact_ids=(
            input_fact_ids
        ),
        limitation=limitation,
    )

    result_sha256 = digest_json(
        core
    )

    bundle_root_sha256 = digest_json(
        {
            "schema":
                SPECIALIZATION_BUNDLE_SCHEMA,
            "generic_identity_sha256":
                request.generic
                .binding_sha256(),
            "machine_profile_sha256":
                request.machine_profile
                .profile_sha256(),
            "policy_sha256":
                request.policy_sha256,
            "specializer_content_sha256":
                request.specializer_content_sha256,
            "specialized_result_sha256":
                result_sha256,
        }
    )

    return SpecializationResult(
        status=status,
        semantic_role=semantic_role,
        specialized_value=(
            specialized_value
        ),
        request_sha256=(
            request.request_sha256()
        ),
        generic_identity_sha256=(
            request.generic
            .binding_sha256()
        ),
        machine_profile_sha256=(
            request.machine_profile
            .profile_sha256()
        ),
        policy_sha256=(
            request.policy_sha256
        ),
        specializer_content_sha256=(
            request
            .specializer_content_sha256
        ),
        specialized_result_sha256=(
            result_sha256
        ),
        bundle_root_sha256=(
            bundle_root_sha256
        ),
        input_fact_ids=(
            input_fact_ids
        ),
        limitation=limitation,
    )
