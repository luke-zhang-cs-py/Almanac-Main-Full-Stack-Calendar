"""
core/
------
The plumbing every other package sits on: settings, and the database.

Two modules, and the reason they are one package is the direction of the
arrows. `config` reads the environment and imports nothing of ours;
`database` imports `config` and nothing else of ours. Everything above --
`accounts`, `domain`, `notify`, `routes` -- imports one or both of these and
neither of them imports back. That is what makes the layering checkable
rather than a claim: if `core` ever grows an import of `domain`, the cycle
says so immediately.

  config.py     every setting, read from the environment, plus the
                SECRET_KEY check that refuses to start a non-debug process
                signing sessions with the committed placeholder
  database.py   one query()/execute() interface over SQLite and Postgres,
                so DATABASE_URL is the only thing that changes between a
                laptop and a managed instance
"""
