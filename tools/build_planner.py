"""Build the planner as one self-contained HTML file.

    python tools/build_planner.py --data ../planner-data.js \
                                  --out ../september-planner.html

One file, opened by double-clicking it. No server, no folder of assets, no
network of any kind: the stylesheet, the engine and the seed are inlined, and
the result keeps everything you add in that browser's localStorage.

Why the seed is a separate file
-------------------------------
The planner used to be one 70KB file with somebody's term timetable, diary
and to-do list declared inline, which is why it has never been in a
repository -- a timetable says where a person is at every hour of every
weekday. Splitting the seed out means the engine can be versioned, reviewed
and tested like anything else, while the part that is nobody's business stays
out of it.

So the default seed is standalone/planner/data.sample.js, which is invented.
Pass --data to build your own. The builder prints which seed it used, every
time, because building the sample by accident and not noticing is the one
confusing failure here.

What it refuses to do
---------------------
It will not write a file that still points at something beside it. A stray
src="app.js" keeps working while the file sits in standalone/planner/ next to
its sources, and breaks the moment it is moved -- which is the one situation
a standalone file exists for.

The Content-Security-Policy is rewritten to forbid the network outright:
`default-src 'none'` with no connect-src means the file *cannot* make a
request, which is a better guarantee than a promise not to. The cost is
`script-src 'unsafe-inline'`, since every script is now inline; with no
network reachable there is nowhere for an injected script to send anything,
and the untrusted text on the page is what you typed into it yourself.
"""

import argparse
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "standalone", "planner")
SAMPLE = os.path.join(SRC, "data.sample.js")
BLANK = os.path.join(SRC, "data.blank.js")

# No frame-ancestors. A <meta> CSP cannot deliver that directive: the
# browser ignores it and logs a notice saying so, which means listing it
# claimed a protection the file was not getting. It works only as an HTTP
# header, and this file is opened over file://, where there is no header to
# set and nothing to frame it. Every other directive here does apply, and
# `default-src 'none'` with no connect-src is the one that matters: the file
# cannot make a request, which is better than a promise not to.
POLICY = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "base-uri 'none'; "
    "form-action 'none'"
)

BANNER = """<!--
  The planner, as one file.

  Built by tools/build_planner.py from standalone/planner/ -- edit the
  sources there and rebuild rather than editing this, which is generated.

  Seed: %s

  Everything is inside this file: the stylesheet, the engine and the seed. It
  makes no network requests and its Content-Security-Policy forbids them, so
  nothing you write here can leave this file. What you add is kept in the
  browser's localStorage for whatever page opened it -- not synced, not
  backed up. Use the export button if you want it to outlive a cache clear.
-->
"""


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def build(data_path=None):
    data_path = data_path or SAMPLE
    page = read(os.path.join(SRC, "index.html"))

    # The policy, rewritten for a file with nothing to fetch.
    page, swapped = re.subn(
        r'<meta http-equiv="Content-Security-Policy" content="[^"]*">',
        '<meta http-equiv="Content-Security-Policy" content="%s">' % POLICY,
        page, count=1)
    if not swapped:
        # The source page may carry no policy at all; a standalone file
        # should have one regardless, so it is added rather than assumed.
        page = page.replace(
            "</title>",
            '</title>\n<meta http-equiv="Content-Security-Policy" '
            'content="%s">' % POLICY, 1)
    assert POLICY in page, "the built file ended up with no content policy"

    style = "<style>\n%s</style>" % read(os.path.join(SRC, "style.css"))
    page = page.replace('<link rel="stylesheet" href="style.css">', style, 1)
    assert "<style>" in page, "the stylesheet link was not replaced"

    scripts = ("<script>\n%s</script>\n<script>\n%s</script>"
               % (read(data_path), read(os.path.join(SRC, "app.js"))))
    page = page.replace('<script src="data.js"></script>\n'
                        '<script src="app.js"></script>', scripts, 1)
    assert 'src="app.js"' not in page and 'src="data.js"' not in page, (
        "the script tags were not replaced, so the file is not self-contained")

    label = os.path.basename(data_path)
    if os.path.abspath(data_path) == os.path.abspath(SAMPLE):
        label += "  (invented -- pass --data to build your own)"
    page = page.replace("<!doctype html>", "<!doctype html>\n" + BANNER % label, 1)
    if "<!doctype html>" not in page.lower()[:200]:
        page = BANNER % label + page
    return page


def loose_references(page):
    """Anything still pointing outside the file."""
    return re.findall(r'(?:src|href)="(?!#|https?:|mailto:|data:)([^"]+)"',
                      page)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=None,
                        help="the seed to inline (default: the sample)")
    parser.add_argument("--blank", action="store_true",
                        help="build the empty calendar: no term, no diary, "
                             "no fixtures, no to-dos")
    parser.add_argument("--out",
                        default=os.path.join(ROOT, "september-planner.html"),
                        help="where to write the file")
    args = parser.parse_args()

    if args.blank and args.data:
        raise SystemExit("--blank and --data both name a seed; pick one")

    data_path = BLANK if args.blank else (args.data or SAMPLE)
    if not os.path.exists(data_path):
        raise SystemExit("no such seed: %s" % data_path)

    page = build(data_path)

    loose = loose_references(page)
    if loose:
        raise SystemExit("these still point outside the file: %s" % loose)

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(page)

    print("  %s" % args.out)
    print("  %.0f KB, seed %s, no external references"
          % (os.path.getsize(args.out) / 1024, os.path.basename(data_path)))
    if os.path.abspath(data_path) == os.path.abspath(SAMPLE):
        print("  NOTE: that is the invented sample seed, not yours.")


if __name__ == "__main__":
    main()
