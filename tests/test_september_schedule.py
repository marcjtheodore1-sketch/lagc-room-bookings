import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SeptemberScheduleTest(unittest.TestCase):
    def test_september_rooms_and_yoga_dates(self):
        with tempfile.TemporaryDirectory() as disk:
            env = {
                **os.environ,
                'RENDER': '1',
                'RENDER_DISK_PATH': disk,
                'ENABLE_EMAIL': 'false',
                'PYTHONPATH': APP_DIR,
            }
            result = subprocess.run(
                [sys.executable, '-c', textwrap.dedent("""
                    import json
                    from app import (
                        Room, YOGA_SESSION_DATES, app, db,
                        get_room_schedule_ids, init_default_data,
                    )

                    with app.app_context():
                        init_default_data()
                        schedule = get_room_schedule_ids()
                        september_dates = [
                            day for day in schedule
                            if day.startswith('2026-09-')
                        ]
                        rooms = {
                            day: [db.session.get(Room, room_id).name
                                  for room_id in schedule[day]]
                            for day in september_dates
                        }
                        print(json.dumps({
                            'rooms': rooms,
                            'yoga': [day for day in YOGA_SESSION_DATES
                                     if day.startswith('2026-09-')],
                        }))
                """)],
                cwd=APP_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        rose_clerkenwell_terrace = [
            'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"', 'Room 5.1',
        ]
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), {
            'rooms': {
                '2026-09-04': rose_clerkenwell_terrace,
                '2026-09-11': rose_clerkenwell_terrace,
                '2026-09-18': rose_clerkenwell_terrace,
                '2026-09-25': [
                    'Room 4.4 "Rose"', 'The Loft', 'Room 5.1',
                ],
            },
            'yoga': [
                '2026-09-04', '2026-09-11',
                '2026-09-18', '2026-09-25',
            ],
        })

    def test_unconfirmed_room_notice_is_removed(self):
        script_path = os.path.join(APP_DIR, 'static', 'js', 'app.js')
        with open(script_path, encoding='utf-8') as script:
            source = script.read()
        self.assertNotIn("Room bookings for this Friday aren't open yet", source)
        self.assertNotIn('roomsPendingNotice', source)


if __name__ == '__main__':
    unittest.main()
