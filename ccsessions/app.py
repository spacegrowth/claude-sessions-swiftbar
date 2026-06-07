"""ccsessions — a SwiftBar launcher for Claude Code sessions.

Two modes:
  (no args)            render the SwiftBar menu
  open      <id>       focus the live iTerm session, or revive it
  rename    <id>       type /rename into the live tab (renames session + tab)
  archive   <id>       hide the session from the main list
  unarchive <id>       restore an archived session
  delete    <id>       permanently delete the transcript (confirm dialog)
  new       [dir]      open a fresh `claude` (optionally in <dir>)
  newpick              pick a folder, then open a fresh `claude` there
  archivedir <cwd>     archive every parked session in <cwd>
  remap     <cwd>      repair sessions whose directory was renamed/moved
  set       <k> <v>    set a preference (Settings menu) — k in DEFAULT_PREFS

Sessions are auto-discovered from ~/.claude/projects/*/*.jsonl (read-only).
The filename UUID *is* the Claude session id, so we resume with the exact id.
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

# User-toggleable preferences (changed from the Settings ▸ menu, stored in
# prefs.json). These are just the defaults used until the file overrides them.
#   revive_in / new_in: "window" (new window) or "tab" (new tab in front window).
#   skip_permissions: start NEW sessions with --dangerously-skip-permissions.
DEFAULT_PREFS = {"revive_in": "window", "new_in": "tab", "skip_permissions": False,
                 "panel_shortcut": "CTRL+CMD+C"}  # global hotkey to open the panel; "" disables

# Command used to start Claude. Use an absolute path if it's not on the
# PATH of freshly-spawned iTerm sessions.
CLAUDE_BIN = "claude"

MAX_NAME_LEN = 55  # display name / iTerm session name length cap

# Title shown on every user-facing dialog and notification (macOS surfaces it
# as the bold header / sender line). Purely cosmetic.
UI_TITLE = "Claude Code Sessions"

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
STATE_DIR = os.path.join(HOME, ".ccsessions")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CACHE_FILE = os.path.join(STATE_DIR, "cache.json")
PREFS_FILE = os.path.join(STATE_DIR, "prefs.json")
GITCACHE_FILE = os.path.join(STATE_DIR, "gitcache.json")  # cwd -> repo/worktree/dir
SERVER_FILE = os.path.join(STATE_DIR, "server.json")  # {port, token} for the webview

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
SUMMARY_MODEL = "haiku"   # fast/cheap Claude model for the one-liners
SUMMARY_MAX = 128         # hard cap on summary length
SUMMARIES_PER_RUN = 8     # bound the Claude calls per background pass
SUMMARY_MIN_INTERVAL = 300  # don't re-summarize the same session more often than
                            # this (s) even if it changed — caps cost on LIVE
                            # sessions whose transcript appends constantly
# `claude -p` itself writes a session transcript, which discover() would pick up
# and summarize recursively. Run those calls from a dedicated cwd so their
# transcripts land in one project folder, and exclude that folder everywhere.
SUMMARY_WORKDIR = os.path.join(STATE_DIR, "summarizer-cwd")

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

# Status glyphs in the dropdown (SF Symbols): live = running, parked = idle.
LIVE_SFSYMBOL = "circle.inset.filled"
PARKED_SFSYMBOL = "circle.dotted"  # "" = no icon (just the name)

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


def discover():
    """Scan ~/.claude/projects for sessions. Uses an mtime+size cache so
    unchanged transcripts are not re-read on every 5s refresh."""
    cache = load_json(CACHE_FILE, {})
    new_cache = {}
    sessions = []
    if not os.path.isdir(PROJECTS_DIR):
        return sessions, False  # signal: projects dir missing

    skip = summarizer_proj_dir()  # the summarizer's own one-shot sessions — never list them
    for proj in os.listdir(PROJECTS_DIR):
        if proj == skip:
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
                tail = {k: hit.get(k, d) for k, d in
                        (("awaiting", False), ("ctx_pct", 0), ("ctx_tokens", 0), ("model", ""))}
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
            sessions.append({"id": sid, "cwd": cwd, "title": title, "mtime": st.st_mtime,
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


def group_by_dir(sessions):
    """Group sessions by directory label; within a group live-first then recent,
    and groups ordered by most-recent activity. Returns [(label, members), …]."""
    groups = {}
    for s in sessions:
        groups.setdefault(group_label(s["cwd"]), []).append(s)
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


def summarizer_proj_dir():
    """The project-folder name Claude uses for SUMMARY_WORKDIR. Excluded from
    discovery so the summarizer's own one-shot `claude -p` sessions never appear
    in the menu/panel or get (recursively) summarized."""
    return encode_project_dir(os.path.realpath(SUMMARY_WORKDIR))


def dir_icon(cwd, gitcache):
    """SF Symbol for a group header: question-folder if the dir is gone, branch
    for a live worktree, else folder. Git-kind is cached in `gitcache`; existence
    is checked fresh each call (it changes when worktrees are added/removed)."""
    if not cwd or dir_missing(cwd):
        return "folder.badge.questionmark"
    if cwd not in gitcache:
        gitcache[cwd] = compute_dir_kind(cwd)
    return {"worktree": "arrow.triangle.branch",
            "workspace": "square.stack.3d.up.fill",
            "repo": "folder.fill"}.get(gitcache[cwd], "folder")


def display_name(session):
    # Name comes from the transcript: your Claude /rename (custom-title), else
    # the ai-title, else the first prompt. Renaming is Claude's job, not ours.
    title = sanitize(session.get("title"))
    if title:
        return title
    base = group_label(session.get("cwd")).split("/")[-1]
    return sanitize(f"{base} · {session['id'][:8]}") if base else f"session {session['id'][:8]}"


# ──────────────────────────── iTerm / osascript ───────────────────
def run_osascript(script):
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )


def iterm_running():
    """True if iTerm is already running. Avoids launching it just to poll
    liveness on every refresh."""
    r = subprocess.run(["pgrep", "-x", "iTerm2"], capture_output=True)
    return r.returncode == 0


def osa(s):
    """Escape a Python string for embedding inside an AppleScript double-quoted literal."""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", ""))


def live_session_names():
    if not iterm_running():
        return set()
    script = (
        f'tell application "{ITERM_APP_NAME}"\n'
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
    r = run_osascript(script)
    if r.returncode != 0:
        return set()
    return {ln for ln in (l.strip() for l in r.stdout.splitlines()) if ln}


def _match_session_block(key, action):
    """AppleScript fragment: walk windows→tabs→sessions and, on the first session
    whose name matches `key` (bounded by Claude's title separator, or as the whole
    tail), run `action` then return. Single source of the focus/rename match rule —
    kept identical to title_is_live() so the menu dot and the click agree."""
    key_e, sep_e = osa(key), osa(TAB_TITLE_SEP)
    # Bounded title match, kept in sync with title_is_live(): the title sits after
    # the glyph's space and before the separator (or at the tail). The leading
    # space stops "model" matching "…_model — …".
    return (
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      repeat with s in sessions of t\n"
        f'        if (name of s contains " {key_e}{sep_e}") or (name of s ends with " {key_e}") or (name of s is equal to "{key_e}") then\n'
        f"{action}"
        "          return\n"
        "        end if\n"
        "      end repeat\n"
        "    end repeat\n"
        "  end repeat\n"
    )


def _create_target_block(mode):
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


def build_open_script(key, set_name, cwd, sid, mode, skip_perms=False):
    """AppleScript that focuses the live iTerm session matching `key`, or opens a
    new window/tab (per `mode`), names it `set_name`, and resumes the exact session
    by id. `skip_perms` adds --dangerously-skip-permissions to the revive command.
    Pure (no side effects) so it can be compile-checked."""
    base = CLAUDE_BIN + (" --dangerously-skip-permissions" if skip_perms else "")
    resume = f"{base} --resume {shlex.quote(sid)}"
    cmd = f"cd {shlex.quote(cwd)} && {resume}" if cwd else resume  # skip cd if dir gone
    name_e, cmd_e = osa(set_name), osa(cmd)
    focus = "          tell w to select\n          select t\n"
    return (
        f'tell application "{ITERM_APP_NAME}"\n'
        "  activate\n"
        f"{_match_session_block(key, focus)}"
        f"{_create_target_block(mode)}"
        "  tell targetSession\n"
        f'    set name to "{name_e}"\n'
        f'    write text "{cmd_e}"\n'
        "  end tell\n"
        "end tell"
    )


def build_new_script(mode, cwd=None, skip_perms=False, prompt=None):
    """AppleScript that opens a new window/tab (per `mode`) and starts fresh
    `claude` — in `cwd` if given, else the new session's default directory.
    `skip_perms` adds --dangerously-skip-permissions; `prompt` (e.g. "/insights")
    is passed as claude's initial input so a slash command runs on launch."""
    base = CLAUDE_BIN + (" --dangerously-skip-permissions" if skip_perms else "")
    if prompt:
        base += " " + shlex.quote(prompt)
    cmd = f"cd {shlex.quote(cwd)} && {base}" if cwd else base
    return (
        f'tell application "{ITERM_APP_NAME}"\n'
        "  activate\n"
        f"{_create_target_block(mode)}"
        "  tell targetSession\n"
        f'    write text "{osa(cmd)}"\n'
        "  end tell\n"
        "end tell"
    )


def build_rename_script(key, new_name):
    """AppleScript that types `/rename <new_name>` into the live session matching
    `key`. Claude then renames the session (custom-title) and the iTerm2 tab."""
    cmd_e = osa("/rename " + new_name)
    action = f'          tell s to write text "{cmd_e}"\n'
    return (
        f'tell application "{ITERM_APP_NAME}"\n'
        f"{_match_session_block(key, action)}"
        "end tell"
    )


def prompt_rename(current):
    """Native text dialog for the new name. Returns it, or None if cancelled."""
    script = (
        f'set r to display dialog "Rename (runs /rename in the live Claude tab):" '
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
    and "model" can't hit "…_model — …". Kept in sync with _match_session_block."""
    if not key:
        return False
    for nm in live_names:
        head = nm.split(TAB_TITLE_SEP, 1)[0]  # the "<glyph> <title>" segment
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


def focus_or_revive(key, set_name, cwd, sid, mode, skip_perms=False):
    run_osascript(build_open_script(key, set_name, cwd, sid, mode, skip_perms))


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


def render_session(s, depth=0):
    """Print a session row (submenu) at the given nesting `depth`: live/parked dot
    + name, then its actions one level deeper. depth=0 = top level; depth=1 nests
    it inside a parent submenu (e.g. under "Past sessions ▸")."""
    pfx, cpfx = "--" * depth, "--" * (depth + 1)
    sym = LIVE_SFSYMBOL if s["live"] else PARKED_SFSYMBOL
    print(fmt(pfx, s["name"], sfimage=sym or None,
              sfcolor=(GREEN if s["live"] else PARKED_COLOR) if sym else None))
    verb = "Jump to session" if s["live"] else "Revive session"
    print(fmt(cpfx, verb, sfimage="arrow.right.circle.fill", **action_params("open", s["id"])))
    if s["live"]:  # /rename only works on a running session
        print(fmt(cpfx, "Rename…", sfimage="pencil", **action_params("rename", s["id"])))
    print(fmt(cpfx, "Archive", sfimage="archivebox", **action_params("archive", s["id"])))


def render_menu():
    state = load_json(STATE_FILE, {})
    sessions, ok = discover()

    if not ok:
        menubar_title(None)
        print("---")
        print("No Claude sessions found")
        print(f"--Expected: {PROJECTS_DIR}")
        print("--Start a session with `claude`, then refresh.")
        print("---")
        print(fmt("", "Refresh", refresh="true", sfimage="arrow.clockwise"))
        return

    live = live_session_names()
    for s in sessions:
        s["name"] = display_name(s)
        s["archived"] = bool(state.get(s["id"], {}).get("archived"))
    assign_liveness(sessions, live)

    active = [s for s in sessions if not s["archived"]]
    archived = [s for s in sessions if s["archived"]]
    live_count = sum(1 for s in active if s["live"])

    # Menu bar title.
    menubar_title(live_count)
    print("---")

    # Webview management panel — opens an HTML panel served by an on-demand,
    # 127.0.0.1-only server (started here if not already running; it idle-exits).
    ensure_server()
    ensure_summarizer()  # background: refresh summaries of changed sessions
    print(fmt("", "Claude Code Sessions", image=CLAUDE_ICON,
              webview="true", webvieww="780", webviewh="560",
              shortcut=(load_prefs().get("panel_shortcut") or None),  # global hotkey opens the panel
              href=f"http://127.0.0.1:{WEBVIEW_PORT}/?t={server_token()}&v={panel_version()}"))
    print("---")

    gitcache = load_json(GITCACHE_FILE, {})  # cwd -> "worktree"/"repo"/"dir"
    gc_before = len(gitcache)

    # New session ▸ — pick a known directory (from any session), or Select folder…
    print(fmt("", "New session", sfimage="plus.circle"))
    seen_dirs = {}
    for s in sessions:
        cwd = s.get("cwd")
        if cwd and not dir_missing(cwd):
            seen_dirs[cwd] = max(seen_dirs.get(cwd, 0.0), s["mtime"])
    for cwd in sorted(seen_dirs, key=lambda c: -seen_dirs[c]):
        print(fmt("--", group_label(cwd), sfimage=dir_icon(cwd, gitcache),
                  **action_params("new", cwd)))
    print(fmt("--", "Select folder…", sfimage="folder.badge.plus", **action_params("newpick")))
    print("---")

    if not active and not archived:
        print("No sessions yet")
        print("--Run `claude` in a project, then refresh.")

    # One block per directory: header (click=open) + New session + live sessions
    # shown directly, then the dir's parked ones tucked under "Past sessions ▸".
    # "---" divider between directory groups.
    need_div = False
    for label, members in group_by_dir(active):
        if need_div:
            print("---")
        need_div = True
        gcwd = members[0].get("cwd")  # all members share this group's dir
        render_active_dir_header(label, gcwd, gitcache)  # ▸ Open + New session here
        for s in members:
            if s["live"]:
                render_session(s)
        parked_here = [s for s in members if not s["live"]]
        if parked_here:
            print(fmt("", f"Past sessions ({len(parked_here)})", sfimage="clock.arrow.circlepath"))
            if gcwd:
                print(fmt("--", f"Archive all ({len(parked_here)})", sfimage="archivebox.fill",
                          **action_params("archivedir", gcwd)))
            for s in parked_here:
                render_session(s, depth=1)  # parked nested inside "Past sessions ▸"

    # The Archived list, grouped at the bottom. Bulk archive/unarchive/delete
    # lives in the webview panel (checkboxes + toolbar), so no menu dialogs here.
    print("---")
    print(fmt("", f"Archived ({len(archived)})", sfimage="tray.full"))
    for label, members in group_by_dir(archived):
        print(dir_header("--", label, members[0].get("cwd"), gitcache))
        for s in members:
            print(f"--{s['name']}")
            print(fmt("----", "Jump / Revive", sfimage="play.fill", **action_params("open", s["id"])))
            print(fmt("----", "Unarchive", sfimage="tray.and.arrow.up", **action_params("unarchive", s["id"])))
            print(fmt("----", "Delete…", sfimage="trash", sfcolor="#FF3B30", **action_params("delete", s["id"])))

    if len(gitcache) != gc_before:  # new dirs were classified
        try:
            save_json(GITCACHE_FILE, gitcache)
        except OSError:
            pass  # best-effort cache; never break the menu render

    print("---")
    prefs = load_prefs()
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
    skip = prefs["skip_permissions"]  # single toggle: click sets the opposite
    print(fmt("--", "Skip permissions (new sessions)",
              sfimage="checkmark" if skip else None,
              **action_params("set", "skip_permissions", param3="off" if skip else "on")))
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
    act on the same authoritative file the menu shows."""
    if not os.path.isdir(PROJECTS_DIR):
        return None
    best, best_mtime = None, -1.0
    for proj in os.listdir(PROJECTS_DIR):
        path = os.path.join(PROJECTS_DIR, proj, sid + ".jsonl")
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue  # not a file / unreadable
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best


def do_open(sid):
    s = find_session(sid)
    if not s or not s.get("cwd"):
        return
    cwd = s["cwd"]
    if dir_missing(cwd):  # gone dir: resume without cd-ing (which would fail)
        notify("Directory is gone — resuming without it.")
        cwd = None
    prefs = load_prefs()
    focus_or_revive(match_key(s), display_name(s), cwd, sid, prefs["revive_in"], prefs["skip_permissions"])


def do_new(cwd=None):
    prefs = load_prefs()
    run_osascript(build_new_script(prefs["new_in"], cwd, prefs["skip_permissions"]))


def choose_folder(prompt):
    """Native folder chooser. Returns the chosen POSIX path, or None if cancelled."""
    r = run_osascript(
        f'set f to choose folder with prompt "{osa(prompt)}"\n'
        "return POSIX path of f"
    )
    path = r.stdout.strip()
    return path if (r.returncode == 0 and path) else None


def do_new_pick():
    """Top-level New session…: native folder chooser → fresh claude in any
    directory (including ones not yet in the menu)."""
    path = choose_folder("Choose a directory for the new Claude session:")
    if path:
        do_new(path)


def do_set(key, value):
    # Bool-typed prefs come in as "on"/"off" from the toggle; store real bools.
    if key in DEFAULT_PREFS and isinstance(DEFAULT_PREFS[key], bool):
        value = value in ("on", "true", "1", "yes")
    set_pref(key, value)


def do_rename(sid):
    s = find_session(sid)
    if not s:
        return
    key = match_key(s)
    if not title_is_live(key, live_session_names()):
        notify("Revive the session first — rename runs /rename in its live tab.")
        return
    new = prompt_rename(display_name(s))
    if new:
        run_osascript(build_rename_script(key, new))


def set_archived(sid, value):
    apply_archived([sid], value)


def apply_archived(ids, value):
    """Set archived=value for a batch of session ids in one state write. Shared by
    the native bulk-archive picker and the webview panel."""
    state = load_json(STATE_FILE, {})
    for sid in ids:
        state.setdefault(sid, {})["archived"] = value
    save_json(STATE_FILE, state)


def delete_sessions(ids):
    """Delete a batch of transcripts + their state entries. Returns the count
    actually removed. Shared by the native delete flow and the webview panel."""
    state = load_json(STATE_FILE, {})
    removed = 0
    for sid in ids:
        if delete_session_file(sid, state):
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
    live_names = live_session_names()
    changed = False
    for s in sessions:
        if s.get("cwd") != cwd:
            continue
        if state.get(s["id"], {}).get("archived") or title_is_live(match_key(s), live_names):
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
    affected = [s for s in sessions if s.get("cwd") == old_cwd]

    # Never remap a LIVE session: its running process keeps writing to the old
    # project folder, so moving the transcript just splits it (a stale copy here,
    # the live original recreated there). Remap is a repair for parked sessions.
    if any(title_is_live(match_key(s), live_session_names()) for s in affected):
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
    dest = os.path.join(PROJECTS_DIR, encode_project_dir(new_cwd))
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError:
        notify("Could not create the destination project folder.")
        return
    moved = 0
    src_proj = None
    for s in affected:
        src = session_file(s["id"])
        if not src:
            continue
        try:
            with open(src, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            with open(os.path.join(dest, s["id"] + ".jsonl"), "w", encoding="utf-8") as fh:
                fh.writelines(rewrite_cwd_line(ln, old_cwd, new_cwd) for ln in lines)
            os.remove(src)
            moved += 1
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
    no-op when alive. Never raises into the menu render."""
    try:
        if server_alive():
            return
        server_token()  # create the token file before the child reads it
        subprocess.Popen(
            [sys.executable, SELF, "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        pass  # the panel just won't open; the native menu is unaffected


def recent_transcript_text(path, max_chars=2500):
    """The tail of a transcript's user/assistant text, for summarizing. Focuses
    on recent activity (keeps the last messages up to max_chars) so the summary
    reflects the session's current state and the Claude call stays cheap."""
    msgs = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("isMeta") or o.get("type") not in ("user", "assistant"):
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
                    msgs.append(f"{o['type']}: {text}")
    except OSError:
        return ""
    tail, total = [], 0
    for m in reversed(msgs):  # keep the most recent messages within the budget
        if tail and total + len(m) > max_chars:
            break
        tail.append(m)
        total += len(m)
    return "\n".join(reversed(tail))[:max_chars]


def claude_path():
    """Absolute path to the claude CLI. The summarizer runs detached (spawned by
    SwiftBar with a minimal PATH), where a bare 'claude' often isn't found — so
    fall back to common install locations and the nvm/npm global bin."""
    import shutil
    import glob
    found = shutil.which(CLAUDE_BIN)
    if found:
        return found
    candidates = [os.path.expanduser("~/.claude/local/claude"),
                  "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    candidates += sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")),
                         reverse=True)
    for c in candidates:
        if os.path.exists(c):
            return c
    return CLAUDE_BIN  # last resort — rely on PATH


def generate_summary(text):
    """Ask Claude (Haiku) for a structured read on the session: a ≤SUMMARY_MAX-char
    one-liner plus a status (done/active/blocked) and a rough progress estimate.
    Returns {"summary","status","progress"} or None if Claude is unavailable/errors."""
    if not text:
        return None
    prompt = ("You index past coding sessions. Below the marker is the tail of an "
              "EXISTING transcript between a user and an AI coding assistant. Do NOT "
              "reply to it or continue it — only describe it from the outside.\n"
              "Output ONE line, EXACTLY this format, nothing else:\n"
              "STATUS=<done|active|blocked>; PROGRESS=<0-100>; SUMMARY=<text>\n"
              "STATUS: done if the task looks finished, blocked if stuck or erroring, "
              "otherwise active. PROGRESS: rough 0-100 estimate of how complete it is. "
              f"SUMMARY: what the session is about — specific (task/feature/files), at "
              f"most {SUMMARY_MAX - 12} characters, no quotes, no trailing period.\n\n"
              "===== TRANSCRIPT TAIL =====\n" + text)
    try:
        os.makedirs(SUMMARY_WORKDIR, exist_ok=True)  # isolate this call's own session transcript
        r = subprocess.run([claude_path(), "-p", "--model", SUMMARY_MODEL, prompt],
                           capture_output=True, text=True, timeout=90,
                           stdin=subprocess.DEVNULL, cwd=SUMMARY_WORKDIR)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return parse_summary(" ".join(r.stdout.split()).strip())


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


def do_summarize(limit=SUMMARIES_PER_RUN):
    """Background pass: (re)generate summaries for sessions whose transcript
    changed since last summarized, bounded to `limit` Claude calls per run.
    Lock-guarded so overlapping render-spawned runs don't stack."""
    import time
    lock = SUMMARY_FILE + ".lock"
    try:
        if os.path.exists(lock) and (time.time() - os.path.getmtime(lock)) < 300:
            return  # a recent run is (probably) still going
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
        assign_liveness(sessions, live_session_names())
        for s in sessions:
            s["archived"] = bool(state.get(s["id"], {}).get("archived"))
        sessions.sort(key=lambda s: (2 if s["archived"] else (0 if s["live"] else 1), -s["mtime"]))
        summaries = load_json(SUMMARY_FILE, {})
        done = 0
        for s in sessions:
            if done >= limit:
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
            text = recent_transcript_text(path)
            info = generate_summary(text) if text else None
            if text and info is None:
                continue  # has content but Claude failed — don't cache empty; retry next pass
            info = info or {}
            summaries[s["id"]] = {"mtime": st.st_mtime, "size": st.st_size, "ts": time.time(),
                                  "summary": info.get("summary", ""),
                                  "status": info.get("status", ""),
                                  "progress": info.get("progress")}
            save_json(SUMMARY_FILE, summaries)  # persist incrementally
            done += 1
        # prune only summaries whose transcript is truly gone — checked via the
        # file, NOT discover()'s set, so a transient/partial discover() can never
        # wipe good summaries (that caused a full re-summarize).
        stale = [k for k in summaries if session_file(k) is None]
        if stale:
            for k in stale:
                summaries.pop(k, None)
            save_json(SUMMARY_FILE, summaries)
    finally:
        # the summarizer's own one-shot `claude -p` sessions are throwaway — clear
        # them so the excluded folder doesn't accumulate.
        import shutil
        shutil.rmtree(os.path.join(PROJECTS_DIR, summarizer_proj_dir()), ignore_errors=True)
        try:
            os.remove(lock)
        except OSError:
            pass


def ensure_summarizer():
    """Spawn a detached background `summarize` pass unless one is already running.
    Cheap no-op otherwise; never raises into the render."""
    import time
    try:
        lock = SUMMARY_FILE + ".lock"
        if os.path.exists(lock) and (time.time() - os.path.getmtime(lock)) < 300:
            return
        subprocess.Popen(
            [sys.executable, SELF, "summarize"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        pass


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
    run_osascript(build_new_script(load_prefs()["new_in"], prompt="/insights"))


def webview_sessions():
    """The full session list for the panel: every session with live/archived
    flags, plus the list of known existing directories (for 'New session here')."""
    sessions, ok = discover()
    if not ok:
        return {"sessions": [], "dirs": []}
    state = load_json(STATE_FILE, {})
    live = live_session_names()
    for s in sessions:
        s["name"] = display_name(s)
        s["archived"] = bool(state.get(s["id"], {}).get("archived"))
    assign_liveness(sessions, live)
    seen = {}
    for s in sessions:
        cwd = s.get("cwd")
        if cwd and not dir_missing(cwd):
            seen[cwd] = max(seen.get(cwd, 0.0), s["mtime"])
    summaries = load_json(SUMMARY_FILE, {})
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
        "name": s["name"],
        "dir": group_label(s.get("cwd")),
        "cwd": s.get("cwd"),
        "dir_kind": dir_kind(s.get("cwd")),   # worktree → branch icon, else folder
        "live": s["live"],
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
        "pending": s["id"] not in summaries,  # not yet processed by the summarizer
    } for s in sessions]
    out.sort(key=lambda s: (not s["live"], -s["mtime"]))
    if len(gitcache) != gc_before:
        save_json(GITCACHE_FILE, gitcache)
    dirs = [{"cwd": c, "label": group_label(c)} for c in sorted(seen, key=lambda c: -seen[c])]
    pending = sum(1 for s in out if s["pending"])
    return {"sessions": out, "dirs": dirs, "prefs": load_prefs(), "pending": pending}


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
                    do_new(body.get("cwd") or None)
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
            ensure_summarizer()

        def _rename(self, sid, new_name):
            new_name = (new_name or "").strip()
            if not new_name:
                return
            s = find_session(sid)
            if not s:
                return
            key = match_key(s)
            if title_is_live(key, live_session_names()):
                run_osascript(build_rename_script(key, new_name))

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
        do_summarize()
        return
    verb = sys.argv[1]
    if verb == "new":  # optional arg = directory to open in
        do_new(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    if verb == "newpick":  # top-level New session… → folder chooser
        do_new_pick()
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
