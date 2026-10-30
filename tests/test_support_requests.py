"""Support approval must be explicit, private, date-bound and enforced by the API."""
import unittest
from test_attendee_booking_experience import run_isolated


class SupportRequestTest(unittest.TestCase):
    def test_review_and_date_bound_booking_permission(self):
        result = run_isolated('''
            import re
            from unittest.mock import patch
            from app import app, db, Room, Booking, SupportRequest, ROOM_SCHEDULE_BY_NAME, attendee_count
            from support_requests import approved_request
            ROOM_SCHEDULE_BY_NAME['2099-01-02'] = ['Clerkenwell']
            ROOM_SCHEDULE_BY_NAME['2099-01-09'] = ['Clerkenwell']
            with app.app_context():
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room); db.session.commit()
                client = app.test_client()
                body = dict(room_id=room.id, date='2099-01-02', name='Example Person',
                            email='person@example.test', mobility_needs=False,
                            bringing_others=True, attendee_type='companion',
                            companions=[dict(first_name='Sam', last_name='Smith'), dict(first_name='Alex', last_name='Jones')])
                with patch('app.send_emails_async') as queued, patch('app.send_confirmation_email', return_value=True) as mail:
                    assert client.post('/api/book', json=body).status_code == 400
                    # Cached forms cannot hide a second companion behind the carer fields.
                    assert client.post('/api/book', json=dict(body, attendee_type=None, carer_attending=True)).status_code == 400
                    request_data = dict(name='Example Person', email='person@example.test', date='2099-01-02',
                        supporters='Sam Smith\\nAlex Jones', reason='Two people provide different practical support.')
                    submitted = client.post('/support-requests', data=request_data)
                    assert submitted.status_code == 200, submitted.text
                    assert Booking.query.count() == 0
                    assert SupportRequest.query.count() == 1
                    notice_mail = queued.call_args.args[0]
                    assert 'different practical support' not in str(notice_mail)
                    assert client.post('/support-requests', data=request_data).status_code == 200
                    assert SupportRequest.query.count() == 1 and queued.call_count == 1
                    assert client.get('/admin/support-requests').status_code == 302
                    with client.session_transaction() as auth:
                        auth['admin_logged_in'] = True
                    page = client.get('/admin/support-requests')
                    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
                    endpoint = '/admin/support-requests/1/decision'
                    assert client.get(endpoint).status_code == 405
                    assert client.post(endpoint, data=dict(decision='approved')).status_code == 403
                    decided = client.post(endpoint, data=dict(decision='approved', csrf=csrf))
                    assert decided.status_code == 200
                    token = re.search(r'&support=([A-Za-z0-9_-]+)', mail.call_args.args[2])[1]
                    assert SupportRequest.query.one().token_hash != token
                    assert Booking.query.count() == 0
                    assert client.post(endpoint, data=dict(decision='approved', csrf=csrf)).status_code == 409
                    assert mail.call_count == 1
                    approval_page = client.get('/book?date=2099-01-02&support=' + token)
                    assert 'Alex Jones' in approval_page.text
                    assert approval_page.headers['Referrer-Policy'] == 'no-referrer'
                    carer = dict(body, companions=[], attendee_type='carer', carer_attending=True,
                        carer_first_name='Sam', carer_last_name='Smith', carer_organisation='Family',
                        carer_phone='07000000000', carer_supervision_agreed=True, support_approval_token=token)
                    for changed in [dict(email='other@example.test'), dict(name='Other Person'),
                                    dict(date='2099-01-09'), dict(support_approval_token='x'*43),
                                    dict(carer_first_name='Wrong')]:
                        reply = client.post('/api/book', json=dict(carer, **changed))
                        assert reply.status_code == 400, reply.get_json()
                    saved = client.post('/api/book', json=carer)
                    assert saved.status_code == 200, saved.get_json()
                    booking = Booking.query.one()
                    assert booking.companion_names == 'Sam Smith; Alex Jones'
                    assert attendee_count(booking) == 3
                    from building_reports import build_snapshot
                    assert {p["name"] for p in build_snapshot(booking.booking_date)["attendees"]} == {"Example Person", "Sam Smith", "Alex Jones"}
                    # Named support people are included in reception reporting.
                    assert booking.additional_attendees == 2
                    with patch('app.booking_registration_closed', return_value=True):
                        assert approved_request(token) is None
                        assert client.post('/api/book', json=carer).status_code == 409
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_declined_and_closed_requests_cannot_grant_access(self):
        result = run_isolated('''
            import re
            from unittest.mock import patch
            from app import app, db, Room, SupportRequest, ROOM_SCHEDULE_BY_NAME
            from support_requests import approved_request
            ROOM_SCHEDULE_BY_NAME['2099-01-02'] = ['Clerkenwell']
            with app.app_context():
                db.session.add(Room(name='Clerkenwell', room_type='open')); db.session.commit()
                c = app.test_client()
                data = dict(name='Example Person', email='person@example.test', date='2099-01-02',
                            supporters='Sam Smith\\nAlex Jones', reason='Two people provide practical support.')
                with patch('app.send_emails_async'), patch('app.send_confirmation_email', return_value=False):
                    assert c.post('/support-requests', data=data).status_code == 200
                    with c.session_transaction() as auth: auth['admin_logged_in'] = True
                    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get('/admin/support-requests').text)[1]
                    endpoint = '/admin/support-requests/1/decision'
                    with patch('app.booking_registration_closed', return_value=True):
                        assert c.post(endpoint, data=dict(decision='approved', csrf=csrf)).status_code == 409
                    assert c.post(endpoint, data=dict(decision='declined', csrf=csrf)).status_code == 400
                    declined = c.post(endpoint, data=dict(decision='declined', csrf=csrf, note='Please contact us about an alternative.'))
                    assert declined.status_code == 200 and 'could not be confirmed' in declined.text
                    assert SupportRequest.query.one().status == 'declined'
                    assert SupportRequest.query.one().token_hash is None
                    assert approved_request('x'*43) is None
                    assert c.post(endpoint, data=dict(decision='approved', csrf=csrf)).status_code == 409
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_short_email_keeps_notes_links_and_clear_cancel_action(self):
        result = run_isolated('''
            from datetime import date
            from unittest.mock import patch
            from app import app, db, Room, Booking, set_setting, send_confirmation_email
            from booking_emails import confirmation_text, html_message
            with app.app_context():
                room = Room(name='Rose', room_type='slot', building_location='Floor 4')
                db.session.add(room); db.session.flush()
                b = Booking(room_id=room.id, user_name='Example Person', user_email='person@example.test',
                    booking_date=date(2099,1,2), start_slot=3, end_slot=5, cancel_token='private-token')
                db.session.add(b); db.session.commit()
                set_setting('confirmation_message', 'Dear {{name}},\\n\\nYour booking has been confirmed!\\n\\nRoom: {{room_name}}\\nDate: {{date}}\\n\\nPlease read the building health and safety policies: https://example.test/safety?a=1&b=2\\n\\nTo cancel your booking, visit:\\n{{cancel_url}}')
                with patch('app.get_room_note', return_value='No step-free access on this date.'):
                    text = confirmation_text(b, 'https://booking.example.test')
                assert text.count('/cancel/private-token') == 1
                assert text.index('/cancel/private-token') < text.index('Before you visit')
                for important in ['No step-free access', 'health and safety', '24 hours', 'fire wardens',
                                  'Thursday at 10am', 'supervision', 'suspension or a ban', 'three-strikes']:
                    assert important in text, important
                assert text.count('/community-guidelines') == 1
                html = html_message(text)
                assert '&amp;b=2' in html and '&amp;amp;' not in html
                assert 'View or cancel your booking' in html
                assert '\\xa0' not in html and 'Apple-converted-space' not in html
                assert 'max-width' not in html and 'width:' not in html
                app.config.update(ENABLE_EMAIL=True, SMTP_USER='sender@example.test', SMTP_PASSWORD='fake', SMTP_FROM='sender@example.test')
                with patch('app.send_smtp_message') as smtp:
                    assert send_confirmation_email('person@example.test', 'Booking Confirmed: Rose', text)
                    parts = smtp.call_args.args[0].get_payload()
                    assert [part.get_content_type() for part in parts] == ['text/plain', 'text/html']
                    assert parts[1].get_payload(decode=True).decode() == html
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
