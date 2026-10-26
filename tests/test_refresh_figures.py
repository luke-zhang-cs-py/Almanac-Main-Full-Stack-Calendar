"""tools/refresh_figures.py, pointed at a miniature repository under tmp_path.

The tool rewrites docs/index.html and the README's one sentence of figures
from a real coverage run. Running it for real from inside the suite would
run the suite from inside the suite, and would rewrite tracked files -- so
here the two subprocesses it starts are replaced by stand-ins that answer
the way pytest does, and ROOT, PAGE and README point at a page, a README and
a tests/ folder built for each test.

What is checked is what makes the tool worth running: it fixes a wrong
figure and reports it, it refuses to invent a description for a module or
test file nobody has described, it flags a row that no longer measures
anything, and a second run over its own output changes nothing.
"""

import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import refresh_figures as rf   # noqa: E402

RUNNING = "%d.%d" % sys.version_info[:2]

PAGE = """<script>
var MODULES = [
  { name: 'pkg/big.py', lines: 1, stmts: 1, missed: 9, does: 'the big one' },
  { name: 'gone.py', lines: 5, stmts: 2, missed: 0, does: 'deleted since' }
];

var TESTS = [
  { file: 'test_big.py', n: 1, of: 'the big tests' },
  { file: 'test_gone.py', n: 4, of: 'tests that went' }
];

var TEST_LINES = 1;
var MEASURED_WITH = 'Python 2.7';
</script>
"""

README = "# Mini\n\n1 tests, 50% of 3 statements. And then prose.\n"


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository with two modules, a test folder and a page about them."""
    root = str(tmp_path)
    put(os.path.join(root, "pkg", "big.py"), "a = 1\nb = 2\nc = 3\n")
    put(os.path.join(root, "small.py"), "x = 1\n")
    put(os.path.join(root, "tests", "test_big.py"), "1\n2\n3\n4\n")
    put(os.path.join(root, "tests", "notes.txt"), "not python\n")
    put(os.path.join(root, "tests", "__pycache__", "stale.py"), "9\n" * 50)
    put(os.path.join(root, "docs", "index.html"), PAGE)
    put(os.path.join(root, "README.md"), README)
    monkeypatch.setattr(rf, "ROOT", root)
    monkeypatch.setattr(rf, "PAGE", os.path.join(root, "docs", "index.html"))
    monkeypatch.setattr(rf, "README", os.path.join(root, "README.md"))
    return root


MEASURED = {
    "pkg/big.py": {"lines": 3, "stmts": 3, "missed": 0},
    "small.py": {"lines": 1, "stmts": 1, "missed": 0},
}
COUNTS = {"test_big.py": 12, "test_small.py": 3}


def described(page):
    """The page with rows for the module and test file it was missing."""
    page = page.replace(
        "  { name: 'gone.py',",
        "  { name: 'small.py', lines: 0, stmts: 0, missed: 0, "
        "does: 'the small one' },\n  { name: 'gone.py',")
    return page.replace(
        "  { file: 'test_gone.py',",
        "  { file: 'test_small.py', n: 0, of: 'the small tests' },\n"
        "  { file: 'test_gone.py',")


# ------------------------------------------------- measuring, with no run


def test_measure_reads_the_json_report_of_a_coverage_run(repo, monkeypatch):
    seen = []

    def run(command, cwd, capture_output, text, timeout):
        seen.append(command)
        report = [arg for arg in command
                  if arg.startswith("--cov-report=json:")][0]
        put(report.split(":", 1)[1], json.dumps({"files": {
            os.path.join("pkg", "big.py"): {"summary": {
                "num_statements": 3, "missing_lines": 1}},
        }}))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rf.subprocess, "run", run)
    assert rf.measure() == {"pkg/big.py": {"lines": 3, "stmts": 3,
                                           "missed": 1}}
    assert seen[0][:5] == [sys.executable, "-m", "pytest", "-q", "--cov"]
    path = seen[0][5].split(":", 1)[1]
    assert not os.path.exists(path), "the temporary report is cleaned up"


def collected(stdout):
    def run(command, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(command, 0, stdout, "")
    return run


def test_collect_counts_tests_per_file(monkeypatch):
    monkeypatch.setattr(rf.subprocess, "run", collected(
        "tests/test_big.py::test_one\n"
        "tests/test_big.py::test_two[a]\n"
        "tests/test_small.py::test_three\n"
        "\n3 tests collected in 0.1s\n"))
    assert rf.collect() == {"test_big.py": 2, "test_small.py": 1}


def test_collect_refuses_a_run_that_collected_nothing(monkeypatch):
    monkeypatch.setattr(rf.subprocess, "run",
                        collected("ERROR: no tests ran\n"))
    with pytest.raises(SystemExit, match="collection produced nothing"):
        rf.collect()


# ------------------------------------------------------ rewriting the page


def test_a_module_with_no_description_stops_the_rewrite(repo):
    with pytest.raises(SystemExit, match="no description on the page for "
                                         "small.py"):
        rf.fix_modules(PAGE, MEASURED, [])


def test_a_test_file_with_no_description_stops_the_rewrite(repo):
    with pytest.raises(SystemExit, match="no description on the page for "
                                         "test_small.py"):
        rf.fix_tests(PAGE, COUNTS, [])


def test_the_modules_are_rewritten_largest_first_and_aligned(repo):
    changes = []
    page = rf.fix_modules(described(PAGE), MEASURED, changes)

    assert ("  { name: 'pkg/big.py', lines:   3, stmts:   3, missed:  0, "
            "does: 'the big one' },\n"
            "  { name: 'small.py',   lines:   1, stmts:   1, missed:  0, "
            "does: 'the small one' }\n];") in page
    assert "gone.py', lines" not in page
    assert any(line.startswith("pkg/big.py") and "(1, 1, 9) -> (3, 3, 0)"
               in line for line in changes)
    assert any("gone.py is on the page but coverage no longer reports it"
               in line for line in changes)


def test_an_unchanged_module_row_is_not_reported(repo):
    page = rf.fix_modules(described(PAGE), MEASURED, [])
    changes = []
    assert rf.fix_modules(page, MEASURED, changes) == page
    assert changes == []


def test_the_tests_are_rewritten_most_first_and_aligned(repo):
    changes = []
    page = rf.fix_tests(described(PAGE), COUNTS, changes)

    assert ("  { file: 'test_big.py',   n: 12, of: 'the big tests' },\n"
            "  { file: 'test_small.py', n:  3, of: 'the small tests' }\n];"
            ) in page
    assert any("test_gone.py is on the page but collects nothing" in line
               for line in changes)
    again = []
    assert rf.fix_tests(page, COUNTS, again) == page
    assert again == []


def test_the_interpreter_is_recorded_and_a_change_reported(repo):
    changes = []
    page = rf.fix_measured_with(PAGE, changes)
    assert "var MEASURED_WITH = 'Python %s';" % RUNNING in page
    assert changes == ["MEASURED_WITH Python 2.7 -> %s" % RUNNING]

    unchanged = []
    assert rf.fix_measured_with(page, unchanged) == page
    assert unchanged == []


def test_a_page_with_no_interpreter_line_is_refused(repo):
    with pytest.raises(SystemExit, match="no MEASURED_WITH line"):
        rf.fix_measured_with("var MODULES = [\n];", [])


def test_test_lines_count_python_files_only_and_skip_caches(repo):
    """Four lines in the one test file: the .txt and the cached .py are not
    part of the suite."""
    changes = []
    page = rf.fix_test_lines(PAGE, changes)
    assert "var TEST_LINES = 4;" in page
    assert changes == ["TEST_LINES 1 -> 4"]

    same = []
    assert rf.fix_test_lines(page, same) == page
    assert same == []

    absent = []
    assert rf.fix_test_lines("no such line", absent) == "no such line"
    assert absent == []


# --------------------------------------------------------------- the README


def test_the_readme_sentence_is_rewritten(repo):
    changes = []
    rf.fix_readme(MEASURED, COUNTS, changes)
    assert read(rf.README) == (
        "# Mini\n\n15 tests, 100% of 4 statements. And then prose.\n")
    assert changes == ["README  1 tests, 50% of 3 statements -> "
                       "15 tests, 100% of 4 statements"]


def test_a_readme_that_is_already_right_is_left_alone(repo):
    put(rf.README, "15 tests, 100% of 4 statements.\n")
    changes = []
    rf.fix_readme(MEASURED, COUNTS, changes)
    assert changes == []


def test_a_readme_that_states_no_figures_is_left_alone(repo):
    put(rf.README, "# Mini\n\nNo figures here.\n")
    rf.fix_readme(MEASURED, COUNTS, [])
    assert read(rf.README) == "# Mini\n\nNo figures here.\n"


def test_no_readme_at_all_is_not_an_error(repo):
    os.remove(rf.README)
    rf.fix_readme(MEASURED, COUNTS, [])
    assert not os.path.exists(rf.README)


# --------------------------------------------------------------- main


@pytest.fixture
def measured(repo, monkeypatch):
    monkeypatch.setattr(rf, "measure", lambda: dict(MEASURED))
    monkeypatch.setattr(rf, "collect", lambda: dict(COUNTS))
    put(rf.PAGE, described(PAGE))


def test_main_rewrites_the_page_and_the_readme_and_says_what_changed(
        measured, capsys):
    rf.main()

    page = read(rf.PAGE)
    assert "var TEST_LINES = 4;" in page
    assert "missed:  0, does: 'the big one'" in page
    assert "15 tests, 100% of 4 statements" in read(rf.README)
    out = capsys.readouterr().out
    assert "TEST_LINES 1 -> 4" in out
    assert out.rstrip().endswith("15 tests, 4 statements, 100% covered")


def test_main_on_a_page_that_is_already_right_prints_only_the_totals(
        measured, capsys, monkeypatch):
    rf.main()
    capsys.readouterr()
    written = []
    monkeypatch.setattr(rf, "write", lambda path, text: written.append(path))

    rf.main()

    assert written == [], "an accurate page and README are not rewritten"
    assert capsys.readouterr().out == (
        "  15 tests, 4 statements, 100% covered\n")


def test_main_refuses_to_write_when_its_own_output_is_not_stable(
        measured, monkeypatch):
    """A tool that reformats the file on every run leaves a diff behind every
    time, and is one nobody runs."""
    passes = []

    def drifting(page, measured, counts, changes):
        passes.append(1)
        return page + "x" * len(passes)

    monkeypatch.setattr(rf, "rewrite", drifting)
    before = read(rf.PAGE)
    with pytest.raises(SystemExit, match="not idempotent"):
        rf.main()
    assert read(rf.PAGE) == before
