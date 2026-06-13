#!/usr/bin/env bash
# Installer for the "Claude Code Sessions" (ccsessions) SwiftBar plugin.
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/spacegrowth/claude-sessions-swiftbar/main/install.sh | bash
#
# Re-run any time to update to the latest version. Idempotent.
#
# The plugin is a thin entry file plus a small Python package (logic + webview
# HTML), so we fetch the repo tarball and install both into SwiftBar's folder:
#   $DIR/Claude Code Sessions.5s.py   ← entry (SwiftBar shows the name as title)
#   $DIR/.lib/ccsessions/             ← package (app.py, panel.html, __init__.py)
# The package goes in a hidden .lib/ so SwiftBar doesn't run its support files as
# their own stray menu-bar plugins (they'd show up as "?" items).
set -euo pipefail

REPO="spacegrowth/claude-sessions-swiftbar"
PLUGIN="Claude Code Sessions.5s.py"       # installed entry name — SwiftBar shows the
                                          # part before the first '.' as the window title
TARBALL="https://github.com/${REPO}/archive/refs/heads/main.tar.gz"
BUNDLE_ID="com.ameba.SwiftBar"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── options ──────────────────────────────────────────────────────
# --local installs from THIS checkout instead of downloading main — for testing
# local changes before they're committed/pushed. Same file-placement either way.
LOCAL=0
for arg in "$@"; do
  case "$arg" in
    --local) LOCAL=1 ;;
    *)       die "Unknown option: $arg (supported: --local)" ;;
  esac
done

bold "Installing the Claude Code Sessions SwiftBar plugin…"

# ── prerequisites ────────────────────────────────────────────────
[ "$(uname)" = "Darwin" ] || die "macOS only (this plugin drives iTerm2 via AppleScript)."
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Xcode Command Line Tools: xcode-select --install"
command -v curl    >/dev/null 2>&1 || die "curl not found."
command -v tar     >/dev/null 2>&1 || die "tar not found."

# SwiftBar is required to *run* the plugin, but not to place the files. Warn, don't block.
if [ -d "/Applications/SwiftBar.app" ] || [ -d "$HOME/Applications/SwiftBar.app" ]; then
  ok "SwiftBar found"
else
  warn "SwiftBar not installed. Get it with:  brew install --cask swiftbar   (or https://swiftbar.app)"
fi

# ── resolve SwiftBar's plugin folder ─────────────────────────────
DIR="$(defaults read "$BUNDLE_ID" PluginDirectory 2>/dev/null || true)"
if [ -z "$DIR" ]; then
  DIR="$HOME/.swiftbar"
  warn "SwiftBar plugin folder not set yet — defaulting to $DIR"
  defaults write "$BUNDLE_ID" PluginDirectory "$DIR" 2>/dev/null \
    && ok "Pointed SwiftBar at $DIR (takes effect when SwiftBar (re)starts)" \
    || warn "Could not preset SwiftBar's plugin folder — set it in SwiftBar ▸ Preferences."
fi
mkdir -p "$DIR"

# ── resolve source: local checkout (--local) or download main ────
# Both paths end with $SRC holding ccsessions.5s.py + ccsessions/, so the
# verify + place-the-files steps below are identical regardless of source.
if [ "$LOCAL" -eq 1 ]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bold "Installing from local checkout: $SRC"
else
  TMPD="$(mktemp -d "${TMPDIR:-/tmp}/ccsessions.XXXXXX")"
  trap 'rm -rf "$TMPD"' EXIT
  bold "Downloading latest plugin…"
  curl -fsSL "$TARBALL" | tar -xz -C "$TMPD" --strip-components=1 \
    || die "Download/extract failed: $TARBALL"
  SRC="$TMPD"
fi

[ -f "$SRC/ccsessions.5s.py" ] && [ -f "$SRC/ccsessions/app.py" ] \
  || die "Source missing expected files — aborting (nothing changed)."
python3 -m py_compile "$SRC/ccsessions.5s.py" "$SRC/ccsessions/app.py" 2>/dev/null \
  || die "Source files failed to compile — aborting (nothing changed)."

rm -f "$DIR/ccsessions.5s.py"                 # remove the old single-file copy if upgrading
cp "$SRC/ccsessions.5s.py" "$DIR/$PLUGIN"
chmod +x "$DIR/$PLUGIN"
rm -rf "$DIR/ccsessions"                       # remove old top-level package (pre-.lib installs):
                                               # SwiftBar ran its files as stray "?" menu-bar items
mkdir -p "$DIR/.lib"
rm -rf "$DIR/.lib/ccsessions"                  # replace the package wholesale
cp -R "$SRC/ccsessions" "$DIR/.lib/ccsessions"
rm -rf "$DIR/.lib/ccsessions/__pycache__"
if [ "$LOCAL" -ne 1 ]; then
  trap - EXIT
  rm -rf "$TMPD"
fi
ok "Installed → $DIR/$PLUGIN  (+ $DIR/.lib/ccsessions/)"

# ── stop any webview server still running the OLD code ───────────
# The plugin runs a long-lived localhost server (`… serve`) for the webview. It
# keeps the previously-installed module — and its file paths — resident in
# memory, so after we move/replace files it would serve a now-deleted panel.html
# (blank webview). Kill it; the next menu render respawns it from the new files.
pkill -f "$PLUGIN serve"     >/dev/null 2>&1 || true
pkill -f "ccsessions.5s.py serve" >/dev/null 2>&1 || true   # pre-rename entry name

# ── nudge SwiftBar to reload ─────────────────────────────────────
open "swiftbar://refreshallplugins" >/dev/null 2>&1 || open -a SwiftBar >/dev/null 2>&1 || true

# ── summary ──────────────────────────────────────────────────────
echo
bold "Done."
echo "For full functionality you'll also want:"
echo "  • iTerm2     — the terminal the plugin focuses/launches"
echo "  • claude     — the Claude Code CLI, on your PATH"
echo
echo "If you don't see the menu-bar item: open SwiftBar and confirm its plugin"
echo "folder is  $DIR  (SwiftBar ▸ Preferences ▸ Plugin Folder)."
echo "Re-run this installer any time to update."
