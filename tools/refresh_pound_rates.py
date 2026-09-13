"""Rewrite rates/eur_legs.csv from the European Central Bank's own history.

    python tools/refresh_pound_rates.py

The pound wallet converts at the rate published on the day money was spent,
so it needs the series rather than today's number. This downloads the ECB's
reference-rate history -- one zip, 41 currencies, every business day back to
1999 -- and keeps the two legs the cross rate is built from.

Only CAD and GBP are kept. The file carries 41 and holding the rest would be
twenty times the size for no reader, but the ones left out are real, so the
pair is a constant here rather than a hard-coded filter buried in a loop.

Two shapes in the ECB file to be careful of: it appends a trailing comma, so
every row has a final empty cell and the header a phantom column; and a
currency that did not exist yet is written "N/A" rather than left blank.

Nothing in the running app calls this. A request never reaches the network --
the app reads the committed file and nothing else, which is what makes its
answers reproducible. Refreshing is a deliberate act by somebody who then
sees the diff.
"""

import argparse
import csv
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
PAIR = ("CAD", "GBP")
OUT = os.path.join(ROOT, "rates", "eur_legs.csv")


def download(timeout=120):
    """The history zip: urllib, then curl.

    Two ways because one of them fails on machines whose certificate store
    urllib will not accept -- it raises CERTIFICATE_VERIFY_FAILED on a site
    every browser on the same machine loads fine. curl carries its own trust
    store and gets through. Neither is asked to skip verification; the
    fallback is a second verifier, not a weaker one.
    """
    try:
        with urllib.request.urlopen(HISTORY_URL, timeout=timeout) as response:
            return response.read()
    except Exception as exc:                        # noqa: BLE001
        print(f"  urllib could not fetch it ({exc}); trying curl")

    curl = shutil.which("curl")
    if not curl:
        raise SystemExit("urllib failed and there is no curl to fall back on")

    done = subprocess.run(
        [curl, "-sSL", "--max-time", str(timeout), HISTORY_URL],
        capture_output=True, timeout=timeout + 30)
    if done.returncode != 0 or not done.stdout:
        raise SystemExit(
            "curl could not fetch it either: "
            + done.stderr.decode("utf-8", "replace")[-300:])
    return done.stdout


def parse(raw, wanted=PAIR):
    """{date: {currency: "1.6064"}} from the history zip."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            rows = csv.reader(io.TextIOWrapper(handle, encoding="utf-8"))
            header = [cell.strip() for cell in next(rows)]
            columns = {code: header.index(code) for code in wanted
                       if code in header}
            missing = set(wanted) - set(columns)
            if missing:
                raise SystemExit(
                    f"the ECB file has no column for {sorted(missing)}")

            out = {}
            for row in rows:
                if not row or not row[0].strip():
                    continue
                on = row[0].strip()
                day = {}
                for code, index in columns.items():
                    text = row[index].strip() if index < len(row) else ""
                    if text and text != "N/A":
                        day[code] = text
                if day:
                    out[on] = day
    return out


def write(rates, path):
    """Newest first, so somebody opening the file sees current rates."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date"] + list(PAIR))
        for on in sorted(rates, reverse=True):
            writer.writerow([on] + [rates[on].get(code, "") for code in PAIR])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    rates = parse(download(args.timeout))
    if not rates:
        raise SystemExit("the ECB history parsed to nothing")
    write(rates, args.out)

    both = sum(1 for day in rates.values() if len(day) == len(PAIR))
    print("  %s" % args.out)
    print("  %d days, %s to %s, %d with both legs"
          % (len(rates), min(rates), max(rates), both))
    print("  the fixture in rates/cases.json is the wallet project's and is")
    print("  not regenerated here -- if a case stops matching, that is the")
    print("  two implementations disagreeing and is the point of it.")


if __name__ == "__main__":
    main()
