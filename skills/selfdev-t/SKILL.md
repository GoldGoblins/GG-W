---
name: selfdev-t
description: Pack SELFDEV into one line where each word is one task. Use when compressing a prompt, writing a HANDOFF, or running a cheap self-loop in the GG AI Desktop prompt box.
---

# Author the prompt first

Write the SELFDEV prompt **as you would write it for yourself**: exact, detailed, based on what this house already can and still cannot. That text lives in `SELFDEV-PROMPT.md`. Update it when the facts change. Do not ask the user to invent the next round.

Then pack **only** the dispatch line into the prompt box. The box is one line. The brief is the file.

# T-line

The prompt box is **one line**. `\n` submits. Pack with ` // `.

Every word after `R:` is one task (one token). Do not write sentences there.

```
T // M:TS Y A=0 // N:<facts> // R:<task> <task> // D:<check> // H:T // R:<next>
```

| Field | Meaning |
|---|---|
| `T` | this is a packed work order |
| `M:` | mandate. `TS` = TASK_SCOPED. `Y` yellow ok. `R` red no. `A=0` authority none |
| `N:` | already true. Do not rediscover |
| `R:` | this round, max two tasks |
| `D:` | observable done-when |
| `H:T` | next line is the same shape |
| last `R:` | next round’s tasks |

Lexicon: `lexicon.txt` in this folder (one token per line, `token TAB meaning`).

Encode/decode:

```
python3 .grok/skills/selfdev-t/pack.py encode "natural text"
python3 .grok/skills/selfdev-t/pack.py decode "T // …"
```

## Loop

End of a `T` turn: click the prompt box (`gg-desk find grokTuiPrompt` then click), type the `H:T // R:…` line, Enter. If this turn is still running, Enter twice.

User restarts the desktop process. Agent RELOADs QML. No one.com, no cart, no wp-admin, no FIND https.

Unknown token → stop and ask. Do not invent tokens in `R:`.
