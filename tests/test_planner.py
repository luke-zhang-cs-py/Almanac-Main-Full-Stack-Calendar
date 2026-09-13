"""The standalone planner: one file, no network, and nobody's timetable in it.

The planner is a single HTML file you double-click. It was written that way
and for a long time it was *only* that way -- 70KB with one person's term,
diary and to-do list declared inline, which is why it had never been in a
repository. A timetable says where somebody is at every hour of every
weekday; that is not a thing to publish to make a build reproducible.

So the engine lives in standalone/planner/ and the seed does not. The
builder inlines whichever seed it is pointed at, and defaults to an invented
sample. Three things have to stay true, and the tests below are in that
order:

  * **No seed in the sources.** The most consequential test here, and the
    one that cannot name what it is looking for -- writing the real module
    codes into an assertion would put them in the repository, which is the
    thing being prevented. So it looks for the *shape* of personal data
    rather than the content: addresses, postcodes, phone numbers, emails.

  * **Nothing points outside the built file.** A stray src="app.js" keeps
    working while the file sits beside its sources and breaks the moment it
    is moved, which is the one situation it exists for.

  * **It runs.** Checked by opening it from disk in a real browser, because
    file:// is where it is used and where fetch does not work.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_planner as builder   # noqa: E402

SRC = os.path.join(ROOT, "standalone", "planner")
SOURCES = ("index.html", "style.css", "app.js", "data.sample.js")

BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def browser():
    for path in BROWSERS:
        if os.path.isfile(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def source(name):
    with io.open(os.path.join(SRC, name), encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def built():
    return builder.build()


# ------------------------------------------------- nobody's timetable in it


def test_the_only_seed_in_the_repository_is_the_sample():
    """A real seed appearing beside the sample is the accident this is here
    to catch -- `data.js` is what the built file's script tag is named, so
    it is the name somebody would reach for."""
    present = sorted(f for f in os.listdir(SRC) if not f.startswith("."))
    assert present == sorted(SOURCES), (
        f"unexpected files in standalone/planner: {present}")


def test_the_sample_says_it_is_invented():
    """Somebody opening it should not have to work out whether these are
    real classes before they edit them."""
    text = source("data.sample.js")
    assert "invented" in text.lower()
    assert "--data" in text, "it should say how to point at your own"


# The shapes personal data takes, rather than the data itself: naming the
# real module codes or address here would put them in the repository, which
# is the thing being prevented.
PERSONAL_SHAPES = {
    "a UK postcode": r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b",
    "an email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "a UK phone number": r"\b(?:\+44|07)\d[\d ]{7,}\b",
    "a street address": r"\b\d+[a-z]?\s+[A-Z][a-z]+\s+"
                        r"(?:Road|Street|Avenue|Lane|Drive|Court|Way)\b",
    "a flight number": r"\b[A-Z]{2}\d{3,4}\b",
}


@pytest.mark.parametrize("what, pattern", sorted(PERSONAL_SHAPES.items()))
def test_no_source_file_carries_personal_data(what, pattern):
    found = []
    for name in SOURCES:
        for hit in re.finditer(pattern, source(name)):
            found.append(f"{name}: {hit.group(0)!r}")
    assert not found, f"{what} in the committed sources: {found}"


def test_that_check_would_actually_catch_something():
    """The negative control. A pattern that matches nothing passes whatever
    it is pointed at, and these are narrow enough to be worth proving
    rather than assuming.

    Every value below is deliberately fictional: ZZ99 3WZ is the dummy
    postcode, 07700 900xxx is the range Ofcom reserves for drama, and
    example.com is reserved by the RFC. A control that used a real address
    to prove it catches real addresses would put one in the repository,
    which is the thing this file exists to prevent -- and the first draft of
    this test did exactly that.
    """
    sample = ("Flight XX999 from ZZ99 3WZ, 1 Nowhere Lane, "
              "call 07700 900123 or someone@example.com")
    missed = [what for what, pattern in PERSONAL_SHAPES.items()
              if not re.search(pattern, sample)]
    assert not missed, f"these patterns match nothing: {missed}"


def test_the_engine_reads_its_seed_rather_than_holding_one():
    """Every setting the planner needs comes through the seed lookup, so a
    value hard-coded back into app.js would be one the seed file cannot
    change and nobody would notice until they tried."""
    app = source("app.js")
    assert "PLANNER_DATA" in app, "the engine does not read a seed at all"
    for name in ("CD_ANCHOR", "FIXTURES", "WEEK_A", "DIARY", "SEED_TODOS"):
        assert re.search(r'\b%s\s*=\s*seed\(' % name, app), (
            f"{name} is not read from the seed")


# ----------------------------------------------------------- the built file


def test_nothing_points_outside_the_built_file(built):
    loose = builder.loose_references(built)
    assert not loose, f"these still point outside the file: {loose}"


def test_the_builder_refuses_to_write_one_that_does(built):
    """The negative control for the check above."""
    broken = built.replace("</body>", '<img src="chart.png"></body>', 1)
    assert builder.loose_references(broken) == ["chart.png"], (
        "the check guarding this would not notice a stray reference")


def test_everything_is_inlined(built):
    assert "<style>" in built and "</style>" in built
    assert "window.PLANNER_DATA" in built, "the seed is not inlined"
    assert 'src="app.js"' not in built and 'src="data.js"' not in built
    # Something from each source, so a half-built file fails here.
    assert "renderCalendar" in built, "the engine is not inlined"


def test_it_cannot_reach_the_network(built):
    policy = re.search(r'Content-Security-Policy" content="([^"]*)"', built)
    assert policy, "the built file has no content policy"
    assert "default-src 'none'" in policy.group(1)
    assert "connect-src" not in policy.group(1), (
        "a file that needs no network should not be allowed one")


def test_the_banner_names_the_seed_it_used(built):
    """Building the sample by accident and not noticing is the one
    confusing failure here, so the file says which seed it holds."""
    assert "data.sample.js" in built
    assert "invented" in built


def test_building_with_a_missing_seed_is_refused(tmp_path):
    with pytest.raises(Exception):
        builder.build(str(tmp_path / "nope.js"))


# --------------------------------------------------------------- it runs


@pytest.mark.skipif(not browser(), reason="no browser to open the file in")
def test_it_seeds_and_renders_from_disk(built):
    """Opened from disk, where it is actually used. The seed runs once into
    localStorage, so what it wrote there is the whole output of the data
    path and is worth reading back rather than trusting."""
    folder = tempfile.mkdtemp()
    try:
        probe = (
            "<script>window.addEventListener('load', function () {"
            "window.setTimeout(function () {"
            "  var store = {};"
            "  for (var i = 0; i < localStorage.length; i++) {"
            "    var k = localStorage.key(i);"
            "    store[k] = localStorage.getItem(k).length;"
            "  }"
            "  var events = JSON.parse("
            "    localStorage.getItem('sept-planner.events.v1') || '{}');"
            "  var out = document.createElement('pre');"
            "  out.id = 'PROBE';"
            "  out.textContent = 'PROBE ' + JSON.stringify({"
            "    origin: location.protocol,"
            "    keys: Object.keys(store).sort(),"
            "    days: Object.keys(events).length,"
            "    cells: document.querySelectorAll('.cell,.day,td').length,"
            "    title: document.title,"
            "    errors: window.__errs || []"
            "  });"
            "  document.body.insertBefore(out, document.body.firstChild);"
            "}, 700); });"
            "window.__errs = [];"
            "window.addEventListener('error', function (e) {"
            "  window.__errs.push(String(e.message)); });</script>"
        )
        path = os.path.join(folder, "planner.html")
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(built.replace("</body>", probe + "</body>", 1))

        done = subprocess.run(
            [browser(), "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-first-run", "--no-default-browser-check",
             "--user-data-dir=" + os.path.join(folder, "profile"),
             "--virtual-time-budget=20000", "--dump-dom",
             "file:///" + path.replace("\\", "/")],
            capture_output=True, timeout=300)
        dom = done.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    found = re.search(r"PROBE (\{.*?\})</pre>", dom, re.S)
    assert found, f"the planner did not run from disk; {len(dom)} bytes of DOM"

    import html as htmllib
    got = json.loads(htmllib.unescape(found.group(1)))

    assert got["origin"] == "file:", "this did not test a file:// origin"
    assert not got["errors"], f"it threw on load: {got['errors']}"
    assert got["days"] > 0, "the seed put no events in the calendar"
    assert got["cells"] > 0, "the calendar rendered no cells"
    assert any(k.startswith("sept-planner.events") for k in got["keys"]), (
        f"nothing was seeded; keys were {got['keys']}")
