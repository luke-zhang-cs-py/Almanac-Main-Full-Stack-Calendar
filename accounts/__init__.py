"""
accounts/
----------
Who you are, and what that lets you do.

One module today, and it is deliberately its own package rather than a file
in `core`: this is the security boundary. Every authenticated route in the
project passes through `token_required` and `roles_required`, so the set of
things that may change how identity is decided wants to be small, named and
obvious in a directory listing -- not filed next to the SQLite adapter.

  auth.py   password hashing, JWT issue and verify, and the two decorators
            that guard every route

The HTTP half of this lives in `routes/auth_routes.py` (register, login,
me), which imports from here. `scripts/login_page.py` is a standalone demo of
the same API shape with its own database; it sits with the other things you
run by hand rather than with anything the app imports.
"""
