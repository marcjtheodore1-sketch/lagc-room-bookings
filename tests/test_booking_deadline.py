import unittest
from test_reminders import run_isolated


class BookingDeadlineTest(unittest.TestCase):
    def test_london_deadline_boundary_before_and_after_clock_change(self):
        result = run_isolated('''
            from datetime import date, datetime
            from zoneinfo import ZoneInfo
            from app import booking_registration_closed
            utc = ZoneInfo('UTC')
            assert not booking_registration_closed(date(2026,10,9), datetime(2026,10,8,8,59,59,tzinfo=utc))
            assert booking_registration_closed(date(2026,10,9), datetime(2026,10,8,9,tzinfo=utc))
            assert not booking_registration_closed(date(2026,10,30), datetime(2026,10,29,9,59,59,tzinfo=utc))
            assert booking_registration_closed(date(2026,10,30), datetime(2026,10,29,10,tzinfo=utc))
            assert booking_registration_closed(date(2026,10,9), datetime(2026,10,9,9,tzinfo=utc))
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_closed_dates_visible_api_enforced_existing_bookings_preserved(self):
        result = run_isolated('''
            from datetime import date, datetime
            from zoneinfo import ZoneInfo
            from unittest.mock import patch
            from app import app, db, Room, Booking
            zone = ZoneInfo('Europe/London')
            class Clock(datetime):
                value = datetime(2026,10,8,9,59,59,tzinfo=zone)
                @classmethod
                def now(cls, tz=None):
                    return cls.value.astimezone(tz) if tz else cls.value.replace(tzinfo=None)
            with app.app_context(), patch('app.datetime', Clock), patch('app.send_emails_async'), patch('app.send_confirmation_email', return_value=True):
                rose = Room(name='Rose', room_type='slot', building_location='Test')
                loft = Room(name='The Loft', room_type='open', building_location='Test')
                db.session.add_all([rose,loft]); db.session.commit()
                client = app.test_client()
                body = dict(room_id=rose.id,date='2026-10-09',name='Test Person',email='one@example.test',
                            mobility_needs=False,start_slot=0,end_slot=1)
                available = client.get('/api/availability/2026-10-09/'+str(rose.id))
                assert available.status_code == 200
                friday = next(f for f in client.get('/api/fridays').json if f['date']=='2026-10-09')
                assert not friday['registration_closed']
                saved = client.post('/api/book', json=body)
                assert saved.status_code == 200, saved.json
                assert '/help-sheet' in saved.json['confirmation_message']
                token = Booking.query.one().cancel_token
                Clock.value = datetime(2026,10,8,10,tzinfo=zone)
                for room in (rose,loft):
                    response = client.post('/api/book', json=dict(body,room_id=room.id,email='late@example.test'))
                    assert response.status_code == 409, response.json
                    assert response.json['registration_closed']
                    assert 'existing bookings remain valid' in response.json['error']
                assert client.get('/api/availability/2026-10-09/'+str(rose.id)).status_code == 409
                assert Booking.query.count() == 1
                friday = next(f for f in client.get('/api/fridays').json if f['date']=='2026-10-09')
                assert friday['registration_closed']
                Clock.value = datetime(2026,10,9,20,tzinfo=zone)
                assert any(f['date']=='2026-10-09' for f in client.get('/api/fridays').json)
                assert client.get('/cancel/'+token).status_code == 200
                assert len(client.post('/api/my-bookings',json={'email':'one@example.test'}).json) == 1
                assert client.post('/api/cancel/'+token).status_code == 200
                assert Booking.query.one().cancelled_at is not None
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_booking_open_reminders_stop_at_deadline_but_booked_reminders_continue(self):
        result = run_isolated('''
            from datetime import date, datetime
            from zoneinfo import ZoneInfo
            from unittest.mock import patch
            from app import app,db,Room,Booking,ReminderSubscription,run_reminder_job
            zone=ZoneInfo('Europe/London')
            with app.app_context():
                room=Room(name='The Loft',room_type='open',building_location='Test')
                db.session.add(room);db.session.flush()
                db.session.add(Booking(room_id=room.id,user_name='Already Booked',user_email='booked@example.test',
                    booking_date=date(2026,10,9),start_slot=0,end_slot=11,cancel_token='saved'))
                db.session.add_all([ReminderSubscription(email='unbooked@example.test',booking_open=True,
                    confirmed_at=datetime(2026,10,1),manage_token='unbooked'),
                    ReminderSubscription(email='booked@example.test',booking_day=True,
                    confirmed_at=datetime(2026,10,1),manage_token='booked')])
                db.session.commit()
                with patch('app.send_confirmation_email',return_value=True) as send:
                    after=run_reminder_job(datetime(2026,10,8,10,tzinfo=zone))
                    assert after['booking_open']==0
                    assert after['booking_day']==1
                    assert '/help-sheet' in send.call_args.args[2]
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
