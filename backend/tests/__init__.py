"""Test package. Importing it (pytest does, for every test module here -- with or without
conftest.py, --noconftest or --confcutdir; so does any `import tests.<module>`) runs the DB target
guard first: no test can fall back to the hosted project in backend/.env (tests/_db_target.py).
"""

from tests._db_target import bootstrap as _bootstrap

GUARD_DECISION = _bootstrap()
