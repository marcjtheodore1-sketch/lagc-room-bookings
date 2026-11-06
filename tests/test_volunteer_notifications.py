"""Exercise rota saves and email outcomes against an isolated SQLite database."""
import unittest
from test_attendee_booking_experience import run_isolated


SETUP = '''
import json
import smtplib
from datetime import date
from unittest.mock import patch
from app import app, db, VolunteerAvailability, VolunteerRotaNotification, EmailDeliveryUncertain
from volunteer_notifications import deliver_notification
ctx = app.app_context()
ctx.push()
app.config.update(ENABLE_EMAIL=True, SMTP_USER='sender@example.test',
    SMTP_FROM='sender@example.test', SMTP_PASSWORD='dummy')
patch('app.get_rota_fridays', return_value=[
    {'date':'2099-01-02', 'display':'First Friday'},
    {'date':'2099-01-09', 'display':'Second Friday'}]).start()
client = app.test_client()
with client.session_transaction() as session:
    session['admin_logged_in'] = True
sent = []
def capture(message, recipients=None):
    # SMTP must only run after the changes and audit entry have been committed.
    assert VolunteerRotaNotification.query.filter_by(status='sending').count() >= 1
    sent.append((message, recipients))
smtp = patch('app.send_smtp_message', side_effect=capture).start()
def available(day='2099-01-02', start='09:00', end='17:00', note=''):
    return dict(date=day, status='available', shift_type='specific',
                start_time=start, end_time=end, note=note)
def save(entries, name='Test Volunteer'):
    response = client.post('/api/admin/volunteers', json=dict(name=name, entries=entries))
    assert response.status_code == 200, response.get_json()
    return response.json
def text_of(message):
    return message.get_payload()[0].get_payload(decode=True).decode('utf-8')
'''


class VolunteerNotificationsTest(unittest.TestCase):
    def run_case(self, script):
        import textwrap
        result = run_isolated(SETUP + '\n' + textwrap.dedent(script))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_transitions_summary_times_noops_and_note_privacy(self):
        self.run_case('''
            result = save([available('2099-01-09', note='Private note'), available()])
            assert result['notification']['status'] == 'sent'
            assert len(sent) == 1
            message, recipients = sent[0]
            assert recipients == ['florence.perdriel@gmail.com']
            assert message['To'] == recipients[0] and message['Cc'] is None
            assert message['From'] == 'sender@example.test'
            body = text_of(message)
            assert 'Friday 2nd January 2099: Not recorded → Available (9am to 5pm)' in body
            assert body.index('2nd January') < body.index('9th January')
            assert 'Private note' not in body
            assert message.get_payload()[1].get_content_type() == 'text/html'
            assert save([available(note='New private note')], name=' test volunteer ')['notification']['status'] == 'unchanged'
            assert len(sent) == 1
            assert VolunteerAvailability.query.filter_by(booking_date=date(2099,1,2)).one().note == 'New private note'
            save([dict(date='2099-01-02', status='unavailable')])
            assert 'Available (9am to 5pm) → Not available' in text_of(sent[-1][0])
            assert VolunteerAvailability.query.filter_by(booking_date=date(2099,1,2)).one().unavailable
            save([available(start='10:30', end='14:45')])
            assert 'Not available → Available (10.30am to 2.45pm)' in text_of(sent[-1][0])
            save([available(start='11:00', end='14:45')])
            assert 'Available (10.30am to 2.45pm) → Available (11am to 2.45pm)' in text_of(sent[-1][0])
            save([dict(date='2099-01-02', status='clear')])
            assert 'Available (11am to 2.45pm) → Not recorded' in text_of(sent[-1][0])
            assert VolunteerAvailability.query.one().booking_date == date(2099,1,9)
            assert save([dict(date='2099-01-02', status='clear')])['notification']['status'] == 'unchanged'
            assert len(sent) == 5 and VolunteerRotaNotification.query.count() == 5
        ''')

    def test_failures_do_not_undo_changes_or_retry(self):
        self.run_case('''
            for error, expected in [(smtplib.SMTPAuthenticationError(535, b'no'), 'failed'),
                                    (EmailDeliveryUncertain('unknown'), 'uncertain')]:
                smtp.side_effect = error
                result = save([available()])
                assert result['notification']['status'] == expected
                assert 'changes are saved' in result['notification']['warning']
                assert VolunteerAvailability.query.one().start_time == '09:00'
                record = VolunteerRotaNotification.query.order_by(VolunteerRotaNotification.id.desc()).first()
                assert record.status == expected and record.error == type(error).__name__
                calls = smtp.call_count
                deliver_notification(record)
                assert save([available()])['notification']['status'] == 'unchanged'
                assert smtp.call_count == calls
                save([dict(date='2099-01-02', status='clear')])
            app.config['ENABLE_EMAIL'] = False
            calls = smtp.call_count
            result = save([available()])
            assert result['notification']['status'] == 'unavailable'
            assert result['notification']['warning']
            assert smtp.call_count == calls
            app.config['ENABLE_EMAIL'] = True
            app.config['SMTP_PASSWORD'] = ''
            result = save([dict(date='2099-01-02', status='unavailable')])
            assert result['notification']['status'] == 'unavailable' and smtp.call_count == calls
        ''')

    def test_removal_validation_auth_and_legacy_entries(self):
        self.run_case('''
            db.session.add_all([
                VolunteerAvailability(name='Test Volunteer', booking_date=date(2099,1,2), shift_type='all_day'),
                VolunteerAvailability(name='Test Volunteer', booking_date=date(2099,1,9), unavailable=True),
                VolunteerAvailability(name='Test Volunteer', booking_date=date(2000,1,7)),
                VolunteerAvailability(name='Someone Else', booking_date=date(2099,1,2))])
            db.session.commit()
            for entry in [dict(date='2099-01-02',status='available'),
                          dict(date='2099-01-03',status='unavailable'),
                          dict(date='2099-01-02',status='unavailable',note=7)]:
                response = client.post('/api/admin/volunteers',json=dict(name='Test Volunteer',entries=[available('2099-01-09'),entry]))
                assert response.status_code == 400
                assert VolunteerAvailability.query.count() == 4
            stranger = app.test_client()
            assert stranger.post('/api/admin/volunteers',json=dict(name='Test Volunteer',entries=[available()])).status_code == 302
            assert not sent and VolunteerRotaNotification.query.count() == 0
            response = client.post('/api/admin/volunteers/remove',json={'name':'test volunteer'})
            assert response.status_code == 200 and response.json['notification']['status'] == 'sent'
            body = text_of(sent[-1][0])
            assert 'Available (times not recorded) → Not recorded' in body
            assert 'Not available → Not recorded' in body
            assert '2000' not in body and len(sent) == 1
            assert VolunteerAvailability.query.count() == 2
            client.post('/api/admin/volunteers/remove',json={'name':'test volunteer'})
            client.post('/api/admin/volunteers/archive',json={'date':'2000-01-07'})
            client.post('/api/admin/volunteers/unarchive',json={'date':'2000-01-07'})
            assert len(sent) == 1
            for name in [[], 'bad\\nname', 'x'*121]:
                assert client.post('/api/admin/volunteers',json=dict(name=name,entries=[available()])).status_code == 400
        ''')

    def test_concurrent_identical_saves_notify_once(self):
        self.run_case('''
            from concurrent.futures import ThreadPoolExecutor
            def submit(_):
                local = app.test_client()
                with local.session_transaction() as session:
                    session['admin_logged_in'] = True
                response = local.post('/api/admin/volunteers',json=dict(name='Concurrent Volunteer',entries=[available()]))
                assert response.status_code == 200, response.get_data(as_text=True)
                return response.json['notification']['status']
            db.session.remove()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, range(2)))
            assert sorted(results) == ['sent', 'unchanged'], results
            assert len(sent) == 1
            assert VolunteerAvailability.query.count() == 1
            assert VolunteerRotaNotification.query.count() == 1
        ''')
