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
                        august_dates = [
                            day for day in schedule
                            if day.startswith('2026-08-')
                        ]
                        rooms = {
                            day: [db.session.get(Room, room_id).name
                                  for room_id in schedule[day]]
                            for day in august_dates
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
        self.assertEqual(payload['rooms'], {
            '2026-08-07': rose_and_clerkenwell,
        })
        self.assertEqual(payload['yoga'], [])

    def test_removed_yoga_dates_keep_existing_admin_records(self):
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
                    from datetime import date
                    from app import YogaBooking, app, db, get_yoga_availability

                    with app.app_context():
                        db.create_all()
                        for booking_id, session_date, name, email in (
                            (1, date(2026, 8, 7), 'August 7 One', 'aug7-one@example.com'),
                            (2, date(2026, 8, 7), 'August 7 Two', 'aug7-two@example.com'),
                            (3, date(2026, 8, 28), 'August 28 One', 'aug28-one@example.com'),
                            (4, date(2026, 8, 28), 'August 28 Two', 'aug28-two@example.com'),
                        ):
                            db.session.add(YogaBooking(
                                id=booking_id,
                                session_date=session_date,
                                name=name,
                                email=email,
                                phone='07000000000',
                                emergency_name='Emergency Contact',
                                emergency_phone='07000000001',
                                agreed_safety=True,
                            ))
                        db.session.commit()

                        public_dates = [
                            session['date'] for session in get_yoga_availability()
                        ]

                        client = app.test_client()
                        with client.session_transaction() as session:
                            session['admin_logged_in'] = True
                        admin_payload = client.get(
                            '/api/admin/yoga-bookings'
                        ).get_json()
                        removed_dates = {}
                        for date_string in ('2026-08-07', '2026-08-28'):
                            admin_session = next(
                                session for session in admin_payload['sessions']
                                if session['date'] == date_string
                            )
                            removed_dates[date_string] = {
                                'booked': admin_session['booked'],
                                'names': [
                                    booking['name']
                                    for booking in admin_session['bookings']
                                ],
                                'database_count': YogaBooking.query.filter_by(
                                    session_date=date.fromisoformat(date_string)
                                ).count(),
                            }
                        print(json.dumps({
                            'public_dates': public_dates,
                            'removed_dates': removed_dates,
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
        self.assertNotIn('2026-08-07', payload['public_dates'])
        self.assertNotIn('2026-08-28', payload['public_dates'])
        self.assertEqual(payload['removed_dates']['2026-08-07'], {
            'booked': 2,
            'names': ['August 7 One', 'August 7 Two'],
            'database_count': 2,
        })
        self.assertEqual(payload['removed_dates']['2026-08-28'], {
            'booked': 2,
            'names': ['August 28 One', 'August 28 Two'],
            'database_count': 2,
        })

    def test_booking_date_cards_do_not_advertise_yoga(self):
        script_path = os.path.join(APP_DIR, 'static', 'js', 'app.js')
        with open(script_path, encoding='utf-8') as script:
            source = script.read()
        self.assertNotIn('Yoga at 10am', source)
        self.assertNotIn('date-yoga-tag', source)


if __name__ == '__main__':
    unittest.main()
