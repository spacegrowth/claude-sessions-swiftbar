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

# ── download tarball + verify + install ──────────────────────────
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/ccsessions.XXXXXX")"
trap 'rm -rf "$TMPD"' EXIT

bold "Downloading latest plugin…"
curl -fsSL "$TARBALL" | tar -xz -C "$TMPD" --strip-components=1 \
  || die "Download/extract failed: $TARBALL"
[ -f "$TMPD/ccsessions.5s.py" ] && [ -f "$TMPD/ccsessions/app.py" ] \
  || die "Tarball missing expected files — aborting (nothing changed)."
python3 -m py_compile "$TMPD/ccsessions.5s.py" "$TMPD/ccsessions/app.py" 2>/dev/null \
  || die "Downloaded files failed to compile — aborting (nothing changed)."

rm -f "$DIR/ccsessions.5s.py"                 # remove the old single-file copy if upgrading
cp "$TMPD/ccsessions.5s.py" "$DIR/$PLUGIN"
chmod +x "$DIR/$PLUGIN"
rm -rf "$DIR/ccsessions"                       # remove old top-level package (pre-.lib installs):
                                               # SwiftBar ran its files as stray "?" menu-bar items
mkdir -p "$DIR/.lib"
rm -rf "$DIR/.lib/ccsessions"                  # replace the package wholesale
cp -R "$TMPD/ccsessions" "$DIR/.lib/ccsessions"
rm -rf "$DIR/.lib/ccsessions/__pycache__"
trap - EXIT
rm -rf "$TMPD"
ok "Installed → $DIR/$PLUGIN  (+ $DIR/.lib/ccsessions/)"

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
