import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SeptemberScheduleTest(unittest.TestCase):
    def test_withdrawn_november_date_rejects_stale_forms(self):
        from test_attendee_booking_experience import run_isolated
        result = run_isolated('''
            from datetime import datetime
            from unittest.mock import patch
            from app import app, db, Room, Booking, init_default_data, get_volunteer_rota
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 10, 21, 12, tzinfo=tz)
            with app.app_context(), patch('app.datetime', Clock), patch('app.send_emails_async') as send:
                init_default_data()
                client = app.test_client()
                rota_rooms = {day['date']: day['rooms'] for day in get_volunteer_rota()['fridays']}
                assert rota_rooms['2026-10-30'] == ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"']
                assert rota_rooms['2026-11-06'] == ['Room 4.4 "Rose"', 'The Loft']
                assert '2026-11-13' not in rota_rooms
                assert '2026-11-13' not in [day['date'] for day in client.get('/api/fridays').json]
                for name in ('Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'):
                    room = Room.query.filter_by(name=name).one()
                    response = client.post('/api/book', json=dict(
                        room_id=room.id, date='2026-11-13', name='Test Person',
                        email='test@example.test', mobility_needs=False,
                        start_slot=0, end_slot=1))
                    assert response.status_code == 409, response.json
                    assert 'no longer available' in response.json['error']
                assert Booking.query.count() == 0
                send.assert_not_called()
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_autumn_rooms_and_yoga_dates(self):
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
                        autumn_dates = [
                            day for day in schedule
                            if day.startswith(('2026-09-', '2026-10-', '2026-11-'))
                        ]
                        rooms = {
                            day: [db.session.get(Room, room_id).name
                                  for room_id in schedule[day]]
                            for day in autumn_dates
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
        rose_and_clerkenwell = [
            'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"',
        ]
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), {
            'rooms': {
                '2026-09-04': rose_and_clerkenwell,
                '2026-09-11': rose_and_clerkenwell,
                '2026-09-18': rose_and_clerkenwell,
                '2026-09-25': [
                    'Room 4.4 "Rose"', 'The Loft',
                ],
                '2026-10-02': rose_and_clerkenwell,
                '2026-10-09': ['Room 4.4 "Rose"', 'The Loft'],
                '2026-10-16': rose_and_clerkenwell,
                '2026-10-23': ['Room 4.4 "Rose"', 'The Loft'],
                '2026-10-30': rose_and_clerkenwell,
                '2026-11-06': ['Room 4.4 "Rose"', 'The Loft'],
                '2026-11-20': rose_and_clerkenwell,
                '2026-11-27': rose_and_clerkenwell,
            },
            'yoga': [
                '2026-09-04', '2026-09-11',
            ],
        })

    def test_unconfirmed_room_notice_is_removed(self):
        script_path = os.path.join(APP_DIR, 'static', 'js', 'app.js')
        with open(script_path, encoding='utf-8') as script:
            source = script.read()
        self.assertNotIn("Room bookings for this Friday aren't open yet", source)
        self.assertNotIn('roomsPendingNotice', source)

    def test_winter_room_hours_and_booking_boundaries(self):
        from test_attendee_booking_experience import run_isolated
        result = run_isolated('''
            from datetime import datetime
            from unittest.mock import patch
            from app import app, Booking, booking_time_display, init_default_data

            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 11, 10, 12, tzinfo=tz)

            expected = {
                '2026-11-27': {'Room 4.4 "Rose"': '3:00 PM', 'Room 4.7 "Clerkenwell"': '6:00 PM'},
                '2026-12-04': {'Room 4.4 "Rose"': '6:00 PM', 'The Loft': '6:00 PM'},
                '2026-12-11': {'Room 4.4 "Rose"': '6:00 PM', 'Room 4.7 "Clerkenwell"': '6:00 PM'},
                '2026-12-18': {'Room 4.4 "Rose"': '6:00 PM', 'Room 4.7 "Clerkenwell"': '6:00 PM'},
            }
            with app.app_context(), patch('app.datetime', Clock), patch('app.send_emails_async'):
                init_default_data()
                client = app.test_client()
                assert set(expected) <= {day['date'] for day in client.get('/api/fridays').json}
                for day, closes in expected.items():
                    rooms = client.get('/api/rooms', query_string={'date': day}).json
                    assert {room['name']: room['override_end'] for room in rooms} == closes
                    assert all(room['override_start'] == '9:30 AM' for room in rooms)
                    rose = next(room for room in rooms if room['room_type'] == 'slot')
                    slots = client.get(f"/api/availability/{day}/{rose['id']}").json
                    assert slots[-1]['display'] == closes[rose['name']]
                    assert not slots[-1]['available'] and slots[-2]['available']
                    start, end = slots[-2]['index'], slots[-1]['index']
                    booking = dict(room_id=rose['id'], date=day, name='Test Person',
                                   email='test@example.test', mobility_needs=False,
                                   room_guidance_agreed=True, start_slot=start, end_slot=end)
                    assert client.post('/api/book', json={**booking, 'end_slot': end + 1}).status_code == 400
                    response = client.post('/api/book', json=booking)
                    assert response.status_code == 200, response.json
                    saved = Booking.query.filter_by(room_id=rose['id']).order_by(Booking.id.desc()).first()
                    assert booking_time_display(saved) == (slots[-2]['display'], closes[rose['name']])
                homepage = client.get('/').get_data(as_text=True)
                assert '27th November (9.30am to 3pm)' in homepage
                assert '27th November (9.30am to 6pm)' in homepage
                assert client.get('/api/slots').json[-1]['time'] == '17:00'
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
