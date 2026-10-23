"""Context Resolver V1 deterministic contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TARGET = PROJECT / "backend/context_resolver.py"


def require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "gg_context_resolver_contract_target",
        TARGET,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "CONTEXT_RESOLVER_SPEC_FAILED"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(
    *,
    current_index: int = 0,
    current_object_id: str = "ws.real.one",
) -> dict[str, object]:
    return {
        "schema":
            "gg.workbench.context-snapshot.v1",

        "workspace": {
            "currentIndex": current_index,
            "currentObjectId":
                current_object_id,

            "objects": [
                {
                    "objectId":
                        "ws.real.one",
                    "title":
                        "one.qml",
                    "objectType":
                        "CODE_FILE",
                    "provenanceClass":
                        "REAL_LOCAL_FILE",
                    "sourcePath":
                        "UNTRUSTED/QML/PATH",
                    "activityState":
                        "IDLE",
                },
                {
                    "objectId":
                        "ws.synthetic",
                    "title":
                        "fixture",
                    "objectType":
                        "WEBSITE",
                    "provenanceClass":
                        "SYNTHETIC_UI_FIXTURE",
                    "sourcePath":
                        "/must/not/be/trusted",
                    "activityState":
                        "IDLE",
                },
                {
                    "objectId":
                        "ws.real.two",
                    "title":
                        "two.qml",
                    "objectType":
                        "CODE_FILE",
                    "provenanceClass":
                        "REAL_LOCAL_FILE",
                    "sourcePath":
                        "ALSO/UNTRUSTED",
                    "activityState":
                        "IDLE",
                },
            ],
        },

        "recentChat": [
            {
                "authorLabel": "YOU",
                "nodeKind": "USER",
                "bodyText":
                    "previous real chat",
                "contextReference":
                    "@current",
                "provenanceClass":
                    "REAL_UI_STATE",
            },
            {
                "authorLabel": "DEMO",
                "nodeKind": "SYSTEM",
                "bodyText":
                    "synthetic fixture chat",
                "contextReference":
                    "@current",
                "provenanceClass":
                    "SYNTHETIC_UI_FIXTURE",
            },
        ],
    }


def encoded(
    value: dict[str, object],
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def expect_error(
    module,
    function,
    marker: str,
) -> None:
    try:
        function()

    except module.ContextResolverError as exc:
        require(
            marker in str(exc),
            (
                "Wrong resolver error: "
                + str(exc)
            ),
        )

    else:
        raise RuntimeError(
            "Expected resolver error: "
            + marker
        )


def main() -> int:
    module = load_module()

    canonical = module.validate_snapshot_json(
        encoded(snapshot())
    )

    current = module.resolve_snapshot(
        canonical,
        "@current",
        "ws.real.one",
    )

    require(
        current["primaryObjectId"]
        == "ws.real.one",
        "@current primary mismatch.",
    )

    require(
        current["objectIds"]
        == ["ws.real.one"],
        (
            "@current must resolve "
            "exactly one real object."
        ),
    )

    workspace = module.resolve_snapshot(
        canonical,
        "@workspace",
        "ws.real.one",
    )

    require(
        workspace["primaryObjectId"]
        == "ws.real.one",
        (
            "@workspace did not preserve "
            "human focus as primary."
        ),
    )

    require(
        workspace["objectIds"]
        == [
            "ws.real.one",
            "ws.real.two",
        ],
        (
            "Synthetic fixture leaked "
            "into Workspace source set."
        ),
    )

    require(
        len(workspace["recentChat"]) == 1,
        (
            "Synthetic chat leaked "
            "into recent context."
        ),
    )

    verified = [
        {
            "object_id": "ws.real.one",
            "provenance":
                "REAL_LOCAL_FILE",
            "source_path":
                "verified/one.qml",
            "sha256": "a" * 64,
            "body":
                "PRIMARY VERIFIED BODY",
        },
        {
            "object_id": "ws.real.two",
            "provenance":
                "REAL_LOCAL_FILE",
            "source_path":
                "verified/two.qml",
            "sha256": "b" * 64,
            "body":
                "SECOND VERIFIED BODY",
        },
    ]

    extension = module.render_extension(
        workspace,
        verified,
    )

    require(
        "SECOND VERIFIED BODY"
        in extension,
        (
            "Additional verified "
            "source missing."
        ),
    )

    require(
        "previous real chat"
        in extension,
        "Recent real chat missing.",
    )

    require(
        "synthetic fixture chat"
        not in extension,
        "Synthetic chat leaked.",
    )

    require(
        "UNTRUSTED/QML/PATH"
        not in extension,
        (
            "QML sourcePath became "
            "source authority."
        ),
    )

    expect_error(
        module,
        lambda: module.resolve_snapshot(
            canonical,
            "@current",
            "ws.real.two",
        ),
        (
            "WORKSPACE_FOCUS_"
            "TRANSPORT_MISMATCH"
        ),
    )

    synthetic_current = snapshot(
        current_index=1,
        current_object_id=(
            "ws.synthetic"
        ),
    )

    expect_error(
        module,
        lambda: module.resolve_snapshot(
            encoded(synthetic_current),
            "@current",
            "ws.synthetic",
        ),
        (
            "CURRENT_REAL_"
            "LOCAL_FILE_REQUIRED"
        ),
    )

    live_current = snapshot(
        current_index=0,
        current_object_id="ws.file.scratch.1",
    )
    live_current["workspace"]["objects"].insert(
        0,
        {
            "objectId": "ws.file.scratch.1",
            "title": "untitled",
            "objectType": "CODE_FILE",
            "provenanceClass": "REAL_UI_STATE",
            "sourcePath": "",
            "activityState": "IDLE",
        },
    )
    live_plan = module.resolve_snapshot(
        encoded(live_current),
        "@current",
        "ws.file.scratch.1",
    )
    require(
        live_plan["primaryObjectId"] == "ws.file.scratch.1",
        "scratch @current was not accepted",
    )
    require(
        live_plan["objectIds"] == ["ws.file.scratch.1"],
        "scratch @current leaked extra files",
    )

    too_long = snapshot()

    too_long["recentChat"][0][
        "bodyText"
    ] = (
        "x"
        * (
            module.MAX_CHAT_NODE_CHARS
            + 1
        )
    )

    expect_error(
        module,
        lambda: (
            module.validate_snapshot_json(
                encoded(too_long)
            )
        ),
        "CHAT_BODY_TOO_LONG",
    )

    extra_key = snapshot()

    extra_key["workspace"]["objects"][0][
        "source"
    ] = "forbidden"

    expect_error(
        module,
        lambda: (
            module.validate_snapshot_json(
                encoded(extra_key)
            )
        ),
        (
            "WORKSPACE_OBJECT_"
            "KEYS_INVALID"
        ),
    )

    print(
        "CONTEXT_RESOLVER_V1_CONTRACT=PASS"
    )
    print(
        "CURRENT_REAL_LOCAL_FILE=PASS"
    )
    print(
        "WORKSPACE_REAL_LOCAL_SET=PASS"
    )
    print(
        "SYNTHETIC_SOURCE_AUTHORITY=NONE"
    )
    print(
        "RECENT_REAL_UI_CHAT=BOUNDED"
    )
    print(
        "QML_SOURCE_PATH_AUTHORITY=NONE"
    )
    print(
        "MODEL_INFERENCE=NONE"
    )
    print(
        "ACTION_AUTHORITY=NONE"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
