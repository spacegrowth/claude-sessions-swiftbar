#!/usr/bin/env bash
# Uninstaller for the "Claude Code Sessions" (ccsessions) SwiftBar plugin.
#
#   curl -fsSL https://raw.githubusercontent.com/spacegrowth/claude-sessions-swiftbar/main/uninstall.sh | bash
#
# Removes the plugin file. By default it KEEPS your ~/.ccsessions state
# (archived flags, prefs). Pass --purge to delete that too.
set -euo pipefail

PLUGIN="Claude Code Sessions.5s.py"
OLD_PLUGIN="ccsessions.5s.py"   # pre-rename name, cleaned up too
BUNDLE_ID="com.ameba.SwiftBar"
STATE_DIR="$HOME/.ccsessions"

ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

DIR="$(defaults read "$BUNDLE_ID" PluginDirectory 2>/dev/null || true)"
[ -n "$DIR" ] || DIR="$HOME/.swiftbar"

# Stop the long-lived webview server first, so it isn't left running after its
# files are gone (it would keep serving from deleted paths until you log out).
pkill -f "$PLUGIN serve"     >/dev/null 2>&1 || true
pkill -f "$OLD_PLUGIN serve" >/dev/null 2>&1 || true

removed=0
for p in "$PLUGIN" "$OLD_PLUGIN"; do
  if [ -e "$DIR/$p" ]; then rm -f "$DIR/$p"; ok "Removed $DIR/$p"; removed=1; fi
done
if [ -d "$DIR/.lib/ccsessions" ]; then rm -rf "$DIR/.lib/ccsessions"; ok "Removed $DIR/.lib/ccsessions/ package"; removed=1; fi
rmdir "$DIR/.lib" 2>/dev/null || true          # drop .lib/ if now empty (leave it if other tools use it)
if [ -d "$DIR/ccsessions" ]; then rm -rf "$DIR/ccsessions"; ok "Removed $DIR/ccsessions/ package (legacy top-level)"; removed=1; fi
[ "$removed" = "1" ] || warn "No plugin found in $DIR"

if [ "$PURGE" = "1" ]; then
  rm -rf "$STATE_DIR"
  ok "Purged state $STATE_DIR"
else
  warn "Kept your state at $STATE_DIR (archived flags, prefs). Pass --purge to remove it."
fi

open "swiftbar://refreshallplugins" >/dev/null 2>&1 || true
ok "Done."
