"""Returning-booker behaviour and separation of public and private answers."""
import unittest
from test_attendee_booking_experience import run_isolated


class MobilityHistoryTest(unittest.TestCase):
    def test_reuse_changed_answers_admin_and_private_email_links(self):
        result = run_isolated('''
            import csv, io, re
            from datetime import date, datetime, timedelta
            from unittest.mock import patch
            from app import app, db, Room, Booking, MobilityAccessLink, previous_mobility_booking, new_mobility_link, run_migrations
            from app import ROOM_SCHEDULE_BY_NAME
            for day in ('2099-01-02', '2099-01-09', '2099-01-16', '2099-01-23'):
                ROOM_SCHEDULE_BY_NAME[day] = ['Clerkenwell']
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
                    # Ordinary confirmations are safe to forward; no credentials.
                    assert '/mobility/access/' not in batch[0][2]
                    assert '/mobility/access/' not in str(public_no)
                    assert 'Lift access' not in str(public_no)
                    assert MobilityAccessLink.query.count() == 0
                    assert previous_mobility_booking('person@example.test', ' TEST  Person ').id == old.id
                    # Known/unknown addresses and valid/invalid dates must be
                    # indistinguishable, without inspecting any history.
                    count = Booking.query.count()
                    outcomes = []
                    with patch('app.previous_mobility_booking', side_effect=AssertionError('Unverified history lookup')):
                        for email in ('person@example.test', 'new@example.test'):
                            for day in ('2099-01-09', '2020-01-03'):
                                response = client.post('/api/book', json=dict(body, email=email, date=day, mobility_needs=True, mobility_reuse=True))
                                assert response.status_code == 400
                                outcomes.append(response.json)
                    assert all(outcome == outcomes[0] for outcome in outcomes)
                    assert Booking.query.count() == count
                    assert client.post('/api/book', json=dict(body, mobility_needs=False, mobility_reuse=True)).status_code == 400
                public_list = client.post('/api/my-bookings', json={'email':'person@example.test'})
                assert 'Lift access' not in public_list.text and '/mobility/access/' not in public_list.text
                # Public cancel tokens cannot serve as a history access link.
                assert client.get('/mobility/access/old-cancel').status_code == 410
                assert client.get('/api/mobility/history').json == {'verified':False}
                url = new_mobility_link('person@example.test', 'request', timedelta(minutes=30))
                another_url = new_mobility_link('person@example.test', 'request', timedelta(minutes=30))
                url = '/mobility/access/' + url.rsplit('/', 1)[-1]
                another_url = '/mobility/access/' + another_url.rsplit('/', 1)[-1]
                db.session.commit()
                token = url.rsplit('/', 1)[-1]
                assert MobilityAccessLink.query.first().token_hash != token
                access_response = client.get(url)
                assert access_response.status_code == 302
                assert 'HttpOnly' in access_response.headers['Set-Cookie']
                assert 'SameSite=Lax' in access_response.headers['Set-Cookie']
                assert 'Secure' in access_response.headers['Set-Cookie']
                assert 'Max-Age=900' in access_response.headers['Set-Cookie']
                metadata = client.get('/api/mobility/history')
                assert metadata.json['verified'] is True
                assert 'email' not in metadata.json and 'previous' not in metadata.json
                assert 'person@example.test' not in metadata.text and 'Lift access' not in metadata.text
                assert client.post('/api/mobility/history', json={'email':'someoneelse@example.test','name':'Test Person'}).json == {'verified':False}
                history = client.post('/api/mobility/history', json={'email':'person@example.test','name':' Test  PERSON '})
                assert history.json['email'] == 'person@example.test'
                assert history.json['previous']['details'] == old.mobility_details
                assert history.headers['Cache-Control'] == 'no-store'
                assert client.get('/book').headers['Referrer-Policy'] == 'no-referrer'
                with patch('app.send_emails_async'):
                    # Verified reuse works even when the most recent answer was No.
                    response = client.post('/api/book', json=dict(body, date='2099-01-09', mobility_needs=True, mobility_reuse=True))
                    assert response.status_code == 200, response.json
                    saved = db.session.get(Booking, response.json['booking_id'])
                    assert saved.mobility_details == old.mobility_details and not saved.mobility_review_needed
                    assert 'Lift access' not in response.text and '/mobility/access/' not in response.text
                    assert client.post('/api/book', json=dict(body, email='other@example.test', mobility_needs=True, mobility_reuse=True)).json == outcomes[0]
                    # Verified readers get an explicit check before changing Yes to No.
                    assert client.post('/api/book', json=dict(body, mobility_needs=False, mobility_history_reviewed=True)).status_code == 400
                    response = client.post('/api/book', json=dict(body, date='2099-01-16', mobility_needs=False, mobility_history_reviewed=True, mobility_change_confirmed=True))
                    assert response.status_code == 200
                    # A cookie by itself must not impose a hidden confirmation.
                    assert client.post('/api/book', json=dict(body, date='2099-01-23', mobility_needs=False)).status_code == 200
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
                other_tab = app.test_client()
                assert other_tab.get(another_url).status_code == 302
                assert client.post('/api/mobility/forget').status_code == 200
                assert client.get('/api/mobility/history').json == {'verified': False}
                assert other_tab.get('/api/mobility/history').json == {'verified': False}
                assert client.get(url).status_code == 410 and client.get(another_url).status_code == 410
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
                    assert client.post('/api/mobility/history', json={'email':'new@example.test','name':'New Person'}).json['previous'] is None
                    # Verification expires independently of the email link.
                    private_session = MobilityAccessLink.query.filter_by(kind='session').one()
                    private_session.expires_at = datetime.utcnow() - timedelta(seconds=1)
                    db.session.commit()
                    assert client.get('/api/mobility/history').json == {'verified': False}
                    assert client.post('/api/book', json={'room_id':1,'date':'2099-01-02','name':'New Person',
                        'email':'new@example.test','mobility_needs':True,'mobility_reuse':True}).status_code == 400
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
                    assert client.post('/api/mobility/request-link', json=['wrong']).status_code == 400
                with patch('app.reminders_mail_ready', return_value=False):
                    assert client.post('/api/mobility/request-link', json={'email':'unique@example.test'}, environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code == 503
                    assert client.get('/book').status_code == 200
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_inbox_legacy_links_cleanup_and_migrations(self):
        result = run_isolated('''
            from datetime import date, datetime, timedelta
            from unittest.mock import patch
            from app import app, db, Room, Booking, MobilityAccessLink, new_mobility_link, run_migrations
            from app import ROOM_SCHEDULE_BY_NAME
            for day in ('2099-01-02', '2099-01-09', '2099-01-16', '2099-01-23'):
                ROOM_SCHEDULE_BY_NAME[day] = ['Clerkenwell']
            with app.app_context():
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room)
                db.session.flush()
                old = Booking(room_id=room.id, user_name='First Person', user_email='shared@example.test',
                    booking_date=date(2026,9,18), start_slot=0, end_slot=16, cancel_token='old',
                    mobility_needs=True, mobility_details='First person private wording')
                db.session.add(old)
                db.session.commit()
                body = dict(room_id=room.id, date='2099-01-02', email='shared@example.test')
                client = app.test_client()
                legacy = new_mobility_link(body['email'], 'book_again', timedelta(days=90))
                expired = new_mobility_link(body['email'], 'request', timedelta(days=-2))
                db.session.commit()
                assert client.get(legacy).status_code == 410
                run_migrations()
                run_migrations()
                assert Booking.query.count() == 1
                assert MobilityAccessLink.query.filter_by(kind='book_again').one().expires_at <= datetime.utcnow()
                link = new_mobility_link(body['email'], 'request', timedelta(minutes=30))
                unrelated = new_mobility_link('unrelated@example.test', 'request', timedelta(minutes=30))
                link = '/mobility/access/' + link.rsplit('/', 1)[-1]
                unrelated = '/mobility/access/' + unrelated.rsplit('/', 1)[-1]
                db.session.commit()
                assert MobilityAccessLink.query.filter(MobilityAccessLink.expires_at < datetime.utcnow()-timedelta(days=1)).count() == 0
                assert client.get(link).status_code == 302
                second = dict(email=body['email'], name='Second Person')
                assert client.post('/api/mobility/history', json=second).json['previous'] is None
                with patch('app.send_emails_async') as emails:
                    assert client.post('/api/book', json=dict(body, name=second['name'], mobility_needs=True, mobility_reuse=True)).status_code == 400
                    response = client.post('/api/book', json=dict(body, name=second['name'], mobility_needs=False))
                    assert response.status_code == 200, response.json
                    assert not db.session.get(Booking, response.json['booking_id']).mobility_review_needed
                    assert 'First person private wording' not in str(emails.call_args)
                    first_no = client.post('/api/book', json=dict(body, date='2099-01-09', name='First Person', mobility_needs=False))
                    assert first_no.status_code == 200, first_no.json
                with client.session_transaction() as session:
                    session['admin_logged_in'] = True
                rows = client.get('/api/admin/bookings').json
                assert next(row for row in rows if row['id'] == first_no.json['booking_id'])['mobility_review_needed']
                assert not next(row for row in rows if row['id'] == response.json['booking_id'])['mobility_review_needed']
                assert client.post('/api/mobility/forget').status_code == 200
                assert client.get(link).status_code == 410
                assert client.get(unrelated).status_code == 302
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
