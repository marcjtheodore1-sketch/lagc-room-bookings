import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AugustScheduleTest(unittest.TestCase):
    def test_august_rooms_and_yoga_dates(self):
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
                        rooms = {
                            day: [db.session.get(Room, room_id).name
                                  for room_id in schedule[day]]
                            for day in (
                                '2026-08-07', '2026-08-14',
                                '2026-08-21', '2026-08-28',
                            )
                        }
                        print(json.dumps({
                            'rooms': rooms,
                            'yoga': [day for day in YOGA_SESSION_DATES
                                     if day.startswith('2026-08-')],
                        }))
                """)],
                cwd=APP_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        rose_and_clerkenwell = [
            'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"',
        ]
        self.assertEqual(payload['rooms']['2026-08-07'], rose_and_clerkenwell)
        self.assertEqual(payload['rooms']['2026-08-14'], rose_and_clerkenwell)
        self.assertEqual(payload['rooms']['2026-08-21'], rose_and_clerkenwell)
        self.assertEqual(payload['rooms']['2026-08-28'], ['The Loft', 'Room 5.1'])
        self.assertEqual(payload['yoga'], ['2026-08-07', '2026-08-28'])

    def test_booking_date_cards_do_not_advertise_yoga(self):
        script_path = os.path.join(APP_DIR, 'static', 'js', 'app.js')
        with open(script_path, encoding='utf-8') as script:
            source = script.read()
        self.assertNotIn('Yoga at 10am', source)
        self.assertNotIn('date-yoga-tag', source)


if __name__ == '__main__':
    unittest.main()
