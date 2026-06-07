# Claude Code Sessions

A macOS menu-bar app for your **Claude Code** sessions, via [SwiftBar](https://swiftbar.app). It
lists every session Claude has on disk, shows which are **live** in iTerm, and on click **jumps**
to the running tab or **revives** it with `claude --resume`. It also opens a webview **panel** with
AI one-line summaries, context-usage, status, search, and a per-session stats page.

## Install

Needs macOS, [SwiftBar](https://swiftbar.app) (`brew install --cask swiftbar`),
[iTerm2](https://iterm2.com), the `claude` CLI, and `python3` (ships with macOS). One line:

```sh
curl -fsSL https://raw.githubusercontent.com/spacegrowth/claude-sessions-swiftbar/main/install.sh | bash
```

Re-run any time to update. To remove it, run the matching `uninstall.sh` the same way
(append `-s -- --purge` to also delete `~/.ccsessions`).

## What you get

**Menu** — sessions grouped by directory with green/grey live dots; per session: Jump / Revive,
Rename, Archive, New-session-here, and a remap tool for directories you've moved or renamed.

**Panel** (the first menu item) — Live / Parked / Archived tabs and a search that highlights
matches across name, summary, and directory. Each row shows a Claude-written summary, a status
bar, a context-usage ring, the model, and a "waiting on you" pill when it's your turn. Click a
row to jump/revive; click the ring for a **Stats** page (turns, tokens, cache, tool-uses). An
**Insights** button opens — or triggers — Claude Code's own `/insights` report.

## How it works

Reads `~/.claude/projects/*/*.jsonl` **read-only**: the filename UUID *is* the session id, so
revive resumes the exact conversation. Liveness is matched against iTerm tab titles. The only
thing written back is an archived flag in `~/.ccsessions/`. Summaries are generated with
`claude -p` (Haiku) and refreshed only when a session changes.

## Hacking

It's a small, stdlib-only Python package — `ccsessions/app.py` (logic) + `ccsessions/panel.html`
(the webview) + a thin `ccsessions.5s.py` entry, with `test_ccsessions.py` covering it. Want a
feature? Point Claude Code at the repo and ask — the structure is easy to pick up.
