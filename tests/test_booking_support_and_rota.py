"""Validate required support information and atomic rota updates on an isolated DB."""
import unittest
from test_attendee_booking_experience import run_isolated


class BookingSupportAndRotaTest(unittest.TestCase):
    def test_booking_validation_storage_export_and_legacy_records(self):
        result = run_isolated('''
            import csv, io
            from datetime import date
            from unittest.mock import patch
            from app import app, db, Booking, Room, run_migrations
            with app.app_context():
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room)
                db.session.commit()
                client = app.test_client()
                body = dict(room_id=room.id, date='2099-01-02', name='Test Person', email='person@example.test')
                with patch('app.send_confirmation_email', return_value=True):
                    assert client.post('/api/book', json=body).status_code == 400
                    assert client.post('/api/book', json=dict(body, mobility_needs='false')).status_code == 400
                    assert client.post('/api/book', json=dict(body, mobility_needs=True, mobility_details='  ')).status_code == 400
                    companion_body = dict(body, mobility_needs=False, bringing_others=True)
                    for bad in [None, [], 'Jo', [{}], [dict(first_name='Jo', last_name=' ')],
                                [dict(first_name='', last_name='Smith')], [dict(first_name=7, last_name='Smith')]]:
                        response = client.post('/api/book', json=dict(companion_body, companions=bad, companion_names='Jo (friend)'))
                        assert response.status_code == 400, response.get_json()
                    response = client.post('/api/book', json=dict(companion_body, email='companions@example.test',
                        companions=[dict(first_name=' Sam ', last_name=' Smith '), dict(first_name='Jo', last_name='Jones')]))
                    assert response.status_code == 200, response.get_json()
                    assert Booking.query.filter_by(user_email='companions@example.test').one().companion_names == 'Sam Smith; Jo Jones'
                    carer = dict(body, mobility_needs=True, mobility_details='Step-free access',
                        accessibility_needs='Quiet space', bringing_others=True, companions=[dict(first_name='Jo', last_name='Smith')],
                        carer_attending=True, carer_name='Legacy name', carer_organisation='Family',
                        carer_phone='07000000000', carer_supervision_agreed=True)
                    for first, last in [('', ''), ('Jo', ''), (' ', 'Smith'), ('', 'Smith')]:
                        response = client.post('/api/book', json=dict(carer, carer_first_name=first, carer_last_name=last))
                        assert response.status_code == 400, response.get_json()
                    assert Booking.query.count() == 1
                    response = client.post('/api/book', json=dict(carer, carer_first_name=' Jo ', carer_last_name=' Smith '))
                    assert response.status_code == 200, response.get_json()
                    response = client.post('/api/book', json=dict(body, email='solo@example.test', mobility_needs=False,
                        mobility_details='stale detail', carer_first_name='Hidden', carer_last_name='Name'))
                    assert response.status_code == 200, response.get_json()
                saved = Booking.query.filter_by(user_email='person@example.test').one()
                assert (saved.carer_first_name, saved.carer_last_name, saved.carer_name) == ('Jo', 'Smith', 'Jo Smith')
                assert saved.companion_names == 'Jo Smith'
                assert saved.mobility_needs is True and saved.mobility_details == 'Step-free access'
                solo = Booking.query.filter_by(user_email='solo@example.test').one()
                assert solo.mobility_details == '' and solo.carer_name == ''
                db.session.add(Booking(room_id=room.id, booking_date=date(2099,1,2), user_name='Legacy',
                    user_email='legacy@example.test', start_slot=0, end_slot=1, carer_name='Original name'))
                db.session.commit()
                run_migrations()
                run_migrations()
                with client.session_transaction() as session:
                    session['admin_logged_in'] = True
                response = client.get('/api/admin/bookings')
                assert response.status_code == 200, response.status_code
                legacy = next(b for b in response.json if b['user_name'] == 'Legacy')
                assert legacy['mobility_needs'] is None and legacy['carer_name'] == 'Original name'
                rows = list(csv.DictReader(io.StringIO(client.get('/api/admin/bookings/export').text)))
                saved = next(r for r in rows if r['Email'] == 'person@example.test')
                assert saved['Carer first name'] == 'Jo' and saved['Carer last name'] == 'Smith'
                assert saved['Mobility needs'] == 'Yes' and saved['Mobility details'] == 'Step-free access'
                assert next(r for r in rows if r['Name'] == 'Legacy')['Mobility needs'] == 'Not yet asked'
                assert client.get('/api/admin/bookings/archive').status_code == 200
                public = client.post('/api/my-bookings', json={'email': 'person@example.test'}).json
                assert all('mobility_details' not in b and 'carer_phone' not in b for b in public)
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rota_requires_explicit_times_and_preserves_records_on_error(self):
        result = run_isolated('''
            from datetime import date
            from unittest.mock import patch
            from app import app, db, VolunteerAvailability
            with app.app_context(), patch('app.get_rota_fridays', return_value=[{'date':'2099-01-02','display':'Test Friday'}, {'date':'2099-01-09','display':'Next Friday'}]):
                client = app.test_client()
                with client.session_transaction() as session:
                    session['admin_logged_in'] = True
                def save(entries):
                    return client.post('/api/admin/volunteers', json={'name':'Test Volunteer', 'entries':entries})
                entry = dict(date='2099-01-02', status='available', note='Original note')
                assert save([dict(entry, shift_type='specific', start_time='09:00', end_time='17:00')]).status_code == 200
                for bad in [entry, dict(entry, shift_type='all_day'),
                            dict(entry, shift_type='all_day', start_time='09:00', end_time='17:00'),
                            dict(entry, shift_type='specific'),
                            dict(entry, shift_type='specific', start_time='14:00', end_time='13:00'),
                            dict(entry, shift_type='specific', start_time='bad', end_time='17:00')]:
                    assert save([bad]).status_code == 400
                    assert VolunteerAvailability.query.one().shift_type == 'specific'
                    assert VolunteerAvailability.query.one().start_time == '09:00'
                assert save([]).status_code == 400
                assert save([dict(entry, shift_type='specific', start_time='10:45', end_time='17:30'),
                    {'date':'2099-01-09', 'status':'unavailable'}]).status_code == 200
                rows = VolunteerAvailability.query.order_by(VolunteerAvailability.booking_date).all()
                assert len(rows) == 2 and rows[0].start_time == '10:45' and rows[1].unavailable
                response = client.get('/api/admin/volunteers').json
                assert response['volunteers'][0]['date_shifts']['2099-01-02']['end_time'] == '17:30'
                assert response['volunteers'][0]['date_notes']['2099-01-02'] == 'Original note'
                assert response['time_options']
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
