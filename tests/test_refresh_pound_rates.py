"""tools/refresh_pound_rates.py, with the ECB replaced by a zip built here.

Nothing in this file reaches the network. The download is exercised through
both of its routes -- urllib, then curl when urllib's certificate store
refuses the site -- with each replaced by a stand-in, and the parser is fed
a history zip with the two shapes the real file has that are easy to get
wrong: the trailing comma on every row, and "N/A" for a currency that did
not exist yet. The CSV is written under tmp_path; rates/eur_legs.csv, which
the app actually reads, is never rewritten from here.
"""

import csv
import io
import os
import subprocess
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import refresh_pound_rates as rates   # noqa: E402


def history_zip(text):
    """An eurofxref-hist.zip holding one CSV, as the ECB ships it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("eurofxref-hist.csv", text)
    return buffer.getvalue()


# The ECB's shape: a phantom final column from the trailing comma, USD as a
# currency nobody asked for, N/A for a leg that did not exist yet, a blank
# line, and one short row.
HISTORY = (
    "Date,USD,CAD,GBP,\n"
    "2026-10-23,1.0800,1.5100,0.8400,\n"
    "2026-10-22,1.0790,1.5090,N/A,\n"
    "1999-01-04,1.1789,N/A,N/A,\n"
    "\n"
    "2026-10-21,1.0780,1.5080\n"
)


# ------------------------------------------------------------------ parse


def test_parse_keeps_the_pair_and_drops_what_is_not_a_rate():
    got = rates.parse(history_zip(HISTORY))
    assert got == {
        "2026-10-23": {"CAD": "1.5100", "GBP": "0.8400"},
        "2026-10-22": {"CAD": "1.5090"},
        "2026-10-21": {"CAD": "1.5080"},
    }, "a day with neither leg is dropped, and a short row is not an error"


def test_parse_refuses_a_file_missing_one_of_the_legs():
    with pytest.raises(SystemExit, match=r"no column for \['GBP'\]"):
        rates.parse(history_zip("Date,USD,CAD,\n2026-10-23,1.08,1.51,\n"))


# ------------------------------------------------------------------ write


def test_write_puts_the_newest_day_first(tmp_path):
    out = tmp_path / "rates" / "eur_legs.csv"
    rates.write(rates.parse(history_zip(HISTORY)), str(out))

    with io.open(str(out), encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["date", "CAD", "GBP"],
        ["2026-10-23", "1.5100", "0.8400"],
        ["2026-10-22", "1.5090", ""],
        ["2026-10-21", "1.5080", ""],
    ]


# --------------------------------------------------------------- download


class Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_uses_urllib_when_it_works(monkeypatch):
    asked = []

    def urlopen(url, timeout):
        asked.append((url, timeout))
        return Response(b"zip bytes")

    monkeypatch.setattr(rates.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(rates.subprocess, "run", pytest.fail)
    assert rates.download(timeout=7) == b"zip bytes"
    assert asked == [(rates.HISTORY_URL, 7)]


@pytest.fixture
def urllib_refuses(monkeypatch):
    def urlopen(url, timeout):
        raise OSError("CERTIFICATE_VERIFY_FAILED")
    monkeypatch.setattr(rates.urllib.request, "urlopen", urlopen)


def test_download_falls_back_to_curl_with_verification_on(urllib_refuses,
                                                          monkeypatch, capsys):
    ran = []

    def run(command, capture_output, timeout):
        ran.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, b"zip bytes", b"")

    monkeypatch.setattr(rates.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(rates.subprocess, "run", run)

    assert rates.download(timeout=5) == b"zip bytes"
    assert "CERTIFICATE_VERIFY_FAILED" in capsys.readouterr().out
    command, timeout = ran[0]
    assert command == ["/usr/bin/curl", "-sSL", "--max-time", "5",
                       rates.HISTORY_URL]
    assert "-k" not in command and "--insecure" not in command
    assert timeout == 35


def test_download_stops_when_there_is_no_curl(urllib_refuses, monkeypatch):
    monkeypatch.setattr(rates.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="no curl"):
        rates.download()


@pytest.mark.parametrize("code, body", [(6, b""), (0, b"")])
def test_download_stops_when_curl_fails_or_returns_nothing(
        urllib_refuses, monkeypatch, code, body):
    monkeypatch.setattr(rates.shutil, "which", lambda name: "curl")
    monkeypatch.setattr(
        rates.subprocess, "run",
        lambda command, capture_output, timeout: subprocess.CompletedProcess(
            command, code, body, b"curl: (6) Could not resolve host"))
    with pytest.raises(SystemExit, match="Could not resolve host"):
        rates.download()


# ------------------------------------------------------------------- main


def test_main_writes_the_file_and_summarises_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rates, "download",
                        lambda timeout: history_zip(HISTORY))
    out = tmp_path / "eur_legs.csv"
    rates.main(["--out", str(out), "--timeout", "3"])

    assert out.read_text(encoding="utf-8").startswith("date,CAD,GBP")
    said = capsys.readouterr().out
    assert "3 days, 2026-10-21 to 2026-10-23, 1 with both legs" in said
    assert "not regenerated here" in said


def test_main_refuses_a_history_that_parses_to_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(rates, "download",
                        lambda timeout: history_zip("Date,CAD,GBP,\n"))
    out = tmp_path / "eur_legs.csv"
    with pytest.raises(SystemExit, match="parsed to nothing"):
        rates.main(["--out", str(out)])
    assert not out.exists(), "an empty history must not replace the file"
