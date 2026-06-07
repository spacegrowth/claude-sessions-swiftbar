"""ccsessions — a SwiftBar launcher for Claude Code sessions.

The plugin entry point is the sibling ``ccsessions.5s.py`` (installed as
``Claude Code Sessions.5s.py``); it adds this package to ``sys.path`` and calls
:func:`ccsessions.app.main`. All logic lives in :mod:`ccsessions.app`, with the
webview markup in :mod:`panel.html`.
"""
