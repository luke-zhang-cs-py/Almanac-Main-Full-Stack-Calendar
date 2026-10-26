"""scripts/login_page.py: the standalone sign-in demo, with its own database.

It is a second, smaller Flask app that speaks the same /api/auth/* shape as
the platform, so it gets the same questions: does it refuse what it should,
does a token it issues come back as the same person, and does it start in a
way that cannot hand the Werkzeug debugger to the network. Every test points
it at a SQLite file under tmp_path; the login_users.db it writes by default
at the project root is never touched.
"""

import datetime

import jwt
import pytest

from core import config
from scripts import login_page


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """The demo app on an empty database of its own."""
    monkeypatch.setattr(login_page, "DB_PATH", str(tmp_path / "login.db"))
    login_page.init_db()
    login_page.app.config["TESTING"] = True
    return login_page.app.test_client()


def sign_up(demo, email="ada@example.com", password="pw12345678", **extra):
    body = {"name": "Ada", "email": email, "password": password}
    body.update(extra)
    return demo.post("/api/auth/register", json=body)


def bearer(token):
    return {"Authorization": "Bearer " + token}


# ----------------------------------------------------------------- register


@pytest.mark.parametrize("body, says", [
    ({}, "all required"),
    ({"name": "Ada", "email": "not-an-email", "password": "pw12345678"},
     "doesn't look valid"),
    ({"name": "Ada", "email": "ada@example.com", "password": "short"},
     "at least 8"),
    ({"name": "Ada", "email": "ada@example.com", "password": "pw12345678",
      "role": "admin"}, "'client' or 'provider'"),
])
def test_register_refuses_what_it_should(demo, body, says):
    """Admin included: nobody self-assigns the role that oversees the book."""
    res = demo.post("/api/auth/register", json=body)
    assert res.status_code == 400
    assert says in res.get_json()["error"]


def test_register_returns_a_token_for_the_new_account(demo):
    res = sign_up(demo, email="  Ada@Example.COM ", role="provider",
                  specialty="  Tutoring ")
    assert res.status_code == 201
    body = res.get_json()
    assert body["user"] == {"id": 1, "name": "Ada", "email": "ada@example.com",
                            "role": "provider", "specialty": "Tutoring"}
    claims = jwt.decode(body["token"], login_page.app.config["SECRET_KEY"],
                        algorithms=["HS256"])
    assert claims["sub"] == "1", "sub must be a string, or PyJWT rejects it"
    assert claims["role"] == "provider"


def test_register_refuses_an_email_that_is_taken(demo):
    sign_up(demo)
    res = sign_up(demo, email="ADA@example.com")
    assert res.status_code == 409
    assert "already exists" in res.get_json()["error"]


# -------------------------------------------------------------------- login


def test_login_with_the_right_password_signs_in(demo):
    sign_up(demo)
    res = demo.post("/api/auth/login",
                    json={"email": "ada@example.com", "password": "pw12345678"})
    assert res.status_code == 200
    assert res.get_json()["user"]["email"] == "ada@example.com"


@pytest.mark.parametrize("email, password", [
    ("ada@example.com", "wrong-password"),
    ("nobody@example.com", "pw12345678"),
])
def test_login_says_the_same_thing_for_either_wrong_half(demo, email,
                                                         password):
    """Whether the email exists is not something a stranger should learn."""
    sign_up(demo)
    res = demo.post("/api/auth/login",
                    json={"email": email, "password": password})
    assert res.status_code == 401
    assert res.get_json()["error"] == "Incorrect email or password"


def test_a_deactivated_account_cannot_sign_in(demo):
    sign_up(demo)
    with login_page.app.app_context():
        conn = login_page.get_db()
        assert login_page.get_db() is conn, "one connection per context"
        conn.execute("UPDATE users SET is_active = 0")
        conn.commit()
    res = demo.post("/api/auth/login",
                    json={"email": "ada@example.com", "password": "pw12345678"})
    assert res.status_code == 403
    assert "deactivated" in res.get_json()["error"]


# ----------------------------------------------------------------------- me


def test_me_returns_whoever_the_token_names(demo):
    token = sign_up(demo).get_json()["token"]
    res = demo.get("/api/auth/me", headers=bearer(token))
    assert res.status_code == 200
    assert res.get_json()["user"]["name"] == "Ada"


def token_for(user_id, hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode({"sub": str(user_id), "role": "client", "name": "X",
                       "iat": now, "exp": now + datetime.timedelta(hours=hours)},
                      login_page.app.config["SECRET_KEY"], algorithm="HS256")


@pytest.mark.parametrize("headers, says", [
    ({}, "Missing authorization token"),
    ({"Authorization": "Token abc"}, "Missing authorization token"),
    (bearer("not.a.jwt"), "Invalid token"),
    (bearer(token_for(1, hours=-1)), "Token expired"),
    (bearer(token_for(999, hours=1)), "Account not found"),
])
def test_me_refuses_anything_but_a_live_token_for_a_real_account(
        demo, headers, says):
    sign_up(demo)
    res = demo.get("/api/auth/me", headers=headers)
    assert res.status_code == 401
    assert says in res.get_json()["error"]


# --------------------------------------------------------------- the page


def test_the_page_is_served_as_html_and_posts_to_the_same_api(demo):
    res = demo.get("/")
    assert res.status_code == 200
    assert res.mimetype == "text/html"
    page = res.get_data(as_text=True)
    assert "<title>Almanac — Sign in</title>" in page
    assert '"/api/auth/login"' in page and '"/api/auth/register"' in page


# ----------------------------------------------------------------- startup


@pytest.fixture
def served(tmp_path, monkeypatch):
    """main() with app.run replaced, so nothing is bound and the arguments
    it would have served with are recorded instead."""
    monkeypatch.setattr(login_page, "DB_PATH", str(tmp_path / "boot.db"))
    calls = []
    monkeypatch.setattr(login_page.app, "run",
                        lambda **kw: calls.append(kw))
    for name in ("HOST", "PORT", "FLASK_DEBUG"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_main_binds_loopback_on_5006_with_debug_by_default(served, tmp_path,
                                                           capsys):
    login_page.main()

    assert served == [{"host": "127.0.0.1", "port": 5006, "debug": True}]
    assert (tmp_path / "boot.db").exists(), "main() creates its database"
    out = capsys.readouterr().out
    assert "http://localhost:5006" in out
    assert str(tmp_path / "boot.db") in out


def test_main_reads_host_port_and_debug_from_the_environment(served,
                                                             monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    login_page.main()
    assert served == [{"host": "0.0.0.0", "port": 8123, "debug": False}]


def test_main_refuses_the_placeholder_key_with_debug_off(served, monkeypatch):
    """The same guard app.py runs: off debug, the committed placeholder would
    let anyone forge a token, so it does not start at all."""
    monkeypatch.setitem(login_page.app.config, "SECRET_KEY",
                        config.DEV_SECRET_KEY)
    monkeypatch.setenv("FLASK_DEBUG", "0")
    with pytest.raises(RuntimeError):
        login_page.main()
    assert served == [], "it must refuse before it serves"
