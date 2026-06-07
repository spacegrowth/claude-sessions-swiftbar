#!/usr/bin/env python3
# <xbar.title>Claude Code Sessions</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>ccsessions</xbar.author>
# <xbar.desc>Launcher for Claude Code sessions: jump to a live iTerm tab or revive it.</xbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
"""ccsessions SwiftBar plugin — thin entry point.

SwiftBar runs this file; it just makes the sibling ``ccsessions/`` package
importable and dispatches to :func:`ccsessions.app.main`. All logic lives in
``ccsessions/app.py`` (see its module docstring for the verbs); the webview
markup lives in ``ccsessions/panel.html``.
"""
import os
import sys

# The package sits next to this file (in the SwiftBar plugin folder). Put that
# folder on sys.path so `import ccsessions.app` resolves wherever we're run from.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from ccsessions.app import main  # noqa: E402

if __name__ == "__main__":
    main()
