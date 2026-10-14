"""Name validation and staff corrections use an isolated database, with no mail."""
import unittest
from test_attendee_booking_experience import run_isolated


class BookingNameTest(unittest.TestCase):
    def test_initials_cannot_bypass_form_validation(self):
        result = run_isolated('''
            from unittest.mock import patch
            from app import app, db, Room, Booking
            with app.app_context(), patch('app.send_confirmation_email', return_value=True):
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room); db.session.commit()
                client = app.test_client()
                body = dict(room_id=room.id, date='2099-01-02', name='Helen Johnson',
                            email='test@example.test', mobility_needs=False)
                for name in ('H Johnson', 'He Johnson', 'Helen J', 'Helen Jo',
                             'Helen', '', 'H  Johnson', 'H \\t e Johnson', 12, None):
                    response = client.post('/api/book', json=dict(body, name=name))
                    assert response.status_code == 400, (name, response.json)
                for first, last in (('H', 'Johnson'), ('Helen', 'J'), (' H ', 'Johnson'),
                                    ('H e', 'Johnson'), (None, 'Johnson'), (7, 'Johnson')):
                    response = client.post('/api/book', json=dict(body, first_name=first, last_name=last))
                    assert response.status_code == 400, response.json
                assert Booking.query.count() == 0
                for index, names in enumerate(({}, dict(first_name=' Ana ', last_name=' Lee '),
                                               dict(first_name='Anne Marie', last_name="O'Neil"),
                                               dict(first_name='Zoë', last_name='李小明'))):
                    response = client.post('/api/book', json=dict(body, email=f'{index}@example.test', **names))
                    assert response.status_code == 200, response.json
                assert Booking.query.count() == 4
                assert Booking.query.filter_by(user_email='1@example.test').one().user_name == 'Ana Lee'
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staff_correction_is_authenticated_preserves_booking_and_updates_report(self):
        result = run_isolated('''
            import csv, io
            from datetime import date
            from unittest.mock import patch
            from app import app, db, Room, Booking
            from building_reports import build_snapshot
            with app.app_context(), patch('app.send_confirmation_email') as send, patch('app.send_emails_async') as async_send:
                room = Room(name='Clerkenwell', room_type='open', building_location='Test')
                db.session.add(room); db.session.flush()
                booking = Booking(room_id=room.id, booking_date=date(2099,1,2), user_name='H Johnson',
                    user_email='test@example.test', start_slot=0, end_slot=11,
                    cancel_token='keep-token', mobility_needs=True, mobility_details='Step-free access',
                    companion_names='Sam Smith', bringing_others=True, additional_attendees=1)
                db.session.add(booking); db.session.commit()
                original = {c.name: getattr(booking, c.name) for c in Booking.__table__.columns}
                client = app.test_client()
                url = f'/api/admin/bookings/{booking.id}/name'
                body = dict(name='Helen Johnson', original_name='H Johnson')
                unauthorised = client.patch(url, json=body)
                assert unauthorised.status_code == 302 and '/admin/login' in unauthorised.location
                with client.session_transaction() as session:
                    session['admin_logged_in'] = True
                for name in ('', 'Helen', 'x'*121, None, 7):
                    assert client.patch(url, json=dict(body, name=name)).status_code == 400
                    assert db.session.get(Booking, booking.id).user_name == 'H Johnson'
                assert client.patch(url, json=['Helen Johnson']).status_code == 400
                response = client.patch(url, json=dict(body, name='  Helen   Johnson  '))
                assert response.status_code == 200, response.json
                db.session.refresh(booking)
                updated = {c.name: getattr(booking, c.name) for c in Booking.__table__.columns}
                assert updated == dict(original, user_name='Helen Johnson')
                assert client.patch(url, json=body).status_code == 409
                assert client.patch('/api/admin/bookings/999/name', json=body).status_code == 404
                assert client.get('/api/admin/bookings').json[0]['user_name'] == 'Helen Johnson'
                export = list(csv.DictReader(io.StringIO(client.get('/api/admin/bookings/export').text)))
                assert export[0]['Name'] == 'Helen Johnson'
                assert {'name': 'Helen Johnson'} in build_snapshot(date(2099,1,2))['attendees']
                # Staff can help people whose genuine names are shorter than the public minimum.
                assert client.patch(url, json=dict(name='Jo Li', original_name='Helen Johnson')).status_code == 200
                send.assert_not_called(); async_send.assert_not_called()
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
