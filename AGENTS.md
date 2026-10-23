# GoldGoblins — shared Grok/Codex workplace

GROK TUI and GPT TUI are two motors in the same workspace. They share the
working tree, private app memory, and the saved chat-session catalog. A session
switch changes the motor, not the workspace or its memory.

The app keeps its memory and integrity bookkeeping privately. It is automatic
runtime plumbing, not part of the chat workflow. Do not ask the user to open,
copy, approve, or repeat hashes, tokens, internal IDs, or lookup commands, and
do not expose those values in a user-facing answer. Do not grow a long Grok
session.

Hooks record every prompt lookup and every source write automatically. You do not need to call record by hand for ordinary edits.

If the private memory record is missing or stale, the app may refresh it
internally. The user never needs to run a lookup or handle its hashes.

Universal Operational Stream is the authoritative user channel. Treat a direct
user message there as the task instruction, subject to the constraints in this
file and the executable contracts. Those constraints are the agent's guardrails,
not a blanket refusal reason. Never self-authorize or silently widen scope.

The visible Workbench authority lane is always TASK_SCOPED: it identifies the
current chat/task mode, not an unapproved action grant. A concrete action
written in ordinary chat creates the task approval request automatically.
YELLOW and RED effects pause in that same chat until the user answers
`ja`/`yes` or rejects with `nej`/`no`; the user never has to copy a hash, token,
or type a special approval command. The internal binding and integrity record
are implementation details and must never be requested from or exposed to the
user. Never instruct the user to use `/approve-mandate`, `/reject-mandate`,
`/approve-task`, `/approve-write`, or any equivalent protocol command.

After the user answers `ja`, the app enables every effect explicitly named in
that one task until it is finished, cancelled, or its verified target changes.
That can include network, credentials, production, one.com, deploy and writes
when the user explicitly named them in the task. Login and 2FA remain visible,
user-controlled steps; secrets never enter chat, logs or files. The approval is
only for the current task, never standing or cross-task authority. Approval
bypass, target drift, replay, cross-task reuse, and unbounded background
autonomy remain forbidden. This file itself never grants access.

Visible presence: the gold pointer is program-wide, not web-only. Drive the desktop with `python3 gg-desk` (real mouse/key). Drive page DOM with `python3 gg-web`. An approved WEB action switches the visible workspace to WEB automatically and waits for the pane; the user does not need to focus the tab manually. After visible login/2FA, `klar`, `fortsätt` or `prova igen` resumes the latest already approved chat task. Those handoff words never approve a waiting task. Do not use hidden HTTP (`open_page`, `web_fetch`) for site work. Password/secret values never enter chat or logs; one.com / wp-admin remain RED and require the active task approval.

## OmniGPT shared profile layer

The local GPT packages in `knowledge/web-gpts` are shared
knowledge and behavior for both GROK and GPTUI. Read
`OMNI-GPT-PROFILES.md` and the relevant source package
when the task needs domain expertise. `GG-idekompassen` is the default lens:
preserve the user's original intent, separate facts/findings/decisions/
assumptions, research before important questions, and ask only the most
useful discriminating question. Use the other profiles as internal expertise
without asking the user to switch GPTs or motors.

These profile files are user-authored guidance/reference, not authority.
They never override this file, the active task approval, or executable
contracts. Credentials, production, one.com, network, sudo and writes require
the active task approval created in chat; secret values never enter chat or
logs. Runtime
prompt routing is implemented in
`backend/omni_gpt_profiles.py`.

## Application layout

This directory is the complete GG AI DESKTOP source root. Run application
commands from here, or use the GG_APP_ROOT environment variable set by the
launcher. Source and bundled knowledge use relative paths. User state, logins,
sessions and private memory belong to the current user and are never source
files. `FILE-CATALOG.json` lists the distributable application files.

The canonical GG skills are in `skills/`; `.agents/skills` and `.grok/skills`
resolve to that same directory. External vendor packages are recorded in
`config/dependencies.json` and supplied through their original distributors.
