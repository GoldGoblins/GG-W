"""Canonical in-memory Merkle domain/subtree identities for GG.

This module is deliberately small.  It does not discover files, read state,
execute capabilities, invoke a model, write knowledge, or decide authority.

It only composes already-attested identities into canonical domain/subtree
roots so downstream compiled-focus bindings can depend on exactly the parts of
the world they need.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


MERKLE_CHILD_SCHEMA = (
    "gg.domain-merkle-child.v1"
)
MERKLE_ROOT_SCHEMA = (
    "gg.domain-merkle-root.v1"
)

LEAF = "LEAF"
SUBTREE = "SUBTREE"

CHILD_KINDS = frozenset(
    (
        LEAF,
        SUBTREE,
    )
)

MAX_CHILDREN = 4096


class DomainMerkleError(
    RuntimeError
):
    """Domain Merkle contract violation."""


def canonical_json(
    value: object,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(
    value: object,
) -> str:
    return hashlib.sha256(
        canonical_json(value)
    ).hexdigest()


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
        raise DomainMerkleError(
            label
            + "_SHA256_INVALID"
        )

    return value


def _require_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise DomainMerkleError(
            label
            + "_TEXT_INVALID"
        )

    return value


@dataclass(frozen=True)
class MerkleChild:
    namespace: str
    kind: str
    root_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.namespace,
            "MERKLE_CHILD_NAMESPACE",
            maximum=512,
        )

        if self.kind not in CHILD_KINDS:
            raise DomainMerkleError(
                "MERKLE_CHILD_KIND_INVALID"
            )

        _require_sha256(
            self.root_sha256,
            "MERKLE_CHILD_ROOT",
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "schema":
                MERKLE_CHILD_SCHEMA,
            "namespace":
                self.namespace,
            "kind":
                self.kind,
            "root_sha256":
                self.root_sha256,
        }


@dataclass(frozen=True)
class DomainMerkleRoot:
    domain: str
    scope: str
    children: tuple[
        MerkleChild,
        ...
    ]

    def validate(
        self,
    ) -> None:
        _require_text(
            self.domain,
            "MERKLE_DOMAIN",
            maximum=128,
        )

        _require_text(
            self.scope,
            "MERKLE_SCOPE",
            maximum=512,
        )

        if (
            not isinstance(
                self.children,
                tuple,
            )
            or not self.children
            or len(
                self.children
            ) > MAX_CHILDREN
        ):
            raise DomainMerkleError(
                "MERKLE_CHILDREN_INVALID"
            )

        seen: set[str] = set()

        for child in self.children:
            if not isinstance(
                child,
                MerkleChild,
            ):
                raise DomainMerkleError(
                    "MERKLE_CHILD_TYPE_INVALID"
                )

            child.validate()

            if child.namespace in seen:
                raise DomainMerkleError(
                    "MERKLE_CHILD_NAMESPACE_DUPLICATE"
                )

            seen.add(
                child.namespace
            )

    def ordered_children(
        self,
    ) -> tuple[
        MerkleChild,
        ...
    ]:
        self.validate()

        return tuple(
            sorted(
                self.children,
                key=lambda item: (
                    item.namespace,
                    item.kind,
                    item.root_sha256,
                ),
            )
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                MERKLE_ROOT_SCHEMA,
            "domain":
                self.domain,
            "scope":
                self.scope,
            "children": [
                child.as_dict()
                for child
                in self.ordered_children()
            ],
        }

    def root_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


def leaf(
    namespace: str,
    content_sha256: str,
) -> MerkleChild:
    child = MerkleChild(
        namespace=namespace,
        kind=LEAF,
        root_sha256=content_sha256,
    )

    child.validate()

    return child


def subtree(
    namespace: str,
    root: DomainMerkleRoot,
) -> MerkleChild:
    if not isinstance(
        root,
        DomainMerkleRoot,
    ):
        raise DomainMerkleError(
            "MERKLE_SUBTREE_TYPE_INVALID"
        )

    root.validate()

    return MerkleChild(
        namespace=namespace,
        kind=SUBTREE,
        root_sha256=root.root_sha256(),
    )


def build_domain_root(
    domain: str,
    scope: str,
    children: tuple[
        MerkleChild,
        ...
    ],
) -> DomainMerkleRoot:
    root = DomainMerkleRoot(
        domain=domain,
        scope=scope,
        children=children,
    )

    root.validate()

    return root
