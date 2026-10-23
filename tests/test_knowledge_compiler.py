from __future__ import annotations

from dataclasses import replace
import hashlib
import sys
import unittest
from pathlib import Path


PROJECT = Path(
    __file__
).resolve().parents[1]

BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

from live_aid.contract import Fact  # noqa: E402
from live_aid import knowledge_compiler as K  # noqa: E402


SPECIALIZER_SHA = "a" * 64
POLICY_SHA = "b" * 64
STATE_BASE = "c" * 40


def fact(
    key: str,
    value: dict,
    *,
    scope: str,
) -> Fact:
    source_sha = hashlib.sha256(
        (
            key
            + scope
        ).encode("utf-8")
    ).hexdigest()

    return Fact(
        key=key,
        value=value,
        epistemic_class=(
            "OBSERVED_CONTENT_BOUND"
        ),
        source_kind="KGC3A_TEST",
        source_id=(
            "kgc3a://"
            + key
        ),
        source_sha256=source_sha,
        scope=scope,
        freshness=(
            "REFRESH_BEFORE_DECISION_CRITICAL_USE"
        ),
    )


def generic_binding(
    aliases: list[str] | None = None,
) -> K.KnowledgeBinding:
    aliases = (
        ["VERIFY", "VERIFIER"]
        if aliases is None
        else aliases
    )

    item = fact(
        "generic.capability.verification-kind",
        {
            "semantic_role":
                "VERIFICATION",
            "candidate_aliases":
                aliases,
        },
        scope="GENERIC_CAPABILITY_CONCEPT",
    )

    return K.KnowledgeBinding.from_fact(
        item,
        plane=K.GENERIC,
    )


def machine_binding(
    key: str,
    value: dict,
) -> K.KnowledgeBinding:
    item = fact(
        key,
        value,
        scope=(
            "MACHINE_GG_PROJECT@"
            + STATE_BASE
        ),
    )

    return K.KnowledgeBinding.from_fact(
        item,
        plane=K.MACHINE,
    )


def profile(
    *,
    allowed: list[str] | None = None,
    examples: list[str] | None = None,
    rejected: list[str] | None = None,
    accepted: list[str] | None = None,
) -> K.MachineProfile:
    return K.MachineProfile(
        profile_id="gg.project.registry",
        state_base_revision=(
            STATE_BASE
        ),
        bindings=(
            machine_binding(
                "machine.registry.allowed_kinds",
                {
                    "values": (
                        [
                            "ACTION",
                            "ANALYZER",
                            "COMPOSITE",
                            "CONTROL",
                            "MODEL",
                            "REPAIR",
                            "STATE_SERVICE",
                            "VERIFIER",
                        ]
                        if allowed is None
                        else allowed
                    ),
                },
            ),
            machine_binding(
                "machine.registry.role_examples",
                {
                    "semantic_role":
                        "VERIFICATION",
                    "values": (
                        ["VERIFIER"]
                        if examples is None
                        else examples
                    ),
                },
            ),
            machine_binding(
                "machine.registry.rejected_aliases",
                {
                    "semantic_role":
                        "VERIFICATION",
                    "values": (
                        ["VERIFY"]
                        if rejected is None
                        else rejected
                    ),
                },
            ),
            machine_binding(
                "machine.registry.accepted_aliases",
                {
                    "semantic_role":
                        "VERIFICATION",
                    "values": (
                        ["VERIFIER"]
                        if accepted is None
                        else accepted
                    ),
                },
            ),
        ),
    )


def request(
    *,
    generic: K.KnowledgeBinding | None = None,
    machine_profile: K.MachineProfile | None = None,
    policy_sha: str = POLICY_SHA,
    specializer_sha: str = SPECIALIZER_SHA,
) -> K.SpecializationRequest:
    return K.SpecializationRequest(
        generic=(
            generic_binding()
            if generic is None
            else generic
        ),
        machine_profile=(
            profile()
            if machine_profile is None
            else machine_profile
        ),
        policy_sha256=policy_sha,
        specializer_content_sha256=(
            specializer_sha
        ),
    )


class KnowledgeCompilerTests(
    unittest.TestCase
):
    def test_fact_binding_is_content_addressed(
        self,
    ) -> None:
        binding = generic_binding()

        self.assertTrue(
            binding.fact_id.startswith(
                "fact-"
            )
        )

        self.assertEqual(
            len(binding.fact_id),
            69,
        )

        self.assertEqual(
            len(
                binding.binding_sha256()
            ),
            64,
        )

    def test_fact_id_tamper_fails_closed(
        self,
    ) -> None:
        binding = generic_binding()

        tampered = replace(
            binding,
            fact_id=(
                "fact-"
                + "0" * 64
            ),
        )

        with self.assertRaisesRegex(
            K.KnowledgeCompilerError,
            "FACT_ID_BINDING_MISMATCH",
        ):
            tampered.validate()

    def test_generic_binding_cannot_enter_machine_profile(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            K.KnowledgeCompilerError,
            "NON_MACHINE_FACT_IN_PROFILE",
        ):
            K.MachineProfile(
                profile_id="bad",
                state_base_revision=(
                    STATE_BASE
                ),
                bindings=(
                    generic_binding(),
                ),
            ).validate()

    def test_machine_binding_cannot_be_generic_input(
        self,
    ) -> None:
        machine = machine_binding(
            "machine.registry.allowed_kinds",
            {
                "values": ["VERIFIER"],
            },
        )

        with self.assertRaisesRegex(
            K.KnowledgeCompilerError,
            "GENERIC_PLANE_REQUIRED",
        ):
            request(
                generic=machine,
            ).validate()

    def test_unique_attested_alias_compiles_verifier(
        self,
    ) -> None:
        result = (
            K.compile_specialization(
                request()
            )
        )

        self.assertTrue(
            result.compiled
        )

        self.assertEqual(
            result.status,
            "COMPILED",
        )

        self.assertEqual(
            result.specialized_value,
            "VERIFIER",
        )

    def test_rejected_verify_never_survives(
        self,
    ) -> None:
        result = (
            K.compile_specialization(
                request()
            )
        )

        self.assertNotEqual(
            result.specialized_value,
            "VERIFY",
        )

    def test_no_machine_supported_alias_is_unsupported(
        self,
    ) -> None:
        result = (
            K.compile_specialization(
                request(
                    machine_profile=profile(
                        allowed=[
                            "ANALYZER"
                        ],
                        examples=[
                            "ANALYZER"
                        ],
                        rejected=[
                            "VERIFY",
                            "VERIFIER",
                        ],
                        accepted=[
                            "ANALYZER"
                        ],
                    )
                )
            )
        )

        self.assertEqual(
            result.status,
            "UNSUPPORTED",
        )

        self.assertFalse(
            result.compiled
        )

    def test_multiple_valid_aliases_are_ambiguous(
        self,
    ) -> None:
        result = (
            K.compile_specialization(
                request(
                    machine_profile=profile(
                        allowed=[
                            "VERIFY",
                            "VERIFIER",
                        ],
                        examples=[
                            "VERIFY",
                            "VERIFIER",
                        ],
                        rejected=[],
                        accepted=[
                            "VERIFY",
                            "VERIFIER",
                        ],
                    )
                )
            )
        )

        self.assertEqual(
            result.status,
            "AMBIGUOUS",
        )

        self.assertFalse(
            result.compiled
        )

    def test_machine_profile_identity_changes_with_fact(
        self,
    ) -> None:
        first = profile()

        second = profile(
            accepted=[
                "VERIFIER",
                "ANALYZER",
            ]
        )

        self.assertNotEqual(
            first.profile_sha256(),
            second.profile_sha256(),
        )

    def test_policy_revision_changes_bundle_root(
        self,
    ) -> None:
        first = (
            K.compile_specialization(
                request()
            )
        )

        second = (
            K.compile_specialization(
                request(
                    policy_sha="d" * 64
                )
            )
        )

        self.assertNotEqual(
            first.bundle_root_sha256,
            second.bundle_root_sha256,
        )

    def test_specializer_revision_changes_bundle_root(
        self,
    ) -> None:
        first = (
            K.compile_specialization(
                request()
            )
        )

        second = (
            K.compile_specialization(
                request(
                    specializer_sha="e" * 64
                )
            )
        )

        self.assertNotEqual(
            first.bundle_root_sha256,
            second.bundle_root_sha256,
        )

    def test_rebuild_is_deterministic_and_grants_no_authority(
        self,
    ) -> None:
        req = request()

        first = (
            K.compile_specialization(
                req
            )
        )

        second = (
            K.compile_specialization(
                req
            )
        )

        self.assertEqual(
            first.as_dict(),
            second.as_dict(),
        )

        self.assertEqual(
            first.action_authority,
            "NONE",
        )

        self.assertEqual(
            first.promotion_authority,
            "NONE",
        )

        self.assertFalse(
            first.canonical_policy_change
        )

        self.assertEqual(
            first.persistent_write,
            "NONE",
        )

        self.assertFalse(
            first.model_inference
        )


if __name__ == "__main__":
    unittest.main()
