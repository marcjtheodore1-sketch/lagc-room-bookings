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
    {'date':'2099-01-09', 'display':'Second Friday'},
    {'date':'2099-01-16', 'display':'Third Friday'}]).start()
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
    def test_frontend_busy_and_error_states(self):
        import os
        import subprocess
        result = subprocess.run(['/opt/homebrew/opt/node@24/bin/node', '--test',
            'tests/test_volunteer_notifications.cjs'],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_case(self, script):
        import textwrap
        result = run_isolated(SETUP + '\n' + textwrap.dedent(script))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_transitions_summary_times_noops_and_note_privacy(self):
        self.run_case('''
            result = save([available(), dict(date='2099-01-16', status='unavailable')])
            assert result['notification']['status'] == 'unchanged'
            assert VolunteerAvailability.query.count() == 2
            assert not sent and VolunteerRotaNotification.query.count() == 0

            result = save([available('2099-01-09', note='New Friday'),
                           available(start='10:00', note='Private note'),
                           available('2099-01-16')])
            assert result['notification']['status'] == 'sent'
            assert VolunteerAvailability.query.count() == 3
            assert VolunteerAvailability.query.filter_by(booking_date=date(2099,1,9)).one().note == 'New Friday'
            assert len(sent) == 1
            message, recipients = sent[0]
            assert recipients == ['florence.perdriel@gmail.com']
            assert message['To'] == recipients[0] and message['Cc'] is None
            assert message['From'] == 'sender@example.test'
            body = text_of(message)
            assert 'Friday 2nd January 2099: Available (9am to 5pm) → Available (10am to 5pm)' in body
            assert 'Friday 16th January 2099: Not available → Available (9am to 5pm)' in body
            assert body.index('2nd January') < body.index('16th January')
            assert '9th January' not in body and 'New Friday' not in body
            assert 'Private note' not in body
            assert message.get_payload()[1].get_content_type() == 'text/html'
            assert save([available(start='10:00', note='New private note')], name=' test volunteer ')['notification']['status'] == 'unchanged'
            assert len(sent) == 1
            assert VolunteerAvailability.query.filter_by(booking_date=date(2099,1,2)).one().note == 'New private note'
            save([dict(date='2099-01-02', status='unavailable')])
            assert 'Available (10am to 5pm) → Not available' in text_of(sent[-1][0])
            assert VolunteerAvailability.query.filter_by(booking_date=date(2099,1,2)).one().unavailable
            save([available(start='10:30', end='14:45')])
            assert 'Not available → Available (10.30am to 2.45pm)' in text_of(sent[-1][0])
            save([available(start='11:00', end='14:45')])
            assert 'Available (10.30am to 2.45pm) → Available (11am to 2.45pm)' in text_of(sent[-1][0])
            save([dict(date='2099-01-02', status='clear')])
            assert 'Available (11am to 2.45pm) → Not recorded' in text_of(sent[-1][0])
            assert {row.booking_date for row in VolunteerAvailability.query.all()} == {date(2099,1,9), date(2099,1,16)}
            assert save([dict(date='2099-01-02', status='clear')])['notification']['status'] == 'unchanged'
            assert len(sent) == 5 and VolunteerRotaNotification.query.count() == 5
        ''')

    def test_failures_do_not_undo_changes_or_retry(self):
        self.run_case('''
            for error, expected in [(smtplib.SMTPAuthenticationError(535, b'no'), 'failed'),
                                    (EmailDeliveryUncertain('unknown'), 'uncertain')]:
                save([available(start='10:00')])
                smtp.side_effect = error
                result = save([available()])
                assert result['notification']['status'] == expected
                assert 'changes are saved' in result['notification']['warning']
                assert VolunteerAvailability.query.one().start_time == '09:00'
                record = VolunteerRotaNotification.query.order_by(VolunteerRotaNotification.id.desc()).first()
                assert record.status == expected and record.error == type(error).__name__
                calls = smtp.call_count
                deliver_notification(record.id)
                assert save([available()])['notification']['status'] == 'unchanged'
                assert smtp.call_count == calls
                save([dict(date='2099-01-02', status='clear')])
            app.config['ENABLE_EMAIL'] = False
            calls = smtp.call_count
            assert save([available()])['notification']['status'] == 'unchanged'
            result = save([available(start='10:00')])
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
            save([available(start='10:00')], name='Concurrent Volunteer')
            db.session.remove()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, range(2)))
            assert sorted(results) == ['sent', 'unchanged'], results
            assert len(sent) == 1
            assert VolunteerAvailability.query.count() == 1
            assert VolunteerRotaNotification.query.count() == 1
        ''')

    def test_unicode_names_and_conflicting_legacy_rows(self):
        self.run_case('''
            for name in ['Élodie Martin', 'ÉLODIE MARTIN', 'E\\u0301lodie Martin']:
                save([available()], name=name)
            assert VolunteerAvailability.query.count() == 1 and not sent
            save([dict(date='2099-01-02', status='clear')], name='élodie martin')
            assert VolunteerAvailability.query.count() == 0
            save([available()], name='Élodie Martin')
            response = client.post('/api/admin/volunteers/remove', json={'name':'ÉLODIE MARTIN'})
            assert response.status_code == 200 and VolunteerAvailability.query.count() == 0
            assert len(sent) == 2

            db.session.add_all([
                VolunteerAvailability(name='Bob', booking_date=date(2099,1,2), start_time='10am', end_time='99:99'),
                VolunteerAvailability(name='bob', booking_date=date(2099,1,2), unavailable=True)])
            db.session.commit()
            save([dict(date='2099-01-02', status='unavailable')], name='BOB')
            assert VolunteerAvailability.query.count() == 1
            body = text_of(sent[-1][0])
            assert 'Conflicting saved entries' in body
            assert 'Available (10am to 99:99)' in body and 'Not available' in body
            assert VolunteerRotaNotification.query.order_by(VolunteerRotaNotification.id.desc()).first().status == 'sent'
        ''')

    def test_post_commit_database_locks_preserve_response_and_surface_history(self):
        self.run_case('''
            import sqlite3
            from sqlalchemy import event
            @event.listens_for(db.engine, 'checkout')
            def shorten_test_wait(connection, *_):
                connection.execute('PRAGMA busy_timeout=30')
            for route in ['/api/admin/volunteers', '/api/admin/volunteers/remove']:
                for stage in ['claim', 'outcome']:
                    VolunteerAvailability.query.delete()
                    VolunteerRotaNotification.query.delete()
                    db.session.add(VolunteerAvailability(name='Test Volunteer', booking_date=date(2099,1,2)))
                    db.session.commit()
                    before_count = len(sent)
                    blocker = sqlite3.connect(db.engine.url.database, timeout=.1)
                    commits = []
                    original_commit = db.session.commit
                    def commit_and_lock():
                        original_commit()
                        commits.append(True)
                        if len(commits) == 1 and stage == 'claim':
                            blocker.execute('BEGIN IMMEDIATE')
                    def capture_and_lock(message, recipients=None):
                        capture(message, recipients)
                        if stage == 'outcome':
                            blocker.execute('BEGIN IMMEDIATE')
                    smtp.side_effect = capture_and_lock
                    with patch.object(db.session, 'commit', side_effect=commit_and_lock):
                        response = client.post(route, json=dict(name='Test Volunteer',
                            entries=[dict(date='2099-01-02', status='unavailable')]))
                    blocker.rollback()
                    blocker.close()
                    assert response.status_code == 200, response.get_data(as_text=True)
                    assert response.json['notification']['warning']
                    assert response.json['notification']['status'] == 'uncertain'
                    if route.endswith('/remove'):
                        assert VolunteerAvailability.query.count() == 0
                        assert response.json['volunteers'] == []
                    else:
                        assert VolunteerAvailability.query.one().unavailable
                        assert response.json['volunteers'][0]['unavailable_dates'] == ['2099-01-02']
                    record = VolunteerRotaNotification.query.one()
                    assert record.status == ('pending' if stage == 'claim' else 'sending')
                    assert len(sent) == before_count + (stage == 'outcome')
                    issues = client.get('/api/admin/volunteer-notifications').json
                    assert issues == [dict(id=record.id, name=record.name, status=record.status,
                        created_at=record.created_at.isoformat()+'Z')]
                    calls = smtp.call_count
                    if route.endswith('/remove'):
                        client.post(route,json={'name':'Test Volunteer'})
                    else:
                        save([dict(date='2099-01-02', status='unavailable')])
                    assert smtp.call_count == calls
            assert app.test_client().get('/api/admin/volunteer-notifications').status_code == 302
        ''')

    def test_concurrent_save_and_removal_keep_both_transitions(self):
        self.run_case('''
            from concurrent.futures import ThreadPoolExecutor
            from threading import Barrier
            db.session.add(VolunteerAvailability(name='Test Volunteer',booking_date=date(2099,1,2)))
            db.session.commit()
            db.session.remove()
            barrier = Barrier(2)
            def submit(remove):
                local = app.test_client()
                with local.session_transaction() as session:
                    session['admin_logged_in'] = True
                barrier.wait(timeout=5)
                response = local.post('/api/admin/volunteers' + ('/remove' if remove else ''),
                    json=dict(name='Test Volunteer', entries=[dict(date='2099-01-02',status='unavailable')]))
                assert response.status_code == 200, response.get_data(as_text=True)
                return response.json
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(submit, [False, True]))
            records = VolunteerRotaNotification.query.order_by(VolunteerRotaNotification.id).all()
            changes = [json.loads(record.changes)[0] for record in records]
            assert len(sent) == len(changes)
            assert changes[0]['before'][0] == 'available'
            rows = VolunteerAvailability.query.all()
            if rows:
                # Removal won the lock first, so the later save is a new entry.
                assert len(rows) == 1 and rows[0].unavailable
                assert len(changes) == 1 and changes[0]['after'][0] == 'clear'
            else:
                assert len(changes) == 2 and changes[0]['after'][0] == 'unavailable'
                assert changes[1]['before'] == changes[0]['after']
                assert changes[1]['after'][0] == 'clear'
        ''')

    def test_real_scheduled_friday_without_mocking_rota_dates(self):
        self.run_case('''
            import app as module
            from datetime import datetime
            from app import init_default_data
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return cls(2026, 11, 6, 15, tzinfo=tz)
            patch.stopall()
            module.send_smtp_message = capture
            init_default_data()
            with patch('app.datetime', Clock):
                days = client.get('/api/admin/volunteers').json['fridays']
                assert '2026-11-20' in [day['date'] for day in days]
                assert save([available('2026-11-20')])['notification']['status'] == 'unchanged'
                result = save([available('2026-11-20', start='10:00')])
                assert result['notification']['status'] == 'sent'
                assert 'Friday 20th November 2026' in text_of(sent[-1][0])
                response = client.post('/api/admin/volunteers/remove',json={'name':'Test Volunteer'})
                assert response.status_code == 200 and len(sent) == 2
                assert VolunteerAvailability.query.count() == 0
        ''')
