"""ccsessions — "Agent Sessions": a SwiftBar launcher for Claude Code and Pi sessions.

The plugin entry point is the sibling ``ccsessions.5s.py`` (installed as
``Agent Sessions.5s.py``); it adds this package to ``sys.path`` and calls
:func:`ccsessions.app.main`. All logic lives in :mod:`ccsessions.app`, with the
webview markup in :mod:`panel.html`.
"""
