"""ccsessions — "Agent Sessions": a SwiftBar launcher for Claude Code and Pi sessions.

Two modes:
  (no args)            render the SwiftBar menu
  open      <id>       focus the live iTerm session, or revive it
  rename    <id>       type /rename into the live tab (renames session + tab)
  archive   <id>       hide the session from the main list
  unarchive <id>       restore an archived session
  delete    <id>       permanently delete the transcript (confirm dialog)
  new  [dir] [harness] open a fresh session (claude or pi; default = pref)
  newpick [harness]    pick a folder, then open a fresh session there
  archivedir <cwd>     archive every parked session in <cwd>
  remap     <cwd>      repair sessions whose directory was renamed/moved
  set       <k> <v>    set a preference (Settings menu) — k in DEFAULT_PREFS

Sessions are auto-discovered from ~/.claude/projects/*/*.jsonl and Pi's
~/.pi/agent/sessions/*/*.jsonl (read-only); each carries its "harness".
The filename UUID *is* the Claude session id, so we resume with the exact id;
Pi resumes from its exact transcript path (`pi --session <file>`).
Names come from Claude's own title (your /rename → custom-title, else ai-title);
Rename drives Claude's /rename (live only). Only the archived flag lives in
~/.ccsessions/state.json.
"""

import json
import os
import re
import shlex
import subprocess
import sys

# ───────────────────────────── config ─────────────────────────────
# AppleScript target. iTerm2 responds to "iTerm" on most installs; some
# versions answer to "iTerm2". Switch this if osascript can't find it.
ITERM_APP_NAME = "iTerm"

# Human label per backend key (live_app), shown when live sessions are split
# across both apps so you can tell where a "Jump to" click lands.
APP_LABEL = {"iterm": "iTerm", "terminal": "Terminal",
             "other": "tmux"}  # "other": live in a tty neither app owns (tmux, another terminal)

# User-toggleable preferences (changed from the Settings ▸ menu, stored in
# prefs.json). These are just the defaults used until the file overrides them.
#   revive_in / new_in: "window" (new window) or "tab" (new tab in front window).
#   skip_permissions: start NEW sessions with --dangerously-skip-permissions.
DEFAULT_PREFS = {"revive_in": "window", "new_in": "tab", "skip_permissions": False,
                 "terminal": "iterm",  # which terminal opens new/revived sessions
                 "scan_workspaces": True,  # discover multi-worktree dirs for New session ▸
                 "summaries": True,  # generate Haiku one-liners for each session
                 "summary_every": 24,  # hours between summary passes (0 = every refresh)
                 "claude_bin": "",  # explicit path to the claude CLI; "" = auto-detect
                 "harness": "claude",  # which agent New session starts: "claude" or "pi"
                 "show_pi": True,  # list Pi sessions (~/.pi/agent/sessions) alongside Claude's
                 "remote_hosts": ""}  # ssh targets (comma-separated) whose sessions to list too

# Command used to start Claude. Use an absolute path if it's not on the
# PATH of freshly-spawned iTerm sessions.
CLAUDE_BIN = "claude"
# Same for Pi (pi.dev's coding agent). Its sessions are listed next to Claude's;
# each session dict carries "harness" ("claude" / "pi") and everything that
# differs between the two (transcript format, resume command, rename command,
# liveness) dispatches on it.
PI_BIN = "pi"
HARNESS_LABEL = {"claude": "Claude", "pi": "Pi"}

MAX_NAME_LEN = 55  # display name / iTerm session name length cap

# Title shown on every user-facing dialog and notification (macOS surfaces it
# as the bold header / sender line). Purely cosmetic.
UI_TITLE = "Agent Sessions"

# The Claude Code logo (lobehub claudecode-color, transparent), downscaled to
# 18px, as a base64 PNG shown on the panel menu item via SwiftBar's image=.
CLAUDE_ICON = "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAHhlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAABKgAwAEAAAAAQAAABIAAAAAqSaGYgAAAAlwSFlzAAALEwAACxMBAJqcGAAAAdhJREFUOBHdUk1rFEEQraqe2V2zKDl4ylH8Qq+Sq/4HDSsIogfxBwQ/jntU0V/gQS9ClnjzKGgEDxJyVdSIJxECHqJhM5vp7iqrJlujUfEHZGCmeuq9fu/11ADs2wv9ZG+HC50Z6M/A5qa3/l9nZ2Ebxtunh8u1EQtnl+PifOjW96tuFwQEEVAc+706diDV0I3lomJLhrdCErgfqJgriEBVgOWfOkBIYFAgBKHcdxPyhTCKSkDi/CaxXDchZoE8vW1tPcOMY1yL7vt/CRFktCiAGxjDayf8WXcx5SiXEbPj+OHW4HnzgjBXIJ1KzN9U7LPazTtpb8VVxY7oJzichd9pyK+G48bwchOvThnGMUFQJzt/zLx3//StDBrdjqsK/bKAThEapPhe1Td2OTLfCbRgApzbo/8l5gbKhSqm5SpmTaiJnPnx9sUrh3rlo61JBHOtVbA3dXPORFObgIkd7JXwYxKvHr+z9NjwdvyceX0S0wqDHNtJeU1nfLZK8hQ0YCNEQDq2Czsir9T+jHLXbU+D6aNNZI33NweXiOSa/imLWWh04u7oqBOt6mA+BeQBAz5gxocn742eON6O3xpB+IsIvkCkLXV49nJ4rk1sa+sZZhzjusg+rz8B+HTi9Lw/v8EAAAAASUVORK5CYII="
# Same Claude Code logo at 72px for the panel heading (shown at 36px → crisp on
# retina); kept separate so the menu icon stays small.
CLAUDE_ICON_LG = "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAAAAXNSR0IArs4c6QAAAHhlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAAEigAwAEAAAAAQAAAEgAAAAAo75y2AAAAAlwSFlzAAALEwAACxMBAJqcGAAABQ1JREFUeAHtmj1sHEUUx+frbp0Agp4KG2GkiAoEJRR0oQ12Kjqa0CE5FqEFEYRIAz0NSoIVJOQKUSBKEC0SiTCkAcVSghT5wL7dnRn+7+7Gt7vO3UzOd+Ycv5Hs/Zg37735zey9tzMrBBcmwASYABNgAkyACTABJsAEmAATYAJMgAk8UgRkSm9ura9camv9WrcsfYr8vMtkxshu6b5fvnztw5ivJibQr5cvLhj9eprs/EsttLQoSns/xdMkQN6LoltaQX+PQpF4bvAoFCl9USlCJ1mGAUVGnwExoAiBSDXPoAigpCgW0dGrzowWmsLDoJTOidy6cDnTY1srYdRwrC3C7rQi7lQAKYBB4vU5gufvQnopvPSIoy8brVYI1CwLgclLdz2X7qd920IuwqcLDqAOW6YCiOaN8eKLpY+v/xwcurV+/rxREoDCndkcYUNYr7557qOrV4OFrbXVlzBMF8L1YY7DeXkYLWiLl5BTdRU+q1/P8qpu66Avk9ueGqDJXZjvlgwoMj4MiAFFCESqk2YQ4nY0Fikvy6otRJEje/Vv2mr6UvUrnCPyRvtEsubXtXPLodGoI7KJJ2MphVVuEbr+DjqU80/D8ZkX8otsVfthhVs0YrRxauO8eKraZpSj8ubFlb1RlZX7LZzHZhutr9CokGeUoWn8TSXPgp5YodlLMzbYJl/J53GFfCWfR5NEpUESHM1XYrOHvICVVs0UEBGloyiwTRNmOBhptukFINp3k9L5lE72YBwVkYZDk9pO6XvssWm4cvIuGVBkzBkQA4oQiFRjtWBslOs19/g1+59+fyPuT15NvZYJfTdYVPpnnBkCA2UUDodhdFyDY1KHfpXoezc2PYy37oVxfcJSqs+9+CzT6mzXHtnbwziXDl2XaS261n2bSfEOlmbHMjLPf7LxR8zizbXVTsJsjKmZm/peX7zoPHP52u2YU2lRTNZy5JjO41Gf2Kc0QMejyzPxkgFFsDIgBhQhEKlOym2QMyhKKENSSbkRJY/VEurCPUotGyL77YPMpMfmhiBFpeZv7kGZoQT5Sn1KsZ8ECPY72M69T0ZxTv2mxajHqgac8B3sp9I3euQvyVByWdsrQ/sd1FmSqbZNPR/opYW4J6ptYGwXJrv7tvtrQ4/XZXoJcUEytDUNXZ1q/ajzJEBlbt89bdrvC1MI/y8stPWrWskvw7Yy7ck759/yhftRnIarkBGZfhPJ5ae0Rz4glmPc3vDGb41yJnYfnROylEvo3nfQ2e6NAr4JQNJ3yXftV8G2bKlXMOVvEAgqtD1tnX/b5/YHktEYuzLfBdR4SQJ05srG/lozqdx6b3W7+XKGaXvn2SsbfwaTWMq915gmvpD+rzMfDGWC7MMcf1k/d8rQ3v+g9Gx4f2+5Yvu3i6t3Qn04InneXqrIhPuxY9Jz2FSC2ULTvFbwIUftHl4ED+jWDZmagsSLB+lo2mr6Qqof5HOKyQOdSGl0kmQYUGS0GRADihCIVCdFsaYOpIwKX96LwvXjFG2u7VpXm424pUmGwg2+cRJ7pcuwBdoIbE3N8WupnZReZwtG0e6oIBu5c7UAoYSEfwpJWT/YtRDmd4u0xLDpwUSAkCNv71m7aQffINKSU67U3apyZ8XtvdJu5vR1PurhayG02qnKTHSu1I4v/dfQ3SL6RJxsVXXlStxVZblJGSkVq3t5/Xb/iv8zASbABJgAE2ACTIAJMAEmwASYwLwT+A/0oKuLZqTxXgAAAABJRU5ErkJggg=="

# Menu-bar icon (purely cosmetic — NOT the terminal app being driven; that's
# ITERM_APP_NAME above). Rendered via sfimage, so any SF Symbol name works.
# Set MENUBAR_SFSYMBOL = "" to show plain MENUBAR_TEXT instead of an icon.
MENUBAR_SFSYMBOL = "terminal"
MENUBAR_TEXT = "CC"

HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
INSIGHTS_DIR = os.path.join(HOME, ".claude", "usage-data")  # where /insights writes report-*.html
# Pi keeps one folder per cwd under <agent dir>/sessions, one <ts>_<id>.jsonl per
# session. PI_CODING_AGENT_DIR relocates the agent dir, as it does for pi itself.
PI_AGENT_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent"))
PI_SESSIONS_DIR = os.path.join(PI_AGENT_DIR, "sessions")
PI_MODELS_FILE = os.path.join(PI_AGENT_DIR, "models-store.json")  # per-model contextWindow
STATE_DIR = os.path.join(HOME, ".ccsessions")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CACHE_FILE = os.path.join(STATE_DIR, "cache.json")
PREFS_FILE = os.path.join(STATE_DIR, "prefs.json")
GITCACHE_FILE = os.path.join(STATE_DIR, "gitcache.json")  # cwd -> repo/worktree/dir
SERVER_FILE = os.path.join(STATE_DIR, "server.json")  # {port, token} for the webview
LAST_OPEN_FILE = os.path.join(STATE_DIR, "last-open.json")  # snapshot of open windows/tabs to restore

# Webview management panel: a tiny localhost server (see do_serve). SwiftBar's
# webview can't load file:// or call back via JS, so an interactive panel needs
# http. The server is 127.0.0.1-only, token-gated, and idle-exits — render_menu
# keeps it alive while SwiftBar runs and it dies on its own once SwiftBar stops.
WEBVIEW_PORT = 53682
SERVER_IDLE_TIMEOUT = 60  # seconds with no request before the server quits

# Per-session one-line summaries, generated by `claude -p` on the recent tail of
# a transcript and cached (keyed by mtime+size) so each changed session is
# summarized at most once. A lock-guarded background `summarize` pass, spawned
# from the render, keeps them fresh; the panel shows them as row subtitles.
SUMMARY_FILE = os.path.join(STATE_DIR, "summaries.json")  # {sid: {mtime,size,summary}}
# Why the last summarize pass couldn't do its job, if it couldn't ({} when healthy).
# A failing pass caches nothing and simply retries, which is indistinguishable from
# "still working" — so the reason has to be recorded somewhere the panel can show it.
SUMMARY_STATUS_FILE = os.path.join(STATE_DIR, "summarizer-status.json")
NO_CLI_ERROR = ("Claude CLI not found — summaries are paused until it's on PATH. "
                "Set an explicit path with:  claude_bin  in ~/.ccsessions/prefs.json")
SUMMARY_MODEL = "haiku"   # fast/cheap Claude model for the one-liners
SUMMARY_MAX = 128         # hard cap on summary length
# Every `claude -p` invocation is a brand-new session server-side (even with
# --no-session-persistence, which only skips the local transcript), and a
# per-session, every-30s summarizer was showing up as tens of thousands of
# "sessions" a week in usage. Two levers keep that in check:
#   * a pass runs only every `summary_every` hours (pref; default daily) — see
#     summarizer_due(). "Re-summarize" in the panel forces one.
#   * each call summarizes a BATCH of transcripts, so a pass over N changed
#     sessions costs ceil(N / SUMMARY_BATCH) sessions, not N.
SUMMARY_BATCH = 8         # transcripts per Claude call (8 x 2.5k chars ≈ 5k tokens)
SUMMARIES_PER_RUN = 64    # sessions (not calls) per pass: a daily pass should
                          # clear its backlog — 64 sessions is 8 calls
# Flags that keep a summary call lean. Not a speed win on their own (the call is
# almost pure network wait), but they keep it hermetic:
#   --safe-mode: ignore the user's CLAUDE.md, skills, plugins, hooks, MCP servers
#     and agents — none apply to a one-shot summary, and MCP startup can cost
#     seconds. Auth is untouched (unlike --bare, which drops OAuth).
#   --tools "": no tools, so the model can't spend turns in a tool loop.
#   --no-session-persistence: don't write a transcript for our own call (the one
#     discover() would otherwise see; see summarizer_proj_dir()).
# generate_summary retries without them if an older CLI rejects any of them.
SUMMARY_ARGS = ["--safe-mode", "--tools", "", "--no-session-persistence"]
SUMMARY_WORKERS = 4       # how many of those calls run concurrently. Each call is
                          # ~all network wait (the CLI itself starts in ~40ms), so a
                          # pass is latency-bound: 4-way concurrency cuts a full run
                          # of 8 batches from ~8x to ~2x a single call.
SUMMARY_LOCK_STALE = 300  # a summarize lock is "stale" only if not heartbeated for
                          # this long (> one 180s batched Claude call); a live pass
                          # refreshes it per batch so it never looks stale and stacks
SUMMARY_MIN_INTERVAL = 300  # don't re-summarize the same session more often than
                            # this (s) even if it changed — caps cost on LIVE
                            # sessions whose transcript appends constantly
# `claude -p` itself writes a session transcript, which discover() would pick up
# and summarize recursively. Run those calls from a dedicated cwd so their
# transcripts land in one project folder, and exclude that folder everywhere.
SUMMARY_WORKDIR = os.path.join(STATE_DIR, "summarizer-cwd")

# Remote hosts: sessions on other machines (e.g. a headless box running agents in
# tmux), reached over ssh. A background `remote-scan` runs one python script per
# host (built from this module's own parsers, see remote_script) and caches what
# it found; the render only reads the cache. Remote session ids are
# "<host>#<id>" so they can't collide with local ones in state/summaries.
REMOTE_CACHE = os.path.join(STATE_DIR, "remote.json")  # {host: {ts, ok, error, hostname, sessions}}
REMOTE_SCAN_TTL = 15          # re-scan at most this often (s) — liveness should feel current
REMOTE_SCAN_LOCK_STALE = 90   # reclaim a scan lock not refreshed within (s)
REMOTE_SSH_TIMEOUT = 40       # one host's whole scan
# BatchMode: never prompt (a background job can't answer). The control master
# keeps one connection per host open between scans, so a scan costs a round trip,
# not a fresh handshake.
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"]

# Background workspace discovery: find directories that group multiple linked
# git worktrees (the same "workspace" notion compute_dir_kind already uses), so
# the New-session menu can offer them even before any session is rooted there.
# The scan walks the user's home once every few minutes in the background and
# caches its result; the render only reads the cache (never walks inline).
WORKSPACES_CACHE = os.path.join(STATE_DIR, "workspaces.json")  # {ts, roots:[...]}
WORKSPACE_SCAN_ROOT = HOME            # where to look; generic, no assumed layout
WORKSPACE_SCAN_MAXDEPTH = 6           # bound the walk (workspaces live shallow)
WORKSPACE_SCAN_TTL = 300              # re-scan at most this often (s)
WORKSPACE_SCAN_LOCK_STALE = 120       # reclaim a scan lock not refreshed within (s)
# Heavy/!interesting trees pruned from the walk (names only, matched anywhere).
# Repos and worktrees are pruned dynamically (we stop at any child holding a
# `.git`), so this list only needs the big non-git sinks.
WORKSPACE_SCAN_PRUNE = {
    "node_modules", "Library", "Applications", ".Trash", ".cache", ".npm",
    ".cargo", ".rustup", ".gradle", ".m2", ".cocoapods", "Pods", "DerivedData",
    "venv", ".venv", "site-packages", ".tox", "dist", "build", ".next", ".nuxt",
    "target", ".terraform", "Pictures", "Movies", "Music", ".git",
}

CONTEXT_WINDOW = 200000       # standard context window (the ctx-% denominator)
CONTEXT_WINDOW_1M = 1000000   # Opus 4.x runs Claude Code's 1M-token window

SELF = os.path.realpath(sys.argv[0])  # the entry plugin SwiftBar ran

GREEN = "#34C759"
PARKED_COLOR = "#AEAEB2"  # lighter gray, keeps the parked dot subtle
HEADER_FONT = "HelveticaNeue-Italic"  # group headers: italic (not grayed-out)

# Claude formats iTerm tab names as "<glyph> <title><sep><path>" where <sep> is
# NBSP + em-dash + NBSP. Match the title bounded by that separator (not a loose
# substring) so e.g. "build" can't match the tab "nightly_build_pipeline — …".
TAB_TITLE_SEP = "\u00a0\u2014"  # NBSP + em dash: the boundary right after the title

# Status dots in the dropdown: live = running (green), parked = idle (gray).
#
# These are the SF Symbols "circle.inset.filled" / "circle.dotted", pre-rendered to
# @2x PNGs (32px of data, 16pt logical) and tinted GREEN / PARKED_COLOR above.
#
# They're emitted with image=, NOT sfimage= + sfcolor=. SwiftBar builds the sfimage
# with the palette colour applied and then unconditionally runs
#     image?.isTemplate = true          # MenuLineParameters.swift
# so AppKit re-tints the glyph with the menu's text colour and sfcolor is silently
# discarded — which is why the dots always rendered dark. image= decodes with
# isTemplate:false and keeps its colour: the same mechanism that makes the
# CLAUDE_ICON crab render orange. Regenerate with scripts/render_dots.swift.
LIVE_DOT_IMG = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAACQAAAAAQAAAJAAAAABAAKgAgAEAAAAAQAAACCgAwAEAAAAAQAAACAAAAAAxqyL9QAAAAlwSFlzAAAWJQAAFiUBSVIk8AAABLdJREFUWAntV01sVFUUPufNvFIkhijGBGGlMVUQCZ0pbaeNRNkYUbExtdMWTTTBDbowBg1ipCYU/EnEBXEhQRfQv6DBxops2gShM1PaaYNaoS5MTEQSgi5oQNKZ947fufMenTcd2k670AUnee/cn3O+8917z7v3PqLb8h/PAJcSvzbRuCpjhZ4j4Xr4VeC5m0hcIusKCV1A/ZSUSW862nVlvrjzIhBJtK4jdt+H8VYAW3OAZ0Cwm21qG67q/G0OW5qdgBBHUy17MMrdAAormBD9AqeTCHKOSS4Lu1C8EkgboJ+Cvt8LegP1nSOxzoNevai6JYFHz724zL6ePQKDBvVElBS51tvDdZ0/FEXyGisTrU9b7O5H9RFtAuFDZN+5Ix39POOZBJQZVaBFK9JmlaUmulB6Bo+Dhp3Dtd0HtKs61bo6K66SqgepVaCWZeKLIjSQW/+OPvifiAxN7GWhXRjAdslMquur+iqUojMQSTXvU2cYZ12xGkZjHX2RkcblPGW3E4sC2YVAXv0ai3xyfbmzd3ztsaloIv4KMR82fcKvF1uOGQSiiZaNCJKEk4U1NE6RwaYH2LL60PaQF2gulRCbturXkDeYGxzmtYWJOTOjmfaZ4MT9ynjd6Za7yLK+LyG4kotxhnrXjjeWpasr3kX9ZzzlkqE26IAECFQmmx7Gem9WCyHnLdVLbPkU0/SglkuUWPlkeDdxm4tl1OVEukg8MtJ8Tz5OgEBIrMZcpwyma3tGkXBrwGRbvkMpZeTRmxuHXlqhOQQc3RNsnmLdS25KgIAwP6Y9LPydatd14lABG20vQZaJZJ419iwnPL9N+f4F4IIlMDKmbxB6PFdd+FtcD0PIYALVj2FACwjQCm3lkHspF1K/80UKy2qDwJLDZDExfNRCAqaeFQsbmIoVyulFvQ0m38TkQMxABWH+1lAh4XtNSJaLRi/mxfSnuuNYyWF6MXzIIAGmCe1wWdZ7Bmd8w4VqET5tfKcxTQwfL0hAxATE5/OkGrjEPb7hAvUU2dY36os1NZj4xAKDChAQkq+9QE9Ez2yrGK3pTJNI7wKDI5vps3T06KWqRPMmbGZrgOParmMI+ZgBArr5oGMIjyUhZ78a2eTsAH3vq9CWeYrQ+JLs0veMNcsHqjELvcnYsUBeBQioEU4zvXyAPDVUJeNNOQfZUiKJC47wlsH6LyajyfgbSMAaQGZJrD2KnS8zCAzHuvvB9JAawfHLylRrzUise8ymbBXaj+c7Fynr3eGw2NmasbrO3/VygqF8nLPj9nSs46dCHwx0pugptvRquB89evn8BxePl3EhMQkZSTZVWsQvgIz23YcHQfkP7JoDIXZ6zlb3/Io2wrH+GqbzAIphJZ6u6Xper1Xaly9FCaiBHiKum9GE0UDqeZyd0K6R+qOBz0j78kUJMoU+goc5VdH37dQd4eYf1x+5lm/nl29JQA10Jsqvhg/CaLvn4EIPCNNJC5dSh+VyGJdScayVaN8gjFwhrvNtYfehuQ/gSPbaZqhZCfjWVYn4ZkxxO+rVftvsmvsxZe/gQnN2djuT7HOZTPfnppexlvgxEf/HBPsV0V+AOo8RnxJxvhqt7Tk/7XW79D+fgX8B3x+nzGyruiwAAAAASUVORK5CYII="
PARKED_DOT_IMG = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAACQAAAAAQAAAJAAAAABAAKgAgAEAAAAAQAAACCgAwAEAAAAAQAAACAAAAAAxqyL9QAAAAlwSFlzAAAWJQAAFiUBSVIk8AAAA55JREFUWAntVk9IFFEYf2921DTNgqSCIlLwoLFUZnURXAwzabXdtZWoDmLkLelQEJaIF8GCgi4R0aVDsezspLOZUWIgYocStILsUBCEkBRJZbs7s/P6vXBiZxx3V92L4IPZ9973/b4/+33ve+8jZG2spgh0dXUJsixv5D7zdSik3JTlvkvGfwiHw5uMdbqzkC6Q45zOfXcZc8xIUv+hsrKKbYSwdsboVc6DM6diMf17okOcnmqkdCAYDB+RpEeHuSIY+41JJYTG/H73F6yPC4JQz3mE6H/wE8c3x3ey3O+Ho5V8nWzQZMxAIJAviutmgWGzswX5LS2uyPDwsOhyuTQ7OYMXCoV3w6E3lJLPHk/DTjusQUsaAb/f/wvAXsZYDzfOhRYznsjTtLkPjJE7iFgvpycbthGQJKUZQhdguLWpqeFdMgWpeKFQXx1S1g2Hzvt8DS+t+EUiwOooZQcdDpIyh1aFC/e0BrRKSmnVQh4hoh0xN1dsj0bjDyYmXj+34y+FpmmRTlHMGZqZmR6ykzOlQFGUPJTSZQAHfb7GUTuB5dKQCi8hQonHc+w6osEMPaYIaBo7CuYVMHm4qg1QZmZ6G8VUJElhBfreGzpNDogifaKqrFsQ9KcGIFMzKqINpVmMQ/3feKZ0r0iP6Qzg5gri8tiVlUWr3G73vxttRdoThBH6Ykr1ZyA99HobOgyWKQUwXgHGVlVV8zFn1AGcuy3QCSfIHsM4ny33gLYf+S/1er1fE0GZWHu97jFdp6U4ZycS9ZkcgOFvYO5YzrOaqNRuLUkD2wWB5FlTa3KAv3y6LozGYuy+nZKV0CjVRlCG45L02PQ4mc6Aw6FOEeJ4hXLhhyWjA7lX8B6UZ2frM2kp5h1PWsA0QMl02RoJhfo70P3MSVKfKw39SSEo7TansyKCBsVnB7R1ALkqBDgb1/J6O6Gl0KBjA/RlQaYgbTn0ARQP02YuIMtKDb7qtIXngegpPMFg316+DQQGihaTN92EVtB8S/YDdN6SFRhdkRVn3QeD/eUoubc4eClbMlMVWBXxlgzn4QbocW4cHe9pBKeZMfWcz+eb5lHSdT3a2Nj4E//WKQj0GkLek5PjGItE4vdQTZNWndZ9Ugc4GPf2RUMIxs9gXUtp1oFAYHBEVWMf0W7xsipB91SHMqtFsKbq6+tfgNaKL+VY5BDay+GaPouwNk1OjiuFhTQKFG/NP3G0qkZvwfhJBKuT79fGqonAX9a2Tp5IMpCUAAAAAElFTkSuQmCC"  # "" = no icon (just the name)

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def menubar_title(count):
    """Menu-bar line: SF Symbol via sfimage (reliable), or plain text."""
    label = "?" if count is None else str(count)
    if MENUBAR_SFSYMBOL:
        print(fmt("", label, sfimage=MENUBAR_SFSYMBOL))
    else:
        print(fmt("", f"{MENUBAR_TEXT} {label}".strip()))


# ─────────────────────────── small helpers ────────────────────────
def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    # Per-process temp name: SwiftBar may run this plugin concurrently (a 5s tick
    # overlapping a click), and a shared "<path>.tmp" would race on os.replace.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)  # atomic; concurrent writers each replace their own tmp


def load_prefs():
    """DEFAULT_PREFS overlaid with whatever the Settings menu has saved."""
    prefs = dict(DEFAULT_PREFS)
    prefs.update(load_json(PREFS_FILE, {}))
    return prefs


def set_pref(key, value):
    if key not in DEFAULT_PREFS:
        return  # ignore unknown keys
    prefs = load_json(PREFS_FILE, {})
    prefs[key] = value
    save_json(PREFS_FILE, prefs)


def sanitize(text):
    """Make a transcript-derived string safe for a SwiftBar title and an
    iTerm session name, and cap its length. The result is used verbatim
    everywhere (menu, iTerm name, liveness compare) so they always agree."""
    if not text:
        return ""
    text = _CTRL.sub(" ", text)
    text = text.replace("|", "¦")  # '|' is SwiftBar's separator
    text = " ".join(text.split())  # collapse whitespace/newlines
    if len(text) > MAX_NAME_LEN:
        text = text[: MAX_NAME_LEN - 1].rstrip() + "…"
    return text


# ─────────────────────────── discovery ────────────────────────────
def parse_session(path):
    """Return (cwd, title) by scanning a transcript. Cheap and tolerant:
    cwd = first line that has one; title = your /rename (custom-title), else the
    latest ai-title, else the first user prompt. A bad/partial line never aborts."""
    cwd = None
    custom_title = None
    ai_title = None
    first_user = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if cwd is None and obj.get("cwd"):
                    cwd = obj["cwd"]
                if obj.get("isMeta"):
                    continue  # injected meta (e.g. a slash-command expansion) — never a title
                t = obj.get("type")
                if t == "custom-title" and obj.get("customTitle"):
                    custom_title = obj["customTitle"]  # user's /rename — wins
                elif t == "ai-title" and obj.get("aiTitle"):
                    ai_title = obj["aiTitle"]  # keep the latest one
                elif first_user is None and t == "user":
                    msg = obj.get("message") or {}
                    content = msg.get("content") if isinstance(msg, dict) else None
                    text = None
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text")
                                break
                    # Skip command/caveat meta (e.g. "<local-command-caveat>…",
                    # "<command-name>…") — keep scanning for a real prompt.
                    if text and not text.lstrip().startswith("<"):
                        first_user = text
    except OSError:
        pass
    return cwd, (custom_title or ai_title or first_user or "")


def short_model(model):
    """Friendly model name: 'claude-opus-4-8-…' → 'opus-4.8', 'claude-3-5-sonnet-…'
    → 'sonnet-3.5'. '' if unknown."""
    if not model:
        return ""
    s = model.lower()
    fam = next((f for f in ("opus", "sonnet", "haiku") if f in s), None)
    if not fam:
        return model
    m = re.search(fam + r"-(\d+)-(\d+)", s) or re.search(r"(\d+)-(\d+)-" + fam, s)
    return f"{fam}-{m.group(1)}.{m.group(2)}" if m else fam


def context_window(model):
    """The token window to measure ctx % against. Opus 4.x runs Claude Code's
    1M-token window; everything else uses the standard 200k."""
    m = re.match(r"opus-(\d+)", model)
    return CONTEXT_WINDOW_1M if m and int(m.group(1)) >= 4 else CONTEXT_WINDOW


# The per-session state tail_info()/pi_tail_info() derive (and discover() caches).
TAIL_DEFAULTS = {"awaiting": False, "ctx_pct": 0, "ctx_tokens": 0, "model": ""}


def tail_info(path, tail_bytes=32768):
    """Read a transcript's tail ONCE and derive light per-session state:
      awaiting   — Claude finished its turn and is waiting on the user (last
                   message is an assistant reply with no pending tool call)
      ctx_tokens — size of the last API context (input + cache-read + cache-write)
      ctx_pct    — that as a % of CONTEXT_WINDOW
      model      — short model name of the latest assistant turn
    Cheap on large transcripts (reads only the tail)."""
    blank = {"awaiting": False, "ctx_tokens": 0, "ctx_pct": 0, "model": ""}
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(-tail_bytes, os.SEEK_END)
            data = fh.read()
    except OSError:
        return blank
    last_msg, usage, model = None, None, ""
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # a partial first line from the seek — skip it
        t = obj.get("type")
        if t in ("user", "assistant") and not obj.get("isMeta"):
            last_msg = obj
        if t == "assistant":
            msg = obj.get("message") or {}
            if isinstance(msg.get("usage"), dict):
                usage = msg["usage"]
            if msg.get("model"):
                model = msg["model"]
    awaiting = False
    if last_msg and last_msg.get("type") == "assistant":
        content = (last_msg.get("message") or {}).get("content")
        has_tool = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        awaiting = not has_tool  # trailing tool_use → waiting on the tool, not you
    ctx = 0
    if usage:
        ctx = (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
               + usage.get("cache_creation_input_tokens", 0))
    sm = short_model(model)
    return {"awaiting": awaiting, "ctx_tokens": ctx,
            "ctx_pct": min(100, round(100 * ctx / context_window(sm))) if ctx else 0,
            "model": sm}


def awaiting_user(path):
    """True if Claude finished its turn and is waiting on the user."""
    return tail_info(path)["awaiting"]


# ── Pi transcripts ──
# A Pi session file opens with a {"type":"session", id, cwd} header, then entries
# linked by parentId (Pi can branch). Conversation turns are {"type":"message",
# "message":{role: user|assistant|toolResult, content, usage, stopReason, model}};
# /name writes {"type":"session_info","name":…}.
def _pi_text(content):
    """Plain text of a Pi message's content (a string, or a list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def pi_session_id(path):
    """Session id from a Pi filename '<timestamp>_<id>.jsonl' (fallback when the
    header is unreadable)."""
    stem = os.path.basename(path)[:-6] if path.endswith(".jsonl") else os.path.basename(path)
    return stem.split("_", 1)[1] if "_" in stem else stem


def parse_pi_session(path):
    """Return (sid, cwd, title) for a Pi transcript. Title = the latest /name,
    else the first user prompt. Tolerant of bad lines, like parse_session."""
    sid = cwd = name = first_user = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                t = obj.get("type")
                if t == "session":
                    sid = sid or obj.get("id")
                    cwd = cwd or obj.get("cwd")
                elif t == "session_info" and "name" in obj:
                    name = obj.get("name") or None  # latest wins; an empty name clears it
                elif t == "message" and first_user is None:
                    msg = obj.get("message") or {}
                    if msg.get("role") == "user":
                        text = _pi_text(msg.get("content")).strip()
                        if text:
                            first_user = text
    except OSError:
        pass
    return sid or pi_session_id(path), cwd, (name or first_user or "")


_PI_WINDOWS = None


def pi_context_window(model):
    """Context window for a Pi model id, from Pi's own models-store.json (it
    lists contextWindow per model, any provider). Claude ids fall back to
    context_window(); anything else unknown → 0 (no ctx %)."""
    global _PI_WINDOWS
    if _PI_WINDOWS is None:
        _PI_WINDOWS = {}
        for prov in (load_json(PI_MODELS_FILE, {}) or {}).values():
            for m in (prov.get("models") if isinstance(prov, dict) else None) or []:
                if isinstance(m, dict) and m.get("id") and m.get("contextWindow"):
                    _PI_WINDOWS[m["id"]] = m["contextWindow"]
    if model in _PI_WINDOWS:
        return _PI_WINDOWS[model]
    sm = short_model(model)
    return context_window(sm) if sm.split("-")[0] in ("opus", "sonnet", "haiku") else 0


def pi_ctx_tokens(usage):
    """Size of the request a Pi usage block describes: fresh input + cache."""
    return (usage.get("input", 0) or 0) + (usage.get("cacheRead", 0) or 0) + (usage.get("cacheWrite", 0) or 0)


def pi_tail_info(path, tail_bytes=32768):
    """tail_info() for a Pi transcript — same keys. awaiting = the last turn is an
    assistant reply that didn't stop to call a tool (stop/aborted/error all hand
    control back to you)."""
    blank = dict(TAIL_DEFAULTS)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(-tail_bytes, os.SEEK_END)
            data = fh.read()
    except OSError:
        return blank
    last_msg, usage, model = None, None, ""
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") != "message":
            continue
        msg = obj.get("message") or {}
        role = msg.get("role")
        if role in ("user", "assistant", "toolResult"):
            last_msg = msg
        if role == "assistant":
            if isinstance(msg.get("usage"), dict):
                usage = msg["usage"]
            if msg.get("model"):
                model = msg["model"]
    awaiting = bool(last_msg and last_msg.get("role") == "assistant"
                    and last_msg.get("stopReason") != "toolUse")
    ctx = pi_ctx_tokens(usage) if usage else 0
    win = pi_context_window(model) if model else 0
    return {"awaiting": awaiting, "ctx_tokens": ctx,
            "ctx_pct": min(100, round(100 * ctx / win)) if ctx and win else 0,
            "model": short_model(model)}


def discover():
    """Scan ~/.claude/projects (and Pi's sessions dir) for sessions. Uses an
    mtime+size cache so unchanged transcripts are not re-read on every 5s refresh.
    Returns (sessions, ok); ok is False only when neither harness has a sessions dir."""
    cache = load_json(CACHE_FILE, {})
    new_cache = {}
    sessions = []
    claude_ok = os.path.isdir(PROJECTS_DIR)
    pi_ok = discover_pi(cache, new_cache, sessions)
    if not claude_ok and not pi_ok:
        return sessions, False  # signal: projects dir missing

    skip = summarizer_proj_dir()  # the summarizer's own one-shot sessions — never list them
    for proj in (os.listdir(PROJECTS_DIR) if claude_ok else []):
        if proj == skip or proj == "-":  # "-" = sub-agent transcript dir, not a real session
            continue
        pdir = os.path.join(PROJECTS_DIR, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            sid = fn[:-6]
            fpath = os.path.join(pdir, fn)
            try:
                st = os.stat(fpath)
            except OSError:
                continue
            hit = cache.get(sid)
            if hit and hit.get("mtime") == st.st_mtime and hit.get("size") == st.st_size:
                cwd, title = hit.get("cwd"), hit.get("title", "")
                tail = {k: hit.get(k, d) for k, d in TAIL_DEFAULTS.items()}
            else:
                cwd, title = parse_session(fpath)
                tail = tail_info(fpath)  # awaiting + ctx + model; one tail read, only when changed
            new_cache[sid] = {
                "mtime": st.st_mtime,
                "size": st.st_size,
                "cwd": cwd,
                "title": title,
                "awaiting": tail["awaiting"],
                "ctx_pct": tail["ctx_pct"],
                "ctx_tokens": tail["ctx_tokens"],
                "model": tail["model"],
            }
            sessions.append({"id": sid, "harness": "claude", "cwd": cwd, "title": title,
                             "mtime": st.st_mtime,
                             "awaiting": tail["awaiting"], "ctx_pct": tail["ctx_pct"],
                             "ctx_tokens": tail["ctx_tokens"], "model": tail["model"]})

    if new_cache != cache:
        try:
            save_json(CACHE_FILE, new_cache)
        except OSError:
            pass  # cache is best-effort; never let a write hiccup break the menu

    # A session id maps to one conversation; if a stale duplicate transcript
    # lingers in another project folder (e.g. a copy a remap left behind), keep
    # only the most-recently-written one so the menu shows a single, live row.
    by_id = {}
    for s in sessions:
        cur = by_id.get(s["id"])
        if cur is None or s["mtime"] > cur["mtime"]:
            by_id[s["id"]] = s
    return list(by_id.values()), True


def pi_enabled():
    return bool(load_prefs().get("show_pi", True))


def pi_available():
    """True if Pi looks installed here (its agent dir exists) — gates the Pi-only
    settings so a Claude-only user never sees them."""
    return os.path.isdir(PI_AGENT_DIR)


def discover_pi(cache, new_cache, sessions):
    """Append Pi sessions to `sessions` (same shape as Claude's, plus harness="pi"
    and the transcript `path`, which `pi --session` resumes from). Cache entries
    are keyed by path — the id lives inside the file, not in its name alone.
    Returns True if Pi's sessions dir exists (and Pi sessions are switched on)."""
    if not pi_enabled() or not os.path.isdir(PI_SESSIONS_DIR):
        return False
    for proj in os.listdir(PI_SESSIONS_DIR):
        pdir = os.path.join(PI_SESSIONS_DIR, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            fpath = os.path.join(pdir, fn)
            try:
                st = os.stat(fpath)
            except OSError:
                continue
            ckey = "pi:" + fpath
            hit = cache.get(ckey)
            if hit and hit.get("mtime") == st.st_mtime and hit.get("size") == st.st_size:
                sid, cwd, title = hit.get("sid"), hit.get("cwd"), hit.get("title", "")
                tail = {k: hit.get(k, d) for k, d in TAIL_DEFAULTS.items()}
            else:
                sid, cwd, title = parse_pi_session(fpath)
                tail = pi_tail_info(fpath)
            if not sid:
                continue
            new_cache[ckey] = {"mtime": st.st_mtime, "size": st.st_size, "sid": sid,
                               "cwd": cwd, "title": title, **tail}
            sessions.append({"id": sid, "harness": "pi", "path": fpath, "cwd": cwd,
                             "title": title, "mtime": st.st_mtime, **tail})
    return True


def group_label(cwd):
    """Header for a session: last two path components, so a repo and its
    git worktrees read distinctly (e.g. 'src/myrepo' vs
    'workspaces/myrepo-feature')."""
    if not cwd:
        return "(unknown directory)"
    parts = [p for p in cwd.rstrip("/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else cwd)


# Plain filenames that declare a multi-project workspace (VS Code / Go / pnpm / Bazel).
_WS_MANIFESTS = ("go.work", "pnpm-workspace.yaml", "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel")


def _has_workspace_manifest(cwd):
    """True if `cwd` declares a workspace the conventional way — a manifest:
    *.code-workspace (VS Code), go.work, pnpm-workspace.yaml, WORKSPACE (Bazel),
    Cargo.toml with [workspace], or package.json with a "workspaces" key."""
    try:
        entries = os.listdir(cwd)
    except OSError:
        return False
    for name in entries:
        if name in _WS_MANIFESTS or name.endswith(".code-workspace"):
            return True
    for fname, pat in (("Cargo.toml", r"^\s*\[workspace\]"), ("package.json", r'"workspaces"\s*:')):
        p = os.path.join(cwd, fname)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    if re.search(pat, f.read(8192), re.M):
                        return True
            except OSError:
                pass
    return False


def _workspace_or_dir(cwd):
    """`cwd` isn't itself a git work tree. It's a 'workspace' only when it's
    *deliberately* one: it declares a workspace manifest (VS Code/Cargo/npm/pnpm/
    Go/Bazel), OR it holds >= 2 linked git WORKTREES directly below it (an
    intentional grouped layout). A folder that merely contains some repos — or a
    single checkout, or nothing — is a plain 'dir'. Cheap: listing + stat
    (+ bounded manifest peek), no subprocess."""
    if _has_workspace_manifest(cwd):
        return "workspace"
    try:
        names = [n for n in os.listdir(cwd) if not n.startswith(".")]
    except OSError:
        return "dir"
    worktrees = 0
    for name in names[:40]:
        if os.path.isfile(os.path.join(cwd, name, ".git")):  # a linked worktree marks itself with a `.git` FILE
            worktrees += 1
            if worktrees >= 2:
                return "workspace"
    return "dir"


def find_workspace_roots(base=None, maxdepth=WORKSPACE_SCAN_MAXDEPTH,
                         prune=WORKSPACE_SCAN_PRUNE):
    """Walk `base` (default the user's home) for linked git worktrees and return
    "New session" candidates — no layout assumed:
      * a container holding >= 2 worktrees → the CONTAINER (a grouped workspace)
      * a container holding exactly 1 worktree → that WORKTREE itself (a single-repo
        workspace still shows, with the worktree/branch icon)

    Cheap by construction: prunes heavy non-git trees and stops at every git
    boundary (a child with a `.git`, file OR dir), so it never enters a working
    tree — only the plain container dirs between you and your worktrees."""
    base = os.path.realpath(base or WORKSPACE_SCAN_ROOT)
    roots = []
    for dirpath, dirnames, _ in os.walk(base):
        depth = dirpath[len(base):].count(os.sep)
        if depth >= maxdepth:
            dirnames[:] = []
            continue
        worktrees, descend = [], []
        for d in dirnames:
            if d in prune:
                continue  # heavy non-git sink → skip
            gitmark = os.path.join(dirpath, d, ".git")
            if os.path.isfile(gitmark):
                worktrees.append(os.path.join(dirpath, d))  # linked worktree (boundary)
            elif os.path.isdir(gitmark):
                pass                      # regular repo (boundary — don't descend)
            else:
                descend.append(d)         # plain container → keep walking
        if len(worktrees) >= 2:
            roots.append(dirpath)         # grouped workspace → the container
            dirnames[:] = []
        elif len(worktrees) == 1:
            roots.append(worktrees[0])    # single-repo workspace → the worktree itself
            dirnames[:] = []
        else:
            dirnames[:] = descend
    return sorted(set(roots))


def compute_dir_kind(cwd):
    """Classify `cwd`: 'worktree' (a linked git worktree), 'repo' (main git
    working tree), 'workspace' (a non-repo dir that declares a workspace manifest
    or holds >=2 git worktrees below it), or 'dir' (none of those). A linked
    worktree's git-dir (…/.git/worktrees/<n>) differs from its common git-dir
    (…/.git)."""
    if not cwd or not os.path.isdir(cwd):
        return "dir"
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "dir"
    if r.returncode != 0:
        return _workspace_or_dir(cwd)  # not inside a repo → maybe a workspace of worktrees
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return _workspace_or_dir(cwd)
    gitdir = os.path.realpath(lines[0])
    common = lines[1]
    common = os.path.realpath(common if os.path.isabs(common) else os.path.join(cwd, common))
    return "worktree" if gitdir != common else "repo"


def session_group(s):
    """A session's group header: its dir label, prefixed with the host for a
    remote session so a remote 'development/app' never merges with a local one."""
    label = group_label(s.get("cwd"))
    return f"{s['host_label']}: {label}" if s.get("host") else label


def group_by_dir(sessions):
    """Group sessions by directory label; within a group live-first then recent,
    and groups ordered by most-recent activity. Returns [(label, members), …]."""
    groups = {}
    for s in sessions:
        groups.setdefault(session_group(s), []).append(s)
    for members in groups.values():
        members.sort(key=lambda s: (not s["live"], -s["mtime"]))
    return sorted(groups.items(), key=lambda kv: max(s["mtime"] for s in kv[1]), reverse=True)


def dir_missing(cwd):
    """True if the session's directory no longer exists on disk (e.g. a pruned
    worktree). cd-ing into it would fail, so revive/new must handle it."""
    return bool(cwd) and not os.path.isdir(cwd)


def encode_project_dir(cwd):
    """Claude's project-folder name for a cwd: every non-alphanumeric char → '-'
    (so '/Users/x/.cfg' → '-Users-x--cfg'). Resume reads a session from the folder
    encoding its cwd, so a remap must move the .jsonl into this folder."""
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def encode_pi_dir(cwd):
    """Pi's session-folder name for a cwd: drop one leading slash, '/', '\\' and
    ':' → '-', wrapped in '--' (mirrors pi's getDefaultSessionDirPath), so
    '/Users/x/app' → '--Users-x-app--'."""
    return "--" + re.sub(r"[/\\:]", "-", re.sub(r"^[/\\]", "", cwd)) + "--"


def session_harness(path):
    """'pi' for a transcript under Pi's sessions dir, else 'claude'."""
    try:
        pi_root = os.path.realpath(PI_SESSIONS_DIR) + os.sep
        return "pi" if os.path.realpath(path).startswith(pi_root) else "claude"
    except (OSError, TypeError):
        return "claude"


def summarizer_proj_dir():
    """The project-folder name Claude uses for SUMMARY_WORKDIR. Excluded from
    discovery so the summarizer's own one-shot `claude -p` sessions never appear
    in the menu/panel or get (recursively) summarized."""
    return encode_project_dir(os.path.realpath(SUMMARY_WORKDIR))


def dir_icon(cwd, gitcache):
    """SF Symbol for a group header: question-folder if the dir is gone, branch
    for a live worktree, else a book (closest SF Symbol to the GitHub octicon
    'repo' glyph) — filled for a git checkout, outline for a plain dir. Git-kind
    is cached in `gitcache`; existence is checked fresh each call (it changes when
    worktrees are added/removed)."""
    if not cwd or dir_missing(cwd):
        return "folder.badge.questionmark"
    if cwd not in gitcache:
        gitcache[cwd] = compute_dir_kind(cwd)
    return {"worktree": "arrow.triangle.branch",
            "workspace": "square.stack.3d.up.fill",
            "repo": "book.closed.fill"}.get(gitcache[cwd], "book.closed")


def display_name(session):
    # Name comes from the transcript: your Claude /rename (custom-title), else
    # the ai-title, else the first prompt. Renaming is Claude's job, not ours.
    title = sanitize(session.get("title"))
    if title:
        return title
    base = group_label(session.get("cwd")).split("/")[-1]
    return sanitize(f"{base} · {session['id'][:8]}") if base else f"session {session['id'][:8]}"


# ──────────────────────────── iTerm / osascript ───────────────────
OSA_READ_TIMEOUT = 3  # seconds; liveness reads must never hang the 5s refresh


def run_osascript(script, timeout=None):
    """Run an AppleScript. `timeout` (seconds) guards liveness reads against a
    wedged terminal — a hung Terminal.app must not block the 5s menu refresh; on
    timeout we return a failed result so callers fall back to 'nothing live'."""
    try:
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["osascript"], 1, "", "osascript timed out")


def osa(s):
    """Escape a Python string for embedding inside an AppleScript double-quoted literal."""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", ""))


# ── per-harness shell commands (what a terminal tab actually runs) ──
def with_cd(cmd, cwd):
    """`cmd` run from `cwd`; no cd when the dir is unknown/gone."""
    return f"cd {shlex.quote(cwd)} && {cmd}" if cwd else cmd


def new_command(harness="claude", skip_perms=False, prompt=None):
    """Start a fresh session. `skip_perms` is Claude-only (Pi has no permission
    prompts); `prompt` becomes the agent's initial input (e.g. "/insights")."""
    if harness == "pi":
        base = PI_BIN
    else:
        base = CLAUDE_BIN + (" --dangerously-skip-permissions" if skip_perms else "")
    return base + (" " + shlex.quote(prompt) if prompt else "")


def resume_command(s, skip_perms=False):
    """Resume session `s` in its own harness: `claude --resume <id>`, or
    `pi --session <transcript path>` (the exact file — Pi ids are only unique
    per project folder)."""
    if s.get("harness") == "pi":
        return f"{PI_BIN} --session {shlex.quote(s.get('path') or s['id'])}"
    return new_command("claude", skip_perms) + f" --resume {shlex.quote(s['id'])}"


def rename_command(s, new_name):
    """What to type into a live session to rename it: Claude's /rename, Pi's /name."""
    return ("/name " if s.get("harness") == "pi" else "/rename ") + new_name


def _parse_window_dump(text):
    """Parse a backend snapshot dump — lines 'W<tab>x1,y1,x2,y2' (a window) and
    'S<tab>key' (a tab inside it; key = tty for Terminal, session title for iTerm) —
    into ordered windows: [{'bounds':[int*4] or [], 'keys':[...]}]. Order preserved."""
    windows = []
    for line in text.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        kind, val = parts[0].strip(), parts[1].strip()
        if kind == "W":
            try:
                b = [int(float(x)) for x in val.split(",")]
            except ValueError:
                b = []
            windows.append({"bounds": b if len(b) == 4 else [], "keys": []})
        elif kind == "S" and windows and val:
            windows[-1]["keys"].append(val)
    return windows


# AppleScript that dumps a terminal's window/tab structure in the _parse_window_dump
# format. `{ttyexpr}` is the per-tab/session expression that yields its tty.
def _snapshot_script(app, inner_loop):
    return (
        f'tell application "{app}"\n'
        '  set out to ""\n'
        '  repeat with w in windows\n'
        '    set b to {0, 0, 0, 0}\n'
        '    try\n'
        '      set b to bounds of w\n'
        '    end try\n'
        '    set out to out & "W\t" & (item 1 of b) & "," & (item 2 of b) & "," & (item 3 of b) & "," & (item 4 of b) & linefeed\n'
        f'{inner_loop}'
        '  end repeat\n'
        '  return out\n'
        'end tell'
    )


class ITermBackend:
    """iTerm2 backend. Sessions live in windows→tabs→sessions; liveness is matched
    against tab *titles* (Claude sets the tab name via OSC). New sessions open in a
    new window or a new tab. The script-builders are pure (no side effects) so they
    can be compile-checked and unit-tested."""
    key = "iterm"
    app = ITERM_APP_NAME

    def running(self):
        """True if iTerm is already running — avoid launching it just to poll
        liveness on every refresh."""
        return subprocess.run(["pgrep", "-x", "iTerm2"], capture_output=True).returncode == 0

    def live_session_names(self):
        if not self.running():
            return set()
        script = (
            f'tell application "{self.app}"\n'
            "  set out to \"\"\n"
            "  repeat with w in windows\n"
            "    repeat with t in tabs of w\n"
            "      repeat with s in sessions of t\n"
            "        set out to out & (name of s) & linefeed\n"
            "      end repeat\n"
            "    end repeat\n"
            "  end repeat\n"
            "  return out\n"
            "end tell"
        )
        r = run_osascript(script, timeout=OSA_READ_TIMEOUT)
        if r.returncode != 0:
            return set()
        return {ln for ln in (l.strip() for l in r.stdout.splitlines()) if ln}

    def snapshot_windows(self):
        """Open windows as [{'bounds', 'keys'}] (order preserved); each key is a
        session *title* — matched to a session the same way liveness does, so fresh
        (un-resumed) sessions are placed too (no `ps`/`--resume` needed)."""
        if not self.running():
            return []
        r = run_osascript(_snapshot_script(self.app,
            '    repeat with t in tabs of w\n'
            '      repeat with s in sessions of t\n'
            '        set out to out & "S\t" & (name of s) & linefeed\n'
            '      end repeat\n'
            '    end repeat\n'), timeout=OSA_READ_TIMEOUT)
        return _parse_window_dump(r.stdout) if r.returncode == 0 else []

    def open_windows(self, live):
        """[{bounds, ids}] for `live` iTerm sessions, grouped by window in tab order.
        Each tab's title is matched to a live session (title_is_live) — the identity
        is the authoritative session list, the structure only orders/groups it."""
        out, used = [], set()
        for win in self.snapshot_windows():
            ids = []
            for title in win["keys"]:
                for s in live:
                    if s["id"] not in used and title_is_live(match_key(s), {title}):
                        ids.append(s["id"]); used.add(s["id"]); break
            out.append({"bounds": win.get("bounds") or [], "ids": ids})
        return out

    def restore_window_script(self, tabs, bounds):
        """AppleScript that recreates one window with `tabs` (a list of shell command
        strings) as iTerm tabs in order, then sizes it to `bounds` if given. Commands
        run via `write text` (iTerm's way), matching build_open_script."""
        lines = [
            f'tell application "{self.app}"',
            '  activate',
            '  set w to (create window with default profile)',
            f'  tell current session of w to write text "{osa(tabs[0])}"',
        ]
        for cmd in tabs[1:]:
            lines.append('  tell w to create tab with default profile')
            lines.append(f'  tell current session of w to write text "{osa(cmd)}"')
        if bounds and len(bounds) == 4 and any(bounds):
            lines.append('  try')
            lines.append(f'    set bounds of w to {{{bounds[0]}, {bounds[1]}, {bounds[2]}, {bounds[3]}}}')
            lines.append('  end try')
        lines.append('end tell')
        return "\n".join(lines)

    def restore_window(self, tabs, bounds):
        run_osascript(self.restore_window_script(tabs, bounds))

    def _match_session_block(self, key, action):
        """AppleScript fragment: walk windows→tabs→sessions and, on the first session
        whose name matches `key` (bounded by Claude's title separator, or as the whole
        tail), run `action` then return. Single source of the focus/rename match rule —
        kept identical to title_is_live() so the menu dot and the click agree."""
        key_e, sep_e = osa(key), osa(TAB_TITLE_SEP)
        # Bounded title match, kept in sync with title_is_live(): the title sits before
        # the separator (or at the tail). It's normally preceded by a status glyph +
        # space, but an idle/older tab can have NO glyph — then the title is at the
        # very start of the name, so we also match `starts with`. The space-or-start
        # boundary stops "model" matching "…_model — …".
        return (
            "  repeat with w in windows\n"
            "    repeat with t in tabs of w\n"
            "      repeat with s in sessions of t\n"
            f'        if (name of s contains " {key_e}{sep_e}") or (name of s starts with "{key_e}{sep_e}") or (name of s ends with " {key_e}") or (name of s is equal to "{key_e}") or (name of s contains " {key_e} (") or (name of s starts with "{key_e} (") then\n'
            f"{action}"
            "          return\n"
            "        end if\n"
            "      end repeat\n"
            "    end repeat\n"
            "  end repeat\n"
        )

    def _create_target_block(self, mode):
        """AppleScript that creates a new session and binds it to `targetSession`.
        mode "tab" = new tab in the front window (new window if none), else new window."""
        if mode == "tab":
            return (
                "  if (count of windows) is 0 then\n"
                "    set newWindow to (create window with default profile)\n"
                "    set targetSession to current session of newWindow\n"
                "  else\n"
                "    tell current window to create tab with default profile\n"
                "    set targetSession to current session of current window\n"
                "  end if\n"
            )
        return (
            "  set newWindow to (create window with default profile)\n"
            "  set targetSession to current session of newWindow\n"
        )

    def open_script(self, key, set_name, cwd, sid, mode, skip_perms=False, cmd=None):
        """AppleScript that focuses the live iTerm session matching `key`, or opens a
        new window/tab (per `mode`), names it `set_name`, and resumes the exact session
        by id. `skip_perms` adds --dangerously-skip-permissions to the revive command.
        `cmd` overrides the resume command; a falsy `key` skips the title match (Pi,
        whose tab titles aren't unique, is focused by tty instead)."""
        cmd = with_cd(cmd or resume_command({"id": sid}, skip_perms), cwd)  # skip cd if dir gone
        name_e, cmd_e = osa(set_name), osa(cmd)
        focus = "          tell w to select\n          select t\n"
        return (
            f'tell application "{self.app}"\n'
            "  activate\n"
            f"{self._match_session_block(key, focus) if key else ''}"
            f"{self._create_target_block(mode)}"
            "  tell targetSession\n"
            f'    set name to "{name_e}"\n'
            f'    write text "{cmd_e}"\n'
            "  end tell\n"
            "end tell"
        )

    def new_script(self, mode, cwd=None, skip_perms=False, prompt=None, harness="claude"):
        """AppleScript that opens a new window/tab (per `mode`) and starts a fresh
        `harness` session — in `cwd` if given, else the new session's default
        directory. `skip_perms` adds --dangerously-skip-permissions; `prompt` (e.g.
        "/insights") is passed as the initial input so a slash command runs on launch."""
        cmd = with_cd(new_command(harness, skip_perms, prompt), cwd)
        return (
            f'tell application "{self.app}"\n'
            "  activate\n"
            f"{self._create_target_block(mode)}"
            "  tell targetSession\n"
            f'    write text "{osa(cmd)}"\n'
            "  end tell\n"
            "end tell"
        )

    def rename_script(self, key, new_name):
        """AppleScript that types `/rename <new_name>` into the live session matching
        `key`. Claude then renames the session (custom-title) and the iTerm2 tab."""
        cmd_e = osa("/rename " + new_name)
        action = f'          tell s to write text "{cmd_e}"\n'
        return (
            f'tell application "{self.app}"\n'
            f"{self._match_session_block(key, action)}"
            "end tell"
        )

    def session_ttys(self):
        """The tty of every iTerm session ('/dev/ttysNNN') — how a Pi process
        (known by its tty) is placed in iTerm."""
        if not self.running():
            return set()
        r = run_osascript(
            f'tell application "{self.app}"\n'
            '  set out to ""\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            '      repeat with s in sessions of t\n'
            '        set out to out & (tty of s) & linefeed\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end repeat\n'
            '  return out\n'
            'end tell', timeout=OSA_READ_TIMEOUT)
        if r.returncode != 0:
            return set()
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("/dev/")}

    def tty_script(self, tty, action):
        """AppleScript that runs `action` on the iTerm session whose tty is `tty`
        (inside the loop `w`/`t`/`s` are its window/tab/session)."""
        return (
            f'tell application "{self.app}"\n'
            "  repeat with w in windows\n"
            "    repeat with t in tabs of w\n"
            "      repeat with s in sessions of t\n"
            f'        if (tty of s) is "{osa(tty)}" then\n'
            f"{action}"
            "          return\n"
            "        end if\n"
            "      end repeat\n"
            "    end repeat\n"
            "  end repeat\n"
            "end tell"
        )

    # ── action layer (shared backend interface) ──
    def mark_live(self, sessions):
        """Tag sessions live by iTerm tab title. Reuses the title algorithm
        (assign_liveness) and stamps live_app. Runs first in mark_all_live, so it
        owns the baseline; the Terminal backend only adds to it."""
        assign_liveness(sessions, live_session_names())
        for s in sessions:
            if s.get("live"):
                s["live_app"] = self.key

    def act_open(self, s, cwd, sid, set_name, mode, skip_perms=False):
        """Jump to the live session matching this title, or open a new window/tab
        and resume it. iTerm matches by title inside the AppleScript itself. Pi
        sessions jump by tty (mark_pi_live found it) and revive without a title match."""
        if s.get("harness") == "pi":
            if s.get("live_tty"):
                run_osascript(self.tty_script(s["live_tty"],
                    "          activate\n          tell w to select\n          select t\n          tell s to select\n"))
                return
            run_osascript(self.open_script("", set_name, cwd, sid, mode, cmd=resume_command(s)))
            return
        run_osascript(self.open_script(match_key(s), set_name, cwd, sid, mode, skip_perms))

    def act_new(self, mode, cwd=None, skip_perms=False, prompt=None, harness="claude"):
        run_osascript(self.new_script(mode, cwd, skip_perms, prompt, harness))

    def act_run(self, cmd, mode, name=""):
        """Run an arbitrary shell command (e.g. an ssh attach) in a new window/tab."""
        run_osascript(self.open_script("", name, None, "", mode, cmd=cmd))

    def act_rename(self, s, new_name):
        if s.get("harness") == "pi":
            if s.get("live_tty"):
                cmd_e = osa(rename_command(s, new_name))
                run_osascript(self.tty_script(s["live_tty"], f'          tell s to write text "{cmd_e}"\n'))
            return
        run_osascript(self.rename_script(match_key(s), new_name))


ITERM = ITermBackend()


# ── Terminal.app process inspection (liveness is matched by tty, not title) ──
_RESUME_RE = re.compile(r"--resume[=\s]+(\S+)")


def _is_claude_cmd(args):
    """True if a `ps` args string is an INTERACTIVE `claude` session (the binary
    is `claude`, not a `claude -p`/`--print` headless run like our summarizer).
    An npm install can show up as `node …/bin/claude` (or …/claude-code/cli.js)."""
    if not args:
        return False
    parts = args.split()
    first = parts[0]
    if os.path.basename(first) in ("node", "bun") and len(parts) > 1:
        first = parts[1]
        if "claude-code" in first:
            first = "claude"
    if os.path.basename(first) != os.path.basename(CLAUDE_BIN) and not first.endswith("/claude"):
        return False
    return " -p " not in f" {args} " and "--print" not in args


def _proc_cwds(pids):
    """{pid: cwd} for the given pids, via one batched lsof. Only needed for fresh
    (no --resume) claude procs that must be matched to a session by directory."""
    if not pids:
        return {}
    r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(pids)],
                       capture_output=True, text=True)
    out, cur = {}, None
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            cur = line[1:]
        elif line.startswith("n") and cur:
            out[cur] = line[1:]
    return out


def claude_procs():
    """Map controlling tty ('/dev/ttysNNN') -> {'sid':resume-id-or-None, 'cwd':...}
    for every interactive `claude` process, so a terminal tab (known by its tty)
    can be matched to the session it is running."""
    r = subprocess.run(["ps", "-axo", "pid=,tty=,args="], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    out, fresh = {}, []
    for line in r.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, tty, args = parts
        if tty in ("??", "-") or not _is_claude_cmd(args):
            continue
        m = _RESUME_RE.search(args)
        sid = m.group(1) if m else None
        if sid and sid.startswith("-"):
            sid = None  # `--resume` with no value swallowed the next flag — not an id
        tkey = "/dev/" + tty
        out[tkey] = {"sid": sid, "cwd": None, "pid": pid}
        if not sid:
            fresh.append((pid, tkey))
    if fresh:
        cwds = _proc_cwds([p for p, _ in fresh])
        for pid, tkey in fresh:
            out[tkey]["cwd"] = cwds.get(pid)
    return out


def _is_pi_cmd(args):
    """True if a `ps` args string is an interactive Pi. Pi sets process.title to
    'pi', so ps shows the bare name and NONE of its flags; a launch that kept
    node's argv shows `node …/bin/pi …`. Print/RPC runs are excluded when their
    flags are visible, and in any case have no tty (filtered by the caller)."""
    parts = (args or "").split()
    if not parts:
        return False
    head = os.path.basename(parts[0])
    if head == os.path.basename(PI_BIN):
        pass
    elif head == "node" and len(parts) > 1 and (parts[1].endswith("/pi") or "pi-coding-agent" in parts[1]):
        pass
    else:
        return False
    padded = f" {args} "
    return not any(f in padded for f in (" -p ", " --print ", " --mode "))


def pi_procs():
    """Map controlling tty ('/dev/ttysNNN') -> {'pid', 'cwd'} for every interactive
    `pi`. Unlike claude_procs there's never a session id to read (Pi hides its
    argv), so a process is tied to a session only through its cwd."""
    r = subprocess.run(["ps", "-axo", "pid=,tty=,args="], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, tty, args = parts
        if tty in ("??", "-") or not _is_pi_cmd(args):
            continue
        out["/dev/" + tty] = {"pid": pid, "cwd": None}
    cwds = _proc_cwds([p["pid"] for p in out.values()])
    for p in out.values():
        p["cwd"] = cwds.get(p["pid"])
    return out


def _real(path):
    try:
        return os.path.realpath(path) if path else path
    except (OSError, ValueError):
        return path


def mark_pi_live(sessions):
    """Light Pi sessions from running `pi` processes. Each process's tty says
    WHERE it runs — an iTerm session, a Terminal tab, or neither (tmux, another
    terminal app: live_app 'other', which can't be jumped to). Its cwd says WHICH
    session: the newest not-yet-live Pi session in that directory, one per
    process (the same rule Terminal uses for fresh Claude sessions). Pi rewrites
    its argv and doesn't hold the transcript open, so cwd is all there is.
    SHORTCUT: two Pi processes in one cwd light the right NUMBER of sessions but
    may swap which tab each jumps to; exact pairing needs Pi to expose its
    session (e.g. an extension writing pid→session to a file)."""
    procs = pi_procs()
    if not procs:
        return
    iterm_ttys = ITERM.session_ttys() if ITERM.running() else set()
    term_wins = {tty: winid for winid, tty in TERMINAL._tabs()} if TERMINAL.running() else {}
    by_cwd = {}
    for tty in sorted(procs):
        cwd = procs[tty].get("cwd")
        if cwd:
            by_cwd.setdefault(_real(cwd), []).append(tty)
    for cwd, ttys in by_cwd.items():
        here = sorted((s for s in sessions if _real(s.get("cwd")) == cwd and not s.get("live")),
                      key=lambda s: -s["mtime"])
        for s, tty in zip(here, ttys):
            s["live"] = True
            s["live_tty"] = tty
            if tty in iterm_ttys:
                s["live_app"] = ITERM.key
            elif tty in term_wins:
                s["live_app"] = TERMINAL.key
                s["live_win"] = term_wins[tty]
            else:
                s["live_app"] = "other"


def _accessibility_denied(stderr):
    """True if an osascript failure text indicates System Events was blocked by the
    Accessibility/TCC gate (vs some other AppleScript error)."""
    t = (stderr or "").lower()
    return ("1002" in t or "-1719" in t or "-25211" in t
            or "not allowed" in t or "assistive" in t or "accessibility" in t)


class TerminalBackend:
    """Terminal.app backend. Liveness can't use tab titles (Terminal exposes
    Claude's OSC-1 title only on the selected tab), so it matches each tab's `tty`
    to a running `claude` process and then to the session (by --resume id, else by
    cwd). New sessions open in a new WINDOW (Terminal has no scriptable tab-create
    without Accessibility); jump/rename target the window by id."""
    key = "terminal"
    app = "Terminal"

    def running(self):
        return subprocess.run(["pgrep", "-x", "Terminal"], capture_output=True).returncode == 0

    def _tabs(self):
        """[(window-id, tty)] for every Terminal tab, foreground and background."""
        script = (
            'tell application "Terminal"\n'
            '  set out to ""\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            '      set out to out & (id of w) & " " & (tty of t) & linefeed\n'
            '    end repeat\n'
            '  end repeat\n'
            '  return out\n'
            'end tell'
        )
        r = run_osascript(script, timeout=OSA_READ_TIMEOUT)
        if r.returncode != 0:
            return []
        tabs = []
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("/dev/"):
                tabs.append((parts[0], parts[1]))
        return tabs

    def snapshot_windows(self):
        """Open windows as [{'bounds', 'keys'}] (order preserved); each key is a tab tty."""
        if not self.running():
            return []
        r = run_osascript(_snapshot_script(self.app,
            '    repeat with t in tabs of w\n'
            '      set out to out & "S\t" & (tty of t) & linefeed\n'
            '    end repeat\n'), timeout=OSA_READ_TIMEOUT)
        return _parse_window_dump(r.stdout) if r.returncode == 0 else []

    def open_windows(self, live):
        """[{bounds, ids}] for `live` Terminal sessions, grouped by window in tab
        order. Each tab's tty → claude process → session (by --resume id, else by
        cwd for a fresh session). Identity still comes from the live session list."""
        procs = claude_procs()
        by_id = {s["id"]: s for s in live}
        out, used = [], set()
        for win in self.snapshot_windows():
            ids = []
            for tty in win["keys"]:
                p = procs.get(tty)
                if not p:
                    continue
                sid = p.get("sid")
                s = by_id.get(sid) if sid and sid in by_id else None
                if not s and p.get("cwd"):  # fresh → newest live session in that cwd
                    here = sorted((x for x in live if x.get("cwd") == p["cwd"] and x["id"] not in used),
                                  key=lambda x: -x["mtime"])
                    s = here[0] if here else None
                if s and s["id"] not in used:
                    ids.append(s["id"]); used.add(s["id"])
            out.append({"bounds": win.get("bounds") or [], "ids": ids})
        return out

    def _new_window_with_bounds(self, cmd, bounds):
        """AppleScript: new window running `cmd`, sized to `bounds` if given."""
        s = (f'tell application "{self.app}"\n  activate\n'
             f'  set t to do script "{osa(cmd)}"\n')
        if bounds and len(bounds) == 4 and any(bounds):
            s += (f'  try\n    set bounds of (window of t) to '
                  f'{{{bounds[0]}, {bounds[1]}, {bounds[2]}, {bounds[3]}}}\n  end try\n')
        return s + 'end tell'

    def restore_window(self, tabs, bounds):
        """Recreate one window: first session as a new window (+ bounds), the rest as
        best-effort tabs in it (falling back to their own window if tab-create fails)."""
        run_osascript(self._new_window_with_bounds(tabs[0], bounds))
        for cmd in tabs[1:]:
            if not self._open_tab(cmd):
                run_osascript(self.new_script(cmd))

    def live_records(self):
        """[{'winid','sid','cwd'}] for each Terminal tab running a claude session."""
        tabs = self._tabs()
        if not tabs:
            return []
        procs = claude_procs()
        out = []
        for winid, tty in tabs:
            p = procs.get(tty)
            if p:
                out.append({"winid": winid, "sid": p.get("sid"), "cwd": p.get("cwd")})
        return out

    def mark_live(self, sessions):
        """Additive: light sessions running in Terminal. Match by resume id first
        (exact), then fall back to cwd for fresh (un-resumed) sessions — newest
        not-yet-live session per directory, mirroring the iTerm default-tab rule."""
        recs = self.live_records()
        by_sid = {r["sid"]: r for r in recs if r.get("sid")}
        for s in sessions:
            r = by_sid.get(s["id"])
            if r:
                s["live"] = True
                s.setdefault("live_app", self.key)
                s.setdefault("live_win", r["winid"])
        fresh = {}
        for r in recs:
            if not r.get("sid") and r.get("cwd"):
                fresh.setdefault(r["cwd"], []).append(r["winid"])
        for cwd, winids in fresh.items():
            here = sorted((s for s in sessions if s.get("cwd") == cwd and not s.get("live")),
                          key=lambda s: -s["mtime"])
            for s, winid in zip(here, winids):
                s["live"] = True
                s.setdefault("live_app", self.key)
                s.setdefault("live_win", winid)

    def new_script(self, cmd):
        """AppleScript: open a NEW window running `cmd`."""
        return (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{osa(cmd)}"\n'
            'end tell'
        )

    def _run_new(self, cmd, mode):
        """Run `cmd` in a new Terminal TAB (mode 'tab', needs Accessibility) or a new
        WINDOW. Falls back to a window whenever the tab can't be created."""
        if mode == "tab" and self._open_tab(cmd):
            return
        run_osascript(self.new_script(cmd))

    def _tab_count(self):
        """Total tabs across all Terminal windows, or None if unreadable."""
        r = run_osascript(
            'tell application "Terminal"\n'
            '  set n to 0\n'
            '  repeat with w in windows\n'
            '    set n to n + (count of tabs of w)\n'
            '  end repeat\n'
            '  return n\n'
            'end tell', timeout=OSA_READ_TIMEOUT)
        if r.returncode != 0:
            return None
        try:
            return int(r.stdout.strip())
        except ValueError:
            return None

    def _open_tab(self, cmd):
        """Open `cmd` in a NEW TAB of the front Terminal window via a System Events
        menu-click (Terminal has no scriptable tab-create — needs Accessibility).
        Returns True if a tab/window was created and given the command, False to fall
        back to a plain window. Verifies the click actually created something (it can
        silently no-op) before injecting the command, so we never type into an
        existing tab. On a permission denial, points the user at Settings (once)."""
        if not self.running():
            return False  # no Terminal window to host a tab → caller opens a window
        before = self._tab_count()
        if not before:  # 0 or None → nothing to tab into
            return False
        # Click Shell ▸ New Tab ▸ <default profile> (the submenu item bound to ⌘T).
        click = (
            'tell application "Terminal" to activate\n'
            'delay 0.2\n'
            'tell application "System Events" to tell process "Terminal"\n'
            '  set frontmost to true\n'
            '  click (first menu item of menu 1 of menu item "New Tab" of menu 1 '
            'of menu bar item "Shell" of menu bar 1 whose value of attribute '
            '"AXMenuItemCmdChar" is "T")\n'
            'end tell'
        )
        r = run_osascript(click, timeout=OSA_READ_TIMEOUT + 2)
        if r.returncode != 0:
            if _accessibility_denied(r.stderr):
                self._prompt_accessibility()
            return False
        after = self._tab_count()
        if not after or after <= before:
            return False  # click created nothing → fall back to a clean window
        run_osascript('tell application "Terminal" to do script "%s" in front window' % osa(cmd))
        self._clear_accessibility_marker()  # tabs work now → re-arm the prompt for any future regression
        return True

    def _ax_marker(self):
        return os.path.join(STATE_DIR, "ax-prompted")  # computed live so tests can redirect STATE_DIR

    def _prompt_accessibility(self):
        """One-time nudge: tell the user Terminal tabs need Accessibility and open the
        pane. Guarded by a marker so a denied user isn't pestered every new session."""
        marker = self._ax_marker()
        if os.path.exists(marker):
            return
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            open(marker, "w").close()
        except OSError:
            pass
        notify("Terminal tabs need Accessibility for SwiftBar — enable it in "
               "System Settings ▸ Privacy & Security ▸ Accessibility, then try again. "
               "Opened a window for now.")
        try:
            subprocess.Popen(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def _clear_accessibility_marker(self):
        try:
            os.remove(self._ax_marker())
        except OSError:
            pass

    def _focus_script(self, winid):
        return (
            'tell application "Terminal"\n'
            f'  set frontmost of window id {winid} to true\n'
            '  activate\n'
            'end tell'
        )

    def act_open(self, s, cwd, sid, set_name, mode, skip_perms=False):
        """Jump to the session's window if live, else open a new window resuming it."""
        if s.get("live_win"):
            run_osascript(self._focus_script(s["live_win"]))
            return
        self._run_new(with_cd(resume_command(s, skip_perms), cwd), mode)

    def act_new(self, mode, cwd=None, skip_perms=False, prompt=None, harness="claude"):
        self._run_new(with_cd(new_command(harness, skip_perms, prompt), cwd), mode)

    def act_run(self, cmd, mode, name=""):
        """Run an arbitrary shell command (e.g. an ssh attach) in a new window/tab."""
        self._run_new(cmd, mode)

    def act_rename(self, s, new_name):
        """Type `/rename <new_name>` into the session's live window (its selected
        tab). No-op if we don't know the window (shouldn't happen — caller checks)."""
        winid = s.get("live_win")
        if not winid:
            return
        cmd_e = osa(rename_command(s, new_name))
        run_osascript(
            'tell application "Terminal"\n'
            f'  do script "{cmd_e}" in window id {winid}\n'
            'end tell'
        )


TERMINAL = TerminalBackend()
BACKENDS = {b.key: b for b in (ITERM, TERMINAL)}


def backend_for_new():
    """Backend that opens NEW / revived sessions, per the `terminal` pref
    (defaults to iTerm)."""
    return BACKENDS.get(load_prefs().get("terminal"), ITERM)


def current_backend():
    """The backend used for newly opened sessions (the `terminal` pref)."""
    return backend_for_new()


def mark_all_live(sessions):
    """Cross-app liveness: a session is live if ANY running terminal shows it.
    Clears flags, then lets each running backend tag the sessions it owns —
    iTerm by tab title, Terminal by tty→process. Stamps s['live_app'] (which app)
    and, for Terminal, s['live_win'] (the window to jump to).

    Each harness is matched only against its own sessions: Claude's title/cwd
    rules must never light a Pi session sharing a directory, and vice versa."""
    for s in sessions:
        s["live"] = False
        s.pop("live_app", None)
        s.pop("live_win", None)
        s.pop("live_tty", None)
    claude = [s for s in sessions if s.get("harness", "claude") == "claude"]
    pi = [s for s in sessions if s.get("harness") == "pi"]
    if ITERM.running():
        ITERM.mark_live(claude)
    if TERMINAL.running():
        TERMINAL.mark_live(claude)
    if pi:
        mark_pi_live(pi)


def capture_open_set(sessions):
    """Snapshot the open windows/tabs (per app, grouped, in order) to LAST_OPEN_FILE
    so the set can be restored later. Skips (and so preserves the prior snapshot)
    when nothing is live — that's what lets you quit a terminal and still restore
    what was there. Only known on-disk sessions (resumable by id) are recorded."""
    live = sorted(s["id"] for s in sessions if s.get("live"))
    if not live:
        return  # nothing open → keep the last snapshot (quitting must not wipe it)
    prev = load_json(LAST_OPEN_FILE, {})
    if sorted(t["id"] for w in prev.get("windows", []) for t in w.get("tabs", [])) == live:
        return  # same set already snapshotted → skip the osascript/ps work this refresh
    import time
    live_sessions = [s for s in sessions if s.get("live")]
    by_id = {s["id"]: s for s in live_sessions}
    windows, placed = [], set()
    # Layout from the structural read: group the (authoritative) live sessions into
    # windows in tab order, with bounds. Each backend identifies its tabs the same
    # way its liveness does (iTerm by title, Terminal by tty).
    for backend in (ITERM, TERMINAL):
        app_live = [s for s in live_sessions if s.get("live_app") == backend.key]
        if not app_live or not backend.running():
            continue
        for win in backend.open_windows(app_live):
            tabs = [{"id": i, "cwd": by_id[i].get("cwd")} for i in win["ids"] if i not in placed]
            placed.update(t["id"] for t in tabs)
            if tabs:
                windows.append({"app": backend.key, "bounds": win.get("bounds") or [], "tabs": tabs})
    # Fallback: any live session the layout couldn't place is STILL captured (from the
    # list's id+cwd), grouped per app into one window — so the snapshot never has gaps.
    leftover = {}
    for s in live_sessions:
        if s["id"] not in placed:
            leftover.setdefault(s.get("live_app") or ITERM.key, []).append(s)
    for app, ss in leftover.items():
        windows.append({"app": app, "bounds": [],
                        "tabs": [{"id": s["id"], "cwd": s.get("cwd")} for s in ss]})
    if windows:
        save_json(LAST_OPEN_FILE, {"ts": int(time.time()), "windows": windows})


def restorable_sessions(live_ids, known_ids):
    """Snapshot sessions worth restoring: saved, still on disk, not already live.
    Returns the list of {app,bounds,tabs} windows filtered to those tabs."""
    snap = load_json(LAST_OPEN_FILE, {})
    out = []
    for win in snap.get("windows", []):
        tabs = [t for t in win.get("tabs", [])
                if t.get("id") in known_ids and t.get("id") not in live_ids]
        if tabs:
            out.append({**win, "tabs": tabs})
    return out


# Module-level delegators for iTerm's pure script builders — call sites and tests
# reference these stable names. (Terminal's actions are not pure strings, so they
# live on the backend object and are reached via the action dispatch below.)
def live_session_names():
    return ITERM.live_session_names()


def build_open_script(key, set_name, cwd, sid, mode, skip_perms=False):
    return ITERM.open_script(key, set_name, cwd, sid, mode, skip_perms)


def build_new_script(mode, cwd=None, skip_perms=False, prompt=None):
    return ITERM.new_script(mode, cwd, skip_perms, prompt)


def build_rename_script(key, new_name):
    return ITERM.rename_script(key, new_name)


def prompt_rename(current, verb="/rename"):
    """Native text dialog for the new name. Returns it, or None if cancelled."""
    script = (
        f'set r to display dialog "Rename (runs {verb} in the live tab):" '
        f'default answer "{osa(current)}" with title "{UI_TITLE}" '
        f'buttons {{"Cancel", "Rename"}} default button "Rename"\n'
        "return text returned of r"
    )
    r = run_osascript(script)
    return None if r.returncode != 0 else r.stdout.strip()


def notify(message):
    run_osascript(f'display notification "{osa(message)}" with title "{UI_TITLE}"')


def match_key(session):
    """The title we look for inside live iTerm tab names. Prefer the raw
    transcript title (custom-title / ai-title — what Claude puts in the tab);
    fall back to the display name."""
    return session.get("title") or display_name(session)


def title_is_live(key, live_names):
    """True if `key` is the WHOLE title of a live tab. Claude renders tabs as
    "<glyph> <title><sep><path>" (or "<glyph> <title>" with no path), so the
    title is the segment before TAB_TITLE_SEP, sitting after the glyph's space.
    Match it as a bounded token — preceded by that space (or start), followed by
    the separator (or end) — so "build" can't hit "nightly_build_pipeline — …"
    and "pipeline" can't hit "…_pipeline — …". Kept in sync with _match_session_block."""
    if not key:
        return False
    for nm in live_names:
        head = nm.split(TAB_TITLE_SEP, 1)[0]  # the "<glyph> <title>" segment
        head = re.sub(r"\s*\([^)]*\)\s*$", "", head)  # strip iTerm profile suffix e.g. "(python)"
        if head == key or head.endswith(" " + key):
            return True
    return False


def default_tab_path(tab_name):
    """If a live iTerm tab still shows Claude's DEFAULT title ('Claude Code' —
    i.e. the session is too new to have been auto-titled), return its cwd (the
    path after the title separator, with a leading '~' expanded), else None.
    Lets liveness fall back to cwd for brand-new sessions that title-matching
    (which needs a real, tab-matching title) can't yet see."""
    marker = "Claude Code" + TAB_TITLE_SEP
    if marker not in tab_name:
        return None
    path = tab_name.split(TAB_TITLE_SEP, 1)[1].strip()  # str.strip() drops the NBSP too
    if path.startswith("~"):
        path = HOME + path[1:]
    return path or None


def assign_liveness(sessions, live_names):
    """Set each session's "live" flag against the set of live iTerm tab names,
    in three passes (mutates `sessions` in place):

    1. Title match — live if the session's title bounds a live tab name.
    2. Same-title dedup — if several sessions match one title (after a remap or a
       duplicated /rename), only the most-recently-written keeps live; the rest
       stop borrowing that tab's green dot.
    3. Default-tab fallback — a brand-new session's tab still shows Claude's
       default "Claude Code" title, which title-matching can't see; match those
       tabs by cwd and light up the most-recent not-yet-live session(s) there
       (one default tab = one untitled live session)."""
    for s in sessions:
        s["live"] = title_is_live(match_key(s), live_names)

    live_by_title = {}
    for s in sessions:
        if s["live"]:
            live_by_title.setdefault(match_key(s), []).append(s)
    for group in live_by_title.values():
        if len(group) > 1:
            keep = max(group, key=lambda s: s["mtime"])
            for s in group:
                s["live"] = s is keep

    default_paths = {}
    for nm in live_names:
        p = default_tab_path(nm)
        if p:
            default_paths[p] = default_paths.get(p, 0) + 1
    for path, count in default_paths.items():
        here = sorted((s for s in sessions if s.get("cwd") == path and not s["live"]),
                      key=lambda s: -s["mtime"])
        for s in here[:count]:
            s["live"] = True


def focus_or_revive(s, cwd, sid, mode, skip_perms=False):
    """Jump to the session in whichever app it's live in, else revive it in the
    pref-selected terminal. Expects mark_all_live() to have run on `s`. A session
    live somewhere neither backend owns (tmux…) is left alone — reviving it would
    start a second copy of a running session."""
    if s.get("live") and s.get("live_app") not in BACKENDS:
        notify("That session is running outside iTerm/Terminal (e.g. tmux) — switch to it there.")
        return
    backend = BACKENDS.get(s.get("live_app")) or backend_for_new()
    backend.act_open(s, cwd, sid, display_name(s), mode, skip_perms)


# ─────────────────────────── menu rendering ───────────────────────
def fmt(prefix, title, **params):
    """Build one SwiftBar line: '<prefix><title> | k=v ...'."""
    parts = []
    for k, v in params.items():
        if v is None:
            continue
        parts.append(f'{k}="{osa(str(v))}"')
    line = f"{prefix}{title}"
    if parts:
        line += " | " + " ".join(parts)
    return line


def action_params(verb, sid=None, **extra):
    p = {
        "bash": SELF,
        "param1": verb,
        "param2": sid,  # None → fmt() omits it (e.g. the no-id "new" action)
        "terminal": "false",
        "refresh": "true",
    }
    p.update(extra)
    return p


def dir_header(prefix, label, cwd, gitcache):
    """A group header: italic (not grayed), with its dir-kind icon. Clickable to
    reveal the directory in Finder when it exists (gone dirs are just a label)."""
    params = {"sfimage": dir_icon(cwd, gitcache), "font": HEADER_FONT, "size": "12"}
    if cwd and not dir_missing(cwd):
        params.update(bash="/usr/bin/open", param1=cwd, terminal="false")
    return fmt(prefix, label, **params)


def render_active_dir_header(label, cwd, gitcache):
    """Active-list directory header as a SUBMENU (▸): icon + italic name, whose
    children are the dir-level actions — Open folder/worktree + New session here.
    Keeps those off the main list (no more a "New session here" row per dir)."""
    print(fmt("", label, sfimage=dir_icon(cwd, gitcache), font=HEADER_FONT, size="12"))
    if cwd and not dir_missing(cwd):
        is_wt = gitcache.get(cwd) == "worktree"  # dir_icon() above cached the kind
        print(fmt("--", "Open worktree" if is_wt else "Open folder",
                  sfimage="arrow.triangle.branch" if is_wt else "folder",
                  bash="/usr/bin/open", param1=cwd, terminal="false"))
        print(fmt("--", "New session here", sfimage="plus.circle", **action_params("new", cwd)))
    elif cwd:  # directory was renamed/moved — offer to repair it
        print(fmt("--", "Remap directory…", sfimage="folder.badge.gearshape",
                  **action_params("remap", cwd)))


def render_remote_dir_header(label, s):
    """Directory header for a remote host's group: a server icon, and New session
    here (in a new tmux session on that host). The folder can't be opened locally."""
    print(fmt("", label, sfimage="server.rack", font=HEADER_FONT, size="12"))
    if s.get("cwd"):
        print(fmt("--", "New session here", sfimage="plus.circle",
                  **action_params("new", s["cwd"], param3="", param4=s["host"])))


def render_session(s, depth=0):
    """Print a session row (submenu) at the given nesting `depth`: live/parked dot
    + name, then its actions one level deeper. depth=0 = top level; depth=1 nests
    it inside a parent submenu (e.g. under "Past sessions ▸")."""
    pfx, cpfx = "--" * depth, "--" * (depth + 1)
    dot = LIVE_DOT_IMG if s["live"] else PARKED_DOT_IMG
    name = s["name"]
    if s.get("harness") == "pi":  # Claude is the default; tag the other harness
        name += "  [Pi]"
    if s.get("show_app_badge"):  # split across both terminals — show which one
        name += f"  [{APP_LABEL.get(s.get('live_app'), '')}]"
    print(fmt(pfx, name, image=dot or None))
    verb = "Jump to session" if s["live"] else "Revive session"
    print(fmt(cpfx, verb, sfimage="arrow.right.circle.fill", **action_params("open", s["id"])))
    if s["live"]:  # running: rename (drives /rename); archiving waits until it's parked
        if not s.get("host") or s.get("tmux_target"):  # remote: only a tmux pane can be typed into
            print(fmt(cpfx, "Rename…", sfimage="pencil", **action_params("rename", s["id"])))
    else:          # parked: can be tucked away
        print(fmt(cpfx, "Archive", sfimage="archivebox", **action_params("archive", s["id"])))


def render_menu():
    state = load_json(STATE_FILE, {})
    sessions, ok = discover()

    if not ok:
        menubar_title(None)
        print("---")
        print("No Claude or Pi sessions found")
        print(f"--Expected: {PROJECTS_DIR}")
        print(f"--or: {PI_SESSIONS_DIR}")
        print("--Start a session with `claude` or `pi`, then refresh.")
        print("---")
        print(fmt("", "Refresh", refresh="true", sfimage="arrow.clockwise"))
        return

    for s in sessions:
        s["name"] = display_name(s)
        s["archived"] = bool(state.get(s["id"], {}).get("archived"))
    mark_all_live(sessions)
    capture_open_set(sessions)  # snapshot the open windows/tabs so they can be restored
    # Remote hosts' sessions join AFTER local liveness/snapshot: their live flags
    # come from the host's own scan, and they're never restored into a local tab.
    ensure_remote_scan()
    for s in remote_sessions():
        s["name"] = remote_name(s)
        s["archived"] = bool(state.get(s["id"], {}).get("archived"))
        sessions.append(s)

    active = [s for s in sessions if not s["archived"]]
    archived = [s for s in sessions if s["archived"]]
    live_count = sum(1 for s in active if s["live"])

    # Only badge the live app when live sessions are split across both terminals —
    # otherwise where a "Jump to" lands is unambiguous and the label is just noise.
    apps_split = len({s.get("live_app") for s in active if s["live"] and not s.get("host")} - {None}) > 1
    for s in sessions:
        s["show_app_badge"] = bool(apps_split and s["live"])

    # Menu bar title.
    menubar_title(live_count)
    print("---")

    # Webview management panel — opens an HTML panel served by an on-demand,
    # 127.0.0.1-only server (started here if not already running; it idle-exits).
    ensure_server()
    ensure_summarizer()  # background: refresh summaries of changed sessions
    ensure_workspace_scan()  # background: refresh the workspace-roots cache
    print(fmt("", UI_TITLE, image=CLAUDE_ICON,
              webview="true", webvieww="780", webviewh="560",
              href=f"http://127.0.0.1:{WEBVIEW_PORT}/?t={server_token()}&v={panel_version()}"))
    print("---")

    gitcache = load_json(GITCACHE_FILE, {})  # cwd -> "worktree"/"repo"/"dir"
    gc_before = len(gitcache)

    # New session ▸ — pick a known directory (from any session) or a discovered
    # workspace root, or Select folder… Workspaces are listed first, then plain
    # folders (mirrors the webview dropdown).
    prefs = load_prefs()
    new_harness = prefs.get("harness", "claude")
    new_label = "New session" + (f" ({HARNESS_LABEL.get(new_harness, '')})"
                                 if pi_available() else "")  # say which agent once there's a choice
    print(fmt("", new_label, sfimage="plus.circle"))
    seen_dirs = {}
    for s in sessions:
        cwd = s.get("cwd")
        if cwd and not s.get("host") and not dir_missing(cwd):  # local dirs only
            seen_dirs[cwd] = max(seen_dirs.get(cwd, 0.0), s["mtime"])
    # session dirs by recency, then workspace roots with no session yet (deduped)
    new_dirs = sorted(seen_dirs, key=lambda c: -seen_dirs[c])
    new_dirs += [r for r in cached_workspace_roots() if r not in seen_dirs]
    # workspaces first, then the rest — stable sort keeps recency order within each
    def _is_ws(c):
        if c not in gitcache:
            gitcache[c] = compute_dir_kind(c)
        return gitcache[c] == "workspace"
    new_dirs.sort(key=lambda c: 0 if _is_ws(c) else 1)
    for cwd in new_dirs:
        print(fmt("--", group_label(cwd), sfimage=dir_icon(cwd, gitcache),
                  **action_params("new", cwd)))
    print(fmt("--", "Select folder…", sfimage="folder.badge.plus", **action_params("newpick")))
    print("---")  # Restore lives in the panel (the menu's already long enough)

    if not active and not archived:
        print("No sessions yet")
        print("--Run `claude` in a project, then refresh.")

    # Keep the native SwiftBar menu lean: it shows live sessions only. Parked/past
    # sessions stay in the webview panel, where hundreds of rows are searchable and
    # cheaper than rebuilding a huge native AppKit menu every refresh.
    groups = group_by_dir(active)
    live_groups = [(l, m) for l, m in groups if any(s["live"] for s in m)]

    need_div = False
    for label, members in live_groups:
        if need_div:
            print("---")
        need_div = True
        gcwd = members[0].get("cwd")  # all members share this group's dir
        if members[0].get("host"):
            render_remote_dir_header(label, members[0])  # ▸ New session here (on that host)
        else:
            render_active_dir_header(label, gcwd, gitcache)  # ▸ Open + New session here
        for s in members:
            if s["live"]:
                render_session(s)  # live sessions stay at the top level — prominent

    # Archived sessions live entirely in the webview panel (tab + checkboxes +
    # toolbar). The native menu stays lean — no inline archived rows.

    if len(gitcache) != gc_before:  # new dirs were classified
        try:
            save_json(GITCACHE_FILE, gitcache)
        except OSError:
            pass  # best-effort cache; never break the menu render

    print("---")
    print(fmt("", "Settings", sfimage="gearshape"))
    # Groups divided by separator lines ("-----" = a separator one level deep).
    for i, (verb_label, key) in enumerate((("Revive in", "revive_in"), ("New session in", "new_in"))):
        if i:
            print("-----")
        for opt in ("window", "tab"):
            on = prefs[key] == opt
            print(fmt("--", f"{verb_label} {opt}",
                      sfimage="checkmark" if on else None,
                      **action_params("set", key, param3=opt)))
    print("-----")
    for opt, label in (("iterm", "iTerm"), ("terminal", "Terminal")):
        on = prefs.get("terminal", "iterm") == opt
        print(fmt("--", f"Open sessions in {label}",
                  sfimage="checkmark" if on else None,
                  **action_params("set", "terminal", param3=opt)))
    if pi_available():  # Pi is installed → choose the agent for New session, and show/hide its sessions
        print("-----")
        for opt in ("claude", "pi"):
            print(fmt("--", f"New sessions use {HARNESS_LABEL[opt]}",
                      sfimage="checkmark" if new_harness == opt else None,
                      **action_params("set", "harness", param3=opt)))
        show_pi = prefs.get("show_pi", True)
        print(fmt("--", "Show Pi sessions",
                  sfimage="checkmark" if show_pi else None,
                  **action_params("set", "show_pi", param3="off" if show_pi else "on")))
    print("-----")
    skip = prefs["skip_permissions"]  # single toggle: click sets the opposite
    print(fmt("--", "Skip permissions (new sessions)",
              sfimage="checkmark" if skip else None,
              **action_params("set", "skip_permissions", param3="off" if skip else "on")))
    hosts = remote_hosts()
    print(fmt("--", "Remote hosts…" + (f" ({len(hosts)})" if hosts else ""), sfimage="server.rack",
              **action_params("remotehosts")))
    scan_ws = prefs.get("scan_workspaces", True)  # discover multi-worktree dirs
    print(fmt("--", "Scan home for workspaces",
              sfimage="checkmark" if scan_ws else None,
              **action_params("set", "scan_workspaces", param3="off" if scan_ws else "on")))
    summ = prefs.get("summaries", True)  # Haiku one-liners shown in the panel
    print(fmt("--", "Summarize sessions (Haiku)",
              sfimage="checkmark" if summ else None,
              **action_params("set", "summaries", param3="off" if summ else "on")))
    print(fmt("", "Refresh", refresh="true", sfimage="arrow.clockwise"))
    print(fmt("", "Reveal state folder", bash="/usr/bin/open", param1=STATE_DIR, terminal="false"))


# ──────────────────────────── mode 2 actions ──────────────────────
def find_session(sid):
    sessions, _ = discover()
    for s in sessions:
        if s["id"] == sid:
            return s
    return None


def session_file(sid):
    """Absolute path to a session's transcript .jsonl, or None if not found. If a
    stale duplicate lingers in another project folder (e.g. a remap copy), return
    the most-recently-written one — matching discover()'s dedupe, so delete/remap
    act on the same authoritative file the menu shows. Falls back to Pi's
    sessions, whose files are named '<timestamp>_<id>.jsonl'."""
    best, best_mtime = None, -1.0
    for proj in (os.listdir(PROJECTS_DIR) if os.path.isdir(PROJECTS_DIR) else []):
        path = os.path.join(PROJECTS_DIR, proj, sid + ".jsonl")
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue  # not a file / unreadable
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best or pi_session_file(sid)


def pi_session_file(sid):
    """Newest Pi transcript for `sid`, or None."""
    if not sid or not os.path.isdir(PI_SESSIONS_DIR):
        return None
    best, best_mtime = None, -1.0
    suffix = "_" + sid + ".jsonl"
    for proj in os.listdir(PI_SESSIONS_DIR):
        pdir = os.path.join(PI_SESSIONS_DIR, proj)
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for fn in names:
            if fn.endswith(suffix) or fn == sid + ".jsonl":
                path = os.path.join(pdir, fn)
                try:
                    mtime = os.stat(path).st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best, best_mtime = path, mtime
    return best


def do_open_remote(s):
    """Jump to a remote session's tmux pane, or resume it on its host in tmux."""
    prefs = load_prefs()
    if s.get("live") and not s.get("tmux_target"):
        notify(f"Running on {s['host_label']} outside tmux — switch to it there.")
        return
    backend_for_new().act_run(remote_attach_command(s, prefs["skip_permissions"]),
                              prefs["revive_in"], remote_name(s))


def do_open(sid):
    if is_remote(sid):
        s = find_remote(sid)
        if s:
            do_open_remote(s)
        return
    sessions, _ = discover()
    mark_all_live(sessions)  # sets live_app / live_win so we jump to the right app
    s = next((x for x in sessions if x["id"] == sid), None)
    if not s or not s.get("cwd"):
        return
    cwd = s["cwd"]
    if dir_missing(cwd):  # gone dir: resume without cd-ing (which would fail)
        notify("Directory is gone — resuming without it.")
        cwd = None
    prefs = load_prefs()
    focus_or_revive(s, cwd, sid, prefs["revive_in"], prefs["skip_permissions"])


def do_new(cwd=None, harness=None, host=None):
    """Fresh session in `cwd`, in `harness` (default: the `harness` pref) — on
    `host` (in a new tmux session there) when given."""
    import time
    prefs = load_prefs()
    harness = harness if harness in HARNESS_LABEL else prefs.get("harness", "claude")
    if host:
        remote = remote_tmux_launch(cwd, new_command(harness, prefs["skip_permissions"]),
                                    _tmux_name(f"{harness}{int(time.time())}"))
        backend_for_new().act_run(f"ssh -t {shlex.quote(host)} {shlex.quote(remote)}",
                                  prefs["new_in"], f"{HARNESS_LABEL[harness]} on {host}")
        return
    backend_for_new().act_new(prefs["new_in"], cwd, prefs["skip_permissions"], harness=harness)


def do_restore():
    """Reopen the last snapshotted set of sessions, each in the app it was in
    (grouped into windows, in tab order, with their window size). Skips any session
    already live, and any whose transcript is gone."""
    sessions, _ = discover()
    mark_all_live(sessions)
    live_ids = {s["id"] for s in sessions if s.get("live")}
    by_id = {s["id"]: s for s in sessions}
    wins = restorable_sessions(live_ids, set(by_id))
    if not wins:
        notify("Nothing to restore — the saved sessions are already open (or none saved).")
        return
    skip = load_prefs()["skip_permissions"]
    opened = 0
    for win in wins:
        backend = BACKENDS.get(win.get("app")) or backend_for_new()
        cmds = []
        for tab in win["tabs"]:
            sid = tab["id"]
            cwd = tab.get("cwd") or by_id[sid].get("cwd")
            if cwd and dir_missing(cwd):
                cwd = None  # gone dir → resume without cd
            cmds.append(with_cd(resume_command(by_id[sid], skip), cwd))
        backend.restore_window(cmds, win.get("bounds") or [])
        opened += len(cmds)
    notify(f"Restored {opened} session(s).")


def choose_folder(prompt):
    """Native folder chooser. Returns the chosen POSIX path, or None if cancelled."""
    r = run_osascript(
        f'set f to choose folder with prompt "{osa(prompt)}"\n'
        "return POSIX path of f"
    )
    path = r.stdout.strip()
    return path if (r.returncode == 0 and path) else None


def do_new_pick(harness=None):
    """Top-level New session…: native folder chooser → fresh session in any
    directory (including ones not yet in the menu)."""
    harness = harness if harness in HARNESS_LABEL else load_prefs().get("harness", "claude")
    path = choose_folder(f"Choose a directory for the new {HARNESS_LABEL[harness]} session:")
    if path:
        do_new(path, harness)


def do_remote_hosts_dialog():
    """Native dialog to edit the `remote_hosts` pref (comma-separated ssh targets)."""
    cur = ", ".join(remote_hosts())
    r = run_osascript(
        f'set r to display dialog "Remote hosts — ssh targets whose Claude/Pi sessions to list '
        f'(comma-separated, e.g. me@box). Needs passwordless ssh." default answer "{osa(cur)}" '
        f'with title "{UI_TITLE}" buttons {{"Cancel", "Save"}} default button "Save"\n'
        "return text returned of r")
    if r.returncode == 0:
        set_pref("remote_hosts", ", ".join(h for h in re.split(r"[,\s]+", r.stdout.strip()) if h))


def do_set(key, value):
    # Bool-typed prefs come in as "on"/"off" from the toggle; store real bools.
    if key in DEFAULT_PREFS and isinstance(DEFAULT_PREFS[key], bool):
        value = value in ("on", "true", "1", "yes")
    elif key in DEFAULT_PREFS and isinstance(DEFAULT_PREFS[key], (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return  # not a number → leave the stored value alone
        value = int(value) if value == int(value) else value
    set_pref(key, value)


def rename_remote(s, new_name):
    """Type the harness's rename command into a remote session's tmux pane."""
    if not (s.get("live") and s.get("tmux_target")):
        notify("Rename needs the session live in tmux on its host.")
        return
    err = remote_send_keys(s, rename_command(s, new_name))
    if err:
        notify(f"Rename on {s['host_label']} failed: {err}")


def do_rename(sid):
    if is_remote(sid):
        s = find_remote(sid)
        new = prompt_rename(remote_name(s), rename_command(s, "").strip()) if s and s.get("tmux_target") else None
        if s and not s.get("tmux_target"):
            rename_remote(s, "")  # explains why it can't
        elif new:
            rename_remote(s, new)
        return
    sessions, _ = discover()
    mark_all_live(sessions)
    s = next((x for x in sessions if x["id"] == sid), None)
    if not s:
        return
    if not s.get("live"):
        notify("Revive the session first — rename runs in its live tab.")
        return
    backend = BACKENDS.get(s.get("live_app"))
    if not backend:
        notify("That session is running outside iTerm/Terminal — rename it there.")
        return
    new = prompt_rename(display_name(s), rename_command(s, "").strip())
    if new:
        backend.act_rename(s, new)


def set_archived(sid, value):
    apply_archived([sid], value)


def apply_archived(ids, value):
    """Set archived=value for a batch of session ids in one state write. Shared by
    the native archive action and the webview panel. Archiving SKIPS live (running)
    sessions — archive means "done with it", and a running session isn't; quit it
    (→ parked) first. Unarchiving is always allowed. Returns the count changed."""
    if value:  # never hide a session that's still running in a terminal
        sessions, _ = discover()
        mark_all_live(sessions)
        live = {s["id"] for s in sessions + remote_sessions() if s.get("live")}
        ids = [sid for sid in ids if sid not in live]
    state = load_json(STATE_FILE, {})
    changed = 0
    for sid in ids:
        entry = state.setdefault(sid, {})
        if entry.get("archived") != value:
            entry["archived"] = value
            changed += 1
    if changed:
        save_json(STATE_FILE, state)
    return changed


def delete_sessions(ids):
    """Delete a batch of transcripts + their state entries. Returns the count
    actually removed. Shared by the native delete flow and the webview panel."""
    state = load_json(STATE_FILE, {})
    removed = 0
    remote = {s["id"]: s for s in remote_sessions()} if any(is_remote(i) for i in ids) else {}
    for sid in ids:
        if sid in remote:  # on its host, over ssh
            if delete_remote_session(remote[sid]):
                state.pop(sid, None)
                removed += 1
        elif delete_session_file(sid, state):
            removed += 1
    if removed:
        save_json(STATE_FILE, state)
    return removed


def ask_action(message, buttons, default):
    """display dialog with up to 3 buttons. Returns the clicked button name, or
    None if cancelled (a button literally named 'Cancel' counts as cancel)."""
    btns = ", ".join(f'"{osa(b)}"' for b in buttons)
    script = (
        f'set r to display dialog "{osa(message)}" with title "{UI_TITLE}" '
        f'buttons {{{btns}}} default button "{osa(default)}"\n'
        "return button returned of r"
    )
    r = run_osascript(script)
    return None if r.returncode != 0 else r.stdout.strip()


def do_archive_dir(cwd):
    """Archive every parked (non-live, non-archived) session in `cwd` at once —
    the 'Archive all' under a directory's Past sessions."""
    state = load_json(STATE_FILE, {})
    sessions, _ = discover()
    mark_all_live(sessions)
    changed = False
    for s in sessions:
        if s.get("cwd") != cwd:
            continue
        if state.get(s["id"], {}).get("archived") or s.get("live"):
            continue  # skip already-archived and live sessions
        state.setdefault(s["id"], {})["archived"] = True
        changed = True
    if changed:
        save_json(STATE_FILE, state)


def last_recorded_cwd(path):
    """The most recent cwd in a transcript. A session that was live through a
    directory rename re-logs its new cwd, so the last value is where it actually
    lives now (vs. parse_session's first value, used for grouping). None on error."""
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("cwd"):
                    last = obj["cwd"]
    except OSError:
        pass
    return last


def detect_remap_target(affected, old_cwd):
    """Auto-detect where a renamed directory went: a session that stayed live
    through the rename re-logged its new cwd. Return the first such cwd that
    differs from the dead `old_cwd` and still exists on disk, else None (a
    session closed before the rename has no record of the new location)."""
    for s in affected:
        src = session_file(s["id"])
        if not src:
            continue
        last = last_recorded_cwd(src)
        if last and last != old_cwd and os.path.isdir(last):
            return last
    return None


def do_remap(old_cwd):
    """Repair sessions whose directory was renamed/moved: rewrite each
    transcript's recorded cwd and relocate the .jsonl (+ sidecar dir) into the
    folder Claude derives from the new path — so grouping, cd, and
    `claude --resume` all work again. The destination is auto-detected from a
    live-renamed session's own latest cwd when possible, else picked by hand."""
    sessions, _ = discover()
    mark_all_live(sessions)
    affected = [s for s in sessions if s.get("cwd") == old_cwd]

    # Never remap a LIVE session: its running process keeps writing to the old
    # project folder, so moving the transcript just splits it (a stale copy here,
    # the live original recreated there). Remap is a repair for parked sessions.
    if any(s.get("live") for s in affected):
        notify("That session is live — quit it first, then remap.")
        return

    detected = detect_remap_target(affected, old_cwd)
    if detected:
        choice = ask_action(
            f"The session recorded its new location:\n\n{detected}\n\n"
            "Remap there, or pick a different folder?",
            ["Cancel", "Pick another…", "Remap"], "Remap")
        if choice == "Remap":
            new_cwd = detected
        elif choice == "Pick another…":
            new_cwd = choose_folder("Pick the new location for this directory "
                                    "(its sessions will be remapped):")
        else:
            return  # cancelled
    else:
        new_cwd = choose_folder("Pick the new location for this directory "
                                "(its sessions will be remapped):")
    new_cwd = (new_cwd or "").rstrip("/")
    if not new_cwd:
        return  # cancelled
    if new_cwd == old_cwd:
        notify("Same directory — nothing to remap.")
        return
    # Each harness keeps its own folder per cwd; a Pi transcript keeps its
    # '<ts>_<id>' filename and has no sidecar dir or project memory to carry.
    dests = {"claude": os.path.join(PROJECTS_DIR, encode_project_dir(new_cwd)),
             "pi": os.path.join(PI_SESSIONS_DIR, encode_pi_dir(new_cwd))}
    dest = dests["claude"]
    try:
        for h in {s.get("harness", "claude") for s in affected} or {"claude"}:
            os.makedirs(dests[h], exist_ok=True)
    except OSError:
        notify("Could not create the destination project folder.")
        return
    moved = 0
    src_proj = None
    for s in affected:
        is_pi = s.get("harness") == "pi"
        src = s.get("path") if is_pi else session_file(s["id"])
        if not src:
            continue
        target = os.path.join(dests["pi"], os.path.basename(src)) if is_pi \
            else os.path.join(dest, s["id"] + ".jsonl")
        try:
            with open(src, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            with open(target, "w", encoding="utf-8") as fh:
                fh.writelines(rewrite_cwd_line(ln, old_cwd, new_cwd) for ln in lines)
            if os.path.realpath(target) != os.path.realpath(src):  # both cwds can encode alike
                os.remove(src)
            moved += 1
            if is_pi:
                continue
            src_proj = os.path.dirname(src)  # old project folder, for memory/ below
            sidecar = src[:-6]  # drop ".jsonl"
            if os.path.isdir(sidecar):
                try:
                    os.replace(sidecar, os.path.join(dest, s["id"]))
                except OSError:
                    pass  # sidecar is best-effort; the transcript is what matters
        except OSError:
            continue
    if moved and src_proj:
        relocate_project_memory(src_proj, dest)  # memory/ is keyed by project folder
    notify(f"Remapped {moved} session(s) → {group_label(new_cwd)}." if moved
           else "No sessions were remapped.")


def rewrite_cwd_line(line, old_cwd, new_cwd):
    """Return `line` with a top-level cwd of old_cwd rewritten to new_cwd, else
    verbatim. JSON-aware (robust to spacing) yet surgical: only lines whose own
    cwd matches are reserialized — every other line, and incidental mentions of
    the old path inside a line's body, pass through untouched."""
    stripped = line.strip()
    if not stripped:
        return line
    try:
        obj = json.loads(stripped)
    except ValueError:
        return line
    if isinstance(obj, dict) and obj.get("cwd") == old_cwd:
        obj["cwd"] = new_cwd
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    return line


def relocate_project_memory(src_proj, dest_proj):
    """Move a project's memory/ dir from its old folder to the remap destination
    (memory is keyed by project folder, so a rename orphans it). No-clobber: only
    move files the destination lacks; rmdir each dir only once it's empty."""
    src_mem = os.path.join(src_proj, "memory")
    if os.path.isdir(src_mem):
        dst_mem = os.path.join(dest_proj, "memory")
        try:
            os.makedirs(dst_mem, exist_ok=True)
            for fn in os.listdir(src_mem):
                dst = os.path.join(dst_mem, fn)
                if not os.path.exists(dst):  # never overwrite the destination's own memory
                    os.replace(os.path.join(src_mem, fn), dst)
            os.rmdir(src_mem)  # only succeeds if now empty
        except OSError:
            pass
    try:
        os.rmdir(src_proj)  # tidy the old project folder if nothing's left
    except OSError:
        pass


def confirm_delete(message):
    """Caution dialog with Cancel/Delete (default Cancel). True only on Delete."""
    script = (
        f'set r to display dialog "{osa(message)}" with title "{UI_TITLE}" '
        f'buttons {{"Cancel", "Delete"}} default button "Cancel" with icon caution\n'
        "return button returned of r"
    )
    r = run_osascript(script)
    return r.returncode == 0 and r.stdout.strip() == "Delete"


def delete_session_file(sid, state):
    """Remove a session's transcript and its (now-orphaned) state entry.
    Returns True if anything changed. Caller saves `state`."""
    path = session_file(sid)
    changed = False
    if path:
        try:
            os.remove(path)
            changed = True
        except OSError:
            pass
    if sid in state:
        del state[sid]
        changed = True
    return changed


def do_delete(sid):
    """Permanently delete one session's transcript .jsonl (after confirming).
    Irreversible: the conversation and its resume capability are gone."""
    if not session_file(sid):
        return
    s = find_session(sid)
    name = display_name(s) if s else sid
    if not confirm_delete(f'Delete "{name}" permanently?\n\nThis removes its '
                          "transcript and cannot be undone — the session can no "
                          "longer be resumed."):
        return
    state = load_json(STATE_FILE, {})
    if delete_session_file(sid, state):
        save_json(STATE_FILE, state)


# ──────────────────────── webview management panel ────────────────────────
# A localhost http server (serve mode) backs an HTML panel opened from the menu
# via SwiftBar's `webview=true href=…`. SwiftBar's webview can't load file:// or
# bridge JS back to the plugin, so an interactive panel needs http. The server is
# 127.0.0.1-only, token-gated, single-file (HTML inlined), and idle-exits.
def server_token():
    """Stable per-user token gating the webview API (stored in server.json, which
    only the user can read). Stops other-origin browser tabs from CSRF-ing the
    destructive endpoints — they can reach 127.0.0.1 but can't read the token."""
    data = load_json(SERVER_FILE, {})
    tok = data.get("token")
    if not tok:
        import secrets
        tok = secrets.token_urlsafe(18)
        save_json(SERVER_FILE, {"port": WEBVIEW_PORT, "token": tok})
    return tok


def server_alive():
    """True if our webview server answers /ping. Doubles as the keep-alive request
    that resets the server's idle timer while SwiftBar keeps rendering."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{WEBVIEW_PORT}/ping", timeout=0.4) as r:
            return r.read(32).startswith(b"ccsessions")
    except Exception:
        return False


def ensure_server():
    """Start the webview server (detached) if it isn't already answering. Cheap
    no-op when alive. Never raises into the menu render.

    After spawning, briefly wait for the port to accept connections before
    returning. render_menu hands the panel URL to SwiftBar's webview in the same
    render, so if we returned before the child bound the port the first open
    after an idle-exit (system sleep, reboot, paused refresh) would hit a
    connection-refused and render blank — the webview doesn't retry. Polling here
    closes that cold-start race; the wait is skipped entirely on the common path
    where the server is already alive."""
    import time
    try:
        if server_alive():
            return
        server_token()  # create the token file before the child reads it
        subprocess.Popen(
            [sys.executable, SELF, "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        deadline = time.time() + 2.0  # cold import of app.py can be slow after sleep
        while time.time() < deadline:
            if server_alive():
                return
            time.sleep(0.05)
    except Exception:
        pass  # the panel just won't open; the native menu is unaffected


def recent_transcript_text(path, max_chars=2500, tail_bytes=65536):
    """The tail of a transcript's user/assistant text, for summarizing. Reads
    only the last `tail_bytes` of the file (not the whole transcript) so large
    sessions are cheap to sample. Keeps the last messages up to `max_chars`."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(-tail_bytes, os.SEEK_END)
            data = fh.read()
    except OSError:
        return ""
    msgs = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        role = o.get("type")
        if role == "message":  # a Pi transcript: the role sits inside the message
            role = (o.get("message") or {}).get("role")
        if o.get("isMeta") or role not in ("user", "assistant"):
            continue
        content = (o.get("message") or {}).get("content")
        text = None
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
        text = " ".join((text or "").split())
        if text and not text.startswith("<"):
            msgs.append(f"{role}: {text}")
    tail, total = [], 0
    for m in reversed(msgs):
        if tail and total + len(m) > max_chars:
            break
        tail.append(m)
        total += len(m)
    return "\n".join(reversed(tail))[:max_chars]


def claude_candidates():
    """Where the claude CLI plausibly lives, best guess first. Guessing is inherently
    fragile — install methods change and this list rots — so the `claude_bin` pref
    is the real answer when it's somewhere unusual; these just cover the common
    cases so most people never need it."""
    import glob
    home = os.path.expanduser("~")
    out = [os.path.join(home, ".local", "bin", "claude"),   # native installer (current default)
           os.path.join(home, ".claude", "local", "claude"),  # older "local install"
           "/opt/homebrew/bin/claude",                      # Homebrew, Apple silicon
           "/usr/local/bin/claude",                         # Homebrew, Intel / manual
           os.path.join(home, "bin", "claude"),
           os.path.join(home, ".volta", "bin", "claude"),
           os.path.join(home, ".bun", "bin", "claude"),
           os.path.join(home, "Library", "pnpm", "claude")]
    for pattern in ("~/.nvm/versions/node/*/bin/claude",
                    "~/.local/share/fnm/node-versions/*/installation/bin/claude",
                    "~/.asdf/installs/nodejs/*/bin/claude"):
        out += sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)  # newest first
    return out


def claude_path():
    """Absolute path to a RUNNABLE claude CLI, or None if we can't find one. The
    summarizer runs detached (SwiftBar spawns it with a minimal PATH), so a bare
    'claude' usually isn't resolvable and the fallbacks below do the real work.

    Returns None rather than a hopeful bare "claude": a path we know will fail is
    worse than an explicit answer, because the caller can then say so out loud
    instead of retrying forever and looking merely slow."""
    import shutil
    runnable = lambda p: p and os.path.isfile(p) and os.access(p, os.X_OK)
    override = (load_prefs().get("claude_bin") or "").strip()
    if override:  # explicit wins over everything, including PATH
        return os.path.expanduser(override) if runnable(os.path.expanduser(override)) else None
    found = shutil.which(CLAUDE_BIN)
    if found:
        return found
    return next((c for c in claude_candidates() if runnable(c)), None)


def generate_summaries(texts):
    """Ask Claude (Haiku) for a structured read on several sessions in ONE call:
    per transcript a ≤SUMMARY_MAX-char one-liner plus a status (done/active/
    blocked) and a rough progress estimate. Returns a list parallel to `texts`
    of {"summary","status","progress"} or None (empty input, unparseable line,
    or Claude unavailable/erroring — in which case every entry is None).

    One call per batch, not per transcript: each `claude -p` process is a new
    session as far as usage accounting goes, so batching divides the session
    count by SUMMARY_BATCH."""
    texts = list(texts or [])
    if not any(texts):
        return [None] * len(texts)
    n = len(texts)
    prompt = ("You index past coding sessions. Below are the tails of "
              f"{n} EXISTING transcript{'s' if n != 1 else ''} between a user and an "
              "AI coding assistant, each under a '### TRANSCRIPT <k>' header. Do NOT "
              "reply to them or continue them — only describe each from the outside.\n"
              f"Output EXACTLY {n} line{'s' if n != 1 else ''}, one per transcript in "
              "order, EXACTLY this format, nothing else:\n"
              "<k>: STATUS=<done|active|blocked>; PROGRESS=<0-100>; SUMMARY=<text>\n"
              "STATUS: done if the task looks finished, blocked if stuck or erroring, "
              "otherwise active. PROGRESS: rough 0-100 estimate of how complete it is. "
              f"SUMMARY: what the session is about — specific (task/feature/files), at "
              f"most {SUMMARY_MAX - 12} characters, no quotes, no trailing period.\n")
    for k, text in enumerate(texts, 1):
        prompt += f"\n### TRANSCRIPT {k}\n{text or '(empty)'}\n"
    exe = claude_path()
    if exe is None:
        return [None] * n  # no CLI to call; do_summarize reports this rather than looping
    raw = None
    for args in (SUMMARY_ARGS, []):  # lean flags first, plain `-p` only if REJECTED
        try:
            os.makedirs(SUMMARY_WORKDIR, exist_ok=True)  # isolate this call's own transcript
            r = subprocess.run([exe, "-p", "--model", SUMMARY_MODEL] + args + [prompt],
                               capture_output=True, text=True, timeout=180,
                               stdin=subprocess.DEVNULL, cwd=SUMMARY_WORKDIR)
        except subprocess.TimeoutExpired:
            note_cli_error("timed out after 180s")
            return [None] * n
        except (OSError, subprocess.SubprocessError) as e:
            note_cli_error(f"could not run it: {e}")
            return [None] * n
        count_summary_call()
        if r.returncode == 0:
            raw = r.stdout
            break
        note_cli_error(cli_error_reason(r))  # keep WHY, so the panel can say more than "it failed"
        if not _flags_rejected(r.stderr):
            break  # a real failure (auth, quota, network): retrying plain would just double the cost
    if raw is None:
        return [None] * n
    return parse_summaries(raw, n)


def cli_error_reason(r):
    """A one-line why from a failed `claude -p`. Prefers stderr, falls back to
    stdout (the CLI reports some refusals there), and always names the exit code
    so an utterly silent failure still says something."""
    for stream in (r.stderr, r.stdout):
        line = " ".join((stream or "").split())
        if line:
            return line[:160] + ("…" if len(line) > 160 else "")
    return f"exited {r.returncode} with no output"


# Set from the summarizer's worker threads, read by do_summarize on the same pass.
# Assignment is atomic under the GIL and every batch fails for the same reason, so
# the last writer winning is exactly the representative sample we want.
_CLI_ERROR = ""


def note_cli_error(reason):
    global _CLI_ERROR
    _CLI_ERROR = reason


def take_cli_error():
    """Read and clear, so a reason never leaks into a later pass."""
    global _CLI_ERROR
    reason, _CLI_ERROR = _CLI_ERROR, ""
    return reason


def _flags_rejected(stderr):
    """True if the CLI choked on one of SUMMARY_ARGS (older CLI), which is the only
    case where retrying without them is worth a second session."""
    s = (stderr or "").lower()
    return any(m in s for m in ("unknown option", "unrecognized", "unknown argument",
                                "too many arguments"))


def generate_summary(text):
    """Single-transcript convenience over generate_summaries()."""
    return generate_summaries([text])[0]


def parse_summaries(raw, n):
    """Split a batched reply into n per-transcript results. Lines are matched by
    their leading '<k>:' index (so a skipped or reordered line lands on the right
    transcript); if the model dropped the indexes entirely, fall back to order."""
    results = [None] * n
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    indexed = []
    for line in lines:
        m = re.match(r"^\W*(\d{1,3})\s*[:.)\-]\s*(.*)$", line)
        if m and 1 <= int(m.group(1)) <= n:
            indexed.append((int(m.group(1)) - 1, m.group(2)))
    if indexed:
        for i, body in indexed:
            if results[i] is None:
                results[i] = parse_summary(body)
    else:
        for i, line in enumerate(lines[:n]):
            results[i] = parse_summary(line)
    return results


def parse_summary(raw):
    """Parse 'STATUS=…; PROGRESS=…; SUMMARY=…' into a dict, tolerantly — if the
    format drifts, treat the whole line as the summary with default status."""
    if not raw:
        return None
    status, progress, summ = "active", None, raw
    m = re.search(r"status\s*=\s*(done|active|blocked)", raw, re.I)
    if m:
        status = m.group(1).lower()
    m = re.search(r"progress\s*=\s*(\d{1,3})", raw, re.I)
    if m:
        progress = max(0, min(100, int(m.group(1))))
    m = re.search(r"summary\s*=\s*(.+)$", raw, re.I)
    if m:
        summ = m.group(1)
    summ = clean_summary(summ.strip().strip('"'))
    return {"summary": summ, "status": status, "progress": progress} if summ else None


def clean_summary(s):
    """Strip the conversational lead-ins Haiku sometimes adds despite the prompt,
    and cap to SUMMARY_MAX. Returns the cleaned one-liner."""
    if not s:
        return ""
    low = s.lower()
    for lead in ("i understand", "sure", "here's a summary", "here is a summary",
                 "here's", "here is", "summary:", "this session is about",
                 "this session covers", "this session", "okay", "ok,", "the session"):
        if low.startswith(lead):
            s = s[len(lead):].lstrip(" ,:.—-–").strip()
            break
    return s[:SUMMARY_MAX]


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True            # signal deliverable → alive
    except ProcessLookupError:
        return False           # ESRCH → no such process
    except PermissionError:
        return True            # EPERM → process exists (just not ours to signal)
    except (OSError, ValueError):
        return False


def summarize_lock_held():
    """True if a summarize pass is genuinely in progress: a lock whose owner pid is
    alive AND that was heartbeated within SUMMARY_LOCK_STALE. A long-running pass
    refreshes the lock each iteration, so it stays held (no duplicate spawns); a
    crashed/killed pass stops heartbeating and is reclaimed once stale. The pid
    check reclaims a dead owner immediately (before staleness), and the staleness
    guard covers pid reuse — both must hold for the lock to count as alive."""
    import time
    lock = SUMMARY_FILE + ".lock"
    try:
        if (time.time() - os.path.getmtime(lock)) >= SUMMARY_LOCK_STALE:
            return False  # not heartbeated recently → owner gone/stuck → reclaim
    except OSError:
        return False  # no lock
    try:
        with open(lock) as fh:
            pid = int(fh.read().strip())  # empty/garbled → ValueError below
    except (OSError, ValueError):
        return True  # fresh lock, mid-write/garbled → assume held (don't race it)
    return _pid_alive(pid)


def set_summarizer_status(error=""):
    """Record why the summarizer can't work (or clear it once it can). Written by
    the background pass, read by the panel — the only channel a detached, silent
    subprocess has to explain itself to the UI."""
    import time
    st = load_json(SUMMARY_STATUS_FILE, {}) or {}
    if error:
        st.update({"error": error, "ts": time.time()})
    else:
        st.pop("error", None)
        st.pop("ts", None)
    save_json(SUMMARY_STATUS_FILE, st)


def summarizer_status():
    """The current summarizer problem, or "" when healthy."""
    return (load_json(SUMMARY_STATUS_FILE, {}) or {}).get("error", "")


def count_summary_call():
    """Tally one `claude -p` invocation against today's date (local), so the
    panel can show how many sessions the summarizer actually created."""
    import time
    st = load_json(SUMMARY_STATUS_FILE, {}) or {}
    calls = st.get("calls") or {}
    day = time.strftime("%Y-%m-%d")
    calls = {day: calls.get(day, 0) + 1}  # keep today only; that's all the UI shows
    st["calls"] = calls
    save_json(SUMMARY_STATUS_FILE, st)


def summary_calls_today():
    import time
    st = load_json(SUMMARY_STATUS_FILE, {}) or {}
    return (st.get("calls") or {}).get(time.strftime("%Y-%m-%d"), 0)


def summary_interval():
    """Seconds between summary passes, from the `summary_every` pref (hours).
    0 = every refresh (the old behaviour). Garbage → the default."""
    try:
        hours = float(load_prefs().get("summary_every", DEFAULT_PREFS["summary_every"]))
    except (TypeError, ValueError):
        hours = DEFAULT_PREFS["summary_every"]
    return max(0.0, hours) * 3600


def summarizer_next_due():
    """Seconds until the next scheduled pass (0 = due now)."""
    import time
    st = load_json(SUMMARY_STATUS_FILE, {}) or {}
    return max(0.0, st.get("last_pass", 0) + summary_interval() - time.time())


def summarizer_due():
    return summarizer_next_due() <= 0


def stamp_summary_pass():
    import time
    st = load_json(SUMMARY_STATUS_FILE, {}) or {}
    st["last_pass"] = time.time()
    save_json(SUMMARY_STATUS_FILE, st)


def do_summarize(limit=SUMMARIES_PER_RUN, force=False):
    """Background pass: (re)generate summaries for sessions whose transcript
    changed since last summarized, bounded to `limit` sessions per run, batched
    SUMMARY_BATCH per Claude call and SUMMARY_WORKERS calls at a time (each is
    almost entirely network wait). Runs only when a pass is due (see
    summarizer_due) unless `force` (the panel's Re-summarize buttons).
    Lock-guarded (heartbeated) so overlapping render-spawned runs don't stack."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    if not load_prefs().get("summaries", True):
        return  # summaries switched off in Settings
    if not force and not summarizer_due():
        return  # next scheduled pass isn't for a while
    if claude_path() is None:
        # Bail loudly rather than attempting calls that can only fail. Without this
        # the pass caches nothing, retries every tick, and the panel just shows a
        # backlog that never drains — which reads as "slow", not "broken".
        return set_summarizer_status(NO_CLI_ERROR)
    if summarizer_status() == NO_CLI_ERROR:
        # The CLI is back. Clear it HERE, not at the end of the pass: the end only
        # runs when there was work to do, so on a machine whose summaries are all
        # cached a fixed install would otherwise show "not found" forever.
        set_summarizer_status("")
    lock = SUMMARY_FILE + ".lock"
    if summarize_lock_held():
        return  # another pass is genuinely running
    try:
        with open(lock, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    try:
        sessions, ok = discover()
        if not ok:
            return
        # Priority order: live first, then parked, then archived (most-recent first
        # within each) — so the sessions you're actively using get summarized soonest.
        state = load_json(STATE_FILE, {})
        mark_all_live(sessions)
        for s in sessions:
            s["archived"] = bool(state.get(s["id"], {}).get("archived"))
        sessions.sort(key=lambda s: (2 if s["archived"] else (0 if s["live"] else 1), -s["mtime"]))
        summaries = load_json(SUMMARY_FILE, {})
        # Pick the work first (cheap, all local stat/read), then fan the Claude
        # calls out. The priority sort above still decides who gets in when the
        # candidate list is longer than `limit`.
        todo = []
        for s in sessions:
            if len(todo) >= limit:
                break
            path = session_file(s["id"])
            if not path:
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            hit = summaries.get(s["id"])
            if hit and hit.get("mtime") == st.st_mtime and hit.get("size") == st.st_size:
                continue  # unchanged since last summary → no Claude call
            if hit and (time.time() - hit.get("ts", 0)) < SUMMARY_MIN_INTERVAL:
                continue  # changed, but summarized very recently — throttle live sessions
            todo.append((s["id"], st, recent_transcript_text(path)))

        attempted = failed = 0
        # Transcripts with nothing to say get an empty summary without a call;
        # the rest are packed SUMMARY_BATCH per call (one session each, as far
        # as usage accounting goes) and the batches run SUMMARY_WORKERS-wide.
        for sid, st, text in todo:
            if not text:
                summaries[sid] = {"mtime": st.st_mtime, "size": st.st_size, "ts": time.time(),
                                  "summary": "", "status": "", "progress": None}
        with_text = [(sid, st, text) for sid, st, text in todo if text]
        batches = [with_text[i:i + SUMMARY_BATCH] for i in range(0, len(with_text), SUMMARY_BATCH)]
        if batches:
            take_cli_error()  # drop any reason left over from an earlier pass
            with ThreadPoolExecutor(max_workers=SUMMARY_WORKERS) as pool:
                # Keep the futures paired with their batch so results land on the
                # right keys; iterate in submission order so the priority sort holds.
                jobs = [(batch, pool.submit(generate_summaries, [t for _, _, t in batch]))
                        for batch in batches]
                for batch, fut in jobs:
                    try:
                        infos = fut.result()
                    except Exception:
                        infos = [None] * len(batch)
                    for (sid, st, text), info in zip(batch, infos):
                        attempted += 1
                        if info is None:
                            failed += 1
                            continue  # Claude failed on this one — don't cache empty; retry next pass
                        summaries[sid] = {"mtime": st.st_mtime, "size": st.st_size, "ts": time.time(),
                                          "summary": info.get("summary", ""),
                                          "status": info.get("status", ""),
                                          "progress": info.get("progress")}
                    save_json(SUMMARY_FILE, summaries)  # persist incrementally, per batch
                    try:
                        os.utime(lock, None)  # heartbeat: keep our lock fresh through a long pass
                    except OSError:
                        pass
        elif todo:
            save_json(SUMMARY_FILE, summaries)  # only empty-transcript entries to record
        # prune only summaries whose transcript is truly gone — checked via the
        # file, NOT discover()'s set, so a transient/partial discover() can never
        # wipe good summaries (that caused a full re-summarize).
        stale = [k for k in summaries if session_file(k) is None]
        if stale:
            for k in stale:
                summaries.pop(k, None)
            save_json(SUMMARY_FILE, summaries)

        # Report the pass's health. Every attempt failing means the CLI resolves but
        # can't actually run (not logged in, quota, a broken install) — the other way
        # this looks merely slow. A partial failure is normal (a timeout here and
        # there) and self-corrects next pass, so it isn't worth alarming about.
        if attempted and failed == attempted:
            why = take_cli_error()
            set_summarizer_status(
                "Claude CLI found but every summary call failed — check `claude -p` "
                "runs in a terminal (login/quota)."
                + (f" It said: {why}" if why else ""))
        elif attempted:
            set_summarizer_status("")  # healthy again → clear any previous complaint
        # Scheduled passes stamp the clock whether or not there was work: the next
        # one is due summary_every hours from now. A forced pass (Re-summarize)
        # doesn't move the schedule.
        if not force:
            stamp_summary_pass()
    finally:
        # the summarizer's own one-shot `claude -p` sessions are throwaway — clear
        # them so the excluded folder doesn't accumulate.
        import shutil
        shutil.rmtree(os.path.join(PROJECTS_DIR, summarizer_proj_dir()), ignore_errors=True)
        try:
            os.remove(lock)
        except OSError:
            pass


def ensure_summarizer(force=False):
    """Spawn a detached background `summarize` pass when one is due (or `force`)
    and none is already running. Cheap no-op otherwise; never raises into the
    render."""
    try:
        if not load_prefs().get("summaries", True):
            return  # summaries switched off in Settings
        if not force and not summarizer_due():
            return  # not time yet — this is what keeps the render from spawning a pass every tick
        if summarize_lock_held():
            return
        subprocess.Popen(
            [sys.executable, SELF, "summarize"] + (["--force"] if force else []),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        pass


# ── background workspace scan (see WORKSPACES_CACHE / find_workspace_roots) ──
def workspace_scan_held():
    """True if a workspace scan is genuinely in progress — a lock whose owner pid
    is alive and was touched within WORKSPACE_SCAN_LOCK_STALE. Same reclaim logic
    as summarize_lock_held()."""
    return _lock_held(WORKSPACES_CACHE + ".lock", WORKSPACE_SCAN_LOCK_STALE)


def do_scan_workspaces():
    """Background pass: walk for workspace roots and cache them. Lock-guarded so
    overlapping render-spawned scans don't stack."""
    import time
    lock = WORKSPACES_CACHE + ".lock"
    if workspace_scan_held():
        return
    try:
        with open(lock, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    try:
        roots = find_workspace_roots()
        save_json(WORKSPACES_CACHE, {"ts": time.time(), "roots": roots})
    except Exception:
        pass  # never let a scan failure break anything; cache just goes stale
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def ensure_workspace_scan():
    """Spawn a detached background scan if the cache is missing or older than
    WORKSPACE_SCAN_TTL and none is already running. Gated by the scan_workspaces
    pref. Cheap no-op otherwise; never raises into the render."""
    import time
    if not load_prefs().get("scan_workspaces", True):
        return
    try:
        try:
            fresh = (time.time() - os.path.getmtime(WORKSPACES_CACHE)) < WORKSPACE_SCAN_TTL
            missing = False
        except OSError:
            fresh, missing = False, True
        if fresh or workspace_scan_held():
            return
        if missing:
            # No cache yet — first run, or an external workspace create/delete just
            # busted it. Scan INLINE so THIS render lists the new workspace, instead
            # of reading an empty cache and only catching up on the next refresh.
            do_scan_workspaces()
            return
        subprocess.Popen(   # stale but present → refresh in the background, no blocking
            [sys.executable, SELF, "scan-workspaces"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        pass


def cached_workspace_roots():
    """Workspace roots from the last cached scan that still exist on disk. Empty
    until the first background scan completes (or if the pref is off)."""
    if not load_prefs().get("scan_workspaces", True):
        return []
    data = load_json(WORKSPACES_CACHE, {})
    return [r for r in data.get("roots", []) if os.path.isdir(r)]


# ── remote hosts: sessions on other machines, over ssh + tmux (see REMOTE_CACHE) ──
def remote_hosts():
    """The ssh targets from the `remote_hosts` pref ('a, user@b' → ['a', 'user@b'])."""
    return [h for h in re.split(r"[,\s]+", str(load_prefs().get("remote_hosts") or "")) if h]


def ssh_base(host):
    """`ssh … host` for background calls: never prompts, shares one connection per
    host across calls (control master under STATE_DIR/ssh)."""
    cdir = os.path.join(STATE_DIR, "ssh")
    if len(cdir) + 41 > 100:  # %C is 40 chars; unix socket paths cap at ~104
        return ["ssh", *SSH_OPTS, host]  # works, just without connection sharing
    os.makedirs(cdir, mode=0o700, exist_ok=True)
    return ["ssh", *SSH_OPTS, "-o", "ControlMaster=auto",
            "-o", "ControlPath=" + os.path.join(cdir, "%C"), "-o", "ControlPersist=600", host]


def remote_collect(cache_path=None):
    """Runs ON THE REMOTE HOST (remote_script ships it with the parsers it uses):
    every Claude/Pi session there, its tmux panes, and the agent processes running
    on a tty, as one JSON-able dict. Re-parses only transcripts that changed since
    the last scan (cache at `cache_path`, on the remote). Liveness is decided on
    this side, in assign_remote_liveness, so it can be tested without a host."""
    import socket
    cache = load_json(cache_path, {}) if cache_path else {}
    new_cache, sessions = {}, []
    for root, harness in ((PROJECTS_DIR, "claude"), (PI_SESSIONS_DIR, "pi")):
        try:
            projs = os.listdir(root)
        except OSError:
            continue
        for proj in projs:
            if harness == "claude" and proj == "-":  # sub-agent transcripts, as in discover()
                continue
            pdir = os.path.join(root, proj)
            try:
                names = os.listdir(pdir)
            except OSError:
                continue
            for fn in names:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(pdir, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                hit = cache.get(path)
                if hit and hit.get("mtime") == st.st_mtime and hit.get("size") == st.st_size:
                    rec = hit["rec"]
                elif harness == "pi":
                    sid, cwd, title = parse_pi_session(path)
                    rec = dict(pi_tail_info(path), id=sid, cwd=cwd, title=title)
                else:
                    cwd, title = parse_session(path)
                    rec = dict(tail_info(path), id=fn[:-6], cwd=cwd, title=title)
                new_cache[path] = {"mtime": st.st_mtime, "size": st.st_size, "rec": rec}
                sessions.append(dict(rec, harness=harness, path=path, mtime=st.st_mtime))
    if cache_path and new_cache != cache:
        try:
            save_json(cache_path, new_cache)
        except OSError:
            pass
    panes = {}
    try:
        r = subprocess.run(["tmux", "list-panes", "-a", "-F",
                            "#{pane_tty}\t#{session_name}\t#{session_name}:#{window_index}.#{pane_index}"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                panes[parts[0]] = {"session": parts[1], "target": parts[2]}
    except (OSError, subprocess.SubprocessError):
        pass  # no tmux, or no tmux server running
    procs = []
    try:
        r = subprocess.run(["ps", "-eo", "pid=,tty=,args="], capture_output=True, text=True, timeout=5)
        lines = r.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        lines = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) < 3 or parts[1] in ("?", "??", "-"):
            continue
        pid, tty, args = parts
        harness = "claude" if _is_claude_cmd(args) else "pi" if _is_pi_cmd(args) else None
        if not harness:
            continue
        m = re.search(r"--resume[=\s]+(\S+)", args)
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")  # Linux; elsewhere cwd stays unknown
        except OSError:
            cwd = None
        procs.append({"harness": harness, "tty": "/dev/" + tty, "cwd": cwd,
                      "sid": m.group(1) if m and not m.group(1).startswith("-") else None})
    return {"hostname": socket.gethostname(), "sessions": sessions, "panes": panes, "procs": procs}


# What remote_script ships: remote_collect and everything it calls, plus the
# globals they read (rebound to the remote's own home in _REMOTE_PRELUDE).
_REMOTE_FUNCS = ("load_json", "save_json", "short_model", "context_window", "parse_session",
                 "tail_info", "_pi_text", "pi_session_id", "parse_pi_session", "pi_context_window",
                 "pi_ctx_tokens", "pi_tail_info", "_is_claude_cmd", "_is_pi_cmd", "remote_collect")
_REMOTE_PRELUDE = """\
import json, os, re, subprocess
HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
PI_AGENT_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR") or os.path.join(HOME, ".pi", "agent"))
PI_SESSIONS_DIR = os.path.join(PI_AGENT_DIR, "sessions")
PI_MODELS_FILE = os.path.join(PI_AGENT_DIR, "models-store.json")
REMOTE_PARSE_CACHE = os.path.join(HOME, ".cache", "agent-sessions", "parse.json")
_PI_WINDOWS = None
"""


def remote_script():
    """Self-contained python source that prints remote_collect()'s JSON on a host.
    Built from this module's own functions (inspect.getsource), so local and remote
    parsing can never drift apart."""
    import inspect
    consts = (f"CLAUDE_BIN = {CLAUDE_BIN!r}\nPI_BIN = {PI_BIN!r}\n"
              f"CONTEXT_WINDOW = {CONTEXT_WINDOW!r}\nCONTEXT_WINDOW_1M = {CONTEXT_WINDOW_1M!r}\n"
              f"TAIL_DEFAULTS = {TAIL_DEFAULTS!r}\n")
    funcs = [inspect.getsource(globals()[n]) for n in _REMOTE_FUNCS]
    return "\n".join([_REMOTE_PRELUDE, consts] + funcs
                     + ["print(json.dumps(remote_collect(REMOTE_PARSE_CACHE)))"])


def assign_remote_liveness(sessions, procs, panes):
    """Mark a host's sessions live from the agent processes running there. A
    `claude --resume <id>` names its session exactly; any other process is matched
    by cwd to the newest not-yet-live session of the same harness (as locally).
    A process whose tty is a tmux pane makes that pane the session's jump target."""
    for s in sessions:
        s["live"] = False
        s.pop("tmux_target", None)
        s.pop("tmux_session", None)

    def light(s, p):
        s["live"] = True
        pane = panes.get(p.get("tty"))
        if pane:
            s["tmux_target"], s["tmux_session"] = pane["target"], pane["session"]

    by_id = {(s.get("harness"), s.get("id")): s for s in sessions}
    rest = []
    for p in procs:
        s = by_id.get((p.get("harness"), p.get("sid"))) if p.get("sid") else None
        if s and not s["live"]:
            light(s, p)
        else:
            rest.append(p)
    for p in sorted(rest, key=lambda p: p.get("tty") or ""):
        if not p.get("cwd"):
            continue
        here = sorted((s for s in sessions if s.get("harness") == p.get("harness")
                       and s.get("cwd") == p["cwd"] and not s["live"]), key=lambda s: -s["mtime"])
        if here:
            light(here[0], p)


def scan_remote_host(host):
    """One host's sessions (liveness assigned) or why it couldn't be read."""
    try:
        r = subprocess.run(ssh_base(host) + ["python3", "-"], input=remote_script(),
                           capture_output=True, text=True, timeout=REMOTE_SSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {REMOTE_SSH_TIMEOUT}s"}
    except OSError as e:
        return {"ok": False, "error": f"could not run ssh: {e}"}
    if r.returncode != 0:
        return {"ok": False, "error": cli_error_reason(r)}
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {"ok": False, "error": "unreadable reply: " + " ".join(r.stdout.split())[:120]}
    sessions = data.get("sessions") or []
    assign_remote_liveness(sessions, data.get("procs") or [], data.get("panes") or {})
    return {"ok": True, "error": "", "hostname": data.get("hostname") or host, "sessions": sessions}


def _lock_held(lock, stale):
    """True if `lock` was touched within `stale` seconds by a pid that's still
    alive (a fresh but unreadable lock counts as held — it's mid-write)."""
    import time
    try:
        if (time.time() - os.path.getmtime(lock)) >= stale:
            return False
    except OSError:
        return False
    try:
        with open(lock) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return True
    return _pid_alive(pid)


def do_remote_scan():
    """Background pass: scan every remote host and cache the result. A host that
    can't be reached keeps its last-known sessions listed, but none of them live —
    a stale green dot would send you to a session that may be gone."""
    import time
    lock = REMOTE_CACHE + ".lock"
    if _lock_held(lock, REMOTE_SCAN_LOCK_STALE):
        return
    try:
        with open(lock, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    try:
        prev = load_json(REMOTE_CACHE, {})
        out = {}
        for host in remote_hosts():
            res = scan_remote_host(host)
            if not res["ok"]:
                old = prev.get(host) or {}
                res["hostname"] = old.get("hostname") or host
                res["sessions"] = [dict(s, live=False) for s in old.get("sessions") or []]
            res["ts"] = time.time()
            out[host] = res
            try:
                os.utime(lock, None)  # heartbeat between hosts
            except OSError:
                pass
        save_json(REMOTE_CACHE, out)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def ensure_remote_scan():
    """Spawn a background remote scan when the cache is older than REMOTE_SCAN_TTL
    or doesn't cover the configured hosts. Cheap no-op otherwise (and with no
    hosts); never raises into the render."""
    import time
    try:
        hosts = remote_hosts()
        if not hosts:
            return
        try:
            fresh = (time.time() - os.path.getmtime(REMOTE_CACHE)) < REMOTE_SCAN_TTL
        except OSError:
            fresh = False
        if fresh and set(load_json(REMOTE_CACHE, {})) == set(hosts):
            return
        if _lock_held(REMOTE_CACHE + ".lock", REMOTE_SCAN_LOCK_STALE):
            return
        subprocess.Popen([sys.executable, SELF, "remote-scan"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass


def remote_sessions():
    """Cached sessions of the configured hosts, shaped like local ones plus
    host / host_label / sid (the id on the host). id is '<host>#<sid>'. live_app:
    'tmux' (jumpable pane), 'remote' (live but not in tmux) or None."""
    hosts = remote_hosts()
    if not hosts:
        return []
    cache = load_json(REMOTE_CACHE, {})
    out = []
    for host in hosts:
        entry = cache.get(host) or {}
        label = entry.get("hostname") or host
        for rec in entry.get("sessions") or []:
            if not rec.get("id"):
                continue
            s = dict(rec, sid=rec["id"], id=f"{host}#{rec['id']}", host=host, host_label=label)
            s["live_app"] = ("tmux" if s.get("tmux_target") else "remote") if s.get("live") else None
            out.append(s)
    return out


def remote_errors():
    """['<host>: <why>'] for hosts whose last scan failed."""
    cache = load_json(REMOTE_CACHE, {})
    return [f"{(cache.get(h) or {}).get('hostname') or h}: {(cache.get(h) or {}).get('error')}"
            for h in remote_hosts() if (cache.get(h) or {}).get("error")]


def is_remote(sid):
    return "#" in (sid or "")


def find_remote(sid):
    return next((s for s in remote_sessions() if s["id"] == sid), None)


def remote_name(s):
    """display_name() of a remote session (its own id, not the host-prefixed one)."""
    return display_name({**s, "id": s.get("sid") or s["id"]})


def _tmux_name(seed):
    return "as-" + re.sub(r"[^A-Za-z0-9]", "", seed)[:12]


def remote_tmux_launch(cwd, cmd, name):
    """Remote shell: create tmux session `name` in `cwd` and TYPE `cmd` into its
    shell (so it runs with your interactive PATH, and the pane survives the agent
    exiting) — unless that session already exists — then attach to it."""
    exact = shlex.quote("=" + name)
    start = (f"tmux new-session -d -s {shlex.quote(name)}" + (f" -c {shlex.quote(cwd)}" if cwd else "")
             + f" \\; send-keys -t {shlex.quote('=' + name + ':')} {shlex.quote(cmd)} Enter")
    return f"tmux has-session -t {exact} 2>/dev/null || {start}; tmux attach-session -t {exact}"


def remote_attach_command(s, skip_perms=False):
    """Local shell command for a terminal tab: attach to the session's tmux pane on
    its host, or (parked) resume it there in a new tmux session."""
    if s.get("live") and s.get("tmux_target"):
        target = s["tmux_target"]
        win = shlex.quote(target.rsplit(".", 1)[0])
        remote = (f"tmux select-window -t {win} \\; select-pane -t {shlex.quote(target)}"
                  f" \\; attach-session -t {shlex.quote('=' + s['tmux_session'])}")
    else:
        cmd = resume_command({**s, "id": s["sid"]}, skip_perms)
        remote = remote_tmux_launch(s.get("cwd"), cmd, _tmux_name(s["sid"]))
    return f"ssh -t {shlex.quote(s['host'])} {shlex.quote(remote)}"


def remote_send_keys(s, text):
    """Type `text` + Enter into a remote session's tmux pane (no terminal needed)."""
    t = shlex.quote(s["tmux_target"])
    remote = f"tmux send-keys -t {t} -l {shlex.quote(text)} \\; send-keys -t {t} Enter"
    try:
        r = subprocess.run(ssh_base(s["host"]) + [remote], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return "" if r.returncode == 0 else cli_error_reason(r)


def delete_remote_session(s):
    """Remove a remote transcript (and drop it from the cache). True on success."""
    try:
        r = subprocess.run(ssh_base(s["host"]) + ["rm -f -- " + shlex.quote(s["path"])],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    cache = load_json(REMOTE_CACHE, {})
    entry = cache.get(s["host"]) or {}
    entry["sessions"] = [x for x in entry.get("sessions") or [] if x.get("path") != s["path"]]
    save_json(REMOTE_CACHE, cache)
    return True


# $ per million tokens (input, output, cache-write, cache-read) — approximate public
# Claude pricing; the session cost is an *estimate* and labelled as such in the UI.
PRICING = {
    "opus":   (15.0, 75.0, 18.75, 1.50),
    "sonnet": (3.0,  15.0,  3.75, 0.30),
    "haiku":  (0.80,  4.0,  1.00, 0.08),
}


def estimate_cost(model, totals):
    """Rough USD cost of a session from its cumulative token totals."""
    fam = next((f for f in PRICING if model.startswith(f)), "opus")
    p_in, p_out, p_cw, p_cr = PRICING[fam]
    return round((totals["input"] * p_in + totals["output"] * p_out
                  + totals["cache_write"] * p_cw + totals["cache_read"] * p_cr) / 1_000_000, 2)


def session_stats(sid):
    """Full `/status`-style breakdown for one session — reads the WHOLE transcript
    (on-demand, one session) and sums token usage across every assistant turn."""
    path = session_file(sid)
    if not path:
        return None
    if session_harness(path) == "pi":
        return pi_session_stats(sid, path)
    cwd, title = parse_session(path)
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    turns = 0
    tool_calls = 0
    thinking_turns = 0
    model = ""
    last_ctx = 0
    first_ts = last_ts = None
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                if o.get("type") == "assistant":
                    msg = o.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, list):  # effort signals: tool calls + extended thinking
                        tool_calls += sum(1 for b in content
                                          if isinstance(b, dict) and b.get("type") == "tool_use")
                        if any(isinstance(b, dict) and b.get("type") == "thinking" for b in content):
                            thinking_turns += 1
                    u = msg.get("usage")
                    if isinstance(u, dict):
                        totals["input"] += u.get("input_tokens", 0)
                        totals["output"] += u.get("output_tokens", 0)
                        totals["cache_read"] += u.get("cache_read_input_tokens", 0)
                        totals["cache_write"] += u.get("cache_creation_input_tokens", 0)
                        last_ctx = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                                    + u.get("cache_creation_input_tokens", 0))
                        turns += 1
                    if msg.get("model"):
                        model = msg["model"]
    except OSError:
        return None
    sm = short_model(model)
    win = context_window(sm)
    return {
        "id": sid,
        "name": display_name({"id": sid, "cwd": cwd, "title": title}),
        "cwd": cwd,
        "model": sm,
        "turns": turns,
        "tool_calls": tool_calls,
        "thinking_turns": thinking_turns,
        "ctx_tokens": last_ctx,
        "ctx_pct": min(100, round(100 * last_ctx / win)) if last_ctx else 0,
        "window": win,
        "totals": totals,
        "total_tokens": sum(totals.values()),
        "cost": estimate_cost(sm, totals),
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def pi_session_stats(sid, path):
    """session_stats() for a Pi transcript — same keys. Pi records each turn's
    actual cost (usage.cost.total), so `cost` is real, not estimated from PRICING."""
    _, cwd, title = parse_pi_session(path)
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    turns = tool_calls = thinking_turns = 0
    cost = 0.0
    model = provider = ""
    last_ctx = 0
    first_ts = last_ts = None
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = ts
                msg = o.get("message") if o.get("type") == "message" else None
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    tool_calls += sum(1 for b in content
                                      if isinstance(b, dict) and b.get("type") == "toolCall")
                    if any(isinstance(b, dict) and b.get("type") == "thinking" for b in content):
                        thinking_turns += 1
                u = msg.get("usage")
                if isinstance(u, dict):
                    totals["input"] += u.get("input", 0) or 0
                    totals["output"] += u.get("output", 0) or 0
                    totals["cache_read"] += u.get("cacheRead", 0) or 0
                    totals["cache_write"] += u.get("cacheWrite", 0) or 0
                    c = u.get("cost")
                    if isinstance(c, dict):
                        cost += c.get("total", 0) or 0
                    last_ctx = pi_ctx_tokens(u)
                    turns += 1
                model = msg.get("model") or model
                provider = msg.get("provider") or provider
    except OSError:
        return None
    win = pi_context_window(model) if model else 0
    return {
        "id": sid,
        "harness": "pi",
        "name": display_name({"id": sid, "cwd": cwd, "title": title}),
        "cwd": cwd,
        "model": short_model(model),
        "provider": provider,
        "turns": turns,
        "tool_calls": tool_calls,
        "thinking_turns": thinking_turns,
        "ctx_tokens": last_ctx,
        "ctx_pct": min(100, round(100 * last_ctx / win)) if last_ctx and win else 0,
        "window": win,
        "totals": totals,
        "total_tokens": sum(totals.values()),
        "cost": round(cost, 2),
        "cost_actual": True,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def latest_insights_report():
    """Path to the newest `/insights` HTML report (or None). /insights is an
    interactive-only command — we can open its output but not generate it headless."""
    try:
        reports = [os.path.join(INSIGHTS_DIR, f) for f in os.listdir(INSIGHTS_DIR)
                   if f.startswith("report-") and f.endswith(".html")]
    except OSError:
        return None
    return max(reports, key=os.path.getmtime) if reports else None


def do_generate_insights():
    """Launch a fresh Claude session in iTerm running /insights (it can't run
    headless). The panel then watches INSIGHTS_DIR for the new report and opens it."""
    backend_for_new().act_new(load_prefs()["new_in"], prompt="/insights")


def webview_sessions():
    """The full session list for the panel: every session with live/archived
    flags, plus the list of known existing directories (for 'New session here')."""
    sessions, ok = discover()
    if not ok:
        return {"sessions": [], "dirs": []}
    state = load_json(STATE_FILE, {})
    for s in sessions:
        s["name"] = display_name(s)
        s["archived"] = bool(state.get(s["id"], {}).get("archived"))
    mark_all_live(sessions)
    seen = {}
    for s in sessions:
        cwd = s.get("cwd")
        if cwd and not dir_missing(cwd):
            seen[cwd] = max(seen.get(cwd, 0.0), s["mtime"])
    summaries = load_json(SUMMARY_FILE, {})
    prefs = load_prefs()
    # With summaries off nothing will ever fill these in, so don't advertise a
    # session as awaiting one — the rows just show no subtitle.
    summarizing = prefs.get("summaries", True)
    gitcache = load_json(GITCACHE_FILE, {})  # cwd -> "worktree"/"repo"/"dir"
    gc_before = len(gitcache)

    def dir_kind(cwd):  # "" for missing/none; frontend uses `missing` for that case
        if not cwd or dir_missing(cwd):
            return ""
        if cwd not in gitcache:
            gitcache[cwd] = compute_dir_kind(cwd)
        return gitcache[cwd]

    out = [{
        "id": s["id"],
        "harness": s.get("harness", "claude"),
        "name": s["name"],
        "dir": group_label(s.get("cwd")),
        "cwd": s.get("cwd"),
        "dir_kind": dir_kind(s.get("cwd")),   # worktree → branch icon, else folder
        "live": s["live"],
        "app": s.get("live_app") or "",       # "iterm"/"terminal"/"other"; "" when parked
        "archived": s["archived"],
        "missing": dir_missing(s.get("cwd")),
        "mtime": s["mtime"],
        "awaiting": bool(s.get("awaiting")) and not s["archived"],  # Claude waiting on you
        "ctx_pct": s.get("ctx_pct", 0),       # % of the context window used
        "ctx_tokens": s.get("ctx_tokens", 0),
        "model": s.get("model", ""),          # short model name, e.g. opus-4.8
        "summary": clean_summary(summaries.get(s["id"], {}).get("summary", "")),
        "status": summaries.get(s["id"], {}).get("status", ""),
        "progress": summaries.get(s["id"], {}).get("progress"),
        "pending": summarizing and s["id"] not in summaries,  # awaiting the summarizer
        "host": "",
    } for s in sessions]
    ensure_remote_scan()  # the panel polls this every few seconds — keep remote state current
    for s in remote_sessions():
        out.append({
            "id": s["id"], "harness": s.get("harness", "claude"), "name": remote_name(s),
            "dir": session_group(s), "cwd": s.get("cwd"), "dir_kind": "remote",
            "live": bool(s.get("live")), "app": s.get("live_app") or "",
            "archived": bool(state.get(s["id"], {}).get("archived")), "missing": False,
            "mtime": s.get("mtime", 0),
            "awaiting": bool(s.get("awaiting")) and not state.get(s["id"], {}).get("archived"),
            "ctx_pct": s.get("ctx_pct", 0), "ctx_tokens": s.get("ctx_tokens", 0),
            "model": s.get("model", ""),
            # not summarized: the summarizer only reads local transcripts
            "summary": "", "status": "", "progress": None, "pending": False,
            "host": s["host"],
        })
    out.sort(key=lambda s: (not s["live"], -s["mtime"]))
    if len(gitcache) != gc_before:
        save_json(GITCACHE_FILE, gitcache)
    dirs = [{"cwd": c, "label": group_label(c), "kind": dir_kind(c), "has_session": True}
            for c in sorted(seen, key=lambda c: -seen[c])]
    # Discovered workspace roots with no session yet — launch targets for the
    # panel's New-session menu, mirroring the SwiftBar "New session ▸" list.
    for root in cached_workspace_roots():
        if root not in seen:
            dirs.append({"cwd": root, "label": group_label(root),
                         "kind": "workspace", "has_session": False})
    pending = sum(1 for s in out if s["pending"])
    live_ids = {s["id"] for s in out if s.get("live")}
    restorable = sum(len(w["tabs"]) for w in restorable_sessions(live_ids, {s["id"] for s in out}))
    return {"sessions": out, "dirs": dirs, "prefs": prefs, "pending": pending,
            "restorable": restorable, "home": HOME,
            "pi_available": pi_available(),
            "remote_errors": remote_errors(),
            # "" when healthy; a sentence the panel shows verbatim when not
            "summarizer_error": summarizer_status() if summarizing else "",
            "summary_calls_today": summary_calls_today(),
            "summarizer_next": int(summarizer_next_due()) if summarizing else 0}


def do_serve():
    """Run the localhost webview server until SERVER_IDLE_TIMEOUT seconds pass with
    no request. Bound to 127.0.0.1; /api/* requires the token from server.json."""
    import http.server
    import threading
    import time
    import urllib.parse

    token = server_token()
    last = {"t": time.time()}

    def ok_json(payload):
        return json.dumps(payload).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # silence default stderr logging

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _body(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}

        def do_GET(self):
            last["t"] = time.time()
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/ping":
                return self._send(200, b"ccsessions", "text/plain")
            if u.path == "/":
                return self._send(200, panel_html().replace("__TOKEN__", token).replace("__ICONLG__", CLAUDE_ICON_LG).replace("__ICON__", CLAUDE_ICON),
                                  "text/html; charset=utf-8")
            if u.path == "/api/sessions":
                if q.get("t", [None])[0] != token:
                    return self._send(403, b'{"error":"forbidden"}')
                return self._send(200, ok_json(webview_sessions()))
            if u.path == "/api/stats":
                if q.get("t", [None])[0] != token:
                    return self._send(403, b'{"error":"forbidden"}')
                return self._send(200, ok_json(session_stats(q.get("id", [""])[0]) or {}))
            if u.path == "/api/insights":
                if q.get("t", [None])[0] != token:
                    return self._send(403, b'{"error":"forbidden"}')
                rep = latest_insights_report()
                return self._send(200, ok_json({"exists": bool(rep),
                                                "mtime": os.path.getmtime(rep) if rep else 0}))
            return self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            last["t"] = time.time()
            u = urllib.parse.urlparse(self.path)
            body = self._body()
            if body.get("t") != token:
                return self._send(403, b'{"error":"forbidden"}')
            ids = [i for i in (body.get("ids") or []) if isinstance(i, str)]
            sid = body.get("id")
            try:
                if u.path == "/api/archive":
                    apply_archived(ids, True)
                elif u.path == "/api/unarchive":
                    apply_archived(ids, False)
                elif u.path == "/api/delete":
                    delete_sessions(ids)
                elif u.path == "/api/open" and sid:
                    do_open(sid)
                elif u.path == "/api/rename" and sid:
                    self._rename(sid, body.get("name", ""))
                elif u.path == "/api/new":
                    do_new(body.get("cwd") or None, body.get("harness"), body.get("host") or None)
                elif u.path == "/api/newpick":
                    do_new_pick(body.get("harness"))  # native folder chooser → fresh session there
                elif u.path == "/api/restore":
                    do_restore()  # reopen the last snapshotted set of sessions
                elif u.path == "/api/prefs":
                    do_set(body.get("key", ""), str(body.get("value", "")))
                elif u.path == "/api/resummarize":
                    self._resummarize(ids + ([sid] if sid else []), body.get("all"))
                elif u.path == "/api/insights":
                    if body.get("action") == "generate":
                        do_generate_insights()
                    elif body.get("action") == "open":
                        rep = latest_insights_report()
                        if rep:
                            subprocess.Popen(["open", rep])
                else:
                    return self._send(404, b'{"error":"not found"}')
            except Exception as e:  # never let one bad action kill the server
                return self._send(500, ok_json({"error": str(e)}))
            return self._send(200, b'{"ok":true}')

        def _resummarize(self, ids, do_all=False):
            # Drop cached summaries so they become 'pending' and get regenerated;
            # the kicked-off summarizer pass picks them up (live-first).
            summaries = {} if do_all else load_json(SUMMARY_FILE, {})
            if not do_all:
                for sid in ids:
                    summaries.pop(sid, None)
            save_json(SUMMARY_FILE, summaries)
            ensure_summarizer(force=True)

        def _rename(self, sid, new_name):
            new_name = (new_name or "").strip()
            if not new_name:
                return
            sessions, _ = discover()
            mark_all_live(sessions)
            s = next((x for x in sessions if x["id"] == sid), None)
            if is_remote(sid):
                s = find_remote(sid)
                if s:
                    rename_remote(s, new_name)
                return
            backend = BACKENDS.get(s.get("live_app")) if s and s.get("live") else None
            if backend:
                backend.act_rename(s, new_name)

    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", WEBVIEW_PORT), Handler)
    except OSError:
        return  # port already bound (another serve instance) — let it own the port

    def idle_watch():
        while True:
            time.sleep(5)
            if time.time() - last["t"] > SERVER_IDLE_TIMEOUT:
                httpd.shutdown()
                return

    threading.Thread(target=idle_watch, daemon=True).start()
    httpd.serve_forever()


def _panel_path():
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "panel.html")


def panel_html():
    """The webview HTML, read from the sibling panel.html (served by do_serve)."""
    with open(_panel_path(), encoding="utf-8") as fh:
        return fh.read()


def panel_version():
    """panel.html's mtime — a cache-bust token in the webview URL so reopening the
    panel after an update loads fresh HTML (WKWebView caches by URL otherwise)."""
    try:
        return int(os.path.getmtime(_panel_path()))
    except OSError:
        return 0



def main():
    if len(sys.argv) < 2:
        render_menu()
        return
    if sys.argv[1] == "serve":  # localhost webview server (see do_serve)
        do_serve()
        return
    if sys.argv[1] == "summarize":  # background: (re)summarize changed sessions
        do_summarize(force="--force" in sys.argv[2:])
        return
    if sys.argv[1] == "scan-workspaces":  # background: refresh workspace-roots cache
        do_scan_workspaces()
        return
    verb = sys.argv[1]
    if verb == "new":  # new [dir] [harness] [host]
        do_new(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None,
               sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None,
               sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None)
        return
    if sys.argv[1] == "remote-scan":  # background: refresh the remote-hosts cache
        do_remote_scan()
        return
    if verb == "remotehosts":  # Settings ▸ Remote hosts… — edit the ssh target list
        do_remote_hosts_dialog()
        return
    if verb == "newpick":  # top-level New session… → folder chooser; newpick [harness]
        do_new_pick(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    if verb == "restore":  # reopen the last snapshotted set of sessions
        do_restore()
        return
    if verb == "set":  # set <key> <value> — Settings menu toggle
        if len(sys.argv) > 3:
            do_set(sys.argv[2], sys.argv[3])
        return
    if verb == "archivedir":  # archive all parked sessions in a directory
        if len(sys.argv) > 2:
            do_archive_dir(sys.argv[2])
        return
    if verb == "remap":  # repair a renamed/moved directory's sessions
        if len(sys.argv) > 2:
            do_remap(sys.argv[2])
        return
    sid = sys.argv[2] if len(sys.argv) > 2 else None
    if not sid:
        return
    if verb == "open":
        do_open(sid)
    elif verb == "rename":
        do_rename(sid)
    elif verb == "archive":
        set_archived(sid, True)
    elif verb == "unarchive":
        set_archived(sid, False)
    elif verb == "delete":
        do_delete(sid)


if __name__ == "__main__":
    main()
