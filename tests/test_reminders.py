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
        return subprocess.run(
            [sys.executable, '-c', textwrap.dedent(script)],
            cwd=APP_DIR,
            env={**os.environ, 'RENDER': '1', 'RENDER_DISK_PATH': disk,
                 'ENABLE_EMAIL': 'true', 'SMTP_PASSWORD': 'dummy'},
            capture_output=True, text=True, timeout=120,
        )


class ReminderTest(unittest.TestCase):
    def test_scheduler_endpoint_needs_secret_header(self):
        result = run_isolated('''
            import json
            import os
            from unittest.mock import patch
            from app import app
            client = app.test_client()
            with patch.dict(os.environ, {'REMINDER_JOB_TOKEN': 'private-token'}):
                no_header = client.post('/api/internal/send-reminders').status_code
                wrong_header = client.post('/api/internal/send-reminders',
                    headers={'X-Reminder-Token': 'incorrect'}).status_code
                right_header = client.post('/api/internal/send-reminders',
                    headers={'X-Reminder-Token': 'private-token'})
            print(json.dumps({'no_header': no_header, 'wrong_header': wrong_header,
                              'right_header': right_header.status_code,
                              'counts': right_header.get_json()}))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual((data['no_header'], data['wrong_header']), (404, 404))
        self.assertEqual(data['right_header'], 200)
        self.assertEqual(data['counts']['failed'], 0)

    def test_opt_in_and_daily_delivery_are_confirmed_and_idempotent(self):
        result = run_isolated('''
            import json
            from datetime import date, datetime
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import (app, db, Booking, Room, ReminderSubscription,
                             ReminderDelivery, run_reminder_job)

            with app.app_context():
                room = Room(name='Room 4.4 "Rose"', building_location='Floor 4', room_type='slot')
                db.session.add(room)
                db.session.flush()
                db.session.add(Booking(room_id=room.id, user_name='Attendee',
                    user_email='attendee@example.test', booking_date=date(2026, 10, 2),
                    start_slot=2, end_slot=4, cancel_token='valid-token'))
                db.session.commit()
                client = app.test_client()
                sent = []
                def fake_send(to, subject, body):
                    sent.append((to, subject, body))
                    return True

                with patch('app.send_confirmation_email', side_effect=fake_send):
                    signup = client.post('/reminders/request', data={
                        'email': 'Attendee@Example.test', 'booking_open': 'on', 'booking_day': 'on'})
                    subscription = ReminderSubscription.query.one()
                    before_confirm = run_reminder_job(datetime(2026, 9, 29, 9, tzinfo=ZoneInfo('Europe/London')))
                    confirmation = client.post('/reminders/confirm/' + subscription.confirm_token)
                    # The person already booked Friday, so there is no "please book" email.
                    open_day = run_reminder_job(datetime(2026, 9, 29, 9, tzinfo=ZoneInfo('Europe/London')))
                    too_early = run_reminder_job(datetime(2026, 10, 1, 9, 30, tzinfo=ZoneInfo('Europe/London')))
                    day_before = run_reminder_job(datetime(2026, 10, 1, 10, 30, tzinfo=ZoneInfo('Europe/London')))
                    repeated = run_reminder_job(datetime(2026, 10, 1, 11, 30, tzinfo=ZoneInfo('Europe/London')))
                    manage = client.post('/reminders/manage/' + subscription.manage_token, data={})
                    after_stop = run_reminder_job(datetime(2026, 10, 8, 9, tzinfo=ZoneInfo('Europe/London')))

                print(json.dumps({'signup': signup.status_code, 'confirmation': confirmation.status_code,
                    'before_confirm': before_confirm, 'open_day': open_day,
                    'too_early': too_early, 'day_before': day_before, 'repeated': repeated, 'manage': manage.status_code,
                    'after_stop': after_stop, 'sent': sent,
                    'deliveries': ReminderDelivery.query.count(),
                    'booking_open': subscription.booking_open, 'booking_day': subscription.booking_day}))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data['signup'], 200)
        self.assertEqual(data['confirmation'], 200)
        self.assertEqual(data['before_confirm']['booking_day'], 0)
        self.assertEqual(data['open_day']['booking_open'], 0)
        self.assertEqual(data['too_early']['booking_day'], 0)
        self.assertEqual(data['day_before']['booking_day'], 1)
        self.assertEqual(data['repeated']['booking_day'], 0)
        self.assertEqual(data['deliveries'], 1)
        self.assertEqual(len(data['sent']), 2)  # confirmation plus one booked-session reminder
        self.assertIn('/cancel/valid-token', data['sent'][1][2])
        self.assertEqual(data['after_stop']['booking_open'], 0)
        self.assertFalse(data['booking_open'])
        self.assertFalse(data['booking_day'])

    def test_unreleased_friday_and_cancelled_booking_are_not_reminded(self):
        result = run_isolated('''
            import json
            from datetime import date, datetime
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import (app, db, Booking, Room, ReminderSubscription,
                             run_reminder_job)

            with app.app_context():
                room = Room(name='Room 4.4 "Rose"', building_location='Floor 4', room_type='slot')
                db.session.add(room)
                db.session.flush()
                db.session.add(Booking(room_id=room.id, user_name='Attendee',
                    user_email='attendee@example.test', booking_date=date(2026, 10, 2),
                    start_slot=2, end_slot=4, cancel_token='cancelled-token',
                    cancelled_at=datetime(2026, 9, 29)))
                db.session.add(ReminderSubscription(email='attendee@example.test',
                    manage_token='manage-token', booking_open=True, booking_day=True,
                    confirmed_at=datetime(2026, 9, 28)))
                db.session.commit()
                with patch('app.send_confirmation_email', return_value=True) as send:
                    thursday = run_reminder_job(datetime(2026, 10, 1, 9, tzinfo=ZoneInfo('Europe/London')))
                    unreleased = run_reminder_job(datetime(2026, 10, 26, 9, tzinfo=ZoneInfo('Europe/London')))
                    repeat = run_reminder_job(datetime(2026, 10, 1, 9, tzinfo=ZoneInfo('Europe/London')))
                print(json.dumps({'thursday': thursday, 'unreleased': unreleased,
                                  'repeat': repeat, 'sends': send.call_count}))
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data['thursday']['booking_open'], 1)
        self.assertEqual(data['thursday']['booking_day'], 0)
        self.assertEqual(data['unreleased']['booking_open'], 0)
        self.assertEqual(data['repeat']['booking_open'], 0)
        self.assertEqual(data['sends'], 1)


if __name__ == '__main__':
    unittest.main()
