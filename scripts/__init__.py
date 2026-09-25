"""Things you run by hand, none of which the app imports.

    python -m scripts.seed_data     an admin and a little sample data
    python -m scripts.seed_luke     one provider, with offerings
    python -m scripts.login_page    the standalone login demo, :5006

Run as modules rather than as files: a file run directly puts its own
directory on sys.path, and scripts/ is not what these import from.
"""
