"""A failed schema migration must never take the whole website down.

Migrations run at import time under WSGI, so anything that escapes stops the
app from loading at all — every page 500s, including pages that never touch
the new column, until someone reloads the web app by hand. A briefly locked
or unwritable SQLite file must not be able to do that.

Each case runs in its own subprocess because that is what is actually being
tested: importing the module the way PythonAnywhere's WSGI process does.
Running in-process would also make the result depend on whichever test module
imported the app first.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import closing

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_COLUMNS = ('default_start', 'default_end')


def _run(script, disk_path):
    """Import the app in a clean process and report what happened."""
    env = {
        **os.environ,
        'RENDER': '1',
        'RENDER_DISK_PATH': disk_path,
        'ENABLE_EMAIL': 'false',
        'PYTHONPATH': APP_DIR,
    }
    return subprocess.run(
        [sys.executable, '-c', textwrap.dedent(script)],
        cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


class StartupResilienceTest(unittest.TestCase):
    def setUp(self):
        self.disk = tempfile.mkdtemp()
        self.db = os.path.join(self.disk, 'bookings.db')
        self.addCleanup(self._cleanup)

        # Build a complete database, then take away only the columns this
        # release adds — the exact shape of the live database on deploy day.
        built = _run("import app", self.disk)
        self.assertEqual(built.returncode, 0, built.stderr)
        with closing(sqlite3.connect(self.db)) as connection:
            for column in NEW_COLUMNS:
                connection.execute(f'ALTER TABLE room DROP COLUMN {column}')
            connection.commit()

    def _cleanup(self):
        os.chmod(self.disk, 0o755)
        if os.path.exists(self.db):
            os.chmod(self.db, 0o644)
        shutil.rmtree(self.disk, ignore_errors=True)

    def _block_writes(self):
        os.chmod(self.db, 0o444)
        os.chmod(self.disk, 0o555)

    def _allow_writes(self):
        os.chmod(self.disk, 0o755)
        os.chmod(self.db, 0o644)

    def _room_columns(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return [
                row[1] for row in connection.execute('PRAGMA table_info(room)')
            ]

    def test_site_stays_up_when_the_migration_cannot_run(self):
        """The outage this guards against: importing must still succeed and
        pages must still serve, rather than every URL returning 500."""
        self._block_writes()
        try:
            result = _run("""
                import json, app
                client = app.app.test_client()
                print(json.dumps({
                    'imported': True,
                    'codes': {p: client.get(p).status_code
                              for p in ('/', '/peer-support', '/yoga', '/book')},
                }))
            """, self.disk)
        finally:
            self._allow_writes()

        self.assertEqual(result.returncode, 0,
                         f'import died instead of degrading:\n{result.stderr}')
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        for path, code in payload['codes'].items():
            self.assertEqual(code, 200, f'{path} went down: {payload["codes"]}')

    def test_schema_self_heals_once_the_database_is_writable(self):
        """A transient failure must not need a manual reload to recover."""
        result = _run("""
            import json, app
            client = app.app.test_client()
            client.get('/')
            print(json.dumps({
                'ready': app._schema_ready,
                'rooms_api': client.get('/api/rooms').status_code,
            }))
        """, self.disk)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload['ready'], 'schema did not self-heal')
        self.assertEqual(payload['rooms_api'], 200)
        for column in NEW_COLUMNS:
            self.assertIn(column, self._room_columns())


if __name__ == '__main__':
    unittest.main()
