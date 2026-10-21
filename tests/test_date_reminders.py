"""One-off reminder consent, timing, privacy and duplicate-delivery safeguards."""
import unittest
from test_attendee_booking_experience import run_isolated


class DateReminderTest(unittest.TestCase):
    def check_case(self, code):
        result = run_isolated(code)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_request_requires_confirmation_and_stop_does_not_change_other_preferences(self):
        self.check_case('''
            import re
            from datetime import date, datetime
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import app,db,Room,Booking,DateBookingReminder,ReminderSubscription
            from date_reminders import token_hash,run_date_reminders
            with app.app_context(), patch('app.reminders_mail_ready',return_value=True), patch('app.send_confirmation_email',return_value=True) as confirmation, patch('date_reminders.send_date_reminder') as send:
                db.session.add(Room(name='Rose',room_type='slot')); db.session.commit()
                client=app.test_client()
                body=dict(email=' Person@Example.test ',date='2026-10-30')
                response=client.post('/reminders/date/request',data=body)
                assert response.status_code==200
                record=DateBookingReminder.query.one()
                assert record.email=='person@example.test' and record.confirmed_at is None
                token=re.search(r'/reminders/date/confirm/(\\S+)',confirmation.call_args.args[2]).group(1)
                assert record.token_hash==token_hash(token) and record.token_hash!=token
                assert Booking.query.count()==0 and ReminderSubscription.query.count()==0
                confirmation_page=client.get('/reminders/date/confirm/'+token)
                assert confirmation_page.status_code==200
                assert confirmation_page.headers['Cache-Control']=='no-store'
                assert confirmation_page.headers['Referrer-Policy']=='no-referrer'
                assert record.confirmed_at is None
                assert run_date_reminders(datetime(2026,10,28,9,tzinfo=ZoneInfo('Europe/London')))['sent']==0
                assert client.post('/reminders/date/confirm/'+token).status_code==200
                assert record.confirmed_at is not None
                assert client.post('/reminders/date/request',data=body).status_code==200
                assert confirmation.call_count==1
                assert client.get('/reminders/date/stop/'+token).status_code==200
                assert record.status=='pending'
                assert client.post('/reminders/date/stop/'+token).status_code==200
                assert record.status=='stopped'
                client.post('/reminders/date/confirm/'+token)
                assert record.status=='stopped'
                assert run_date_reminders(datetime(2026,10,28,9,tzinfo=ZoneInfo('Europe/London')))['sent']==0
                assert client.get('/reminders/date/confirm/not-a-token').status_code==404
                assert client.post('/reminders/date/request',data=dict(body,date='2026-11-27')).status_code==409
                assert client.post('/reminders/date/request',data=dict(body,date='2026-10-09')).status_code==409
                assert client.post('/reminders/date/request',data=dict(body,email='bad\\n@example.test')).status_code==400
                assert client.post('/reminders/date/request',data=dict(body,email='zara.lagc@gmail.com')).status_code==200
                assert DateBookingReminder.query.count()==1
                send.assert_not_called()
        ''')

    def test_remaining_autumn_dates_send_at_wednesday_nine_once_after_clock_change(self):
        self.check_case('''
            from datetime import date,datetime,timedelta
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import app,db,Room,DateBookingReminder,run_reminder_job
            from date_reminders import run_date_reminders,reminder_due
            zone=ZoneInfo('Europe/London')
            days=[date(2026,10,30),date(2026,11,6),date(2026,11,20)]
            with app.app_context(), patch('app.reminders_mail_ready',return_value=True), patch('date_reminders.send_date_reminder') as send:
                db.session.add(Room(name='Rose',room_type='slot'));db.session.commit()
                for day in days:
                    db.session.add(DateBookingReminder(email=f'{day}@example.test',session_date=day,token_hash=day.isoformat(),confirmed_at=datetime(2026,10,14)))
                db.session.commit()
                for day in days:
                    due=reminder_due(day)
                    assert due.weekday()==2 and due.hour==9 and due.utcoffset()==timedelta(0)
                    assert run_date_reminders(due-timedelta(seconds=1))['sent']==0
                    counts=run_reminder_job(due)
                    assert counts['date_booking']==1 and counts['failed']==0,counts
                    body=send.call_args.args[2]
                    assert 'does not reserve a place' in body and 'Thursday at 10am' in body
                    assert 'community-guidelines' in body and 'condition of attending' in body
                    assert day.isoformat() in body and 'different email address' in body
                    assert run_date_reminders(due)['sent']==0
                assert send.call_count==3
                assert all(r.status=='sent' and r.sent_at for r in DateBookingReminder.query.all())
        ''')

    def test_booked_cancelled_stopped_closed_and_withdrawn_dates(self):
        self.check_case('''
            from datetime import date,datetime
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import app,db,Room,Booking,DateBookingReminder
            from date_reminders import run_date_reminders
            day=date(2026,10,30); zone=ZoneInfo('Europe/London')
            with app.app_context(),patch('date_reminders.send_date_reminder') as send:
                room=Room(name='Rose',room_type='slot');db.session.add(room);db.session.flush()
                records={}
                for name in ['booked','cancelled','stopped','closed','withdrawn']:
                    r=DateBookingReminder(email=name+'@example.test',session_date=day,token_hash=name,confirmed_at=datetime(2026,10,14),status='stopped' if name=='stopped' else 'pending')
                    records[name]=r;db.session.add(r)
                for name in ['booked','cancelled']:
                    db.session.add(Booking(room_id=room.id,user_name='Test Person',user_email=(name+'@example.test').upper(),booking_date=day,start_slot=3,end_slot=4,cancel_token=name,cancelled_at=datetime(2026,10,14) if name=='cancelled' else None))
                db.session.commit()
                # Hold later scenarios out of the first due run.
                records['closed'].confirmed_at=None;records['withdrawn'].confirmed_at=None;db.session.commit()
                assert run_date_reminders(datetime(2026,10,28,10,tzinfo=zone))['sent']==1
                assert send.call_args.args[0]=='cancelled@example.test'
                assert records['booked'].status=='booked' and records['stopped'].status=='stopped'
                records['closed'].confirmed_at=datetime(2026,10,14);db.session.commit()
                assert run_date_reminders(datetime(2026,10,29,10,tzinfo=zone))['sent']==0
                assert records['closed'].status=='closed'
                records['withdrawn'].confirmed_at=datetime(2026,10,14);db.session.commit()
                with patch('app.get_room_schedule_ids',return_value={}):
                    assert run_date_reminders(datetime(2026,10,28,9,tzinfo=zone))['sent']==0
                assert records['withdrawn'].status=='closed'
                assert send.call_count==1
        ''')

    def test_atomic_claim_failure_retry_and_uncertain_delivery(self):
        self.check_case('''
            from datetime import date,datetime
            from unittest.mock import patch
            from zoneinfo import ZoneInfo
            from app import app,db,Room,DateBookingReminder,EmailDeliveryUncertain
            from date_reminders import run_date_reminders
            now=datetime(2026,10,28,9,tzinfo=ZoneInfo('Europe/London'))
            with app.app_context():
                db.session.add(Room(name='Rose',room_type='slot'))
                record=DateBookingReminder(email='test@example.test',session_date=date(2026,10,30),token_hash='test',confirmed_at=datetime(2026,10,14))
                db.session.add(record);db.session.commit()
                with patch('date_reminders.send_date_reminder',side_effect=RuntimeError('Definite failure')):
                    assert run_date_reminders(now)=={'sent':0,'failed':1}
                assert record.status=='failed'
                nested=[]
                def sending(*args):
                    nested.append(run_date_reminders(now))
                with patch('date_reminders.send_date_reminder',side_effect=sending) as send:
                    assert run_date_reminders(now)=={'sent':1,'failed':0}
                    assert nested==[{'sent':0,'failed':0}] and send.call_count==1
                record.status='pending';record.sent_at=None;db.session.commit()
                with patch('date_reminders.send_date_reminder',side_effect=EmailDeliveryUncertain('Uncertain')):
                    assert run_date_reminders(now)=={'sent':0,'failed':1}
                assert record.status=='uncertain'
                with patch('date_reminders.send_date_reminder') as send:
                    assert run_date_reminders(now)=={'sent':0,'failed':0}
                    send.assert_not_called()
        ''')

    def test_request_rate_limit_and_required_booking_email_wording(self):
        self.check_case('''
            from datetime import date
            from unittest.mock import patch
            from app import app,db,Room,DateBookingReminder
            from app import ROOM_SCHEDULE_BY_NAME
            ROOM_SCHEDULE_BY_NAME['2099-01-02'] = ['Clerkenwell']
            with app.app_context(),patch('app.reminders_mail_ready',return_value=True),patch('app.send_confirmation_email',return_value=True) as send,patch('app.send_emails_async') as queue:
                room=Room(name='Clerkenwell',room_type='open');db.session.add(room);db.session.commit()
                client=app.test_client()
                for index in range(21):
                    assert client.post('/reminders/date/request',data=dict(email=f'{index}@example.test',date='2026-10-30')).status_code==200
                assert send.call_count==20 and DateBookingReminder.query.count()==20
                response=client.post('/api/book',json=dict(room_id=room.id,date='2099-01-02',name='Test Person',email='booker@example.test',mobility_needs=False))
                assert response.status_code==200,response.json
                email=next(body for recipient,subject,body in queue.call_args.args[0] if recipient=='booker@example.test')
                for phrase in ['community-guidelines','condition of attending','fire wardens','24 hours','suspension or a ban','relationship with Pan Macmillan','no automatic three-strikes rule']:
                    assert phrase in email,phrase
                assert 'contact you privately' not in email
                html=client.get('/book').text
                assert 'community-guidelines' in html and 'condition of attending' in html
        ''')


if __name__ == '__main__':
    unittest.main()
