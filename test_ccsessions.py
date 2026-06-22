#!/usr/bin/env python3
"""Unit tests for ccsessions.5s.py — stdlib unittest, no external deps.

Run:  python3 test_ccsessions.py            (or: python3 -m unittest -v)

The plugin filename ('ccsessions.5s.py') isn't a legal module name, so we load
it by path via importlib. Tests that touch the filesystem (discover/do_remap/
session_file) point the module's PROJECTS_DIR/CACHE_FILE at a fresh tempdir and
monkeypatch the osascript-driven helpers (notify/ask_action/choose_folder/
live_session_names), so nothing real is read or mutated.
"""
import json
import os
import tempfile
import shutil
import sys
import time
import unittest

# Logic lives in the ccsessions package (ccsessions/app.py); the plugin file
# 'ccsessions.5s.py' is just a thin entry point. Import the module directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import ccsessions.app as cc  # noqa: E402

SEP = cc.TAB_TITLE_SEP  # NBSP + em-dash


def _jsonl(path, objs):
    with open(path, "w", encoding="utf-8") as fh:
        for o in objs:
            fh.write(json.dumps(o) + "\n")


# ─────────────────────── pure string/path helpers ───────────────────────
class TestEncodeProjectDir(unittest.TestCase):
    def test_slash_and_basic(self):
        self.assertEqual(cc.encode_project_dir("/Users/x/development/app"),
                         "-Users-x-development-app")

    def test_dot_and_underscore_become_dash(self):
        # every non-alphanumeric → '-', so '.cfg' and 'a_b' both collapse
        self.assertEqual(cc.encode_project_dir("/Users/x/.cfg"), "-Users-x--cfg")
        self.assertEqual(cc.encode_project_dir("/a/test_me"), "-a-test-me")

    def test_hyphen_preserved(self):
        self.assertEqual(cc.encode_project_dir("/a/my-repo"), "-a-my-repo")


class TestGroupLabel(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(cc.group_label(None), "(unknown directory)")
        self.assertEqual(cc.group_label(""), "(unknown directory)")

    def test_last_two_components(self):
        self.assertEqual(cc.group_label("/Users/x/development/app"), "development/app")

    def test_single_component(self):
        self.assertEqual(cc.group_label("/app"), "app")

    def test_trailing_slash(self):
        self.assertEqual(cc.group_label("/Users/x/dev/app/"), "dev/app")


class TestSanitize(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cc.sanitize(""), "")
        self.assertEqual(cc.sanitize(None), "")

    def test_pipe_replaced(self):  # '|' is SwiftBar's separator
        self.assertEqual(cc.sanitize("a|b"), "a¦b")

    def test_control_chars_and_whitespace_collapse(self):
        self.assertEqual(cc.sanitize("a\tb\n c"), "a b c")

    def test_length_cap_adds_ellipsis(self):
        out = cc.sanitize("x" * 200)
        self.assertEqual(len(out), cc.MAX_NAME_LEN)
        self.assertTrue(out.endswith("…"))


class TestDefaultTabPath(unittest.TestCase):
    def test_default_titled_tab_returns_expanded_cwd(self):
        tab = f"✳ Claude Code{SEP}~/development/test"
        self.assertEqual(cc.default_tab_path(tab), cc.HOME + "/development/test")

    def test_absolute_path_not_under_home(self):
        tab = f"✳ Claude Code{SEP}/tmp/work"
        self.assertEqual(cc.default_tab_path(tab), "/tmp/work")

    def test_titled_tab_returns_none(self):
        tab = f"✳ my session{SEP}~/development/app"
        self.assertIsNone(cc.default_tab_path(tab))

    def test_garbage_returns_none(self):
        self.assertIsNone(cc.default_tab_path("random text"))


class TestTitleIsLive(unittest.TestCase):
    def setUp(self):
        self.tabs = {f"✳ build{SEP}~/dev/a", f"✳ nightly_build_pipeline{SEP}~/dev/b"}

    def test_bounded_match(self):
        self.assertTrue(cc.title_is_live("build", self.tabs))

    def test_substring_does_not_falsely_match(self):
        # "build" must not match inside "nightly_build_pipeline"
        self.assertTrue(cc.title_is_live("nightly_build_pipeline", self.tabs))
        self.assertFalse(cc.title_is_live("pipeline", self.tabs))

    def test_tail_match_without_separator(self):
        self.assertTrue(cc.title_is_live("foo", {"glyph foo"}))

    def test_iterm_profile_suffix_is_stripped(self):
        # iTerm appends the profile name e.g. "(python)" after the title; it must
        # still match (Python side) and the AppleScript must carry the same clause.
        self.assertTrue(cc.title_is_live("build", {f"✳ build (python){SEP}~/dev/a"}))
        self.assertIn('contains " build (', cc.build_open_script("build", "n", "/w", "s", "window"))

    def test_glyphless_tab_matches_jump_not_just_dot(self):
        # An idle/older tab can have NO status glyph, so the title sits at the
        # very START of the name (no leading space). The green dot already matched
        # it; the jump/rename AppleScript must too — regression: it used to fall
        # through the match and spawn a NEW session instead of focusing the tab.
        tab = f"my_project{SEP}~/proj/app"
        self.assertTrue(cc.title_is_live("my_project", {tab}))
        self.assertIn(f'starts with "my_project{SEP}',
                      cc.build_open_script("my_project", "n", "/w", "s", "window"))
        self.assertIn(f'starts with "my_project{SEP}',
                      cc.build_rename_script("my_project", "newname"))

    def test_empty_key_is_never_live(self):
        self.assertFalse(cc.title_is_live("", self.tabs))
        self.assertFalse(cc.title_is_live(None, self.tabs))


# ─────────────────────── transcript parsing ───────────────────────
class TestRewriteCwdLine(unittest.TestCase):
    def test_matching_cwd_rewritten(self):
        line = '{"cwd":"/old","type":"user"}\n'
        out = cc.rewrite_cwd_line(line, "/old", "/new")
        self.assertEqual(json.loads(out)["cwd"], "/new")

    def test_spaced_json_also_rewritten(self):
        line = '{"cwd": "/old", "type": "x"}\n'
        self.assertEqual(json.loads(cc.rewrite_cwd_line(line, "/old", "/new"))["cwd"], "/new")

    def test_nonmatching_cwd_untouched(self):
        line = '{"cwd":"/other","type":"user"}\n'
        self.assertEqual(cc.rewrite_cwd_line(line, "/old", "/new"), line)

    def test_body_mention_preserved(self):
        line = '{"cwd":"/x","note":"ran in /old"}\n'
        out = cc.rewrite_cwd_line(line, "/old", "/new")
        self.assertIn("/old", out)  # body mention is NOT a cwd field → untouched

    def test_unicode_preserved_not_escaped(self):
        line = '{"cwd":"/old","msg":"café"}\n'
        out = cc.rewrite_cwd_line(line, "/old", "/new")
        self.assertIn("café", out)
        self.assertNotIn("caf\\u", out)

    def test_non_json_and_blank_passthrough(self):
        self.assertEqual(cc.rewrite_cwd_line("not json\n", "/o", "/n"), "not json\n")
        self.assertEqual(cc.rewrite_cwd_line("\n", "/o", "/n"), "\n")


class TestParseSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, objs):
        p = os.path.join(self.tmp, "s.jsonl")
        _jsonl(p, objs)
        return p

    def test_first_cwd_and_custom_title_wins(self):
        p = self._write([
            {"cwd": "/first", "type": "user", "message": {"content": "hi"}},
            {"cwd": "/second", "type": "ai-title", "aiTitle": "AI Name"},
            {"type": "custom-title", "customTitle": "My Name"},
        ])
        cwd, title = cc.parse_session(p)
        self.assertEqual(cwd, "/first")       # first cwd seen
        self.assertEqual(title, "My Name")    # custom-title beats ai-title

    def test_ismeta_message_skipped_for_title(self):
        # a slash-command expansion is an isMeta user message; must NOT be the title
        p = self._write([
            {"cwd": "/x", "type": "user", "isMeta": True,
             "message": {"content": "# Bridge Command\n..."}},
        ])
        _, title = cc.parse_session(p)
        self.assertEqual(title, "")

    def test_angle_bracket_user_skipped(self):
        p = self._write([
            {"type": "user", "message": {"content": "<command-name>/x</command-name>"}},
            {"type": "user", "message": {"content": "real prompt"}},
        ])
        _, title = cc.parse_session(p)
        self.assertEqual(title, "real prompt")

    def test_ai_title_when_no_custom(self):
        p = self._write([{"type": "ai-title", "aiTitle": "Generated"}])
        _, title = cc.parse_session(p)
        self.assertEqual(title, "Generated")

    def test_missing_file_is_tolerant(self):
        cwd, title = cc.parse_session(os.path.join(self.tmp, "nope.jsonl"))
        self.assertIsNone(cwd)
        self.assertEqual(title, "")


class TestLastRecordedCwd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_last_cwd(self):
        p = os.path.join(self.tmp, "s.jsonl")
        _jsonl(p, [{"cwd": "/old"}, {"cwd": "/old"}, {"cwd": "/new"}])
        self.assertEqual(cc.last_recorded_cwd(p), "/new")

    def test_missing_file_returns_none(self):
        self.assertIsNone(cc.last_recorded_cwd(os.path.join(self.tmp, "nope.jsonl")))


# ─────────────────────── filesystem-backed (discover/remap) ───────────────────────
class FSTestBase(unittest.TestCase):
    """Points the module at a throwaway projects dir + cache, restores after."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.projects = os.path.join(self.tmp, "projects")
        os.makedirs(self.projects)
        self._saved = {k: getattr(cc, k) for k in
                       ("PROJECTS_DIR", "CACHE_FILE", "STATE_FILE", "SERVER_FILE", "PREFS_FILE",
                        "SUMMARY_FILE", "SUMMARY_MIN_INTERVAL", "SUMMARY_WORKDIR", "GITCACHE_FILE",
                        "WEBVIEW_PORT", "SERVER_IDLE_TIMEOUT",
                        "generate_summary", "assign_liveness", "mark_all_live", "ensure_summarizer",
                        "notify", "ask_action", "choose_folder", "live_session_names")}
        cc.PROJECTS_DIR = self.projects
        cc.CACHE_FILE = os.path.join(self.tmp, "cache.json")
        cc.STATE_FILE = os.path.join(self.tmp, "state.json")
        # redirect ALL ~/.ccsessions state at temp so no test can clobber real files
        cc.SUMMARY_FILE = os.path.join(self.tmp, "summaries.json")
        cc.PREFS_FILE = os.path.join(self.tmp, "prefs.json")
        cc.SERVER_FILE = os.path.join(self.tmp, "server.json")
        cc.GITCACHE_FILE = os.path.join(self.tmp, "gitcache.json")
        cc.notify = lambda *_: None
        # Nothing live unless a test overrides. mark_all_live is the cross-app
        # liveness seam every flow goes through; neutralising it keeps tests off
        # the real iTerm/Terminal (pgrep + osascript).
        cc.mark_all_live = lambda sessions: [s.__setitem__("live", False) for s in sessions]
        cc.live_session_names = lambda: set()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(cc, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_session(self, project_folder, sid, cwd_lines, *, mtime=None):
        """Create projects/<project_folder>/<sid>.jsonl with one line per cwd."""
        pdir = os.path.join(self.projects, project_folder)
        os.makedirs(pdir, exist_ok=True)
        path = os.path.join(pdir, sid + ".jsonl")
        _jsonl(path, [{"cwd": c, "type": "user", "message": {"content": "hi"}} for c in cwd_lines])
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path


class TestDiscover(FSTestBase):
    def test_missing_projects_dir_signals_false(self):
        shutil.rmtree(self.projects)
        sessions, ok = cc.discover()
        self.assertFalse(ok)
        self.assertEqual(sessions, [])

    def test_dedupe_by_id_keeps_newest(self):
        sid = "11111111-2222-3333-4444-555555555555"
        # same id in two project folders; newer one should win
        self.make_session("-a-test", sid, ["/a/test"], mtime=1000)
        self.make_session("-a-test-me", sid, ["/a/test_me"], mtime=2000)
        sessions, ok = cc.discover()
        self.assertTrue(ok)
        rows = [s for s in sessions if s["id"] == sid]
        self.assertEqual(len(rows), 1)                 # deduped to one
        self.assertEqual(rows[0]["cwd"], "/a/test_me")  # the newer copy

    def test_subagent_dash_dir_is_skipped(self):
        # the "-" project dir holds sub-agent transcripts, not real sessions
        self.make_session("-", "99999999-0000-0000-0000-000000000009", ["/x"])
        self.make_session("-real", "11111111-0000-0000-0000-000000000001", ["/real"])
        sessions, ok = cc.discover()
        ids = {s["id"] for s in sessions}
        self.assertNotIn("99999999-0000-0000-0000-000000000009", ids)
        self.assertIn("11111111-0000-0000-0000-000000000001", ids)


class TestExcludeSummarizerSessions(FSTestBase):
    def test_summarizer_own_sessions_are_not_discovered(self):
        # the summarizer's `claude -p` calls write their own transcripts; those
        # must never appear in discovery (they'd be summarized recursively).
        cc.SUMMARY_WORKDIR = os.path.join(self.tmp, "sumwd")
        self.make_session("-real", "real-1", ["/p"])
        self.make_session(cc.summarizer_proj_dir(), "junk-1", ["/x"])  # in the excluded folder
        ids = [s["id"] for s in cc.discover()[0]]
        self.assertIn("real-1", ids)
        self.assertNotIn("junk-1", ids)


class TestSessionFile(FSTestBase):
    def test_returns_newest_of_duplicates(self):
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.make_session("-a-test", sid, ["/a/test"], mtime=1000)
        newer = self.make_session("-a-test-me", sid, ["/a/test_me"], mtime=2000)
        self.assertEqual(cc.session_file(sid), newer)

    def test_unknown_id_returns_none(self):
        self.assertIsNone(cc.session_file("no-such-id"))


class TestAssignLiveness(unittest.TestCase):
    def _s(self, sid, title, cwd, mtime):
        return {"id": sid, "title": title, "cwd": cwd, "mtime": mtime}

    def test_title_match_sets_live(self):
        s = self._s("1", "myproj", "/p", 1)
        cc.assign_liveness([s], {f"✳ myproj{SEP}~/p"})
        self.assertTrue(s["live"])

    def test_same_title_dedup_keeps_newest(self):
        a = self._s("a", "dup", "/p", 100)
        b = self._s("b", "dup", "/p", 200)  # newer
        cc.assign_liveness([a, b], {f"✳ dup{SEP}~/p"})
        self.assertFalse(a["live"])
        self.assertTrue(b["live"])

    def test_default_tab_fallback_lights_newest_in_dir(self):
        # no title match possible (tab is the default "Claude Code"); match by cwd
        old = self._s("a", "", "/dev/test", 100)
        new = self._s("b", "", "/dev/test", 200)
        cc.assign_liveness([old, new], {f"✳ Claude Code{SEP}/dev/test"})
        self.assertFalse(old["live"])
        self.assertTrue(new["live"])

    def test_nothing_live_when_no_tabs(self):
        s = self._s("1", "myproj", "/p", 1)
        cc.assign_liveness([s], set())
        self.assertFalse(s["live"])


class TestDetectRemapTarget(FSTestBase):
    def test_positive_live_renamed_path_exists(self):
        sid = "11111111-1111-1111-1111-111111111111"
        new_dir = os.path.join(self.tmp, "renamed")
        os.makedirs(new_dir)
        self.make_session("-old", sid, ["/old", new_dir])  # last cwd = new_dir (exists)
        affected = [{"id": sid, "cwd": "/old"}]
        self.assertEqual(cc.detect_remap_target(affected, "/old"), new_dir)

    def test_negative_no_record(self):
        sid = "22222222-2222-2222-2222-222222222222"
        self.make_session("-old", sid, ["/old"])  # only old cwd, never renamed
        affected = [{"id": sid, "cwd": "/old"}]
        self.assertIsNone(cc.detect_remap_target(affected, "/old"))

    def test_negative_new_path_gone(self):
        sid = "33333333-3333-3333-3333-333333333333"
        self.make_session("-old", sid, ["/old", "/vanished/dir"])  # last cwd doesn't exist
        affected = [{"id": sid, "cwd": "/old"}]
        self.assertIsNone(cc.detect_remap_target(affected, "/old"))


class TestDoRemap(FSTestBase):
    def _setup_renamed(self, sid="ssssssss-tttt-uuuu-vvvv-wwwwwwwwwwww"):
        """A parked session whose dir was renamed: transcript in the old project
        folder, new dir exists on disk."""
        old_cwd = "/sandbox/old"
        new_cwd = os.path.join(self.tmp, "newname")
        os.makedirs(new_cwd)
        op = cc.encode_project_dir(old_cwd)
        self.make_session(op, sid, [old_cwd, old_cwd, new_cwd])  # live-renamed: last cwd = new
        return sid, old_cwd, new_cwd

    def test_autodetect_moves_and_skips_picker(self):
        sid, old_cwd, new_cwd = self._setup_renamed()
        cc.ask_action = lambda *_: "Remap"             # accept detected path
        calls = {"picker": 0}
        cc.choose_folder = lambda *_: calls.__setitem__("picker", calls["picker"] + 1)

        cc.do_remap(old_cwd)

        new_path = os.path.join(self.projects, cc.encode_project_dir(new_cwd), sid + ".jsonl")
        old_path = os.path.join(self.projects, cc.encode_project_dir(old_cwd), sid + ".jsonl")
        self.assertTrue(os.path.isfile(new_path))      # moved to correct folder
        self.assertFalse(os.path.exists(old_path))     # old removed
        self.assertEqual(calls["picker"], 0)           # picker skipped
        cwds = {json.loads(l)["cwd"] for l in open(new_path) if l.strip()}
        self.assertEqual(cwds, {new_cwd})              # all cwd lines unified

    def test_live_session_is_refused(self):
        sid, old_cwd, new_cwd = self._setup_renamed()
        # make the affected session look live (remap must refuse live sessions)
        orig = cc.mark_all_live
        cc.mark_all_live = lambda sessions: [s.__setitem__("live", True) for s in sessions]
        try:
            cc.do_remap(old_cwd)
        finally:
            cc.mark_all_live = orig
        # nothing moved
        old_path = os.path.join(self.projects, cc.encode_project_dir(old_cwd), sid + ".jsonl")
        self.assertTrue(os.path.isfile(old_path))

    def test_same_directory_is_noop(self):
        sid, old_cwd, new_cwd = self._setup_renamed()
        cc.ask_action = lambda *_: "Pick another…"
        cc.choose_folder = lambda *_: old_cwd            # user picks the same (dead) dir
        cc.do_remap(old_cwd)
        old_path = os.path.join(self.projects, cc.encode_project_dir(old_cwd), sid + ".jsonl")
        self.assertTrue(os.path.isfile(old_path))        # unchanged


class TestRelocateProjectMemory(FSTestBase):
    def test_moves_memory_no_clobber(self):
        src = os.path.join(self.projects, "-src")
        dst = os.path.join(self.projects, "-dst")
        os.makedirs(os.path.join(src, "memory"))
        os.makedirs(dst)
        with open(os.path.join(src, "memory", "PLAN.md"), "w") as f:
            f.write("plan")
        cc.relocate_project_memory(src, dst)
        self.assertTrue(os.path.isfile(os.path.join(dst, "memory", "PLAN.md")))
        self.assertFalse(os.path.exists(os.path.join(src, "memory")))

    def test_no_clobber_keeps_destination_copy(self):
        src = os.path.join(self.projects, "-src")
        dst = os.path.join(self.projects, "-dst")
        os.makedirs(os.path.join(src, "memory"))
        os.makedirs(os.path.join(dst, "memory"))
        with open(os.path.join(src, "memory", "M.md"), "w") as f:
            f.write("SRC")
        with open(os.path.join(dst, "memory", "M.md"), "w") as f:
            f.write("DST")
        cc.relocate_project_memory(src, dst)
        # destination's own file must survive untouched
        with open(os.path.join(dst, "memory", "M.md")) as f:
            self.assertEqual(f.read(), "DST")


class TestStateBatch(FSTestBase):
    def test_apply_and_delete(self):
        cc.STATE_FILE = os.path.join(self.tmp, "state.json")
        self.make_session("-p", "id-a", ["/p"])
        self.make_session("-p", "id-b", ["/p"])
        cc.apply_archived(["id-a", "id-b"], True)
        st = cc.load_json(cc.STATE_FILE, {})
        self.assertTrue(st["id-a"]["archived"] and st["id-b"]["archived"])
        cc.apply_archived(["id-a"], False)
        self.assertFalse(cc.load_json(cc.STATE_FILE, {})["id-a"]["archived"])
        n = cc.delete_sessions(["id-a", "id-b"])
        self.assertEqual(n, 2)
        self.assertIsNone(cc.session_file("id-a"))

    def test_archiving_skips_live_sessions(self):
        # a running session can't be archived (must be quit→parked first); a
        # parked one in the same batch still archives. Assert both in one run.
        self.make_session("-p", "id-live", ["/p"])
        self.make_session("-p", "id-parked", ["/p"])
        cc.mark_all_live = lambda ss: [s.__setitem__("live", s["id"] == "id-live") for s in ss]
        n = cc.apply_archived(["id-live", "id-parked"], True)
        st = cc.load_json(cc.STATE_FILE, {})
        self.assertFalse(st.get("id-live", {}).get("archived"))   # live NOT hidden
        self.assertTrue(st["id-parked"]["archived"])              # parked archived
        self.assertEqual(n, 1)

    def test_unarchive_always_allowed_even_if_live(self):
        self.make_session("-p", "id-x", ["/p"])
        cc.apply_archived(["id-x"], True)                         # archive while parked
        cc.mark_all_live = lambda ss: [s.__setitem__("live", True) for s in ss]
        cc.apply_archived(["id-x"], False)                        # now live → unarchive still works
        self.assertFalse(cc.load_json(cc.STATE_FILE, {})["id-x"]["archived"])


class TestMenuLayout(FSTestBase):
    def _render(self):
        cc.ensure_server = lambda: None
        cc.ensure_summarizer = lambda: None
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cc.render_menu()
        return [ln.split("|")[0].rstrip() for ln in buf.getvalue().splitlines()]

    def test_past_sessions_nested_in_dir_submenu_live_stays_top(self):
        for sid in ("live-aaa", "park-bbb", "park-ccc"):
            self.make_session("-p-app", sid, ["/p/app"])
        cc.mark_all_live = lambda ss: [s.__setitem__("live", s["id"] == "live-aaa") for s in ss]
        titles = self._render()
        # "Past sessions" sits INSIDE the dir submenu — level 1 ("--"), not top level
        past = [t for t in titles if "Past sessions" in t]
        self.assertTrue(past, titles)
        self.assertTrue(past[0].startswith("--") and not past[0].startswith("----"), past)
        # parked sessions nest two levels deep (Archive all at level 2 = "----")
        self.assertTrue(any(t.startswith("----Archive all") for t in titles), titles)
        # the LIVE session stays at the top level → its action is at level 1
        self.assertIn("--Jump to session", titles)        # live verb
        self.assertNotIn("Past sessions (2)", titles)     # never a bare top-level row
        self.assertIn("--Past sessions (2)", titles)


class TestWebviewSessions(FSTestBase):
    def test_payload_shape_and_flags(self):
        cc.live_session_names = lambda: set()
        self.make_session("-p", "live-1", ["/p/app"])
        self.make_session("-p", "arch-1", ["/p/app"])
        cc.apply_archived(["arch-1"], True)
        out = cc.webview_sessions()
        ids = {s["id"]: s for s in out["sessions"]}
        self.assertIn("live-1", ids)
        self.assertTrue(ids["arch-1"]["archived"])
        # every row has the keys the panel JS expects
        for s in out["sessions"]:
            self.assertEqual(set(s),
                {"id", "name", "dir", "cwd", "dir_kind", "live", "app", "archived", "missing", "mtime",
                 "awaiting", "ctx_pct", "ctx_tokens", "model", "summary", "status",
                 "progress", "pending"})
        self.assertIsInstance(out["dirs"], list)

    def test_dirs_payload_includes_workspace_roots_deduped(self):
        # session rooted in a real dir → listed with has_session True
        sdir = os.path.join(self.tmp, "proj"); os.makedirs(sdir)
        self.make_session("-proj", "s1", [sdir])
        # a discovered workspace root with no session → appended (kind=workspace)
        wsroot = os.path.join(self.tmp, "ws"); os.makedirs(wsroot)
        orig = cc.WORKSPACES_CACHE
        self.addCleanup(lambda: setattr(cc, "WORKSPACES_CACHE", orig))
        cc.WORKSPACES_CACHE = os.path.join(self.tmp, "workspaces.json")
        # include sdir in the cache too → must NOT be double-listed
        with open(cc.WORKSPACES_CACHE, "w") as fh:
            json.dump({"ts": 0, "roots": [wsroot, sdir]}, fh)
        out = cc.webview_sessions()
        self.assertEqual(out["home"], cc.HOME)               # panel uses it to ~-abbrev paths
        dirs = {d["cwd"]: d for d in out["dirs"]}
        self.assertTrue(dirs[sdir]["has_session"])           # session dir
        self.assertEqual(dirs[wsroot]["kind"], "workspace")  # workspace launch target
        self.assertFalse(dirs[wsroot]["has_session"])
        # every dir row carries the keys the panel reads
        for d in dirs.values():
            self.assertEqual(set(d), {"cwd", "label", "kind", "has_session"})
        # sdir appears once despite being in both the session list and the cache
        self.assertEqual(sum(1 for d in cc.webview_sessions()["dirs"] if d["cwd"] == sdir), 1)

    def test_missing_projects_dir(self):
        import shutil as _sh
        _sh.rmtree(self.projects)
        self.assertEqual(cc.webview_sessions(), {"sessions": [], "dirs": []})


class TestServerToken(FSTestBase):
    def test_generates_then_reuses(self):
        cc.SERVER_FILE = os.path.join(self.tmp, "server.json")
        t1 = cc.server_token()
        self.assertTrue(t1)
        self.assertEqual(cc.server_token(), t1)  # stable across calls


class TestWebviewServerIntegration(FSTestBase):
    """Boot the real do_serve() on a free port in a thread and exercise the HTTP
    API end-to-end (token gating + each mutation)."""
    def test_endpoints(self):
        import socket, threading, time, urllib.request, urllib.error
        import json as J
        sock = socket.socket(); sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]; sock.close()
        cc.WEBVIEW_PORT = port
        cc.SERVER_FILE = os.path.join(self.tmp, "server.json")
        cc.SERVER_IDLE_TIMEOUT = 30
        cc.live_session_names = lambda: set()
        sid = "abcd1234-0000-0000-0000-000000000001"
        self.make_session("-p", sid, ["/p/app"])

        threading.Thread(target=cc.do_serve, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                if urllib.request.urlopen(base + "/ping", timeout=0.3).read().startswith(b"ccsessions"):
                    break
            except Exception:
                time.sleep(0.1)
        else:
            self.fail("server did not start")
        tok = cc.server_token()

        def post(path, payload):
            req = urllib.request.Request(base + path, data=J.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
            return urllib.request.urlopen(req).read()

        # GET /api/sessions requires token
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(base + "/api/sessions")
        self.assertEqual(cm.exception.code, 403)

        data = J.loads(urllib.request.urlopen(base + "/api/sessions?t=" + tok).read())
        self.assertIn(sid, [s["id"] for s in data["sessions"]])

        # bad-token POST → 403, nothing changes
        with self.assertRaises(urllib.error.HTTPError) as cm:
            post("/api/archive", {"ids": [sid], "t": "wrong"})
        self.assertEqual(cm.exception.code, 403)

        # archive → unarchive → delete round-trip
        post("/api/archive", {"ids": [sid], "t": tok})
        self.assertTrue(cc.load_json(cc.STATE_FILE, {}).get(sid, {}).get("archived"))
        post("/api/unarchive", {"ids": [sid], "t": tok})
        self.assertFalse(cc.load_json(cc.STATE_FILE, {}).get(sid, {}).get("archived"))
        post("/api/delete", {"ids": [sid], "t": tok})
        self.assertIsNone(cc.session_file(sid))

        # prefs round-trip: POST /api/prefs → reflected in load_prefs + payload
        cc.PREFS_FILE = os.path.join(self.tmp, "prefs.json")
        post("/api/prefs", {"key": "revive_in", "value": "tab", "t": tok})
        self.assertEqual(cc.load_prefs()["revive_in"], "tab")
        post("/api/prefs", {"key": "skip_permissions", "value": "on", "t": tok})
        self.assertIs(cc.load_prefs()["skip_permissions"], True)
        payload = J.loads(urllib.request.urlopen(base + "/api/sessions?t=" + tok).read())
        self.assertEqual(payload["prefs"]["revive_in"], "tab")

        # re-summarize: drops the cached summary so it becomes pending again
        cc.ensure_summarizer = lambda: None  # don't spawn a real summarizer subprocess
        cc.save_json(cc.SUMMARY_FILE, {sid: {"summary": "old", "mtime": 1, "size": 1}})
        post("/api/resummarize", {"id": sid, "t": tok})
        self.assertNotIn(sid, cc.load_json(cc.SUMMARY_FILE, {}))


class TestRecentTranscriptText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, objs):
        p = os.path.join(self.tmp, "s.jsonl")
        _jsonl(p, objs)
        return p

    def test_keeps_recent_text_skips_meta_and_commands(self):
        p = self._write([
            {"type": "user", "isMeta": True, "message": {"content": "# Bridge Command"}},  # skipped
            {"type": "user", "message": {"content": "<command-name>/x</command-name>"}},   # skipped
            {"type": "user", "message": {"content": "build the webview panel"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "done, added serve mode"}]}},
        ])
        out = cc.recent_transcript_text(p)
        self.assertIn("build the webview panel", out)
        self.assertIn("done, added serve mode", out)
        self.assertNotIn("Bridge Command", out)
        self.assertNotIn("command-name", out)

    def test_tail_budget_keeps_most_recent(self):
        p = self._write([{"type": "user", "message": {"content": "X" * 500}},
                         {"type": "assistant", "message": {"content": "Y" * 500}},
                         {"type": "user", "message": {"content": "NEWEST"}}])
        out = cc.recent_transcript_text(p, max_chars=120)
        self.assertIn("NEWEST", out)          # newest always kept
        self.assertLessEqual(len(out), 130)   # bounded


class TestDoSummarize(FSTestBase):
    def setUp(self):
        super().setUp()
        cc.SUMMARY_FILE = os.path.join(self.tmp, "summaries.json")
        cc.live_session_names = lambda: set()
        self.calls = []
        cc.generate_summary = lambda text: (self.calls.append(text) or {"summary": "a summary", "status": "active", "progress": 50})

    def test_summarizes_changed_only_and_caps_length(self):
        self.make_session("-p", "sid-1", ["/p"])
        cc.do_summarize()
        summaries = cc.load_json(cc.SUMMARY_FILE, {})
        self.assertEqual(summaries["sid-1"]["summary"], "a summary")
        self.assertEqual(len(self.calls), 1)
        # second run: unchanged → no new Claude call
        cc.do_summarize()
        self.assertEqual(len(self.calls), 1)

    def test_unchanged_session_not_resummarized_after_change_within_interval(self):
        path = self.make_session("-p", "sid-2", ["/p"])
        cc.do_summarize()
        self.assertEqual(len(self.calls), 1)
        # mutate the transcript (size changes) but keep within the throttle window
        with open(path, "a") as f:
            f.write('{"type":"user","message":{"content":"more"}}\n')
        cc.SUMMARY_MIN_INTERVAL = 9999  # force throttle
        cc.do_summarize()
        self.assertEqual(len(self.calls), 1)  # throttled despite the change

    def test_failed_summary_not_cached_so_it_retries(self):
        # a session WITH text whose Claude call fails must NOT be cached empty,
        # so the next pass retries it (the bug that left 49 sessions blank).
        self.make_session("-p", "sid-fail", ["/p"])
        cc.generate_summary = lambda text: None  # simulate Claude failure
        cc.do_summarize()
        self.assertNotIn("sid-fail", cc.load_json(cc.SUMMARY_FILE, {}))
        # once Claude works, it gets summarized
        cc.generate_summary = lambda text: {"summary": "recovered", "status": "done", "progress": 100}
        cc.do_summarize()
        self.assertEqual(cc.load_json(cc.SUMMARY_FILE, {})["sid-fail"]["summary"], "recovered")

    def test_priority_live_then_parked_then_archived(self):
        cc.SUMMARIES_PER_RUN = 99
        cc.mark_all_live = lambda sessions: [s.__setitem__("live", s["id"] == "liv") for s in sessions]
        for sid, mt in (("arch", 300), ("park", 200), ("liv", 100)):
            p = self.make_session("-p", sid, ["/p"])
            _jsonl(p, [{"cwd": "/p", "type": "user", "message": {"content": "TASK-" + sid}}])
            os.utime(p, (mt, mt))
        cc.apply_archived(["arch"], True)
        order = []
        def gen(text):
            for sid in ("arch", "park", "liv"):
                if "TASK-" + sid in text:
                    order.append(sid)
            return {"summary": "s", "status": "active", "progress": 0}
        cc.generate_summary = gen
        cc.do_summarize()
        self.assertEqual(order, ["liv", "park", "arch"])  # live first, archived last

    def test_prune_only_removes_truly_gone_transcripts(self):
        self.make_session("-p", "keep", ["/p"])  # has a transcript on disk
        cc.save_json(cc.SUMMARY_FILE, {"keep": {"summary": "x", "mtime": 1, "size": 1},
                                       "gone": {"summary": "y", "mtime": 1, "size": 1}})
        cc.do_summarize()
        c = cc.load_json(cc.SUMMARY_FILE, {})
        self.assertIn("keep", c)       # transcript exists → survives a discover() pass
        self.assertNotIn("gone", c)    # no transcript anywhere → pruned

    def test_hard_truncation_to_128(self):
        real = self._saved["generate_summary"]  # the real function (saved pre-monkeypatch)
        orig = cc.subprocess.run
        cc.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "z" * 400})()
        try:
            out = real("some text")  # claude returns 400 chars → must clamp to 128
        finally:
            cc.subprocess.run = orig
        self.assertEqual(len(out["summary"]), 128)


class TestSummarizeLock(unittest.TestCase):
    """The summarize lock must hold for a live, heartbeated pass and be reclaimed
    when the owner is gone — otherwise long passes stack and run forever."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._sf = cc.SUMMARY_FILE
        cc.SUMMARY_FILE = os.path.join(self.tmp, "summaries.json")
        self.lock = cc.SUMMARY_FILE + ".lock"

    def tearDown(self):
        cc.SUMMARY_FILE = self._sf
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _set(self, content, age=0):
        with open(self.lock, "w") as f:
            f.write(content)
        t = time.time() - age
        os.utime(self.lock, (t, t))

    def test_no_lock_not_held(self):
        self.assertFalse(cc.summarize_lock_held())

    def test_live_owner_fresh_is_held(self):
        self._set(str(os.getpid()))
        self.assertTrue(cc.summarize_lock_held())

    def test_old_unheartbeated_is_reclaimed(self):
        # THE BUG: a live pid whose lock wasn't heartbeated past the stale window
        # must be reclaimable (the old code used a fixed 300s < 720s max run).
        self._set(str(os.getpid()), age=cc.SUMMARY_LOCK_STALE + 10)
        self.assertFalse(cc.summarize_lock_held())

    def test_heartbeat_keeps_live_lock_held(self):
        self._set(str(os.getpid()), age=cc.SUMMARY_LOCK_STALE + 10)
        os.utime(self.lock, None)  # heartbeat
        self.assertTrue(cc.summarize_lock_held())

    def test_dead_owner_reclaimed_even_when_fresh(self):
        import subprocess
        p = subprocess.Popen(["true"]); p.wait(); time.sleep(0.05)
        self._set(str(p.pid))  # fresh but owner is gone
        self.assertFalse(cc.summarize_lock_held())

    def test_garbled_fresh_lock_assumed_held(self):
        self._set("")  # mid-write, pid not yet written → don't race it
        self.assertTrue(cc.summarize_lock_held())


class TestAwaitingUser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, objs):
        p = os.path.join(self.tmp, "s.jsonl"); _jsonl(p, objs); return p

    def test_assistant_text_last_is_awaiting(self):
        p = self._w([{"type": "user", "message": {"content": "hi"}},
                     {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}])
        self.assertTrue(cc.awaiting_user(p))

    def test_trailing_user_is_not_awaiting(self):
        p = self._w([{"type": "assistant", "message": {"content": "x"}},
                     {"type": "user", "message": {"content": "do this"}}])
        self.assertFalse(cc.awaiting_user(p))

    def test_assistant_tool_use_is_not_awaiting(self):
        p = self._w([{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}])
        self.assertFalse(cc.awaiting_user(p))

    def test_missing_file(self):
        self.assertFalse(cc.awaiting_user(os.path.join(self.tmp, "nope.jsonl")))


class TestShortModel(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(cc.short_model("claude-opus-4-8-20250101"), "opus-4.8")
        self.assertEqual(cc.short_model("claude-sonnet-4-6"), "sonnet-4.6")
        self.assertEqual(cc.short_model("claude-3-5-sonnet-20241022"), "sonnet-3.5")
        self.assertEqual(cc.short_model("claude-haiku-4-5-20251001"), "haiku-4.5")
        self.assertEqual(cc.short_model(""), "")


class TestTailInfo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, objs):
        p = os.path.join(self.tmp, "s.jsonl"); _jsonl(p, objs); return p

    def test_opus_uses_1m_window(self):  # Opus 4.x → 1M denominator
        p = self._w([{"type": "assistant", "message": {
            "model": "claude-opus-4-8", "content": [{"type": "text", "text": "done"}],
            "usage": {"input_tokens": 250000, "cache_read_input_tokens": 200000,
                      "cache_creation_input_tokens": 50000, "output_tokens": 5}}}])
        info = cc.tail_info(p)
        self.assertEqual(info["ctx_tokens"], 500000)
        self.assertEqual(info["ctx_pct"], 50)        # 500k / 1M
        self.assertEqual(info["model"], "opus-4.8")
        self.assertTrue(info["awaiting"])

    def test_sonnet_uses_200k_window(self):  # non-Opus → 200k denominator
        p = self._w([{"type": "assistant", "message": {
            "model": "claude-sonnet-4-6", "usage": {"input_tokens": 100000}}}])
        info = cc.tail_info(p)
        self.assertEqual(info["ctx_pct"], 50)        # 100k / 200k
        self.assertEqual(info["model"], "sonnet-4.6")

    def test_ctx_pct_capped_at_100(self):
        p = self._w([{"type": "assistant", "message": {"usage": {"input_tokens": 300000}}}])
        self.assertEqual(cc.tail_info(p)["ctx_pct"], 100)  # 300k / 200k → capped

    def test_no_usage_is_zero(self):
        info = cc.tail_info(self._w([{"type": "user", "message": {"content": "hi"}}]))
        self.assertEqual(info["ctx_pct"], 0)
        self.assertEqual(info["model"], "")


class TestEstimateCost(unittest.TestCase):
    def test_opus_input_rate(self):
        c = cc.estimate_cost("opus-4.8", {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0})
        self.assertEqual(c, 15.0)

    def test_unknown_model_falls_back_to_opus(self):
        self.assertEqual(cc.estimate_cost("mystery", {"input": 1_000_000, "output": 0,
                                                      "cache_read": 0, "cache_write": 0}), 15.0)


class TestSessionStats(FSTestBase):
    def test_sums_usage_turns_ctx_and_cost(self):
        pdir = os.path.join(self.projects, "-work"); os.makedirs(pdir, exist_ok=True)
        sid = "stat0001-0000-0000-0000-000000000000"
        _jsonl(os.path.join(pdir, sid + ".jsonl"), [
            {"cwd": "/work", "type": "user", "message": {"content": "hi"}, "timestamp": "2026-06-07T07:00:00Z"},
            {"type": "assistant", "timestamp": "2026-06-07T07:05:00Z", "message": {
                "model": "claude-sonnet-4-6",
                "content": [{"type": "thinking", "thinking": "hmm"},
                            {"type": "tool_use", "name": "Bash"},
                            {"type": "tool_use", "name": "Read"}],
                "usage": {"input_tokens": 1000, "output_tokens": 500,
                          "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 100}}},
            {"type": "assistant", "timestamp": "2026-06-07T07:10:00Z", "message": {
                "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "b"}],
                "usage": {"input_tokens": 1000, "output_tokens": 500,
                          "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0}}},
        ])
        st = cc.session_stats(sid)
        self.assertEqual(st["turns"], 2)
        self.assertEqual(st["tool_calls"], 2)       # two tool_use blocks (turn 1)
        self.assertEqual(st["thinking_turns"], 1)   # one assistant msg used thinking
        self.assertEqual(st["totals"], {"input": 2000, "output": 1000, "cache_read": 5000, "cache_write": 100})
        self.assertEqual(st["model"], "sonnet-4.6")
        self.assertEqual(st["ctx_tokens"], 4000)     # last turn: 1000 + 3000 + 0
        self.assertEqual(st["window"], 200000)        # sonnet → 200k
        self.assertEqual(st["ctx_pct"], 2)            # 4000 / 200000
        self.assertEqual(st["total_tokens"], 8100)
        self.assertEqual(st["cost"], round((2000 * 3 + 1000 * 15 + 100 * 3.75 + 5000 * 0.30) / 1e6, 2))
        self.assertEqual((st["first_ts"], st["last_ts"]), ("2026-06-07T07:00:00Z", "2026-06-07T07:10:00Z"))

    def test_missing_session_is_none(self):
        self.assertIsNone(cc.session_stats("nope"))


class TestReviveSkipPerms(unittest.TestCase):
    def test_revive_adds_skip_perms_when_enabled(self):
        s = cc.build_open_script("key", "name", "/w", "sid-123", "window", skip_perms=True)
        self.assertIn("--dangerously-skip-permissions", s)
        self.assertIn("--resume", s)

    def test_revive_omits_skip_perms_by_default(self):
        s = cc.build_open_script("key", "name", "/w", "sid-123", "window")
        self.assertNotIn("--dangerously-skip-permissions", s)


class TestInsights(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._dir, self._osa = cc.INSIGHTS_DIR, cc.run_osascript
        cc.INSIGHTS_DIR = self.tmp

    def tearDown(self):
        cc.INSIGHTS_DIR, cc.run_osascript = self._dir, self._osa
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_none_when_no_reports(self):
        self.assertIsNone(cc.latest_insights_report())

    def test_returns_newest_report(self):
        a = os.path.join(self.tmp, "report-2026-06-01.html"); open(a, "w").write("a")
        b = os.path.join(self.tmp, "report-2026-06-07.html"); open(b, "w").write("b")
        os.utime(a, (1000, 1000)); os.utime(b, (2000, 2000))
        self.assertEqual(cc.latest_insights_report(), b)

    def test_ignores_non_report_files(self):
        open(os.path.join(self.tmp, "facets.json"), "w").write("x")
        self.assertIsNone(cc.latest_insights_report())

    def test_generate_launches_claude_with_insights_command(self):
        captured = {}
        cc.run_osascript = lambda s: captured.__setitem__("s", s)
        cc.do_generate_insights()
        self.assertIn("/insights", captured["s"])
        self.assertIn(cc.CLAUDE_BIN, captured["s"])


class TestParseSummary(unittest.TestCase):
    def test_structured_line(self):
        r = cc.parse_summary("STATUS=done; PROGRESS=90; SUMMARY=Built the webview panel")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["progress"], 90)
        self.assertEqual(r["summary"], "Built the webview panel")

    def test_drifted_format_falls_back_to_plain_summary(self):
        r = cc.parse_summary("Refactor the parser for speed")
        self.assertEqual(r["status"], "active")          # default
        self.assertIsNone(r["progress"])
        self.assertEqual(r["summary"], "Refactor the parser for speed")

    def test_progress_clamped_and_bad_status_defaults(self):
        r = cc.parse_summary("STATUS=weird; PROGRESS=250; SUMMARY=x")
        self.assertEqual(r["status"], "active")  # 'weird' not allowed → default
        self.assertEqual(r["progress"], 100)     # clamped

    def test_empty_returns_none(self):
        self.assertIsNone(cc.parse_summary(""))


class TestCleanSummary(unittest.TestCase):
    def test_strips_conversational_preambles(self):
        self.assertEqual(cc.clean_summary("I understand — Build the webview panel"), "Build the webview panel")
        self.assertEqual(cc.clean_summary("This session is about: fixing the tests"), "fixing the tests")
        self.assertEqual(cc.clean_summary("Summary: add login flow"), "add login flow")
        self.assertEqual(cc.clean_summary("Here's a summary, refactor parser"), "refactor parser")

    def test_leaves_clean_summary_untouched(self):
        self.assertEqual(cc.clean_summary("Add dark mode toggle to settings"), "Add dark mode toggle to settings")

    def test_caps_to_128(self):
        self.assertEqual(len(cc.clean_summary("z" * 300)), 128)


class TestWorkspaceKind(unittest.TestCase):
    """compute_dir_kind: a non-repo dir is a 'workspace' if it declares one via a
    manifest OR holds >=2 git checkouts (repos/worktrees) below it; a single
    checkout (or none) is a plain 'dir'. Asserts both positive and negative cases
    so the detection actually discriminates."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()  # not inside a git repo → rev-parse fails → workspace/dir check

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _worktree(self, name):  # a linked worktree → `.git` is a FILE
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with open(os.path.join(d, ".git"), "w") as f:
            f.write("gitdir: /some/repo/.git/worktrees/x\n")

    def _repo(self, name):      # a normal repo → `.git` is a DIR
        os.makedirs(os.path.join(self.tmp, name, ".git"))

    def test_two_worktrees_is_workspace(self):
        self._worktree("repo-a"); self._worktree("repo-b")
        self.assertEqual(cc.compute_dir_kind(self.tmp), "workspace")

    def test_folder_of_plain_repos_is_dir(self):
        # a folder that merely holds repos (incidental) is NOT a workspace — only a
        # manifest or a deliberate grouping of WORKTREES counts
        self._repo("svc-a"); self._repo("svc-b")
        self.assertEqual(cc.compute_dir_kind(self.tmp), "dir")

    def test_single_worktree_is_dir(self):
        self._worktree("only-one")  # one worktree below a folder isn't a deliberate grouping
        self.assertEqual(cc.compute_dir_kind(self.tmp), "dir")

    def test_go_work_manifest_is_workspace(self):
        with open(os.path.join(self.tmp, "go.work"), "w") as f:
            f.write("go 1.22\n")
        self.assertEqual(cc.compute_dir_kind(self.tmp), "workspace")

    def test_cargo_workspace_manifest_is_workspace(self):
        with open(os.path.join(self.tmp, "Cargo.toml"), "w") as f:
            f.write('[workspace]\nmembers = ["a"]\n')
        self.assertEqual(cc.compute_dir_kind(self.tmp), "workspace")

    def test_plain_folder_is_dir(self):
        os.makedirs(os.path.join(self.tmp, "just-files"))
        with open(os.path.join(self.tmp, "notes.txt"), "w") as f:
            f.write("hi")
        self.assertEqual(cc.compute_dir_kind(self.tmp), "dir")


class TestTerminalBackend(unittest.TestCase):
    """Terminal.app backend: tty→process liveness + window-id actions."""

    def setUp(self):
        self.scripts = []
        self._osa = cc.run_osascript
        cc.run_osascript = lambda s: (self.scripts.append(s) or type("R", (), {"returncode": 0, "stdout": ""})())
        self._lr = cc.TERMINAL.live_records

    def tearDown(self):
        cc.run_osascript = self._osa
        cc.TERMINAL.live_records = self._lr

    def _s(self, sid, cwd, mtime):
        return {"id": sid, "cwd": cwd, "mtime": mtime}

    # ── is-claude detection ──
    def test_is_claude_cmd_accepts_interactive(self):
        self.assertTrue(cc._is_claude_cmd("/Users/x/.nvm/bin/claude --resume abc"))
        self.assertTrue(cc._is_claude_cmd("claude"))

    def test_is_claude_cmd_rejects_headless_and_others(self):
        self.assertFalse(cc._is_claude_cmd("claude -p --model haiku"))   # the summarizer
        self.assertFalse(cc._is_claude_cmd("node /app/server.js"))
        self.assertFalse(cc._is_claude_cmd(""))

    # ── liveness: match by resume id, then cwd fallback ──
    def test_mark_live_matches_by_resume_id(self):
        s = self._s("sid-1", "/p", 10)
        cc.TERMINAL.live_records = lambda: [{"winid": "42", "sid": "sid-1", "cwd": "/p"}]
        cc.TERMINAL.mark_live([s])
        self.assertTrue(s["live"])
        self.assertEqual(s["live_app"], "terminal")
        self.assertEqual(s["live_win"], "42")

    def test_mark_live_cwd_fallback_lights_newest(self):
        old = self._s("a", "/p", 100)
        new = self._s("b", "/p", 200)  # newer wins the un-resumed tab
        cc.TERMINAL.live_records = lambda: [{"winid": "7", "sid": None, "cwd": "/p"}]
        cc.TERMINAL.mark_live([old, new])
        self.assertFalse(old.get("live", False))
        self.assertTrue(new["live"])
        self.assertEqual(new["live_win"], "7")

    def test_mark_live_no_records_marks_nothing(self):
        s = self._s("sid-1", "/p", 10)
        cc.TERMINAL.live_records = lambda: []
        cc.TERMINAL.mark_live([s])
        self.assertFalse(s.get("live", False))

    # ── actions: jump vs revive ──
    def test_act_open_jumps_to_live_window(self):
        s = {"id": "x", "live_win": "99", "live_app": "terminal", "title": "t"}
        cc.TERMINAL.act_open(s, "/p", "x", "name", "window")
        self.assertIn("window id 99", self.scripts[-1])
        self.assertNotIn("--resume", self.scripts[-1])

    def test_act_open_revives_when_not_live(self):
        s = {"id": "x", "title": "t"}  # no live_win
        cc.TERMINAL.act_open(s, "/p", "sid-9", "name", "window", skip_perms=True)
        script = self.scripts[-1]
        self.assertIn("do script", script)
        self.assertIn("--resume", script)
        self.assertIn("--dangerously-skip-permissions", script)

    def test_act_new_opens_window_with_prompt(self):
        cc.TERMINAL.act_new("window", "/p", False, "/insights")
        self.assertIn("/insights", self.scripts[-1])
        self.assertIn("do script", self.scripts[-1])


class TestOsascriptTimeout(unittest.TestCase):
    def test_timeout_returns_failed_not_hang(self):
        import time
        t0 = time.time()
        r = cc.run_osascript("delay 10", timeout=1)
        self.assertNotEqual(r.returncode, 0)
        self.assertLess(time.time() - t0, 3)  # killed, not waited out

    def test_tabs_empty_when_osascript_fails(self):
        saved = cc.run_osascript
        cc.run_osascript = lambda s, timeout=None: type("R", (), {"returncode": 1, "stdout": ""})()
        try:
            self.assertEqual(cc.TERMINAL._tabs(), [])
        finally:
            cc.run_osascript = saved


class TestTerminalTabCreate(unittest.TestCase):
    """Opt-in Terminal tab-create: System Events menu-click with window fallback +
    Accessibility prompt. All osascript/notify/Popen stubbed — nothing real opens."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = {k: getattr(cc, k) for k in ("run_osascript", "notify", "STATE_DIR")}
        self._popen, self._running = cc.subprocess.Popen, cc.TERMINAL.running
        cc.STATE_DIR = self.tmp
        cc.notify = lambda *_: None
        self.popen_calls = []
        cc.subprocess.Popen = lambda *a, **k: (self.popen_calls.append(a) or type("P", (), {})())

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(cc, k, v)
        cc.subprocess.Popen, cc.TERMINAL.running = self._popen, self._running
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _R(self, rc=0, out="", err=""):
        return type("R", (), {"returncode": rc, "stdout": out, "stderr": err})()

    def _record(self, fn):
        self.seen = []
        cc.run_osascript = lambda s, timeout=None: (self.seen.append(s) or fn(s))

    def test_accessibility_denied_detection(self):
        self.assertTrue(cc._accessibility_denied("System Events ... (1002)"))
        self.assertTrue(cc._accessibility_denied("not allowed assistive access"))
        self.assertFalse(cc._accessibility_denied("Terminal got an error: AppleEvent timed out (-1712)"))
        self.assertFalse(cc._accessibility_denied(""))

    def test_window_mode_never_uses_system_events(self):
        self._record(lambda s: self._R())
        cc.TERMINAL._run_new("CMD", "window")
        self.assertTrue(any("do script" in s for s in self.seen))
        self.assertFalse(any("System Events" in s for s in self.seen))

    def test_tab_falls_back_to_window_when_not_running(self):
        cc.TERMINAL.running = lambda: False
        self._record(lambda s: self._R())
        cc.TERMINAL._run_new("CMD", "tab")
        self.assertTrue(any("do script" in s and "System Events" not in s for s in self.seen))

    def test_tab_success_injects_into_new_tab(self):
        cc.TERMINAL.running = lambda: True
        counts = iter(["1", "2"])  # tab count before=1, after=2 → a tab was created
        def fn(s):
            if "count of tabs" in s: return self._R(out=next(counts))
            return self._R()  # System Events click + do-script both succeed
        self._record(fn)
        self.assertTrue(cc.TERMINAL._open_tab("CMD"))
        self.assertTrue(any('do script "CMD" in front window' in s for s in self.seen))

    def test_tab_denied_falls_back_and_prompts_once(self):
        cc.TERMINAL.running = lambda: True
        def fn(s):
            if "count of tabs" in s: return self._R(out="1")
            if "System Events" in s: return self._R(rc=1, err="error 1002 not allowed assistive")
            return self._R()
        self._record(fn)
        self.assertFalse(cc.TERMINAL._open_tab("CMD"))   # denied → fall back
        self.assertEqual(len(self.popen_calls), 1)       # opened Settings once
        cc.TERMINAL._open_tab("CMD")                      # second denial
        self.assertEqual(len(self.popen_calls), 1)       # marker guard → no repeat prompt

    def test_tab_noop_click_does_not_inject_into_existing_tab(self):
        cc.TERMINAL.running = lambda: True
        def fn(s):
            if "count of tabs" in s: return self._R(out="1")  # before == after == 1 → nothing created
            return self._R()                                  # click "succeeds" but made nothing
        self._record(fn)
        self.assertFalse(cc.TERMINAL._open_tab("CMD"))
        self.assertFalse(any("do script" in s and "in front window" in s for s in self.seen))


class TestSessionRestore(unittest.TestCase):
    """Snapshot the open window/tab set and restore it per app."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = {k: getattr(cc, k) for k in
            ("LAST_OPEN_FILE", "claude_procs", "discover", "mark_all_live", "notify", "load_prefs", "dir_missing")}
        self._iterm = (cc.ITERM.running, cc.ITERM.snapshot_windows, cc.ITERM.open_windows, cc.ITERM.restore_window)
        self._term = (cc.TERMINAL.running, cc.TERMINAL.snapshot_windows, cc.TERMINAL.open_windows, cc.TERMINAL.restore_window)
        cc.LAST_OPEN_FILE = os.path.join(self.tmp, "last-open.json")
        cc.notify = lambda *_: None

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(cc, k, v)
        cc.ITERM.running, cc.ITERM.snapshot_windows, cc.ITERM.open_windows, cc.ITERM.restore_window = self._iterm
        cc.TERMINAL.running, cc.TERMINAL.snapshot_windows, cc.TERMINAL.open_windows, cc.TERMINAL.restore_window = self._term
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_capture_groups_by_window_keeps_order(self):
        cc.ITERM.running, cc.TERMINAL.running = (lambda: True), (lambda: False)
        cc.ITERM.open_windows = lambda live: [{"bounds": [0, 0, 800, 600], "ids": ["A", "B"]}]
        cc.capture_open_set([{"id": "A", "cwd": "/a", "live": True, "live_app": "iterm"},
                             {"id": "B", "cwd": "/b", "live": True, "live_app": "iterm"}])
        win = cc.load_json(cc.LAST_OPEN_FILE, {})["windows"][0]
        self.assertEqual(win["app"], "iterm")
        self.assertEqual([t["id"] for t in win["tabs"]], ["A", "B"])     # order preserved
        self.assertEqual(win["tabs"][0]["cwd"], "/a")                    # cwd from the session list
        self.assertEqual(win["bounds"], [0, 0, 800, 600])

    def test_capture_falls_back_for_sessions_layout_cant_place(self):
        # identity is the live LIST: a live session the structural read doesn't place
        # must STILL be captured (fallback window) — no gaps vs the webview list.
        cc.ITERM.running, cc.TERMINAL.running = (lambda: True), (lambda: False)
        cc.ITERM.open_windows = lambda live: [{"bounds": [0, 0, 9, 9], "ids": ["A"]}]  # only A placed
        cc.capture_open_set([{"id": "A", "cwd": "/a", "live": True, "live_app": "iterm"},
                             {"id": "B", "cwd": "/b", "live": True, "live_app": "iterm"}])  # B unplaced
        ids = [t["id"] for w in cc.load_json(cc.LAST_OPEN_FILE, {})["windows"] for t in w["tabs"]]
        self.assertEqual(sorted(ids), ["A", "B"])   # B still captured via fallback

    def test_capture_noop_preserves_snapshot_when_nothing_live(self):
        cc.save_json(cc.LAST_OPEN_FILE, {"windows": [{"app": "iterm", "bounds": [], "tabs": [{"id": "A", "cwd": "/a"}]}]})
        cc.ITERM.open_windows = lambda live: (_ for _ in ()).throw(AssertionError("must not read when nothing live"))
        cc.capture_open_set([{"id": "X", "cwd": "/x", "live": False}])   # must not raise / not overwrite
        self.assertTrue(cc.load_json(cc.LAST_OPEN_FILE, {})["windows"])  # snapshot intact

    def test_iterm_open_windows_maps_by_title_incl_fresh(self):
        # the whole point: a session with no --resume id is still placed, by title
        cc.ITERM.snapshot_windows = lambda: [{"bounds": [1, 2, 3, 4], "keys": ["✳ alpha" + SEP + "~/a", "✳ beta" + SEP + "~/b"]}]
        live = [{"id": "fresh", "title": "alpha", "mtime": 1}, {"id": "res", "title": "beta", "mtime": 1}]
        wins = cc.ITERM.open_windows(live)
        self.assertEqual(wins[0]["ids"], ["fresh", "res"])
        self.assertEqual(wins[0]["bounds"], [1, 2, 3, 4])

    def test_terminal_open_windows_maps_by_tty(self):
        cc.claude_procs = lambda: {"/dev/t1": {"sid": "S1", "cwd": None}}
        cc.TERMINAL.snapshot_windows = lambda: [{"bounds": [], "keys": ["/dev/t1"]}]
        wins = cc.TERMINAL.open_windows([{"id": "S1", "cwd": "/p", "mtime": 1}])
        self.assertEqual(wins[0]["ids"], ["S1"])

    def test_restorable_skips_live_and_unknown(self):
        cc.save_json(cc.LAST_OPEN_FILE, {"windows": [{"app": "iterm", "bounds": [], "tabs": [
            {"id": "A", "cwd": "/a"}, {"id": "B", "cwd": "/b"}, {"id": "GONE", "cwd": "/g"}]}]})
        wins = cc.restorable_sessions(live_ids={"B"}, known_ids={"A", "B"})  # B live, GONE not on disk
        self.assertEqual([t["id"] for w in wins for t in w["tabs"]], ["A"])

    def test_restore_dispatches_per_app_skips_live_keeps_bounds(self):
        cc.save_json(cc.LAST_OPEN_FILE, {"windows": [
            {"app": "iterm", "bounds": [0, 0, 800, 600], "tabs": [{"id": "A", "cwd": "/a"}, {"id": "B", "cwd": "/b"}]},
            {"app": "terminal", "bounds": [5, 5, 9, 9], "tabs": [{"id": "C", "cwd": "/c"}]}]})
        cc.discover = lambda: ([{"id": "A", "cwd": "/a"}, {"id": "B", "cwd": "/b"}, {"id": "C", "cwd": "/c"}], True)
        cc.mark_all_live = lambda ss: [s.__setitem__("live", s["id"] == "B") for s in ss]  # B already open
        cc.dir_missing = lambda c: False
        cc.load_prefs = lambda: dict(cc.DEFAULT_PREFS)
        calls = []
        cc.ITERM.restore_window = lambda tabs, b: calls.append(("iterm", list(tabs), b))
        cc.TERMINAL.restore_window = lambda tabs, b: calls.append(("terminal", list(tabs), b))
        cc.do_restore()
        iterm = next(c for c in calls if c[0] == "iterm")
        self.assertTrue(any("--resume A" in cmd and "cd /a" in cmd for cmd in iterm[1]))
        self.assertFalse(any("B" in cmd for cmd in iterm[1]))           # live one skipped
        term = next(c for c in calls if c[0] == "terminal")
        self.assertEqual(term[2], [5, 5, 9, 9])                         # bounds carried through
        self.assertTrue(any("--resume C" in cmd for cmd in term[1]))


class TestBackendDispatch(unittest.TestCase):
    def setUp(self):
        self._prefs = cc.load_prefs

    def tearDown(self):
        cc.load_prefs = self._prefs

    def test_backend_for_new_defaults_to_iterm(self):
        cc.load_prefs = lambda: dict(cc.DEFAULT_PREFS)
        self.assertIs(cc.backend_for_new(), cc.ITERM)

    def test_backend_for_new_honours_terminal_pref(self):
        cc.load_prefs = lambda: {**cc.DEFAULT_PREFS, "terminal": "terminal"}
        self.assertIs(cc.backend_for_new(), cc.TERMINAL)

    def test_mark_all_live_clears_then_merges_both_apps(self):
        # iTerm lights 'a', Terminal lights 'b' — both end live, tagged by app.
        a = {"id": "a", "cwd": "/p", "mtime": 1, "live": True}  # stale flag must clear
        b = {"id": "b", "cwd": "/p", "mtime": 1}
        saved = (cc.ITERM.running, cc.ITERM.mark_live, cc.TERMINAL.running, cc.TERMINAL.mark_live)
        try:
            cc.ITERM.running = lambda: True
            cc.ITERM.mark_live = lambda ss: [s.__setitem__("live", True) or s.__setitem__("live_app", "iterm")
                                             for s in ss if s["id"] == "a"]
            cc.TERMINAL.running = lambda: True
            cc.TERMINAL.mark_live = lambda ss: [s.__setitem__("live", True) or s.__setitem__("live_app", "terminal")
                                                for s in ss if s["id"] == "b"]
            cc.mark_all_live([a, b])
        finally:
            cc.ITERM.running, cc.ITERM.mark_live, cc.TERMINAL.running, cc.TERMINAL.mark_live = saved
        self.assertEqual((a["live"], a["live_app"]), (True, "iterm"))
        self.assertEqual((b["live"], b["live_app"]), (True, "terminal"))


# ─────────────────────── workspace discovery ───────────────────────
class TestWorkspaceDiscovery(unittest.TestCase):
    """find_workspace_roots / cached_workspace_roots — all on a synthetic tree
    in a tempdir, so nothing real is read. A 'linked worktree' is a dir with a
    `.git` FILE; a 'regular repo' is a dir with a `.git` DIR."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())  # fn realpaths base too
        self._saved = (cc.WORKSPACES_CACHE, cc.PREFS_FILE)
        cc.WORKSPACES_CACHE = os.path.join(self.base, "workspaces.json")
        cc.PREFS_FILE = os.path.join(self.base, "prefs.json")

    def tearDown(self):
        cc.WORKSPACES_CACHE, cc.PREFS_FILE = self._saved
        shutil.rmtree(self.base, ignore_errors=True)

    def _worktree(self, rel):
        p = os.path.join(self.base, rel)
        os.makedirs(p)
        with open(os.path.join(p, ".git"), "w") as fh:
            fh.write("gitdir: /somewhere/.git/worktrees/x")

    def _repo(self, rel):
        os.makedirs(os.path.join(self.base, rel, ".git"))

    def _rel(self, roots):
        return sorted(r[len(self.base):] for r in roots)

    def test_detects_multi_worktree_dirs(self):
        self._worktree("ws1/repoA")
        self._worktree("ws1/repoB")
        self._worktree("group/ws2/x")
        self._worktree("group/ws2/y")
        self.assertEqual(self._rel(cc.find_workspace_roots(self.base)),
                         ["/group/ws2", "/ws1"])

    def test_ignores_plain_repos_and_pruned(self):
        self._repo("folderOfRepos/r1")       # regular repos (.git dir), NOT worktrees
        self._repo("folderOfRepos/r2")
        self._worktree("node_modules/wsX/a")  # inside a pruned dir → skipped
        self._worktree("node_modules/wsX/b")
        self.assertEqual(cc.find_workspace_roots(self.base), [])

    def test_single_worktree_lists_the_worktree(self):
        # a single-repo workspace still shows — as the worktree itself (gets the
        # worktree/branch icon), while a 2+ group shows as the container.
        self._worktree("solo/only")
        self._worktree("grp/a")
        self._worktree("grp/b")
        self.assertEqual(self._rel(cc.find_workspace_roots(self.base)),
                         ["/grp", "/solo/only"])

    def test_maxdepth_bounds_the_walk(self):
        self._worktree("a/b/c/deep/x")        # 'deep' sits ~4 levels down
        self._worktree("a/b/c/deep/y")
        self.assertEqual(cc.find_workspace_roots(self.base, maxdepth=2), [])
        self.assertEqual(self._rel(cc.find_workspace_roots(self.base, maxdepth=8)),
                         ["/a/b/c/deep"])

    def test_does_not_descend_into_worktrees(self):
        # A worktree that itself nests a child workspace: the walk must stop at
        # the worktree boundary and never surface the nested one.
        self._worktree("ws/a")
        self._worktree("ws/b")
        self._worktree("ws/a/nested/x")       # inside worktree 'a' → ignored
        self._worktree("ws/a/nested/y")
        self.assertEqual(self._rel(cc.find_workspace_roots(self.base)), ["/ws"])

    def test_cached_roots_drops_missing_and_honors_pref(self):
        self._worktree("ws/a")
        self._worktree("ws/b")
        roots = cc.find_workspace_roots(self.base)
        with open(cc.WORKSPACES_CACHE, "w") as fh:
            json.dump({"ts": 0, "roots": roots + [self.base + "/vanished"]}, fh)
        # default pref (scan_workspaces=True): existing roots only, missing dropped
        self.assertEqual(sorted(cc.cached_workspace_roots()), sorted(roots))
        # pref off → empty even with a populated cache
        with open(cc.PREFS_FILE, "w") as fh:
            json.dump({"scan_workspaces": False}, fh)
        self.assertEqual(cc.cached_workspace_roots(), [])

    def test_do_scan_workspaces_writes_cache(self):
        self._worktree("ws/a")
        self._worktree("ws/b")
        saved_root = cc.WORKSPACE_SCAN_ROOT
        cc.WORKSPACE_SCAN_ROOT = self.base    # scan our synthetic tree, not $HOME
        try:
            cc.do_scan_workspaces()
        finally:
            cc.WORKSPACE_SCAN_ROOT = saved_root
        with open(cc.WORKSPACES_CACHE) as fh:
            data = json.load(fh)
        self.assertEqual(self._rel(data["roots"]), ["/ws"])
        self.assertFalse(os.path.exists(cc.WORKSPACES_CACHE + ".lock"))  # lock released

    def _spy_popen(self):
        """Replace cc.subprocess.Popen with a call-counter (restored on cleanup).
        Returns a list whose length is the number of Popen calls — manual
        monkeypatch, matching this suite's no-mock convention."""
        calls = []
        saved = cc.subprocess.Popen
        cc.subprocess.Popen = lambda *a, **k: calls.append((a, k))
        self.addCleanup(lambda: setattr(cc.subprocess, "Popen", saved))
        return calls

    def test_ensure_scan_inline_when_cache_missing(self):
        # Missing cache (first run, or a writer just busted it): ensure_workspace_scan
        # must scan INLINE so the cache exists by the time this same render reads it —
        # not spawn a detached scan whose result only lands on the next refresh.
        self._worktree("ws/a")
        self._worktree("ws/b")
        self.assertFalse(os.path.exists(cc.WORKSPACES_CACHE))
        calls = self._spy_popen()   # if it goes background, the write defers past this call
        saved_root = cc.WORKSPACE_SCAN_ROOT
        cc.WORKSPACE_SCAN_ROOT = self.base
        try:
            cc.ensure_workspace_scan()
        finally:
            cc.WORKSPACE_SCAN_ROOT = saved_root
        self.assertEqual(calls, [])  # scanned inline, not detached
        with open(cc.WORKSPACES_CACHE) as fh:
            data = json.load(fh)
        self.assertEqual(self._rel(data["roots"]), ["/ws"])

    def test_ensure_scan_stale_present_runs_in_background(self):
        # Present-but-stale cache: refresh must NOT block the render — it spawns a
        # detached scan and returns immediately (the negative of the case above).
        with open(cc.WORKSPACES_CACHE, "w") as fh:
            json.dump({"ts": 0, "roots": []}, fh)        # ts=0 → far older than the TTL
        os.utime(cc.WORKSPACES_CACHE, (0, 0))            # mtime in 1970 → stale by the TTL
        calls = self._spy_popen()
        cc.ensure_workspace_scan()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
