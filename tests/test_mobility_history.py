"""Returning-booker behaviour and separation of public and private answers."""
import unittest
from test_attendee_booking_experience import run_isolated


class MobilityHistoryTest(unittest.TestCase):
    def test_reuse_changed_answers_admin_and_private_email_links(self):
        result = run_isolated('''
            import csv, io, re
            from datetime import date
            from unittest.mock import patch
            from app import app, db, Room, Booking, MobilityAccessLink, previous_mobility_booking, run_migrations
            with app.app_context():
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room)
                db.session.flush()
                old = Booking(room_id=room.id, user_name='Test Person', user_email='Person@Example.test',
                    booking_date=date(2026,9,18), start_slot=0, end_slot=16,
                    mobility_needs=True, mobility_details='Lift access <script>private</script>', cancel_token='old-cancel')
                db.session.add(old)
                db.session.commit()
                client = app.test_client()
                body = dict(room_id=room.id, date='2099-01-02', name='Test Person', email='PERSON@example.test')
                assert client.get('/api/mobility/history?email=person@example.test').json == {'verified': False}
                with patch('app.send_emails_async') as emails:
                    # Ordinary No has no extra hurdle, but preserves history and alerts admins.
                    response = client.post('/api/book', json=dict(body, mobility_needs=False))
                    assert response.status_code == 200, response.json
                    public_no = response.json
                    changed = db.session.get(Booking, public_no['booking_id'])
                    assert changed.mobility_needs is False and changed.mobility_review_needed
                    assert changed.mobility_previous_booking_id == old.id
                    batch = emails.call_args.args[0]
                    assert 'Mobility answer changed' in batch[1][2]
                    assert 'Lift access' in batch[1][2]
                    # Returning link only appears in the email to the owner's address.
                    url = re.search(r'https://[^\\s]+/mobility/access/[^\\s]+', batch[0][2]).group()
                    token = url.rsplit('/', 1)[-1]
                    assert token not in str(public_no) and '/mobility/access/' not in str(public_no)
                    assert 'Lift access' not in str(public_no)
                    assert MobilityAccessLink.query.one().token_hash != token
                    assert previous_mobility_booking('person@example.test').id == old.id
                    # Hidden reuse must not be lost because the most recent answer was No.
                    response = client.post('/api/book', json=dict(body, date='2099-01-09', mobility_needs=True, mobility_reuse=True))
                    assert response.status_code == 200, response.json
                    saved = db.session.get(Booking, response.json['booking_id'])
                    assert saved.mobility_details == old.mobility_details
                    assert not saved.mobility_review_needed
                    assert 'Lift access' not in response.text
                    assert client.post('/api/book', json=dict(body, email='new@example.test', mobility_needs=True, mobility_reuse=True)).status_code == 400
                    assert client.post('/api/book', json=dict(body, mobility_needs=False, mobility_reuse=True)).status_code == 400
                public_list = client.post('/api/my-bookings', json={'email':'person@example.test'})
                assert 'Lift access' not in public_list.text and '/mobility/access/' not in public_list.text
                # Public cancel tokens cannot serve as a history access link.
                assert client.get('/mobility/access/old-cancel').status_code == 410
                assert client.get('/api/mobility/history').json == {'verified':False}
                access_response = client.get('/mobility/access/' + token)
                assert access_response.status_code == 302
                assert 'HttpOnly' in access_response.headers['Set-Cookie']
                assert 'SameSite=Lax' in access_response.headers['Set-Cookie']
                history = client.get('/api/mobility/history?email=someoneelse@example.test')
                assert history.json['email'] == 'person@example.test'
                assert history.json['previous']['details'] == old.mobility_details
                assert history.headers['Cache-Control'] == 'no-store'
                assert client.get('/book').headers['Referrer-Policy'] == 'no-referrer'
                with patch('app.send_emails_async'):
                    # Verified readers get an explicit check before changing Yes to No.
                    assert client.post('/api/book', json=dict(body, mobility_needs=False)).status_code == 400
                    response = client.post('/api/book', json=dict(body, date='2099-01-16', mobility_needs=False, mobility_change_confirmed=True))
                    assert response.status_code == 200
                    # Another email is an ordinary booking; private history must not be inferred.
                    assert client.post('/api/book', json=dict(body, email='other@example.test', mobility_needs=False)).status_code == 200
                with client.session_transaction() as session:
                    session['admin_logged_in'] = True
                rows = client.get('/api/admin/bookings').json
                changed_row = next(b for b in rows if b['id'] == changed.id)
                assert changed_row['mobility_review_needed'] is True
                assert changed_row['mobility_previous_details'] == old.mobility_details
                assert client.get('/api/admin/bookings/archive').status_code == 200
                rows = list(csv.DictReader(io.StringIO(client.get('/api/admin/bookings/export').text)))
                assert any(r['Mobility answer changed'] == 'Yes' and r['Earlier mobility details'] == old.mobility_details for r in rows)
                # Verification does not depend on one WSGI worker's Flask key.
                app.config['SECRET_KEY'] = 'another-worker-key'
                assert client.get('/api/mobility/history').json['verified'] is True
                assert client.post('/api/mobility/forget').status_code == 200
                assert client.get('/api/mobility/history').json == {'verified': False}
                run_migrations()
                run_migrations()
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_requested_links_expiry_rate_limits_and_no_enumeration(self):
        result = run_isolated('''
            import re
            from datetime import datetime, timedelta
            from unittest.mock import patch
            from app import app, db, MobilityAccessLink
            with app.app_context():
                client = app.test_client()
                with patch('app.reminders_mail_ready', return_value=True), patch('app.send_emails_async') as emails:
                    response = client.post('/api/mobility/request-link', json={'email':' New@Example.test '})
                    assert response.status_code == 200 and emails.call_count == 1
                    assert '/mobility/access/' not in response.text
                    message = emails.call_args.args[0][0][2]
                    token = re.search(r'/mobility/access/([^\\s]+)', message).group(1)
                    generic = response.json
                    assert client.post('/api/mobility/request-link', json={'email':'new@example.test'}).json == generic
                    assert emails.call_count == 1
                    assert client.get('/mobility/access/' + token).status_code == 302
                    assert client.get('/api/mobility/history').json['previous'] is None
                    # Verification expires independently of the email link.
                    private_session = MobilityAccessLink.query.filter_by(kind='session').one()
                    private_session.expires_at = datetime.utcnow() - timedelta(seconds=1)
                    db.session.commit()
                    assert client.get('/api/mobility/history').json == {'verified': False}
                    link = MobilityAccessLink.query.filter_by(kind='request').one()
                    link.expires_at = datetime.utcnow() - timedelta(seconds=1)
                    db.session.commit()
                    assert client.get('/mobility/access/' + token).status_code == 410
                    for number in range(1, 13):
                        assert client.post('/api/mobility/request-link', json={'email':f'test{number}@example.test'}).json == generic
                    assert emails.call_count == 10
                    assert MobilityAccessLink.query.filter_by(kind='request').count() == 10
                    assert client.post('/api/mobility/request-link', json={'email':123}).status_code == 400
                    assert client.post('/api/mobility/request-link', json={'email':'wrong'}).status_code == 400
                with patch('app.reminders_mail_ready', return_value=False):
                    assert client.post('/api/mobility/request-link', json={'email':'unique@example.test'}, environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code == 503
                    assert client.get('/book').status_code == 200
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
