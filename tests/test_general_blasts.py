import json
import unittest
from test_reminders import run_isolated


FIXTURE = '''
import json
from datetime import date, datetime
from unittest.mock import patch
from app import app, db, Room, Booking, YogaBooking, GeneralEmailBlast, EmailDeliveryUncertain
from general_blasts import past_recipients
app.config.update(ENABLE_EMAIL=True, SMTP_HOST='smtp.example.test',
    SMTP_USER='sender@example.test', SMTP_PASSWORD='dummy', SMTP_FROM='sender@example.test')
client = app.test_client()
with client.session_transaction() as session:
    session['admin_logged_in'] = True
with app.app_context():
    room = Room(name='Rose', room_type='slot', building_location='Example')
    db.session.add(room)
    db.session.flush()
    def book(email, day, **extra):
        db.session.add(Booking(room_id=room.id, user_name='Example', user_email=email,
            booking_date=date.fromisoformat(day), start_slot=0, end_slot=1, **extra))
    book('RECENT@example.test', '2026-07-02', attended=True)
    book('recent@example.test', '2026-09-25')
    book('edge6@example.test', '2026-04-02')
    book('edge12@example.test', '2025-10-02')
    book('older@example.test', '2025-10-01')
    book('cancelled@example.test', '2026-09-25', cancelled_at=datetime(2026,9,24))
    book('noshow@example.test', '2026-09-25', attended=False)
    book('future@example.test', '2099-10-09')
    book('zara.lagc@gmail.com', '2026-09-25')
    book('invalid', '2026-09-25')
    db.session.add(YogaBooking(name='Yoga Person', email='yoga@example.test',
        session_date=date(2026,9,11), phone='000', emergency_name='Example',
        emergency_phone='000', agreed_safety=True, attended=True))
    db.session.commit()
'''


def run_case(code):
    result = run_isolated(FIXTURE + code)
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


class GeneralBlastTest(unittest.TestCase):
    def test_calendar_month_ranges_and_honest_attendance_audience(self):
        result = run_case('''
    today = date(2026,10,2)
    print(json.dumps({p: past_recipients(p, 'bookings', today) for p in ('all','3','6','12')} |
                     {'attended': past_recipients('all','attended',today)}))
''')
        self.assertEqual(result['3'], ['recent@example.test', 'yoga@example.test'])
        self.assertEqual(result['6'], ['edge6@example.test', 'recent@example.test', 'yoga@example.test'])
        self.assertIn('edge12@example.test', result['12'])
        self.assertNotIn('older@example.test', result['12'])
        self.assertIn('older@example.test', result['all'])
        self.assertEqual(result['attended'], ['recent@example.test', 'yoga@example.test'])

    def test_draft_is_unsent_auth_protected_and_bad_period_rejected(self):
        result = run_case('''
    with patch('app.send_smtp_message') as smtp:
        draft = client.get('/api/admin/general-email/draft?period=all').get_json()
        bad = client.get('/api/admin/general-email/draft?period=2').status_code
        history = client.get('/api/admin/general-email/history').get_json()
        unauthorised = app.test_client().get('/api/admin/general-email/draft').status_code
        print(json.dumps({'draft':draft,'bad':bad,'history':history,
                          'unauthorised':unauthorised,'calls':smtp.call_count}))
''')
        self.assertEqual(result['calls'], 0)
        self.assertEqual(result['history'], [])
        self.assertEqual(result['bad'], 400)
        self.assertEqual(result['unauthorised'], 302)
        self.assertIn('before Thursday at 10am', result['draft']['body'])
        self.assertIn('Registration closes automatically', result['draft']['body'])
        self.assertIn('/help-sheet', result['draft']['body'])

    def test_bcc_privacy_edited_content_html_escaping_and_duplicate_submission(self):
        result = run_case('''
    draft = client.get('/api/admin/general-email/draft').get_json()
    draft.update(subject='Important update', body='Hello <everyone>\u005cn\u005cnBookings remain open.',
                 recipients=['new@example.test','NEW@example.test','zara.lagc@gmail.com'])
    with patch('app.send_smtp_message') as smtp:
        first = client.post('/api/admin/general-email/send',json=draft)
        again = client.post('/api/admin/general-email/send',json=draft)
        message = smtp.call_args.args[0]
        html = message.get_payload()[1].get_payload(decode=True).decode()
        print(json.dumps({'status':first.status_code,'sent':first.get_json(),
            'again':again.get_json(),'calls':smtp.call_count,'headers':str(message.items()),
            'recipients':smtp.call_args.kwargs['recipients'],'html':html,
            'history':client.get('/api/admin/general-email/history').get_json()}))
''')
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['sent']['sent_to'], 1)
        self.assertTrue(result['again']['already_sent'])
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['recipients'], ['new@example.test'])
        self.assertNotIn('new@example.test', result['headers'])
        self.assertIn('&lt;everyone&gt;', result['html'])
        self.assertEqual(result['history'][0]['status'], 'sent')

    def test_uncertain_send_is_blocked_and_disabled_mail_never_claims_success(self):
        result = run_case('''
    draft = client.get('/api/admin/general-email/draft').get_json()
    with patch('app.send_smtp_message',side_effect=EmailDeliveryUncertain('Unclear result')) as smtp:
        first = client.post('/api/admin/general-email/send',json=draft)
        again = client.post('/api/admin/general-email/send',json=draft)
        calls = smtp.call_count
    record = GeneralEmailBlast.query.first()
    app.config['ENABLE_EMAIL'] = False
    offline = client.post('/api/admin/general-email/send',json=client.get('/api/admin/general-email/draft').get_json())
    print(json.dumps({'first':first.status_code,'again':again.status_code,'calls':calls,
                     'record':record.status,'offline':offline.status_code,
                     'records':GeneralEmailBlast.query.count()}))
''')
        self.assertEqual((result['first'], result['again']), (502, 409))
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['record'], 'uncertain')
        self.assertEqual(result['offline'], 503)
        self.assertEqual(result['records'], 1)

    def test_invalid_payloads_cannot_send_or_inject_headers(self):
        result = run_case('''
    draft = client.get('/api/admin/general-email/draft').get_json()
    with patch('app.send_smtp_message') as smtp:
        statuses = [client.post('/api/admin/general-email/send',json=draft | change).status_code
            for change in ({'subject':'Hello\u005cnBcc: secret@example.test'}, {'recipients':'wrong'},
                           {'recipients':['bad']}, {'audience':[]}, {'body':''})]
        print(json.dumps({'statuses':statuses,'calls':smtp.call_count}))
''')
        self.assertEqual(result['statuses'], [400] * 5)
        self.assertEqual(result['calls'], 0)
