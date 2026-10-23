# GG AI DESKTOP application directory

This directory is the application source root in a standalone GitHub checkout
and in the GoldGoblins development workspace. Resources resolve relative to
this directory. `FILE-CATALOG.json` lists every distributed file, its category,
size and integrity check.

| Directory or file | Purpose |
|---|---|
| `main.py`, `startup.py`, `run-gg-ai-desktop.sh` | Desktop startup |
| `AGENTS.md` | Shared operating instructions and approval boundaries |
| `backend/` | Features, integrations and runtime contracts |
| `qml/` | Interface and application resources |
| `native/` | Engine libraries and build sources |
| `knowledge/web-gpts/` | All seven GG GPT source packages |
| `skills/` | Blender workflow, live eyes, visible web and SELFDEV |
| `.agents/skills`, `.grok/skills` | Links to the canonical skills directory |
| `support/` | Cognitive core, orchestrator, code gates and debug tools |
| `config/`, `schemas/` | Defaults, dependency catalog and data contracts |
| `tools/` | Helpers and tool installation sources |
| `tests/` | Source and behavior verification |
| `packaging/` | Catalog, export and distribution scripts |

## Install and start

The Windows desktop core uses Python 3.12 or later, ConPTY and the Qt Windows
platform plugin. Run `setup-windows.cmd`, then `run-gg-ai-desktop.cmd`.
Dependencies use `.venv-windows` with the verified Qt 6.11.2 Windows version.
The shared skills paths use Windows directory junctions and refer to `skills/`.
Native Windows game libraries live in `backend/native/windows-x86_64/`.
Build helpers in `tools/world/` select MSVC/Rust on Windows and retain their
Linux build paths. Rebuild the Linux libraries after changing native sources;
their integrity checks reject stale binaries. Remaining feature limitations
are recorded in [README.md](README.md) and `WINDOWS-PORT.json`.

The original Linux target uses X11 or Wayland/XWayland and Python 3.10 or
later. PySide6 provides Qt WebEngine and Qt Quick 3D; Linux display libraries
must also be installed. Tested versions are recorded in the dependency catalog.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python gg-setup --check
.venv/bin/python gg-setup --prepare
PYTHON="$PWD/.venv/bin/python" ./run-gg-ai-desktop.sh
```

Install and sign in to Codex for GPT TUI or Grok Build for GROK TUI.
`--prepare` exposes the four GG skills to the local client homes. Provider
settings and authentication are not distributed with GG. A standalone
installation uses this directory as its default workspace; development
checkouts retain their parent shared workspace.

Feature-specific dependencies for Blender, FFmpeg, native capture, Rust
libraries and research integrations are listed in `config/dependencies.json`.
Installation helpers live in `tools/`. Registered MCP tools and account-backed
services require the user's own installation and provider access.

Codex's system skills and Grok's bundled skills are supplied by those clients.
The catalog also records all detected external plugins and their skills.
Install those plugins through their original provider directories. The OpenAI
documents package explicitly prohibits third-party copying and distribution;
its cached files are therefore not part of the GG source distribution.

## Export and verify

```bash
python3 packaging/catalog.py verify
python3 packaging/catalog.py export /path/to/new/GG-AI-DESKTOP
```

The exporter creates a new destination, copies only cataloged files and checks
the completed export. External links and credential patterns fail validation.
It never recursively copies a user's home, state or CLI cache. Local game
content stays in the authoring environment, outside the application export.
Native format and physics test fixtures remain engine source dependencies.
The desktop's required rendering helpers and neutral texture are distributed
under `qml/components/engine/`, alongside the interface that imports them.

After changing source files, run `python3 packaging/catalog.py write`.
`SOURCE-MANIFEST.json` retains the original implementation contracts;
`FILE-CATALOG.json` describes the complete current distribution.

## User data and overrides

Private state follows XDG directories under the current user's home. Source,
knowledge and GG skills remain in this application directory. Sessions,
authentication, private memory, databases and model weights are user data.
On Windows, private desktop state defaults to
`%LOCALAPPDATA%\GoldGoblins\gg-ai-desktop`; `GG_DESKTOP_STATE_ROOT` can override
it. The earlier Windows `GG_DATA_HOME` setting remains supported.

| Variable | Override |
|---|---|
| `GG_WORKSPACE` | User's working project |
| `GG_DESKTOP_STATE_ROOT` | Private desktop state |
| `GG_DESKTOP_DATA_ROOT` | User-installed tools/data |
| `GG_GPT_KNOWLEDGE_ROOT` | Explicitly selected GG knowledge directory |
| `GG_USER_CODEX_HOME` | User's normal Codex configuration home |
| `GG_GROK_BIN` | Installed Grok executable |
| `PYTHON` | Launcher Python interpreter |

The older content-locked local-model harness is retained unchanged as a
historical component. Its local execution requires separately verified model
weights and container images; cloud TUI startup does not require those weights.
