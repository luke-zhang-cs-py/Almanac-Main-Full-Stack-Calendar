"""tools/build_planner.py as a command, and the source shapes it tolerates.

tests/test_planner.py checks what the builder produces from the real
sources. This file checks the command around it: which seeds it will and
will not build, where it writes, what it says about the seed it used -- and
the two fallbacks in build() for a source page that carries no policy and no
doctype, which the real index.html never exercises. Every file it writes
goes under tmp_path; docs/planner.html is not rebuilt from here.
"""

import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_planner as builder   # noqa: E402


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------------------ the command


def test_main_writes_the_sample_build_and_warns_that_it_is_invented(
        tmp_path, capsys):
    out = tmp_path / "planner.html"
    builder.main(["--out", str(out)])

    assert read(str(out)) == builder.build()
    said = capsys.readouterr().out
    assert str(out) in said
    assert "seed data.sample.js, no external references" in said
    assert "NOTE: that is the invented sample seed" in said


def test_main_builds_the_blank_calendar_without_the_sample_warning(
        tmp_path, capsys):
    out = tmp_path / "blank.html"
    builder.main(["--blank", "--out", str(out)])

    assert read(str(out)) == builder.build(builder.BLANK)
    said = capsys.readouterr().out
    assert "seed data.blank.js" in said
    assert "NOTE" not in said


def test_main_builds_your_own_seed(tmp_path, capsys):
    seed = tmp_path / "mine.js"
    seed.write_text("window.PLANNER_SEED = {};\n", encoding="utf-8")
    out = tmp_path / "mine.html"
    builder.main(["--data", str(seed), "--out", str(out)])

    page = read(str(out))
    assert "window.PLANNER_SEED = {};" in page
    assert "Seed: mine.js\n" in page, "the banner names the seed, unlabelled"
    assert "NOTE" not in capsys.readouterr().out


def test_main_refuses_two_seeds_at_once(tmp_path):
    with pytest.raises(SystemExit, match="pick one"):
        builder.main(["--blank", "--data", "x.js",
                      "--out", str(tmp_path / "x.html")])


def test_main_refuses_a_seed_that_is_not_there(tmp_path):
    out = tmp_path / "x.html"
    with pytest.raises(SystemExit, match="no such seed"):
        builder.main(["--data", str(tmp_path / "nope.js"), "--out", str(out)])
    assert not out.exists()


def test_main_refuses_to_write_a_file_that_points_outside_itself(
        tmp_path, monkeypatch):
    """The one situation a standalone file exists for is being moved, and a
    stray relative reference is what breaks when it is."""
    monkeypatch.setattr(builder, "build",
                        lambda data_path: '<img src="chart.png">')
    out = tmp_path / "x.html"
    with pytest.raises(SystemExit, match="chart.png"):
        builder.main(["--out", str(out)])
    assert not out.exists(), "nothing is written when it refuses"


# ------------------------------------------- a source page with less in it


@pytest.fixture
def bare_sources(tmp_path, monkeypatch):
    """A planner source folder whose index.html has no CSP and no doctype."""
    for name in ("style.css", "app.js"):
        (tmp_path / name).write_text("/* %s */\n" % name, encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "<html><head><title>Planner</title>\n"
        '<link rel="stylesheet" href="style.css">\n</head><body>\n'
        '<script src="data.js"></script>\n<script src="app.js"></script>\n'
        "</body></html>\n", encoding="utf-8")
    seed = tmp_path / "seed.js"
    seed.write_text("var SEED = 1;\n", encoding="utf-8")
    monkeypatch.setattr(builder, "SRC", str(tmp_path))
    return str(seed)


def test_a_page_with_no_policy_is_given_one(bare_sources):
    page = builder.build(bare_sources)
    assert ('</title>\n<meta http-equiv="Content-Security-Policy" '
            'content="%s">' % builder.POLICY) in page
    assert page.count('<meta http-equiv="Content-Security-Policy"') == 1


def test_a_page_with_no_doctype_still_gets_the_banner_first(bare_sources):
    page = builder.build(bare_sources)
    assert page.startswith("<!--\n  The planner, as one file.")
    assert "Seed: seed.js\n" in page
    assert "<style>\n/* style.css */\n</style>" in page
    assert "<script>\nvar SEED = 1;\n</script>" in page
    assert builder.loose_references(page) == []



def test_an_uppercase_doctype_still_gets_the_banner(bare_sources):
    """<!DOCTYPE html> is the same declaration as <!doctype html>; the banner
    goes straight after it, as it does for the lower-case spelling."""
    index = os.path.join(builder.SRC, "index.html")
    text = "<!DOCTYPE html>\n" + read(index)
    with io.open(index, "w", encoding="utf-8") as handle:
        handle.write(text)

    page = builder.build(bare_sources)
    assert page.startswith("<!DOCTYPE html>\n<!--\n  The planner, as one file.")
    assert page.count("The planner, as one file.") == 1

def test_a_page_with_its_own_policy_has_it_replaced(bare_sources):
    """A source page that allows the network gets the no-network policy
    instead, in place, rather than a second policy beside the first."""
    index = os.path.join(builder.SRC, "index.html")
    text = read(index).replace(
        "</title>", '</title>\n<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'self'; connect-src *\">")
    with io.open(index, "w", encoding="utf-8") as handle:
        handle.write(text)

    page = builder.build(bare_sources)
    assert "connect-src *" not in page
    assert ('<meta http-equiv="Content-Security-Policy" content="%s">'
            % builder.POLICY) in page
    assert page.count('<meta http-equiv="Content-Security-Policy"') == 1
