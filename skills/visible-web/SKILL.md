---
name: visible-web
description: Drive the GG AI Desktop WEB tab with a visible agent cursor. Use when browsing, clicking, typing, or working on goldgoblins.se / the local SITE in the WEB pane. Use when the user runs /visible-web. Never use hidden HTTP (open_page, web_fetch) for site work.
---

# Visible operator

The gold pointer is the visual body of Grok in GG AI Desktop, not a web-only gadget. Look first, then move, then click. Do not click by memory.

1. `gg-desk snapshot` — picture plus visible chrome labels (`names` with x,y)
2. `gg-desk find WEB` — only labels that match
3. Move the gold pointer and click **WEB**: `gg-desk click --name workspaceKindWEB` (never let `gg-web` switch tabs)
4. Then page DOM: `gg-web snapshot` then `gg-web click 'text=RINGAR'`

`gg-web` returns `WEB_NOT_FOCUSED` if WEB is not the current host. Click WEB with `gg-desk` first.

QML reload: click **RELOAD** yourself (`gg-desk click --name topBarReloadButton`). Do not ask the user. Full GG AI Desktop process restart is the only step the user does.

Self-plan in this chat: click the **prompt box** (about `80,875`, the `>` field above Shift+Tab), not the transcript. Type, then `gg-desk key Enter`. If this turn is still running, **Enter twice**.

Do not write thin `PLAN: 1 … 2 …` lines. The next prompt is a work order to the next Grok turn. TYPE cannot send newline (`\n` becomes Enter and submits early), so the box is **one line**, fields split by ` // `.

Shape (every field, every time):

`SELFDEV // MANDATE: … // NOW: … // THIS ROUND: … // DONE WHEN: … // HANDOFF: …`

Packed form (one word = one task): skill `selfdev-t`. Use a `T //` line when the box must stay cheap.

- **MANDATE** — TASK_SCOPED, YELLOW allowed, RED forbidden, AUTHORITY=NONE. Named files if this round edits.
- **NOW** — live URL/tab, what already works, open bugs with evidence. Do not make the next turn rediscover.
- **THIS ROUND** — one or two outcomes. Eyes before jewelry. Look-move-click to verify, not as the whole job.
- **DONE WHEN** — observable checks (`gg-desk find WEB` lists `workspaceKindWEB`, grab matches scroll, …).
- **HANDOFF** — same shape for the following turn. Reins: look then move then click. RELOAD yourself. User only restarts the process. No one.com, no cart, no FIND https, no `QObject.children()` into Chromium.

Write the next two rounds inside THIS ROUND + HANDOFF, not as a separate shopping list.
5. Scroll with the pointer: `gg-web scroll --dy 360` or `gg-web scroll --selector 'text=Aurora'`
6. Hover before click: `gg-web hover 'text=Aurora'`
7. `gg-web back` / `gg-web forward` for history

If FIND/CLICK returns `MISS`, read `names` — that is what was actually visible. Use `gg-web` only for page DOM inside the WEB pane.

```bash
python3 gg-web <action> ...
```

Actions:

- `stage` — local rehearsal page, no network (GREEN)
- `snapshot` — read visible page text/links (GREEN)
- `move --x N --y N` or `move --selector SEL` — move the agent cursor (GREEN)
- `wait` — wait for load (GREEN)
- `reload` / `back` (GREEN)
- `open URL` — navigate in the WEB tab (YELLOW; one.com and wp-admin are RED)
- `hover SEL` / `click SEL` / `type SEL TEXT` (YELLOW)
- `key Enter --selector SEL` (YELLOW; Tab/Escape/Space/arrows too)
- `tab-new` clicks the + tab; `tab-new URL` types the URL in the address bar; `tab-new --selector A` middle-clicks a link
- `tab-close` / `tab-next` / `tab-prev`
- `open URL` types the address in the WEB address field, then goes
- `forward` / `select SEL TEXT`
- `scroll --dy N` (YELLOW)

SNAPSHOT also writes `web-operator/view.png` of the visible pane.

Do not TYPE into password fields. GG types one.com / wp-admin logins in the pane.

Do not call `open_page` or `web_fetch` for this work. If `gg-web` returns `OPERATOR_TIMEOUT`, the desktop WEB tab is not running.
