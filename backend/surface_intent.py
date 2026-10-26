from __future__ import annotations

import re

_OPEN = re.compile(
    r"\b(öppna|visa|gå till|byt till|switch(?:a)?(?:\s+to)?|open|show)\b",
    re.IGNORECASE,
)
_TERMINAL = re.compile(r"\b(terminal(?:en)?|term|konsol(?:en)?|pty)\b", re.IGNORECASE)
_WEB = re.compile(
    r"\b(webb(?:en)?|web(?:ben)?|browser|webbläsare)\b",
    re.IGNORECASE,
)
_EXTERNAL = re.compile(
    r"\b(external|extern(?:t)?|program(?:met)?|app(?:en)?)\b",
    re.IGNORECASE,
)
_CODE = re.compile(
    r"\b(kod(?:en)?|filen|code|coden|qml|editorn)\b",
    re.IGNORECASE,
)
_SITE = re.compile(
    r"\b(sajt(?:en)?|site|hemsida(?:n)?|wordpress|dreamweaver|webbplats(?:en)?)\b",
    re.IGNORECASE,
)
_TMOG = re.compile(
    r"\b(tmog|task\s*manager)\b",
    re.IGNORECASE,
)
_OSINT = re.compile(
    r"\b(osint|osiris(?:ai)?|intelligence|recon(?:naissance)?)\b",
    re.IGNORECASE,
)
_RESEARCH = re.compile(
    r"\b(research|research desk|researcha|undersök(?:a|ning)?|evidence|evidens|källor|metodminne|sql preview|ghidra|rea|reverse engineering)\b",
    re.IGNORECASE,
)
_KNOWLEDGE = re.compile(
    r"\b(knowledge|kunskap(?:en|svärld(?:en)?|skarta(?:n)?)?|material(?:et)?|atlas)\b",
    re.IGNORECASE,
)
_QIP = re.compile(
    r"\b(qip|wasm|webassembly|component\s+debugger)\b",
    re.IGNORECASE,
)
_GAME_ENGINE = re.compile(
    r"\b(game\s+engine|gameengine|spelmotor(?:n)?|spel\s+motor)\b",
    re.IGNORECASE,
)
_NODES = re.compile(
    r"\b(nodes?|nod(?:er|erna)?|geometry\s*nodes|flöde(?:t)?|node\s*graph)\b",
    re.IGNORECASE,
)
_MARKETPLACE = re.compile(
    r"\b(marketplace|nft|handelsplats(?:en)?|marknad(?:en)?)\b",
    re.IGNORECASE,
)
_MEDIA = re.compile(
    r"\b(media|musik(?:en)?|radio(?:n)?|tv(?:n)?|teve|emulator(?:n)?|spel(?:en)?|game|cliamp|torlink|fetch)\b",
    re.IGNORECASE,
)
_DRAW = re.compile(
    r"\b(draw|rita|rit(?:a)?|gimp|photoshop|illustrator|photopea|pixel|canvas|2d|bildrediger(?:are)?)\b",
    re.IGNORECASE,
)
_BLENDER = re.compile(r"\b(blender)\b", re.IGNORECASE)
_BARE = {
    "terminal": "TERMINAL",
    "term": "TERMINAL",
    "web": "WEB",
    "webb": "WEB",
    "external": "EXTERNAL",
    "ext": "EXTERNAL",
    "blender": "EXTERNAL",
    "kod": "CODE",
    "code": "CODE",
    "site": "SITE",
    "sajt": "SITE",
    "hemsida": "SITE",
    "tmog": "TMOG",
    "osint": "OSINT",
    "osiris": "OSINT",
    "osirisai": "OSINT",
    "knowledge": "KNOWLEDGE",
    "kunskap": "KNOWLEDGE",
    "kunskapsvärlden": "KNOWLEDGE",
    "kunskapskartan": "KNOWLEDGE",
    "atlas": "KNOWLEDGE",
    "research": "RESEARCH",
    "research desk": "RESEARCH",
    "evidens": "RESEARCH",
    # Compatibility intents; WorkspaceSurface redirects these to RESEARCH / WASM LAB.
    "qip": "QIP",
    "wasm": "QIP",
    "webassembly": "QIP",
    "ghidra": "RESEARCH",
    "rea": "RESEARCH",
    "game engine": "GAME_ENGINE",
    "gameengine": "GAME_ENGINE",
    "spelmotor": "GAME_ENGINE",
    "spelmotorn": "GAME_ENGINE",
    "nodes": "NODES",
    "noder": "NODES",
    "node": "NODES",
    "marketplace": "MARKETPLACE",
    "nft": "MARKETPLACE",
    "handelsplats": "MARKETPLACE",
    "marknad": "MARKETPLACE",
    "media": "MEDIA",
    "musik": "MEDIA",
    "radio": "MEDIA",
    "tv": "MEDIA",
    "spel": "MEDIA",
    "game": "MEDIA",
    "emulator": "MEDIA",
    "cliamp": "MEDIA",
    "torlink": "MEDIA",
    "fetch": "MEDIA",
    "draw": "DRAW",
    "rita": "DRAW",
    "gimp": "DRAW",
    "photoshop": "DRAW",
    "canvas": "DRAW",
}


def parse_surface_intent(text: str) -> str:
    value = " ".join(str(text or "").strip().split())
    if not value or len(value) > 80:
        return ""
    bare = _BARE.get(value.lower(), "")
    if bare:
        return bare
    if not _OPEN.search(value):
        return ""
    if _TERMINAL.search(value):
        return "TERMINAL"
    if _SITE.search(value):
        return "SITE"
    if _TMOG.search(value):
        return "TMOG"
    if _OSINT.search(value):
        return "OSINT"
    if _KNOWLEDGE.search(value):
        return "KNOWLEDGE"
    if _RESEARCH.search(value):
        return "RESEARCH"
    if _QIP.search(value):
        return "QIP"
    if _GAME_ENGINE.search(value):
        return "GAME_ENGINE"
    if _NODES.search(value):
        return "NODES"
    if _MARKETPLACE.search(value):
        return "MARKETPLACE"
    if _MEDIA.search(value):
        return "MEDIA"
    if _DRAW.search(value):
        return "DRAW"
    if _BLENDER.search(value):
        return "EXTERNAL"
    if _WEB.search(value):
        return "WEB"
    if _EXTERNAL.search(value):
        return "EXTERNAL"
    if _CODE.search(value):
        return "CODE"
    return ""
