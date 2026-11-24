"""The colour themes: every page opens dark, switches, remembers, and reads.

Every page this repository serves or publishes takes its colours from CSS
custom properties in one block per theme, keyed on a class on <html>:

  * static/css/style.css -- the Flask app, its coffee-chat page, and (copied
    by tools/build_static.py) the published slot-engine demo in docs/app/;
  * docs/architecture.html -- a single-file page carrying a copy of those
    same two blocks, which must not drift from the original;
  * docs/index.html -- the shared write-up template, whose two blocks are the
    same in every project that uses it;
  * standalone/planner/style.css -- the planner, built into docs/planner.html
    and docs/calendar.html.

`class="theme-dark"` is in each page's markup, so a page is themed before --
and without -- any script. A tiny script in <head> restores a saved choice
from localStorage['theme'], and a button steps through the page's THEMES.

What would break, and what catches it:

  * a theme listed in THEMES with no block, or a block missing a token the
    default sets -- the page would fall back to dark for that one colour;
  * a pairing below WCAG AA in any theme -- checked from the tokens, so a
    pair that only shows in a hover, an error or a selected row is checked
    even though no page scan would ever see it;
  * the class missing from <html>, or a component reading a raw colour, or
    prefers-color-scheme creeping back in;
  * and, in a real browser where one is available, the no-JS render, the
    toggle, the saved choice, an unknown saved theme, and every visible line
    of text in both themes.

The token checks need nothing but Python, so they run in CI. The browser
half needs Playwright, which CI does not install; there it is skipped,
not collected differently, so the published test counts stay the same.
"""
import io
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


# ------------------------------------------------------------ the token blocks

CONTRACT = ("bg", "surface", "surface-subtle", "border", "border-strong",
            "text-primary", "text-muted", "text-subtle", "accent",
            "accent-hover", "accent-subtle", "text-on-accent", "danger")


def theme_blocks(css):
    """{theme name: {token: value}} for every `.theme-<name> { ... }` block."""
    blocks = {}
    for found in re.finditer(r"\.theme-([a-z]+)\s*\{([^}]*)\}", css):
        if "color-scheme" not in found.group(2):
            continue              # a component such as .theme-toggle, not a theme
        blocks[found.group(1)] = dict(
            (name, value.strip()) for name, value in
            re.findall(r"--([\w-]+)\s*:\s*([^;]+);", found.group(2)))
    return blocks


def themes_listed(source):
    """The THEMES list a page's script steps through."""
    found = re.search(r"THEMES = \[([^\]]*)\]", source)
    assert found, "no THEMES list in the page's script"
    return re.findall(r"['\"]([a-z]+)['\"]", found.group(1))


def lum(hexcolour):
    value = hexcolour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Each group: where its blocks live, which scripts list its THEMES, and the
# pairs its pages actually draw -- foreground token on background token.
# Text at 4.5:1; UI boundaries that identify a control or carry meaning at 3:1.
ALMANAC_SURFACES = ("bg", "surface", "surface-subtle", "surface-raised",
                    "surface-sunken")
ALMANAC_TEXT = [(fg, bg) for fg in ("text-primary", "text-muted", "text-subtle",
                                    "accent-strong", "secondary", "danger",
                                    "warning")
                for bg in ALMANAC_SURFACES]
ALMANAC_TEXT += [(fg, bg) for fg in ("text-primary", "text-muted", "text-subtle",
                                     "accent-strong")
                 for bg in ("accent-subtle", "accent-wash", "hover-wash")]
ALMANAC_TEXT += [
    ("secondary", "secondary-subtle"), ("text-muted", "secondary-subtle"),
    ("danger", "danger-subtle"),
    ("text-subtle", "neutral-subtle"), ("text-muted", "neutral-subtle"),
    ("text-on-accent", "accent"), ("text-on-accent", "accent-hover"),
]
ALMANAC_UI = [(fg, bg) for fg in ("border-strong", "accent", "danger",
                                  "secondary-fill", "series-new",
                                  "series-existing")
              for bg in ("bg", "surface", "surface-subtle")]
ALMANAC_UI += [(fg, "track") for fg in ("accent", "warning", "danger")]

TEMPLATE_TEXT = [(fg, bg) for fg in ("text-primary", "text-muted", "text-subtle",
                                     "accent", "danger", "success")
                 for bg in ("bg", "surface", "surface-subtle", "accent-subtle")]
TEMPLATE_TEXT += [("text-on-accent", "accent"), ("text-on-accent", "accent-hover")]
TEMPLATE_UI = [(fg, bg) for fg in ("border-strong", "accent")
               for bg in ("bg", "surface")]

PLANNER_SURFACES = ("bg", "surface", "surface-subtle", "surface-past",
                    "accent-subtle")
PLANNER_TEXT = [(fg, bg) for fg in ("text-primary", "text-muted", "text-subtle",
                                    "accent", "danger")
                for bg in PLANNER_SURFACES]
PLANNER_TEXT += [("text-on-accent", "accent"), ("text-on-accent", "accent-hover")]
PLANNER_UI = [(fg, bg) for fg in ("border-strong", "accent")
              for bg in ("bg", "surface", "surface-subtle")]

GROUPS = {
    "almanac": dict(css=("static", "css", "style.css"),
                    scripts=[("static", "js", "app.js"),
                             ("templates", "coffee.html"),
                             ("tools", "static_src", "js", "demo.js")],
                    text=ALMANAC_TEXT, ui=ALMANAC_UI),
    "architecture": dict(css=("docs", "architecture.html"),
                         scripts=[("docs", "architecture.html")],
                         text=ALMANAC_TEXT, ui=ALMANAC_UI),
    "write-up": dict(css=("docs", "index.html"),
                     scripts=[("docs", "index.html")],
                     text=TEMPLATE_TEXT, ui=TEMPLATE_UI),
    "planner": dict(css=("standalone", "planner", "style.css"),
                    scripts=[("standalone", "planner", "app.js")],
                    text=PLANNER_TEXT, ui=PLANNER_UI),
}


def blocks_of(group):
    return theme_blocks(read(*GROUPS[group]["css"]))


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_every_listed_theme_has_a_complete_block(group):
    """Adding a theme is one block and one THEMES entry. A block that leaves
    a token out silently inherits nothing -- the property is simply unset --
    so the set has to match the default's exactly."""
    blocks = blocks_of(group)
    assert blocks, f"{group}: no .theme-* blocks were found, so this is vacuous"
    for script in GROUPS[group]["scripts"]:
        listed = themes_listed(read(*script))
        assert listed and listed[0] == "dark", (
            f"{'/'.join(script)}: THEMES must start with the theme in the "
            f"markup, dark; it is {listed}")
        default = set(blocks["dark"])
        for name in listed:
            assert name in blocks, f"{'/'.join(script)} lists {name!r} but no .theme-{name} block exists"
            assert set(blocks[name]) == default, (
                f"{group}: .theme-{name} differs from .theme-dark by "
                f"{sorted(set(blocks[name]) ^ default)}")
    missing = [t for t in CONTRACT if "color-" + t not in blocks["dark"]]
    assert not missing, f"{group}: the dark block lacks contract tokens {missing}"


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_every_pair_meets_aa_in_every_theme(group):
    blocks = blocks_of(group)
    short = []
    for name, tokens in sorted(blocks.items()):
        def colour(token):
            value = tokens["color-" + token]
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), (
                f"{group} .theme-{name} --color-{token} is {value!r}; a token "
                f"that is part of a pairing has to be an opaque hex colour")
            return value
        for pairs, need in ((GROUPS[group]["text"], 4.5), (GROUPS[group]["ui"], 3)):
            for fg, bg in pairs:
                ratio = contrast(colour(fg), colour(bg))
                if ratio < need:
                    short.append(f"{name}: {fg} on {bg} {ratio:.2f} < {need}")
    assert not short, f"{group} pairings below AA:\n  " + "\n  ".join(short)


def test_the_architecture_page_carries_the_app_s_own_blocks():
    """It is a single-file page, so it holds a copy; a copy nobody compares
    is a fork."""
    assert blocks_of("architecture") == blocks_of("almanac")


def test_the_write_up_uses_the_shared_template_blocks():
    """Seven repositories publish the same write-up template, and its two
    blocks are meant to be identical in all of them. These values are the
    ones that fixed the old light palette (--ink-muted at 3.35:1, --series at
    4.34:1); changing one here forks the template."""
    blocks = blocks_of("write-up")
    assert blocks["dark"]["color-bg"] == "#0d0d0d"
    assert blocks["light"]["color-text-subtle"] == "#665632"
    assert blocks["light"]["color-accent"] == "#1f63b8"
    assert blocks["dark"]["color-warning"] == blocks["light"]["color-warning"] == "#fab219"
    assert len(blocks["dark"]) == 17, sorted(blocks["dark"])


# ------------------------------------------------------- markup and stylesheets

PAGES = {
    "app": ("templates", "index.html"),
    "coffee": ("templates", "coffee.html"),
    "demo source": ("tools", "static_src", "index.html"),
    "demo": ("docs", "app", "index.html"),
    "architecture": ("docs", "architecture.html"),
    "write-up": ("docs", "index.html"),
    "planner source": ("standalone", "planner", "index.html"),
    "planner": ("docs", "planner.html"),
    "calendar": ("docs", "calendar.html"),
}


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_page_opens_dark_from_its_markup(page):
    """No JavaScript needed: the class is in the HTML. The restore script
    reads the one key the whole origin shares, swallows a storage error, and
    accepts only a plain lower-case name."""
    text = read(*PAGES[page])
    assert re.search(r'<html lang="en" class="theme-dark">', text), (
        f"{page}: <html> does not carry class=\"theme-dark\"")
    head = text[:text.index("</head>")]
    assert "localStorage.getItem('theme')" in head, f"{page}: no pre-paint restore in <head>"
    assert "/^[a-z]+$/.test(" in head and "catch (e)" in head
    assert "prefers-color-scheme" not in text, f"{page}: still follows the system theme"
    assert "data-theme=" not in text, f"{page}: still switches on a data-theme attribute"


STYLESHEETS = {
    "almanac": ("static", "css", "style.css"),
    "demo": ("tools", "static_src", "css", "demo.css"),
    "coffee": ("templates", "coffee.html"),
    "architecture": ("docs", "architecture.html"),
    "write-up": ("docs", "index.html"),
    "planner": ("standalone", "planner", "style.css"),
}


def component_rules(text):
    """The CSS outside the theme blocks, which must read tokens only."""
    if "<style>" in text:
        text = text[text.index("<style>"):text.index("</style>")]
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?::where\(:root\),\s*)?\.theme-[a-z]+\s*\{[^}]*color-scheme[^}]*\}", "", text)
    # the planner's pick-your-own event colours are data, not theme (and say so)
    text = re.sub(r"\.c-[a-z]+\{background:#[0-9a-fA-F]{6}\}", "", text)
    return text


@pytest.mark.parametrize("sheet", sorted(STYLESHEETS))
def test_components_read_tokens_not_raw_colours(sheet):
    rules = component_rules(read(*STYLESHEETS[sheet]))
    raw = re.findall(r"#[0-9a-fA-F]{3,8}\b(?![\w-])|rgba?\([^)]*\)|hsla?\([^)]*\)", rules)
    # href="#..." and ids are not colours; only values after a colon are
    raw = [r for r in raw if re.search(r":[^;{}]*" + re.escape(r), rules)]
    assert not raw, f"{sheet}: raw colours in component rules: {raw[:8]}"


def test_the_app_script_sets_no_colour_of_its_own():
    """The pound wallet's meter used to write #d03b3b and #fab219 into style
    attributes, which no theme could reach."""
    source = read("static", "js", "app.js")
    assert not re.findall(r"#[0-9a-fA-F]{6}\b|rgba?\(", source)


# --------------------------------------------------------------- in a browser

try:
    from playwright.sync_api import sync_playwright
except ImportError:              # CI: the static checks above still run
    sync_playwright = None

needs_browser = pytest.mark.skipif(sync_playwright is None,
                                   reason="playwright is not installed")

# Every visible line of text against whatever is actually painted behind it.
# Text inside something deliberately dimmed (a finished event, a day gone by,
# a disabled button: effective opacity under .6) is left out on purpose.
SCAN = r"""() => {
  const parse = c => { const n = c.match(/[\d.]+/g).map(Number);
                       return { rgb: n.slice(0, 3).map(v => v / 255), a: n.length > 3 ? n[3] : 1 }; };
  const lum = c => { const [r, g, b] = parse(c).rgb.map(v => v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
                     return .2126 * r + .7152 * g + .0722 * b; };
  const behind = el => { for (let e = el; e; e = e.parentElement) { const bg = getComputedStyle(e).backgroundColor;
                     if (/\d/.test(bg) && parse(bg).a > .5) return bg; } return getComputedStyle(document.body).backgroundColor; };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || !el.getClientRects().length) continue;
    if (el.closest('[hidden], .hidden, noscript, option, script, style')) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= +getComputedStyle(e).opacity;
    if (op < .6) continue;
    const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && +s.fontWeight >= 700);
    const [L1, L2] = [lum(s.color), lum(behind(el))].sort((a, b) => b - a);
    const r = (L1 + .05) / (L2 + .05);
    if (r < (big ? 3 : 4.5)) out.push(el.tagName + '.' + el.className + ' ' + r.toFixed(2) + ' "' + el.textContent.trim().slice(0, 30) + '"');
  }
  return [...new Set(out)];
}"""
THEME = r"(document.documentElement.className.match(/(?:^|\s)theme-(\S+)/) || [])[1]"
TOGGLE = "[data-theme-toggle]:visible, #themeBtn:visible"
SERVED = "http://almanac.test"


def file_url(*parts):
    return "file:///" + os.path.join(ROOT, *parts).replace("\\", "/")


@pytest.fixture(scope="module")
def chromium():
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:                 # no browser downloaded
            pytest.skip(f"no Chromium for playwright: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def served(client, provider):
    """The Flask app answering a fake origin inside the browser, through the
    test client: no port, no thread, and the test database behind it."""
    from domain import coffee_chats as cc
    with client.application.app_context():
        invite = cc.create_invite(provider["id"], cc.InviteRequest("guest@test.local"))

    def answer(route):
        request = route.request
        path = request.url[len(SERVED):]
        reply = client.open(path, method=request.method,
                            headers={k: v for k, v in request.headers.items()
                                     if k.lower() in ("authorization", "content-type")},
                            data=request.post_data_buffer)
        route.fulfill(status=reply.status_code, body=reply.get_data(),
                      headers={"content-type": reply.headers.get("Content-Type", "text/plain")})

    return {"answer": answer, "provider": provider, "invite": invite["token"]}


# (name, url or callable(served) -> url, dark --color-bg, logged in?, something to open)
BROWSER_PAGES = {
    "demo": (file_url("docs", "app", "index.html"), "rgb(18, 22, 29)", False, None),
    "architecture": (file_url("docs", "architecture.html"), "rgb(18, 22, 29)", False, None),
    "write-up": (file_url("docs", "index.html"), "rgb(13, 13, 13)", False, None),
    "planner": (file_url("docs", "planner.html"), "rgb(6, 9, 15)", False, "#grid .day:not(.outside)"),
    "calendar": (file_url("docs", "calendar.html"), "rgb(6, 9, 15)", False, "#grid .day:not(.outside)"),
    "app sign-in": (SERVED + "/", "rgb(18, 22, 29)", False, None),
    "app signed in": (SERVED + "/", "rgb(18, 22, 29)", True, None),
    "coffee": (None, "rgb(18, 22, 29)", False, ".cc-slot"),
}


def open_page(browser, name, served, saved=None, js=True):
    url, _, signed_in, _ = BROWSER_PAGES[name]
    context = browser.new_context(java_script_enabled=js, viewport={"width": 1280, "height": 900})
    init = ""
    if signed_in:
        init += ("localStorage.setItem('appt_token', %s);"
                 "localStorage.setItem('appt_user', %s);"
                 % (json.dumps(served["provider"]["token"]),
                    json.dumps(json.dumps(served["provider"]["user"]))))
    if saved:
        init += "localStorage.setItem('theme', %s);" % json.dumps(saved)
    if init:
        context.add_init_script(init)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text else None)
    page.route(SERVED + "/**", served["answer"])
    page.goto(url or SERVED + "/coffee/" + served["invite"])
    page.wait_for_timeout(500)
    return context, page, errors


@pytest.fixture
def served_or_files(request):
    """The Flask fixtures only for the pages that need them, so the static
    pages do not pay for a database."""
    url = BROWSER_PAGES[request.param][0]
    if url is None or url.startswith(SERVED):
        return request.param, request.getfixturevalue("served")
    return request.param, {"answer": lambda route: route.abort()}


@needs_browser
@pytest.mark.parametrize("served_or_files", sorted(BROWSER_PAGES), indirect=True)
def test_with_javascript_off_the_page_is_dark(chromium, served_or_files):
    name, served = served_or_files
    context, page, _ = open_page(chromium, name, served, js=False)
    try:
        seen = [page.get_attribute("html", "class"),
                page.eval_on_selector("body", "b => getComputedStyle(b).backgroundColor")]
        assert seen == ["theme-dark", BROWSER_PAGES[name][1]], f"{name}: {seen}"
    finally:
        context.close()


@needs_browser
@pytest.mark.parametrize("served_or_files", sorted(BROWSER_PAGES), indirect=True)
def test_the_toggle_switches_remembers_and_survives_a_bad_value(chromium, served_or_files):
    name, served = served_or_files
    context, page, errors = open_page(chromium, name, served)
    try:
        assert page.evaluate(THEME) == "dark"
        button = page.locator(TOGGLE).first
        assert button.get_attribute("aria-label") == "Switch to light theme"
        button.click()
        page.wait_for_timeout(150)
        assert page.evaluate(THEME) == "light"
        assert button.get_attribute("aria-label") == "Switch to dark theme"
        assert page.evaluate("localStorage.getItem('theme')") == "light"
        meta = page.evaluate("(document.querySelector('meta[name=theme-color]') || {}).content")
        light_bg = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim()")
        assert meta == light_bg, f"{name}: the toolbar colour did not follow ({meta} vs {light_bg})"
        page.reload()
        page.wait_for_timeout(400)
        assert page.evaluate(THEME) == "light", f"{name}: the choice was not remembered"
        assert not errors, f"{name}: {errors[:3]}"
    finally:
        context.close()

    context, page, _ = open_page(chromium, name, served, saved="sepia")
    try:
        classes = page.evaluate("document.documentElement.className")
        assert re.findall(r"theme-\S+", classes) == ["theme-dark"], f"{name}: {classes}"
        bg = page.eval_on_selector("body", "b => getComputedStyle(b).backgroundColor")
        assert bg == BROWSER_PAGES[name][1], f"{name}: an unknown saved theme left {bg}"
    finally:
        context.close()


@needs_browser
@pytest.mark.parametrize("served_or_files", sorted(BROWSER_PAGES), indirect=True)
def test_every_visible_line_of_text_meets_aa_in_both_themes(chromium, served_or_files):
    name, served = served_or_files
    opener = BROWSER_PAGES[name][3]
    found = {}
    for theme in ("dark", "light"):
        context, page, _ = open_page(chromium, name, served, saved=theme)
        try:
            assert page.evaluate(THEME) == theme
            if opener:                    # a selected day, a selected slot
                page.click(opener)
                page.wait_for_timeout(250)
            found[theme] = page.evaluate(SCAN)
            if page.locator("#cdOpen:visible").count():   # the countdown overlay too
                page.click("#cdOpen")
                page.wait_for_timeout(250)
                found[theme + " overlay"] = page.evaluate(SCAN)
        finally:
            context.close()
    bad = {k: v for k, v in found.items() if v}
    assert not bad, f"{name}: text below AA: {bad}"
