"""The two seed scripts, run against a database of their own.

`python -m scripts.seed_data` and `python -m scripts.seed_luke` are run by
hand, outside any Flask application context, through
`db.standalone_connection()`. That is the one path in the project that opens
a connection without `g` -- so these tests point it at a throwaway SQLite
file under tmp_path rather than at the suite's shared database, and never at
a real one.

What matters about both scripts is that they are safe to run twice: a second
run must not create a second account or duplicate the catalogue, because
running it again after editing a description is the realistic use.
"""

import pytest

from accounts.auth import verify_password
from core import database as db
from scripts import seed_data, seed_luke


@pytest.fixture
def seed_db(tmp_path, monkeypatch):
    """A fresh SQLite file for the scripts to seed, and a way to read it.

    Config.DATABASE_URL is read when a connection is opened, not cached, so
    pointing it somewhere else is enough to keep the scripts away from the
    suite's database.
    """
    path = tmp_path / "seed.db"
    monkeypatch.setattr(db.Config, "DATABASE_URL", "sqlite:///" + str(path))

    def rows(sql, params=()):
        with db.standalone_connection() as conn:
            return db.query(sql, params, conn=conn)
    return rows


# ---------------------------------------------------------------- seed_data


def test_seed_data_creates_an_admin_and_says_how_to_sign_in(seed_db, capsys):
    seed_data.main()

    out = capsys.readouterr().out
    assert "Created admin account:" in out
    assert seed_data.ADMIN_EMAIL in out and seed_data.ADMIN_PASSWORD in out

    admins = seed_db("SELECT * FROM users WHERE email = ?",
                     (seed_data.ADMIN_EMAIL,))
    assert len(admins) == 1
    assert admins[0]["role"] == "admin"
    assert verify_password(seed_data.ADMIN_PASSWORD, admins[0]["password_hash"])


def test_seed_data_run_twice_leaves_one_admin(seed_db, capsys):
    seed_data.main()
    capsys.readouterr()
    seed_data.main()

    assert capsys.readouterr().out.strip() == (
        f"Admin already exists: {seed_data.ADMIN_EMAIL}")
    assert len(seed_db("SELECT id FROM users")) == 1


# ---------------------------------------------------------------- seed_luke


def test_seed_luke_creates_the_provider_hours_and_catalogue(seed_db, capsys):
    assert seed_luke.main([]) == 0

    out = capsys.readouterr().out
    assert f"Created provider {seed_luke.NAME} <{seed_luke.EMAIL}>" in out
    assert f"password: {seed_luke.PASSWORD}" in out
    assert f"availability windows added: {len(seed_luke.AVAILABILITY)}" in out
    assert f"offerings added: {len(seed_luke.CATALOGUE)}" in out
    assert f"{len(seed_luke.CATALOGUE)} offering(s)" in out

    user = seed_db("SELECT * FROM users WHERE email = ?", (seed_luke.EMAIL,))[0]
    assert user["role"] == "provider"
    assert user["specialty"] == seed_luke.SPECIALTY
    assert out.rstrip().endswith(
        f"/api/providers/{user['id']}/offerings")

    windows = seed_db("SELECT day_of_week, start_time, end_time, slot_minutes "
                      "FROM availability ORDER BY day_of_week")
    assert [tuple(w.values()) for w in windows] == seed_luke.AVAILABILITY
    titles = [row["title"] for row in seed_db(
        "SELECT title FROM offerings ORDER BY sort_order")]
    assert titles == [entry[0] for entry in seed_luke.CATALOGUE]


def test_seed_luke_run_twice_adds_nothing_and_prints_no_password(seed_db,
                                                                 capsys):
    seed_luke.main([])
    capsys.readouterr()
    seed_luke.main([])

    out = capsys.readouterr().out
    assert f"Found provider {seed_luke.NAME}" in out
    assert "password:" not in out, "the password is only shown on creation"
    assert "availability windows added: 0" in out
    assert "offerings added: 0" in out
    assert len(seed_db("SELECT id FROM users")) == 1
    assert len(seed_db("SELECT id FROM offerings")) == len(seed_luke.CATALOGUE)


def test_seed_luke_corrects_a_stale_grid_without_adding_a_window(seed_db,
                                                                 capsys):
    """A 30-minute grid left behind would make every 45-minute session
    unbookable, so a re-run fixes the slot size in place."""
    seed_luke.main([])
    with db.standalone_connection() as conn:
        db.execute("UPDATE availability SET slot_minutes = 30 "
                   "WHERE day_of_week = 1", conn=conn)
    seed_luke.main([])

    assert "availability windows added: 0" in capsys.readouterr().out
    grids = {row["slot_minutes"] for row in seed_db(
        "SELECT slot_minutes FROM availability")}
    assert grids == {15}
    assert len(seed_db("SELECT id FROM availability")) == len(
        seed_luke.AVAILABILITY)


def test_seed_luke_reset_replaces_the_catalogue(seed_db, capsys):
    seed_luke.main([])
    before = {row["id"] for row in seed_db("SELECT id FROM offerings")}
    capsys.readouterr()

    seed_luke.main(["--reset"])

    assert f"offerings added: {len(seed_luke.CATALOGUE)}" in (
        capsys.readouterr().out)
    after = {row["id"] for row in seed_db("SELECT id FROM offerings")}
    assert len(after) == len(seed_luke.CATALOGUE)
    assert not before & after, "--reset should delete the old rows"


def test_seed_luke_list_shows_without_seeding(seed_db, capsys):
    """--list still creates the account (it needs an id to list), but adds
    no hours and no offerings."""
    assert seed_luke.main(["--list"]) == 0

    out = capsys.readouterr().out
    assert "0 offering(s)" in out
    assert "availability windows added" not in out
    assert seed_db("SELECT id FROM availability") == []


def test_show_groups_by_category_and_puts_unknown_ones_last(seed_db, capsys):
    """Categories print in the catalogue's order, and a row with no category
    is filed under "Other", which is one of them. One the catalogue does not
    know still appears, after all of those, rather than vanishing. A row with
    no level or summary prints neither."""
    with db.standalone_connection() as conn:
        db.init_db(conn=conn)
        user, _ = seed_luke.ensure_luke(conn)
        for title, category, level, summary in (
                ("Kerning", "Typography", None, None),
                ("Untitled", None, "Any", "No category."),
                ("Mock interview", "Software engineering", "Mid", "Real.")):
            db.execute(
                "INSERT INTO offerings (provider_id, title, category, level, "
                "summary, duration_min, price_cents) VALUES (?,?,?,?,?,30,0)",
                (user["id"], title, category, level, summary), conn=conn)
        seed_luke.show(user["id"], conn)

    out = capsys.readouterr().out
    order = [out.index(name) for name in
             ("Software engineering", "Other", "Typography")]
    assert order == sorted(order)
    assert "[Mid]" in out and "Real." in out
    kerning = next(line for line in out.splitlines() if "Kerning" in line)
    assert "[" not in kerning, "no level means no bracket"
    assert "3 offering(s)" in out
