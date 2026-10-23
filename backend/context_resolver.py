"""Bounded deterministic Workbench context resolution."""

from __future__ import annotations

import json


SNAPSHOT_SCHEMA = "gg.workbench.context-snapshot.v1"
RESOLVED_SCHEMA = "gg.workbench.resolved-context.v1"

MAX_SNAPSHOT_JSON_BYTES = 65536
MAX_WORKSPACE_OBJECTS = 32
MAX_RECENT_CHAT_NODES = 12
MAX_CHAT_NODE_CHARS = 2000
MAX_TEXT_FIELD_CHARS = 4096
MAX_VERIFIED_SOURCE_CHARS = 8000
MAX_EXTENSION_CHARS = 24000


class ContextResolverError(RuntimeError):
    """Fail-closed context resolver contract error."""


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ContextResolverError(
            label + "_KEYS_INVALID"
        )


def _text(
    value: object,
    label: str,
    *,
    maximum: int = MAX_TEXT_FIELD_CHARS,
    allow_empty: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ContextResolverError(
            label + "_TYPE_INVALID"
        )

    if len(value) > maximum:
        raise ContextResolverError(
            label + "_TOO_LONG"
        )

    if not allow_empty and not value:
        raise ContextResolverError(
            label + "_EMPTY"
        )

    return value


def _workspace_object(
    value: object,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContextResolverError(
            "WORKSPACE_OBJECT_TYPE_INVALID"
        )

    _exact_keys(
        value,
        {
            "objectId",
            "title",
            "objectType",
            "provenanceClass",
            "sourcePath",
            "activityState",
        },
        "WORKSPACE_OBJECT",
    )

    return {
        "objectId": _text(
            value["objectId"],
            "WORKSPACE_OBJECT_ID",
            maximum=1024,
            allow_empty=False,
        ),
        "title": _text(
            value["title"],
            "WORKSPACE_OBJECT_TITLE",
        ),
        "objectType": _text(
            value["objectType"],
            "WORKSPACE_OBJECT_TYPE",
            maximum=1024,
        ),
        "provenanceClass": _text(
            value["provenanceClass"],
            "WORKSPACE_OBJECT_PROVENANCE",
            maximum=1024,
        ),
        "sourcePath": _text(
            value["sourcePath"],
            "WORKSPACE_OBJECT_SOURCE_PATH",
        ),
        "activityState": _text(
            value["activityState"],
            "WORKSPACE_OBJECT_ACTIVITY",
            maximum=1024,
        ),
    }


def _chat_node(
    value: object,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ContextResolverError(
            "CHAT_NODE_TYPE_INVALID"
        )

    _exact_keys(
        value,
        {
            "authorLabel",
            "nodeKind",
            "bodyText",
            "contextReference",
            "provenanceClass",
        },
        "CHAT_NODE",
    )

    return {
        "authorLabel": _text(
            value["authorLabel"],
            "CHAT_AUTHOR",
            maximum=1024,
        ),
        "nodeKind": _text(
            value["nodeKind"],
            "CHAT_KIND",
            maximum=1024,
        ),
        "bodyText": _text(
            value["bodyText"],
            "CHAT_BODY",
            maximum=MAX_CHAT_NODE_CHARS,
        ),
        "contextReference": _text(
            value["contextReference"],
            "CHAT_CONTEXT_REFERENCE",
            maximum=1024,
        ),
        "provenanceClass": _text(
            value["provenanceClass"],
            "CHAT_PROVENANCE",
            maximum=1024,
        ),
    }


def parse_snapshot_json(
    raw: str,
) -> dict[str, object]:
    if not isinstance(raw, str):
        raise ContextResolverError(
            "SNAPSHOT_JSON_TYPE_INVALID"
        )

    if (
        len(raw.encode("utf-8"))
        > MAX_SNAPSHOT_JSON_BYTES
    ):
        raise ContextResolverError(
            "SNAPSHOT_JSON_TOO_LARGE"
        )

    try:
        value = json.loads(raw)

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ContextResolverError(
            "SNAPSHOT_JSON_INVALID"
        ) from exc

    if not isinstance(value, dict):
        raise ContextResolverError(
            "SNAPSHOT_TYPE_INVALID"
        )

    _exact_keys(
        value,
        {
            "schema",
            "workspace",
            "recentChat",
        },
        "SNAPSHOT",
    )

    if value["schema"] != SNAPSHOT_SCHEMA:
        raise ContextResolverError(
            "SNAPSHOT_SCHEMA_INVALID"
        )

    workspace = value["workspace"]

    if not isinstance(workspace, dict):
        raise ContextResolverError(
            "WORKSPACE_TYPE_INVALID"
        )

    _exact_keys(
        workspace,
        {
            "currentIndex",
            "currentObjectId",
            "objects",
        },
        "WORKSPACE",
    )

    current_index = workspace["currentIndex"]

    if (
        not isinstance(current_index, int)
        or isinstance(current_index, bool)
    ):
        raise ContextResolverError(
            "CURRENT_INDEX_TYPE_INVALID"
        )

    current_object_id = _text(
        workspace["currentObjectId"],
        "CURRENT_OBJECT_ID",
        maximum=1024,
    )

    raw_objects = workspace["objects"]

    if not isinstance(raw_objects, list):
        raise ContextResolverError(
            "WORKSPACE_OBJECTS_TYPE_INVALID"
        )

    if len(raw_objects) > MAX_WORKSPACE_OBJECTS:
        raise ContextResolverError(
            "WORKSPACE_OBJECTS_TOO_MANY"
        )

    objects = [
        _workspace_object(item)
        for item in raw_objects
    ]

    object_ids = [
        item["objectId"]
        for item in objects
    ]

    if len(object_ids) != len(set(object_ids)):
        raise ContextResolverError(
            "WORKSPACE_OBJECT_ID_DUPLICATE"
        )

    if objects:
        if (
            current_index < 0
            or current_index >= len(objects)
        ):
            raise ContextResolverError(
                "CURRENT_INDEX_RANGE_INVALID"
            )

        if (
            objects[current_index]["objectId"]
            != current_object_id
        ):
            raise ContextResolverError(
                "CURRENT_OBJECT_ID_INDEX_MISMATCH"
            )

    elif (
        current_index != -1
        or current_object_id
    ):
        raise ContextResolverError(
            "EMPTY_WORKSPACE_CURRENT_INVALID"
        )

    raw_chat = value["recentChat"]

    if not isinstance(raw_chat, list):
        raise ContextResolverError(
            "RECENT_CHAT_TYPE_INVALID"
        )

    if len(raw_chat) > MAX_RECENT_CHAT_NODES:
        raise ContextResolverError(
            "RECENT_CHAT_TOO_MANY"
        )

    recent_chat = [
        _chat_node(item)
        for item in raw_chat
    ]

    return {
        "schema": SNAPSHOT_SCHEMA,
        "workspace": {
            "currentIndex": current_index,
            "currentObjectId": current_object_id,
            "objects": objects,
        },
        "recentChat": recent_chat,
    }


def validate_snapshot_json(
    raw: str,
) -> str:
    snapshot = parse_snapshot_json(raw)

    return json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def resolve_snapshot(
    raw: str,
    context_reference: str,
    workspace_object_id: str,
) -> dict[str, object]:
    snapshot = parse_snapshot_json(raw)

    if context_reference not in (
        "@current",
        "@workspace",
    ):
        raise ContextResolverError(
            "CONTEXT_REFERENCE_UNSUPPORTED"
        )

    if not isinstance(workspace_object_id, str):
        raise ContextResolverError(
            "WORKSPACE_OBJECT_ID_TYPE_INVALID"
        )

    if len(workspace_object_id) > 1024:
        raise ContextResolverError(
            "WORKSPACE_OBJECT_ID_TOO_LONG"
        )

    workspace = snapshot["workspace"]

    if not isinstance(workspace, dict):
        raise ContextResolverError(
            "WORKSPACE_INTERNAL_INVALID"
        )

    current_object_id = str(
        workspace["currentObjectId"]
    )

    if (
        workspace_object_id
        and workspace_object_id
        != current_object_id
    ):
        raise ContextResolverError(
            "WORKSPACE_FOCUS_TRANSPORT_MISMATCH"
        )

    raw_objects = workspace["objects"]

    if not isinstance(raw_objects, list):
        raise ContextResolverError(
            "WORKSPACE_OBJECTS_INTERNAL_INVALID"
        )

    real_objects = [
        item
        for item in raw_objects
        if (
            isinstance(item, dict)
            and item.get("provenanceClass")
            == "REAL_LOCAL_FILE"
        )
    ]

    live_objects = [
        item
        for item in raw_objects
        if (
            isinstance(item, dict)
            and item.get("provenanceClass")
            in {"REAL_LOCAL_FILE", "REAL_UI_STATE"}
        )
    ]

    if context_reference == "@current":
        selected = [
            item
            for item in live_objects
            if item.get("objectId")
            == current_object_id
        ]

        if len(selected) != 1:
            raise ContextResolverError(
                "CURRENT_REAL_LOCAL_FILE_REQUIRED"
            )

        primary = selected[0]

        object_ids = [
            str(primary["objectId"])
        ]

    else:
        if not real_objects:
            raise ContextResolverError(
                "WORKSPACE_REAL_LOCAL_FILE_REQUIRED"
            )

        current_real = [
            item
            for item in real_objects
            if item.get("objectId")
            == current_object_id
        ]

        primary = (
            current_real[0]
            if current_real
            else real_objects[0]
        )

        object_ids = [
            str(item["objectId"])
            for item in real_objects
        ]

    recent_chat = [
        item
        for item in snapshot["recentChat"]
        if (
            isinstance(item, dict)
            and item.get("provenanceClass")
            == "REAL_UI_STATE"
        )
    ][-MAX_RECENT_CHAT_NODES:]

    return {
        "schema": RESOLVED_SCHEMA,
        "requestedReference":
            context_reference,
        "primaryObjectId":
            str(primary["objectId"]),
        "objectIds":
            object_ids,
        "recentChat":
            recent_chat,
    }


def _verified_context_text(
    value: object,
    object_id: str,
) -> str:
    if not isinstance(value, dict):
        raise ContextResolverError(
            "VERIFIED_CONTEXT_TYPE_INVALID"
        )

    if str(value.get("object_id", "")) != object_id:
        raise ContextResolverError(
            "VERIFIED_CONTEXT_ID_MISMATCH"
        )

    provenance = str(value.get("provenance", ""))
    if provenance not in {"REAL_LOCAL_FILE", "REAL_UI_STATE"}:
        raise ContextResolverError(
            "VERIFIED_CONTEXT_PROVENANCE_INVALID"
        )

    body = value.get("body")

    if not isinstance(body, str):
        raise ContextResolverError(
            "VERIFIED_CONTEXT_BODY_INVALID"
        )

    return (
        "Object id: "
        + object_id
        + "\nSource path: "
        + str(value.get("source_path", ""))
        + "\nSHA256: "
        + str(value.get("sha256", ""))
        + "\nContent:\n"
        + body[:MAX_VERIFIED_SOURCE_CHARS]
        + "\n"
    )


def render_extension(
    plan: dict[str, object],
    verified_contexts: list[
        dict[str, object]
    ],
) -> str:
    if plan.get("schema") != RESOLVED_SCHEMA:
        raise ContextResolverError(
            "RESOLVED_PLAN_SCHEMA_INVALID"
        )

    object_ids = plan.get("objectIds")

    if not isinstance(object_ids, list):
        raise ContextResolverError(
            "RESOLVED_OBJECT_IDS_INVALID"
        )

    if len(verified_contexts) != len(object_ids):
        raise ContextResolverError(
            "VERIFIED_CONTEXT_COUNT_MISMATCH"
        )

    paired = list(
        zip(
            object_ids,
            verified_contexts,
            strict=True,
        )
    )

    for object_id, context in paired:
        _verified_context_text(
            context,
            str(object_id),
        )

    parts = [
        "\n\n----- GG RESOLVED CONTEXT V1 -----\n",
        (
            "Requested reference: "
            + str(
                plan.get(
                    "requestedReference",
                    "",
                )
            )
            + "\n"
        ),
        (
            "Primary object id: "
            + str(
                plan.get(
                    "primaryObjectId",
                    "",
                )
            )
            + "\n"
        ),
        (
            "Verified object ids: "
            + ", ".join(
                str(item)
                for item in object_ids
            )
            + "\n"
        ),
        "QML metadata is not source authority.\n",
    ]

    for object_id, context in paired[1:]:
        parts.extend(
            [
                (
                    "\n----- ADDITIONAL VERIFIED "
                    "WORKSPACE SOURCE -----\n"
                ),
                _verified_context_text(
                    context,
                    str(object_id),
                ),
            ]
        )

    recent_chat = plan.get("recentChat")

    if not isinstance(recent_chat, list):
        raise ContextResolverError(
            "RESOLVED_RECENT_CHAT_INVALID"
        )

    if recent_chat:
        parts.append(
            "\n----- RECENT VISIBLE CHAT -----\n"
        )

        for item in recent_chat:
            if not isinstance(item, dict):
                raise ContextResolverError(
                    "RESOLVED_CHAT_ITEM_INVALID"
                )

            parts.extend(
                [
                    str(item.get("authorLabel", "")),
                    " · ",
                    str(item.get("nodeKind", "")),
                    " · ",
                    str(
                        item.get(
                            "contextReference",
                            "",
                        )
                    ),
                    "\n",
                    str(item.get("bodyText", "")),
                    "\n",
                ]
            )

    return "".join(parts)[:MAX_EXTENSION_CHARS]
