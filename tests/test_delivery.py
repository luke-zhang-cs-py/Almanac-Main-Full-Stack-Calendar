"""Actually sending the mail, and the sweep that decides when to.

Everything else in the suite runs with SMTP_HOST unset, so the message is
printed rather than sent and `_deliver` has never been executed. That leaves
the part with the security-relevant decisions in it -- whether STARTTLS is
negotiated, whether credentials are offered -- as the only part nothing
checks. A fake SMTP class stands in for the socket; every call it receives is
recorded, so the order can be asserted rather than assumed.

The scheduler's loop is here for the same reason: it runs on a thread nobody
watches, and a dead scheduler is silent. It is driven directly with a stop
event instead of being left to a timer, so the test does not sleep.
"""

import smtplib

import pytest

from notify import mailer
from notify import scheduler


class FakeSMTP:
    """Records what a real server would have been asked to do."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls = []
        self.sent = []
        FakeSMTP.instances.append(self)

    # The context manager `with smtp:` uses.
    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append("send")
        self.sent.append(msg)


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    return FakeSMTP


def a_message(**over):
    body = dict(kind="welcome", to="someone@test.local", subject="Hello",
                text="Plain body", html="<p>Rich body</p>")
    body.update(over)
    return mailer.Message(**body)


MAIL_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_TIMEOUT", "SMTP_USE_TLS",
             "SMTP_USE_SSL", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM",
             "MAIL_REPLY_TO")


@pytest.fixture
def configure(app):
    """Set the mail config for one test and put it back afterwards.

    conftest hands out the same module-level Flask app to every test, so a
    config value written here stays written. Setting SMTP_HOST and leaving it
    set made every later test try to resolve a hostname that does not exist --
    which is how the first version of this file turned into forty warnings
    and three failures elsewhere.
    """
    original = {k: app.config.get(k) for k in MAIL_KEYS}

    def apply(_app, **over):
        _app.config.update({
            "SMTP_HOST": "smtp.test.local", "SMTP_PORT": 587,
            "SMTP_TIMEOUT": 5, "SMTP_USE_TLS": True, "SMTP_USE_SSL": False,
            "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
            "MAIL_FROM": "Almanac <no-reply@test.local>", "MAIL_REPLY_TO": "",
        })
        _app.config.update(over)

    yield apply
    app.config.update(original)


# ---------------------------------------------------------------- delivery


def test_a_plain_connection_negotiates_starttls(app, smtp, configure):
    with app.app_context():
        configure(app)
        mailer._deliver(a_message())

    sent = smtp.instances[0]
    assert isinstance(sent, FakeSMTP) and not isinstance(sent, FakeSMTPSSL)
    assert sent.calls == ["enter", "ehlo", "starttls", "ehlo", "send", "quit"], (
        "a plain connection must upgrade before the message goes over it")


def test_an_ssl_connection_does_not_also_starttls(app, smtp, configure):
    """Wrapping TLS inside TLS is an error, not belt and braces."""
    with app.app_context():
        configure(app, SMTP_USE_SSL=True, SMTP_PORT=465)
        mailer._deliver(a_message())

    sent = smtp.instances[0]
    assert isinstance(sent, FakeSMTPSSL)
    assert "starttls" not in sent.calls
    assert sent.port == 465


def test_credentials_are_offered_only_when_there_are_any(app, smtp, configure):
    with app.app_context():
        configure(app)
        mailer._deliver(a_message())
    assert not any(isinstance(c, tuple) for c in smtp.instances[0].calls)

    with app.app_context():
        configure(app, SMTP_USERNAME="postmaster", SMTP_PASSWORD="hunter2")
        mailer._deliver(a_message())
    assert ("login", "postmaster", "hunter2") in smtp.instances[1].calls


def test_a_reply_to_is_set_when_configured(app, smtp, configure):
    with app.app_context():
        configure(app, MAIL_REPLY_TO="ask@test.local")
        mailer._deliver(a_message())
    assert smtp.instances[0].sent[0]["Reply-To"] == "ask@test.local"

    with app.app_context():
        configure(app)
        mailer._deliver(a_message())
    assert smtp.instances[1].sent[0]["Reply-To"] is None


def test_no_smtp_host_prints_instead_of_connecting(app, smtp, configure):
    """The default in development. Nothing should reach a socket."""
    with app.app_context():
        configure(app, SMTP_HOST="")
        mailer._deliver(a_message())
    assert smtp.instances == []


# ------------------------------------------------------------- the queue


def test_a_message_is_delivered_inline_when_no_worker_runs(app, smtp,
                                                           monkeypatch,
                                                           configure):
    """Scripts and tests have no delivery thread, so send() must not simply
    drop the message into a queue nobody is reading."""
    monkeypatch.setattr(mailer, "_worker", None)
    with app.app_context():
        configure(app)
        assert mailer.send(a_message(to="inline@test.local")) is True
    assert smtp.instances and smtp.instances[0].calls.count("send") == 1


def test_starting_the_worker_twice_does_not_stack_threads(app, monkeypatch):
    """No real thread is started here, and that is not squeamishness: a live
    worker outlives the test, so every later test has its mail delivered
    asynchronously instead of inline and assertions about the log race it.
    The first version of this test did exactly that and broke three tests in
    another file.

    monkeypatch also restores mailer._worker afterwards, so the module is
    left as it was found.
    """
    made = []

    class FakeThread:
        def __init__(self, **kwargs):
            made.append(kwargs)
            self.daemon = False

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(mailer.threading, "Thread", FakeThread)
    monkeypatch.setattr(mailer, "_worker", None)

    mailer.init_app(app)
    mailer.init_app(app)
    assert len(made) == 1, "a second worker was started over a live one"


def test_a_failed_message_is_queued_again_rather_than_ignored(client, booking):
    """De-duplication must not turn a delivery failure into permanent
    silence: the row is reclaimed so the next attempt can go out.

    It needs an appointment id, because the unique index that does the
    de-duplication is declared WHERE appointment_id IS NOT NULL -- without
    one the insert simply succeeds again and the reclaim path is never
    reached.
    """
    from core import database as db

    def claim():
        return mailer._claim(a_message(to="retry@test.local",
                                       kind="reminder_client",
                                       appointment_id=booking["id"]))

    first = claim()
    assert first is not None
    assert claim() is None, "a second claim of a sent message is refused"

    db.execute("UPDATE email_log SET status = 'failed' WHERE id = ?", (first,))

    again = claim()
    assert again == first, "the failed row should be reclaimed, not duplicated"
    row = db.query("SELECT status FROM email_log WHERE id = ?", (first,),
                   one=True)
    assert row["status"] == "queued"


def test_marking_nothing_is_harmless(ctx):
    """_mark is called on every outcome, including ones where no row was
    ever claimed."""
    mailer._mark(None, "sent")          # must not raise


# ---------------------------------------------------------- the sweep loop


def test_the_loop_sweeps_and_then_stops(app, monkeypatch):
    """The body of the background thread. It had never been executed: the
    existing test stops the loop before its first pass."""
    passes = []
    monkeypatch.setattr(scheduler, "sweep", lambda: passes.append(1))

    scheduler._stop.clear()

    real_wait = scheduler._stop.wait

    def wait_once(timeout=None):
        """Let the startup delay through, then stop after one sweep."""
        if passes:
            scheduler._stop.set()
        return real_wait(0)

    monkeypatch.setattr(scheduler._stop, "wait", wait_once)
    try:
        scheduler._loop(app, interval=0.01)
    finally:
        scheduler._stop.clear()

    assert passes, "the loop never called sweep()"
