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

import compiled_focus as F  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def dependency(
    namespace: str,
    value: str,
) -> F.FocusDependency:
    return F.FocusDependency(
        namespace=namespace,
        root_sha256=h(value),
    )


def binding(
    *,
    dependencies: tuple[
        F.FocusDependency,
        ...
    ] | None = None,
    policy: str = "policy-a",
    compiler: str = "compiler-a",
) -> F.FocusBinding:
    if dependencies is None:
        dependencies = (
            dependency(
                "knowledge.generic",
                "generic-a",
            ),
            dependency(
                "knowledge.machine",
                "machine-a",
            ),
        )

    return F.FocusBinding(
        domain="knowledge.specialization",
        focus_id="verification-kind",
        dependencies=dependencies,
        policy_revision_sha256=h(
            policy
        ),
        compiler_revision_sha256=h(
            compiler
        ),
    )


class CompiledFocusTests(
    unittest.TestCase
):
    def test_dependency_order_is_canonical(
        self,
    ) -> None:
        first = binding(
            dependencies=(
                dependency(
                    "a",
                    "one",
                ),
                dependency(
                    "b",
                    "two",
                ),
            )
        )

        second = binding(
            dependencies=(
                dependency(
                    "b",
                    "two",
                ),
                dependency(
                    "a",
                    "one",
                ),
            )
        )

        self.assertEqual(
            first.binding_sha256(),
            second.binding_sha256(),
        )

    def test_dependency_change_invalidates_binding(
        self,
    ) -> None:
        first = binding()

        second = binding(
            dependencies=(
                dependency(
                    "knowledge.generic",
                    "generic-a",
                ),
                dependency(
                    "knowledge.machine",
                    "machine-b",
                ),
            )
        )

        self.assertNotEqual(
            first.binding_sha256(),
            second.binding_sha256(),
        )

    def test_policy_change_invalidates_binding(
        self,
    ) -> None:
        self.assertNotEqual(
            binding(
                policy="policy-a"
            ).binding_sha256(),
            binding(
                policy="policy-b"
            ).binding_sha256(),
        )

    def test_focus_compiler_change_invalidates_binding(
        self,
    ) -> None:
        self.assertNotEqual(
            binding(
                compiler="compiler-a"
            ).binding_sha256(),
            binding(
                compiler="compiler-b"
            ).binding_sha256(),
        )

    def test_compile_handle_is_content_addressed(
        self,
    ) -> None:
        item = binding()

        handle = F.compile_focus(
            item,
            b'{"value":"VERIFIER"}',
        )

        self.assertEqual(
            handle.handle_id,
            item.binding_sha256(),
        )

        self.assertEqual(
            handle.binding_sha256,
            item.binding_sha256(),
        )

        self.assertEqual(
            handle.payload_sha256,
            hashlib.sha256(
                b'{"value":"VERIFIER"}'
            ).hexdigest(),
        )

    def test_same_binding_different_payload_collides_closed(
        self,
    ) -> None:
        cache = F.CompiledFocusCache()

        item = binding()

        cache.store(
            F.compile_focus(
                item,
                b"one",
            )
        )

        with self.assertRaisesRegex(
            F.CompiledFocusError,
            "FOCUS_HANDLE_COLLISION",
        ):
            cache.store(
                F.compile_focus(
                    item,
                    b"two",
                )
            )

    def test_lookup_is_direct_and_returns_same_handle(
        self,
    ) -> None:
        cache = F.CompiledFocusCache()

        handle = cache.compile_and_store(
            binding(),
            b"compiled",
        )

        self.assertIs(
            cache.lookup(
                handle.handle_id
            ),
            handle,
        )

    def test_stale_binding_is_a_cache_miss(
        self,
    ) -> None:
        cache = F.CompiledFocusCache()

        current = binding()

        handle = cache.compile_and_store(
            current,
            b"compiled",
        )

        stale = binding(
            dependencies=(
                dependency(
                    "knowledge.generic",
                    "generic-a",
                ),
                dependency(
                    "knowledge.machine",
                    "machine-stale",
                ),
            )
        )

        self.assertIsNotNone(
            cache.lookup(
                handle.handle_id
            )
        )

        self.assertIsNone(
            cache.lookup(
                stale.binding_sha256()
            )
        )

    def test_cache_is_bounded(
        self,
    ) -> None:
        cache = F.CompiledFocusCache(
            max_entries=2
        )

        first = cache.compile_and_store(
            binding(
                policy="policy-1"
            ),
            b"one",
        )

        second = cache.compile_and_store(
            binding(
                policy="policy-2"
            ),
            b"two",
        )

        third = cache.compile_and_store(
            binding(
                policy="policy-3"
            ),
            b"three",
        )

        self.assertEqual(
            cache.size,
            2,
        )

        self.assertIsNone(
            cache.lookup(
                first.handle_id
            )
        )

        self.assertIsNotNone(
            cache.lookup(
                second.handle_id
            )
        )

        self.assertIsNotNone(
            cache.lookup(
                third.handle_id
            )
        )

    def test_duplicate_dependency_namespace_fails_closed(
        self,
    ) -> None:
        item = binding(
            dependencies=(
                dependency(
                    "same",
                    "one",
                ),
                dependency(
                    "same",
                    "two",
                ),
            )
        )

        with self.assertRaisesRegex(
            F.CompiledFocusError,
            "FOCUS_DEPENDENCY_NAMESPACE_DUPLICATE",
        ):
            item.validate()

    def test_invalid_dependency_hash_fails_closed(
        self,
    ) -> None:
        item = F.FocusBinding(
            domain="knowledge",
            focus_id="x",
            dependencies=(
                F.FocusDependency(
                    namespace="x",
                    root_sha256="bad",
                ),
            ),
            policy_revision_sha256=h(
                "policy"
            ),
            compiler_revision_sha256=h(
                "compiler"
            ),
        )

        with self.assertRaisesRegex(
            F.CompiledFocusError,
            "DEPENDENCY_ROOT_SHA256_INVALID",
        ):
            item.validate()

    def test_focus_handle_grants_no_authority(
        self,
    ) -> None:
        handle = F.compile_focus(
            binding(),
            b"compiled",
        )

        self.assertEqual(
            handle.action_authority,
            "NONE",
        )

        self.assertEqual(
            handle.promotion_authority,
            "NONE",
        )

        self.assertEqual(
            handle.persistent_write,
            "NONE",
        )

        self.assertFalse(
            handle.model_inference
        )

    def test_handle_metadata_excludes_raw_payload(
        self,
    ) -> None:
        handle = F.compile_focus(
            binding(),
            b"secret-not-persisted",
        )

        metadata = (
            handle.as_dict()
        )

        self.assertNotIn(
            "payload_bytes",
            metadata,
        )

        self.assertEqual(
            metadata["payload_size"],
            len(
                b"secret-not-persisted"
            ),
        )

    def test_tampered_payload_fails_closed(
        self,
    ) -> None:
        handle = F.compile_focus(
            binding(),
            b"compiled",
        )

        tampered = replace(
            handle,
            payload_bytes=b"tampered",
        )

        with self.assertRaisesRegex(
            F.CompiledFocusError,
            "FOCUS_PAYLOAD_BINDING_MISMATCH",
        ):
            tampered.validate()


if __name__ == "__main__":
    unittest.main()
