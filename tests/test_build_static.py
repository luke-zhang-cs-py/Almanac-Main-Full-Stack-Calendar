"""tools/build_static.py, with the browser replaced and the Python left real.

The build runs every scenario through the real calendar_logic -- its real
SQL, against a real SQLite database, inside a real app context -- and then
through the JavaScript port in a browser, and refuses to publish if the two
disagree anywhere. tests/test_static_demo.py checks what the build wrote;
this checks the build itself.

The Python half runs for real here. The browser half does not: CI installs
no Playwright and no Chromium, and the suite should not need them. So the
`playwright` module is replaced by a stand-in whose page answers with the
Python's own results -- an agreeing port -- or with those results altered,
which is a port with a bug in it. That is enough to watch every decision
the build makes: agree and it writes, disagree and it stops, sabotage the
bundle and `--prove` has to notice. Whether the real slots.js agrees is the
question `python tools/build_static.py` answers with a real browser, and it
is not one these tests pretend to answer.

Every file the build writes goes under tmp_path; docs/app/ is only read.
"""

import copy
import io
import json
import os
import shutil
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_static as bs   # noqa: E402

PUBLISHED = os.path.join(ROOT, "docs", "app")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def cases():
    return bs.scenarios()


@pytest.fixture(scope="module")
def ours(cases):
    """The real Python's answers to every scenario, computed once."""
    import app as flask_app
    from core import database as db

    with flask_app.app.app_context():
        db.init_db()
    return bs.python_side(cases)


# ------------------------------------------------------- a stand-in browser


class Browser:
    """Playwright's sync API, as far as build_static uses it.

    `answer(html, payload)` decides what the page's evaluate() returns;
    `on_load` and `on_evaluate` are (event, argument) pairs fired at the
    page's listeners when content is set and when the check runs.
    """

    def __init__(self, answer):
        self.answer = answer
        self.on_load = []
        self.on_evaluate = []
        self.launched = []
        self.closed = 0
        self.pages = []

    # sync_playwright() -> context manager -> object with .chromium
    def __call__(self):
        return self

    def __enter__(self):
        return types.SimpleNamespace(chromium=self)

    def __exit__(self, *exc):
        return False

    def launch(self, **options):
        self.launched.append(options)
        return self

    def new_page(self):
        page = Page(self)
        self.pages.append(page)
        return page

    def close(self):
        self.closed += 1


class Page:
    def __init__(self, browser):
        self.browser = browser
        self.listeners = {}
        self.html = None

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def fire(self, events):
        for event, argument in events:
            for handler in self.listeners.get(event, []):
                handler(argument)

    def set_content(self, html):
        self.html = html
        self.fire(self.browser.on_load)

    def evaluate(self, script, payload):
        assert script == bs.SLOTS_JS
        self.fire(self.browser.on_evaluate)
        return self.browser.answer(self.html, payload)


def message(kind, text):
    return types.SimpleNamespace(type=kind, text=text)


@pytest.fixture
def chromium(monkeypatch):
    """Install a stand-in Playwright; returns a function that arms it."""
    def install(answer):
        fake = Browser(answer)
        package = types.ModuleType("playwright")
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = fake
        package.sync_api = sync_api
        monkeypatch.setitem(sys.modules, "playwright", package)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
        monkeypatch.setattr(bs, "CHROME", os.path.join(ROOT, "no-chrome-here"))
        return fake
    return install


def _refusals_as_the_port(value):
    """Python refuses a bad date with ValueError; slots.js throws DateError.
    The build accepts that pair as agreement, and the wording is not
    compared, so an agreeing port is the Python's answers with that name
    swapped."""
    if isinstance(value, dict):
        if "error" in value:
            return {"error": "DateError", "says": value["says"]}
        return {key: _refusals_as_the_port(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_refusals_as_the_port(item) for item in value]
    return value


def as_the_port(answers):
    return _refusals_as_the_port(copy.deepcopy(answers))


def broken(answers):
    """An agreeing port's answers with the first free slot anywhere moved by
    a minute, as a port that mis-tiled one window would produce."""
    wrong = as_the_port(answers)
    for case in wrong:
        for row in case["asks"]:
            if row["free"].get("ok"):
                row["free"]["ok"][0]["start"] = "09:01"
                return wrong
    raise AssertionError("no scenario has a free slot to break")


def agreeing(ours, source=None):
    """A port that agrees -- unless `source` is given and the page loaded
    something other than it, in which case it is a broken port."""
    def answer(html, payload):
        if source is not None and source not in html:
            return broken(ours)
        return as_the_port(ours)
    return answer


def pristine():
    return read(os.path.join(bs.SRC, "js", "slots.js"))


# --------------------------------------------------------------- scenarios


def test_every_scenario_has_a_unique_name_and_a_demo_to_open_on(cases):
    names = [case["name"] for case in cases]
    assert len(names) == len(set(names))
    assert any(case["demo"] for case in cases)


def test_a_scenario_opens_on_its_first_question_unless_told_otherwise():
    hours = bs.nine_to_five()
    assert bs.scenario("x", "", hours, asks=[bs.ask(bs.THU)])["date"] == bs.THU
    assert bs.scenario("x", "", hours)["date"] == bs.WED
    assert bs.scenario("x", "", hours, asks=[bs.ask(bs.THU)],
                       date=bs.FRI)["date"] == bs.FRI


def test_nine_to_five_is_monday_to_friday_only():
    days = [row[1] for row in bs.nine_to_five(provider=bs.OTHER, slot=45)]
    assert days == [1, 2, 3, 4, 5]
    assert bs.nine_to_five(provider=bs.OTHER, slot=45)[0] == (
        bs.OTHER, 1, "09:00", "17:00", 45)


# ------------------------------------------------------------ python side


def test_frozen_pins_now_and_always_puts_the_clock_back():
    from domain import calendar_logic

    real = calendar_logic.dt.datetime
    with pytest.raises(RuntimeError, match="the comparison blew up"):
        with bs.frozen(calendar_logic, "2026-09-16T10:30"):
            assert calendar_logic.dt.datetime.now() == real(2026, 9, 16, 10, 30)
            raise RuntimeError("the comparison blew up")
    assert calendar_logic.dt.datetime is real


def test_called_records_an_answer_or_the_refusal():
    assert bs.called(lambda: [1]) == {"ok": [1]}
    assert bs.called(lambda: int("x")) == {
        "error": "ValueError",
        "says": "invalid literal for int() with base 10: 'x'"}


def test_the_python_side_answers_every_question_in_every_scenario(cases, ours):
    assert len(ours) == len(cases)
    for case, answers in zip(cases, ours):
        assert len(answers["asks"]) == len(case["asks"])
        assert len(answers["probes"]) == len(case["probes"])
        for row in answers["asks"]:
            assert sorted(row["starts"]) == sorted(
                str(m) for m in case["durations"])


def test_the_python_side_gives_the_answers_the_engine_gives(cases, ours):
    """Spot checks on the first scenario, nine to five on a Wednesday at
    10:30: Sunday and Saturday have no hours, Tuesday is past, and Thursday
    is a full day of half-hour slots from nine."""
    first = dict(zip([q["date"] for q in cases[0]["asks"]], ours[0]["asks"]))
    assert first[bs.SUN]["free"] == {"ok": []}
    assert first[bs.SAT]["free"] == {"ok": []}
    assert first[bs.TUE]["free"] == {"ok": []}
    thursday = first[bs.THU]["free"]["ok"]
    assert thursday[0] == {"start": "09:00", "end": "09:30"}
    assert len(thursday) == 16
    assert first[bs.THU]["windows"] == {"ok": [["09:00", "17:00", 30]]}
    assert ours[0]["probes"][0] == {"ok": True}


def test_some_scenarios_are_refused_by_the_python(ours):
    """The dates that are not dates. If none were refused, the matrix would
    have lost the cases where both sides have to say no."""
    refused = [part for answers in ours for row in answers["asks"]
               for part in (row["free"],) if "error" in part]
    assert refused
    assert {part["error"] for part in refused} <= set(bs.PY_REFUSALS)


def test_the_real_scenarios_have_no_ties(cases, ours):
    assert bs.refuse_ties(cases, ours) is None


def test_two_slots_with_one_start_and_different_ends_stop_the_build():
    case = {"name": "Tied", "asks": [bs.ask(bs.THU), bs.ask(bs.FRI)]}
    answers = {"asks": [
        {"free": {"ok": [{"start": "09:00", "end": "10:00"},
                         {"start": "09:00", "end": "10:00"},
                         {"start": "09:00", "end": "09:30"}]}},
        {"free": {"error": "ValueError", "says": "no"}},
    ]}
    with pytest.raises(SystemExit) as stopped:
        bs.refuse_ties([case], [answers])
    assert "Tied / %s: 09:00 ends at both 10:00 and 09:30" % bs.THU in str(
        stopped.value)


# -------------------------------------------------------------- comparing


def test_differences_reports_each_place_with_its_path():
    found = bs.differences(
        {"a": [1, 2], "b": {"c": True}, "only_py": 1},
        {"a": [1, 3], "b": {"c": 1}, "only_js": 2})
    assert found == [
        ".a[1]: python 2, browser 3",
        ".b.c: python True, browser 1",
        ".only_js: only the browser has it (2)",
        ".only_py: only python has it (1)",
    ]


def test_differences_compares_lengths_and_numbers_across_json_types():
    assert bs.differences((1, 2), [1.0, 2.0]) == []
    (short,) = bs.differences([1, 2], [1])
    assert short.startswith(".: python has 2, browser has 1")
    assert bs.differences("x", "y") == [".: python 'x', browser 'y'"]


@pytest.mark.parametrize("mine, yours, says", [
    ({"error": "TypeError", "says": "bad"}, {"ok": 1},
     "python raised TypeError: bad, which is not a refusal -- it is a bug "
     "in calendar_logic"),
    ({"ok": 1}, {"error": "TypeError", "says": "x is undefined"},
     "the browser raised TypeError: x is undefined, which is not a refusal "
     "-- it is a bug in the port"),
    ({"error": "ValueError", "says": "bad date"}, {"ok": []},
     "python refused (ValueError: bad date), the browser returned []"),
    ({"ok": []}, {"error": "DateError", "says": "bad date"},
     "python returned [], the browser refused (DateError: bad date)"),
])
def test_an_outcome_is_wrong_when_only_one_side_refuses_or_either_crashes(
        mine, yours, says):
    (found,) = bs.outcome_difference("label", mine, yours)
    assert found == "label: " + says


def test_two_refusals_agree_whatever_their_wording():
    assert bs.outcome_difference(
        "x", {"error": "ValueError", "says": "day is out of range"},
        {"error": "DateError", "says": "not a date"}) == []
    assert bs.outcome_difference("x", {"ok": [1]}, {"ok": [2]}) == [
        "x[0]: python 1, browser 2"]


def test_compare_counts_every_answer_and_every_refusal(cases, ours):
    wrong, compared, refusals = bs.compare(cases, ours, as_the_port(ours))
    assert wrong == []
    expected = sum(3 * len(c["asks"]) + len(c["asks"]) * len(c["durations"])
                   + len(c["probes"]) for c in cases)
    assert compared == expected
    assert 0 < refusals < compared


def test_compare_reports_a_silent_browser_and_a_missing_answer(cases, ours):
    theirs = as_the_port(ours)
    theirs[0] = None
    del theirs[1]["asks"][0]["starts"]["60"]
    wrong, _compared, _refusals = bs.compare(cases, ours, theirs)
    assert wrong[0] == "%s: the browser answered nothing" % cases[0]["name"]
    assert any("slot_starts_for(60)" in line and "raised Missing" in line
               for line in wrong)


def test_report_is_silent_when_nothing_is_wrong():
    assert bs.report([]) is None


def test_report_stops_and_counts_one_difference():
    with pytest.raises(SystemExit) as stopped:
        bs.report(["a: python 1, browser 2"])
    assert "disagrees with domain/calendar_logic.py in 1 place." in str(
        stopped.value)
    assert "Nothing has been written" in str(stopped.value)


def test_report_shows_thirty_and_says_how_many_more():
    with pytest.raises(SystemExit) as stopped:
        bs.report(["line %d" % n for n in range(45)])
    text = str(stopped.value)
    assert "in 45 places" in text
    assert "line 29" in text and "line 30" not in text
    assert text.endswith("... and 15 more")


# ---------------------------------------------------------------- browser


def test_without_playwright_the_build_says_how_to_get_it(monkeypatch):
    """No --skip-checks: an unchecked port is the thing this prevents."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(SystemExit, match="pip install playwright"):
        with bs.browser(["var x = 1;"]):
            pass


def test_the_browser_loads_each_source_in_its_own_script(chromium):
    fake = chromium(lambda html, payload: [])
    with bs.browser(["var a = 1;", "var b = 2;"]) as (page, problems):
        assert "<script>\nvar a = 1;\n</script><script>\nvar b = 2;\n</script>" \
            in page.html
        assert problems == []
    assert fake.launched == [{}], "no system Chrome here, so Playwright's own"
    assert fake.closed == 1


def test_the_system_chrome_is_used_when_it_is_there(chromium, monkeypatch,
                                                    tmp_path):
    fake = chromium(lambda html, payload: [])
    chrome = tmp_path / "chrome.exe"
    chrome.write_bytes(b"")
    monkeypatch.setattr(bs, "CHROME", str(chrome))
    with bs.browser([]):
        pass
    assert fake.launched == [{"executable_path": str(chrome)}]


def test_a_bundle_that_throws_on_load_stops_the_build(chromium):
    fake = chromium(lambda html, payload: [])
    fake.on_load = [("pageerror", "SyntaxError: Unexpected token"),
                    ("console", message("log", "just chatter")),
                    ("console", message("error", "AlmanacSlots is not defined"))]
    with pytest.raises(SystemExit) as stopped:
        with bs.browser(["oops("]):
            pytest.fail("the body must not run on a page that did not load")
    text = str(stopped.value)
    assert "does not load" in text
    assert "SyntaxError: Unexpected token" in text
    assert "AlmanacSlots is not defined" in text
    assert "just chatter" not in text, "only console errors count"
    assert fake.closed == 1, "the browser is closed even when it refuses"


def test_run_checks_passes_a_port_that_agrees(chromium, cases, ours):
    chromium(agreeing(ours))
    wrong, compared, refusals = bs.run_checks(pristine(), cases, ours)
    assert wrong == []
    assert compared > refusals > 0


def test_run_checks_reports_errors_logged_while_checking(chromium, cases,
                                                         ours):
    fake = chromium(agreeing(ours))
    fake.on_evaluate = [("console", message("error", "slow script"))]
    wrong, _compared, _refusals = bs.run_checks(pristine(), cases, ours)
    assert wrong == ["the bundle's JavaScript logged errors while being "
                     "checked: slow script"]


def test_run_checks_hands_the_browser_only_what_it_needs(chromium, cases,
                                                         ours):
    sent = []

    def answer(html, payload):
        sent.append(payload)
        return as_the_port(ours)

    chromium(answer)
    bs.run_checks(pristine(), cases, ours)
    assert len(sent[0]) == len(cases)
    assert set(sent[0][0]) == {"name", "now", "data", "asks", "durations",
                               "probes"}


# ------------------------------------------------------------------ prove


def test_prove_requires_every_sabotage_to_be_caught(chromium, cases, ours,
                                                    capsys):
    source = pristine()
    fake = chromium(agreeing(ours, source=source))
    bs.prove(source, cases, ours)

    out = capsys.readouterr().out
    assert "all %d caught." % len(bs.SABOTAGE) in out
    for name, _old, _new, _what in bs.SABOTAGE:
        assert "caught   %-12s" % name in out
    assert len(fake.pages) == len(bs.SABOTAGE)
    assert all(source not in page.html for page in fake.pages), (
        "every check ran on a broken copy, never on the original")


def test_a_sabotage_that_survives_is_a_build_failure(chromium, cases, ours,
                                                     capsys):
    """The `format` sabotage made harmless: the stand-in agrees whenever the
    hour stops being zero-padded, which is what a matrix with no single-digit
    hour in it would do."""
    source = pristine()
    (made_harmless,) = [new for name, _old, new, _what in bs.SABOTAGE
                        if name == "format"]

    def answer(html, payload):
        if made_harmless in html:
            return as_the_port(ours)
        return broken(ours)

    chromium(answer)
    with pytest.raises(SystemExit) as stopped:
        bs.prove(source, cases, ours)
    assert "1 sabotage survived every check" in str(stopped.value)
    assert "format -- stop zero-padding the hour" in str(stopped.value)
    assert "SURVIVED format" in capsys.readouterr().out


def test_a_sabotage_with_nothing_to_break_stops_the_proof(cases, ours):
    """A sabotage whose anchor has moved would 'survive' by not running."""
    with pytest.raises(SystemExit, match="'past-date' has nothing to break"):
        bs.prove("/* the port moved */", cases, ours)


# ----------------------------------------------------------------- bundle


def test_the_scenarios_script_holds_only_the_demo_presets(cases):
    text = bs.scenarios_js(cases)
    assert "a fetch() of a relative" in text
    body = text.split("var AlmanacScenarios = ", 1)[1].rstrip().rstrip(";")
    data = json.loads(body)
    assert data["providerId"] == bs.SUBJECT
    assert [p["name"] for p in data["presets"]] == [
        c["name"] for c in cases if c["demo"]]


def test_a_bundle_with_no_demo_scenario_is_refused(cases):
    with pytest.raises(SystemExit, match="no scenario is marked demo=True"):
        bs.scenarios_js([dict(case, demo=False) for case in cases])


def test_collect_is_what_is_published(cases):
    """The same six files test_static_demo.py checks, byte for byte."""
    written = bs.collect(cases)
    assert sorted(written) == ["css/demo.css", "css/style.css", "index.html",
                               "js/demo.js", "js/scenarios.js", "js/slots.js"]
    for name, body in written.items():
        assert read(os.path.join(PUBLISHED, name)) == body, name
    assert written["css/style.css"].startswith(
        bs.BANNER % "static/css/style.css")


def test_a_page_that_no_longer_links_home_is_refused(cases, tmp_path,
                                                     monkeypatch):
    src = tmp_path / "static_src"
    shutil.copytree(bs.SRC, str(src))
    index = src / "index.html"
    index.write_text(read(str(index)).replace(bs.REPO, "https://example.com"),
                     encoding="utf-8")
    monkeypatch.setattr(bs, "SRC", str(src))
    with pytest.raises(SystemExit, match="no longer links back"):
        bs.collect(cases)


def test_prune_removes_what_the_build_no_longer_writes(tmp_path, monkeypatch,
                                                       capsys):
    out = tmp_path / "app"
    (out / "js").mkdir(parents=True)
    (out / "js" / "slots.js").write_text("kept", encoding="utf-8")
    (out / "js" / "old.js").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(bs, "OUT", str(out))

    bs.prune({"js/slots.js"})

    assert (out / "js" / "slots.js").exists()
    assert not (out / "js" / "old.js").exists()
    assert "removed stale" in capsys.readouterr().out


def test_prune_with_nothing_built_yet_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "OUT", str(tmp_path / "never-built"))
    assert bs.prune(set()) is None
    assert not (tmp_path / "never-built").exists()


def test_write_creates_the_folders_it_needs(tmp_path):
    path = tmp_path / "a" / "b" / "c.txt"
    bs.write(str(path), "line\n")
    assert path.read_bytes() == b"line\n", "LF on every platform"


# ------------------------------------------------------------------- main


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """main()'s environment changes undone afterwards, its scratch database
    folder somewhere visible, and docs/app replaced by a folder of our own."""
    for name, value in (("DATABASE_URL", os.environ["DATABASE_URL"]),
                        ("SECRET_KEY", os.environ["SECRET_KEY"]),
                        ("SMTP_HOST", ""), ("MAIL_ENABLED", "1"),
                        ("REMINDERS_ENABLED", "1")):
        monkeypatch.setenv(name, value)
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(bs.tempfile, "mkdtemp",
                        lambda prefix: (scratch.mkdir(), str(scratch))[1])
    out = tmp_path / "app"
    out.mkdir()
    (out / "leftover.js").write_text("from an older build", encoding="utf-8")
    monkeypatch.setattr(bs, "OUT", str(out))
    return {"scratch": scratch, "out": out}


def test_main_writes_the_published_bundle_when_the_port_agrees(
        isolated, chromium, ours, capsys):
    chromium(agreeing(ours))
    bs.main([])

    out = isolated["out"]
    for name in ("index.html", "js/slots.js", "js/demo.js", "js/scenarios.js",
                 "css/style.css", "css/demo.css"):
        assert read(str(out / name)) == read(os.path.join(PUBLISHED, name)), (
            "a fresh build should reproduce docs/app/%s exactly" % name)
    assert not (out / "leftover.js").exists()

    said = capsys.readouterr().out
    assert "calendar_logic.py == slots.js" in said
    assert "wrote 6 files to docs/app" in said
    assert "removed stale leftover.js" in said

    assert not isolated["scratch"].exists(), "its database folder is removed"
    assert os.environ["DATABASE_URL"].endswith("build.db")
    assert os.environ["MAIL_ENABLED"] == "1", "setdefault, not overwrite"


def test_main_writes_nothing_when_the_port_disagrees(isolated, chromium,
                                                     ours):
    chromium(lambda html, payload: broken(ours))
    with pytest.raises(SystemExit, match="Nothing has been written"):
        bs.main([])
    assert sorted(os.listdir(str(isolated["out"]))) == ["leftover.js"]
    assert not isolated["scratch"].exists(), "cleaned up on failure too"


def test_main_reads_prove_from_the_command_line_and_writes_nothing(
        isolated, chromium, ours, monkeypatch, capsys):
    chromium(agreeing(ours, source=pristine()))
    monkeypatch.setattr(sys, "argv", ["build_static.py", "--prove"])
    bs.main()

    assert "all %d caught." % len(bs.SABOTAGE) in capsys.readouterr().out
    assert sorted(os.listdir(str(isolated["out"]))) == ["leftover.js"]
