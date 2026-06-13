#!/usr/bin/env python3
# <xbar.title>Claude Code Sessions</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>ccsessions</xbar.author>
# <xbar.desc>Launcher for Claude Code sessions: jump to a live iTerm tab or revive it.</xbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
"""ccsessions SwiftBar plugin — thin entry point.

SwiftBar runs this file; it just makes the ``ccsessions/`` package importable
and dispatches to :func:`ccsessions.app.main`. All logic lives in
``ccsessions/app.py`` (see its module docstring for the verbs); the webview
markup lives in ``ccsessions/panel.html``. When installed the package sits in a
hidden ``.lib/`` folder beside this file (see the sys.path setup below).
"""
import os
import sys

# Locate the `ccsessions` package. When installed, it lives in a hidden `.lib/`
# folder beside this entry file so SwiftBar doesn't pick up the package's support
# files (app.py, panel.html, __init__.py) as their own stray menu-bar plugins. In
# a dev checkout the package sits directly beside this file instead. Put both
# candidates on sys.path so `import ccsessions.app` resolves in either layout
# (.lib first, so the installed copy wins).
_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, ".lib"))

from ccsessions.app import main  # noqa: E402

if __name__ == "__main__":
    main()
