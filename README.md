# Claude Code Sessions

A macOS menu-bar app for your **Claude Code** sessions, via [SwiftBar](https://swiftbar.app). It
lists every session Claude has on disk, shows which are **live** in iTerm **or** Terminal, and on
click **jumps** to the running tab/window or **revives** it with `claude --resume`. It also opens a webview **panel** with
AI one-line summaries, context-usage, status, search, and a per-session stats page.

## Install

**Prerequisites — install these yourself first:** macOS, [SwiftBar](https://swiftbar.app)
(`brew install --cask swiftbar`), a terminal — [iTerm2](https://iterm2.com) or the built-in
**Terminal.app** — the `claude` CLI, and `python3` (ships with macOS). Then run:

```sh
curl -fsSL https://raw.githubusercontent.com/spacegrowth/claude-sessions-swiftbar/main/install.sh | bash
```

The script **only installs the plugin** — it downloads the files into SwiftBar's plugin folder and
reloads SwiftBar. It does **not** install SwiftBar, a terminal, or `claude` (it just warns if SwiftBar
is missing). Re-run any time to update. To remove it, run the matching `uninstall.sh` the same way
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
revive resumes the exact conversation. Liveness is detected across **both** iTerm (by tab title)
and Terminal.app (by each tab's running process), so a session lights up — and Jump goes to — the
right app either way. Choose which terminal opens new/revived sessions (and tab vs window) in the
panel's ⚙ **Settings**. The only thing written back is an archived flag in `~/.ccsessions/`.
Summaries are generated with `claude -p` (Haiku) and refreshed only when a session changes.
