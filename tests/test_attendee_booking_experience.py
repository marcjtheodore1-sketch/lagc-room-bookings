import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_isolated(script):
    with tempfile.TemporaryDirectory() as disk:
        env = {
            **os.environ,
            'RENDER': '1',
            'RENDER_DISK_PATH': disk,
            'ENABLE_EMAIL': 'false',
            'PYTHONPATH': APP_DIR,
        }
        return subprocess.run(
            [sys.executable, '-c', textwrap.dedent(script)],
            cwd=APP_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )


class AttendeeBookingExperienceTest(unittest.TestCase):
    def test_my_bookings_combines_rooms_and_yoga_without_private_answers(self):
        result = run_isolated("""
            import json
            from datetime import date
            from app import Booking, Room, YogaBooking, app, db

            with app.app_context():
                db.create_all()
                room = Room(
                    name='Room 4.7 "Clerkenwell"',
                    building_location='Floor 4 - Pan Macmillan HQ',
                    room_type='open',
                )
                db.session.add(room)
                db.session.flush()
                db.session.add(Booking(
                    room_id=room.id,
                    user_name='Example Person',
                    user_email='Example@Email.test',
                    booking_date=date(2099, 1, 2),
                    start_slot=0,
                    end_slot=16,
                    cancel_token='room-token',
                ))
                db.session.add(YogaBooking(
                    session_date=date(2099, 1, 9),
                    name='Example Person',
                    email='example@email.test',
                    phone='07000000000',
                    emergency_name='Private Contact',
                    emergency_phone='07000000001',
                    health_info='Private health answer',
                    agreed_safety=True,
                    cancel_token='yoga-token',
                ))
                db.session.commit()

                response = app.test_client().post(
                    '/api/my-bookings', json={'email': 'EXAMPLE@EMAIL.TEST'}
                )
                print(json.dumps({
                    'status': response.status_code,
                    'bookings': response.get_json(),
                }))
        """)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['status'], 200)
        self.assertEqual(
            [item['booking_type'] for item in payload['bookings']],
            ['room', 'yoga'],
        )
        self.assertEqual(
            [item['cancel_url'] for item in payload['bookings']],
            ['/cancel/room-token', '/yoga/cancel/yoga-token'],
        )
        self.assertEqual(
            payload['bookings'][1]['title'], 'Gentle Yoga with Marlijn'
        )
        self.assertNotIn('health_info', payload['bookings'][1])
        self.assertNotIn('emergency_phone', payload['bookings'][1])

    def test_self_cancelling_room_emails_admin_and_attendee(self):
        result = run_isolated("""
            import json
            from datetime import date
            from unittest.mock import patch
            from app import Booking, Room, app, db

            with app.app_context():
                db.create_all()
                room = Room(
                    name='Room 4.4 "Rose"',
                    building_location='Floor 4 - Pan Macmillan HQ',
                    room_type='slot',
                )
                db.session.add(room)
                db.session.flush()
                db.session.add(Booking(
                    room_id=room.id,
                    user_name='Example Person',
                    user_email='person@example.test',
                    booking_date=date(2099, 1, 2),
                    start_slot=1,
                    end_slot=3,
                    cancel_token='cancel-me',
                ))
                db.session.commit()

                with patch('app.send_confirmation_email', return_value=True) as send:
                    response = app.test_client().post('/api/cancel/cancel-me')
                    calls = [
                        {'recipient': call.args[0], 'subject': call.args[1],
                         'message': call.args[2]}
                        for call in send.call_args_list
                    ]
                cancelled = Booking.query.filter_by(
                    cancel_token='cancel-me'
                ).first().cancelled_at is not None
                print(json.dumps({
                    'status': response.status_code,
                    'cancelled': cancelled,
                    'calls': calls,
                }))
        """)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['status'], 200)
        self.assertTrue(payload['cancelled'])
        self.assertEqual(
            [call['recipient'] for call in payload['calls']],
            ['londonautismgroupcharity@gmail.com', 'person@example.test'],
        )
        attendee_email = payload['calls'][1]
        self.assertIn('Your room booking has been cancelled', attendee_email['subject'])
        self.assertIn('Room 4.4 "Rose"', attendee_email['message'])
        self.assertIn('Friday, January 02, 2099', attendee_email['message'])

    def test_front_end_uses_booking_specific_cancel_links(self):
        script_path = os.path.join(APP_DIR, 'static', 'js', 'app.js')
        with open(script_path, encoding='utf-8') as script:
            source = script.read()
        self.assertIn('booking.cancel_url', source)
        self.assertIn("booking.booking_type === 'yoga'", source)


if __name__ == '__main__':
    unittest.main()
