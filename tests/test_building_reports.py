import json
import unittest
from test_reminders import run_isolated


FIXTURE = '''
import json
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from app import (app, db, Booking, Room, VolunteerAvailability,
                 BuildingReportDispatch, set_setting, EmailDeliveryUncertain)
from building_reports import (build_snapshot, report_content, due_batch,
                              run_building_report_job, send_report_email)
zone = ZoneInfo('Europe/London')
day = date(2026, 10, 9)
with app.app_context():
    room = Room(name='The Loft', building_location='Floor 6', room_type='open',
                default_start='10:45', default_end='16:00')
    db.session.add(room)
    db.session.flush()
    first = Booking(room_id=room.id, user_name='Avery Jones',
        user_email='private@example.test', booking_date=day, start_slot=0, end_slot=15,
        bringing_others=True, companion_names='Taylor Smith', additional_attendees=1,
        mobility_needs=True, mobility_details='Uses a wheelchair',
        other_info='Private counselling details', cancel_token='secret-cancel-link')
    db.session.add_all([first,
        VolunteerAvailability(name='Sam Volunteer', booking_date=day,
            shift_type='specific', start_time='10:30', end_time='16:30'),
        VolunteerAvailability(name='Cannot Attend', booking_date=day, unavailable=True)])
    db.session.commit()
    set_setting('building_reports_enabled', 'true')
'''


def run_case(code):
    result = run_isolated(FIXTURE + code)
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


class BuildingReportTest(unittest.TestCase):
    def test_full_report_names_mobility_custom_hours_and_privacy(self):
        result = run_case('''
    content = report_content(day, build_snapshot(day))
    with patch('app.send_smtp_message') as smtp:
        send_report_email(content)
        message = smtp.call_args.args[0]
        envelope = smtp.call_args.kwargs['recipients']
    print(json.dumps({'body': content['body'], 'html': content['html'],
        'to': message['To'], 'cc': message['Cc'], 'envelope': envelope}))
''')
        for value in ('Avery Jones', 'Taylor Smith', 'Sam Volunteer', 'Mobility needs reported: Yes', 'Total names: 3'):
            self.assertIn(value, result['body'])
        for value in ('Cannot Attend', 'private@example.test', 'Private counselling', 'secret-cancel-link',
                      'Uses a wheelchair', '10.30am', '10.45am', 'The Loft'):
            self.assertNotIn(value, result['body'] + result['html'])
        self.assertIn('emma.perez@macmillan.com', result['to'])
        self.assertIn('martha.fisher@macmillan.com', result['to'])
        self.assertIn('florence.perdriel@gmail.com', result['cc'])
        self.assertEqual(len(result['envelope']), 3)

    def test_one_final_list_no_later_updates_and_names_deduplicated(self):
        result = run_case('''
    db.session.add(Booking(room_id=room.id, user_name='  AVERY  Jones  ',
        user_email='second@example.test', booking_date=day, start_slot=1, end_slot=2,
        carer_attending=True, bringing_others=True, carer_first_name='Taylor',
        carer_last_name='Smith', companion_names='Taylor Smith (carer); Sam Volunteer',
        cancel_token='duplicate-names'))
    db.session.commit()
    sent = []
    with patch('building_reports.send_report_email', side_effect=lambda content: sent.append(content)):
        initial = run_building_report_job(datetime(2026, 10, 8, 10, tzinfo=zone))
        repeat = run_building_report_job(datetime(2026, 10, 8, 10, tzinfo=zone))
        first.cancelled_at = datetime(2026, 10, 8, 11)
        db.session.commit()
        later = run_building_report_job(datetime(2026, 10, 8, 12, tzinfo=zone))
        friday = run_building_report_job(datetime(2026, 10, 9, 10, tzinfo=zone))
    snapshot = json.loads(BuildingReportDispatch.query.one().snapshot)
    print(json.dumps({'sent': sent, 'counts': [initial, repeat, later, friday], 'snapshot': snapshot}))
''')
        self.assertEqual([c['sent'] for c in result['counts']], [1, 0, 0, 0])
        self.assertEqual(len(result['sent']), 1)
        for name in ('Avery Jones', 'Taylor Smith', 'Sam Volunteer'):
            self.assertEqual(result['sent'][0]['body'].count(name), 1)
        self.assertEqual(result['snapshot']['total'], 3)
        self.assertNotIn('Uses a wheelchair', json.dumps(result['snapshot']))

    def test_failure_retry_within_10am_window_and_uncertain_delivery_waits(self):
        result = run_case('''
    with patch('building_reports.send_report_email', side_effect=RuntimeError('SMTP login rejected')):
        failed = run_building_report_job(datetime(2026, 10, 8, 10, tzinfo=zone))
    first.user_name = 'Changed after deadline'
    db.session.commit()
    with patch('building_reports.send_report_email', side_effect=EmailDeliveryUncertain('Check delivery')):
        uncertain = run_building_report_job(datetime(2026, 10, 8, 10, 1, tzinfo=zone))
    with patch('building_reports.send_report_email') as send:
        blocked = run_building_report_job(datetime(2026, 10, 8, 10, 2, tzinfo=zone))
        blocked_calls = send.call_count
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    row = BuildingReportDispatch.query.filter_by(status='sending').one()
    resolved = client.post('/api/admin/building-reports/resolve/' + str(row.id), json={'action': 'not_sent'})
    with patch('building_reports.send_report_email') as send:
        recovered = run_building_report_job(datetime(2026, 10, 8, 10, 3, tzinfo=zone))
        body = send.call_args.args[0]['body']
        repeat = run_building_report_job(datetime(2026, 10, 8, 10, 4, tzinfo=zone))
    print(json.dumps({'counts': [failed, uncertain, blocked, recovered, repeat],
                     'blocked_calls': blocked_calls, 'resolved': resolved.status_code, 'body': body,
                     'rows': BuildingReportDispatch.query.count()}))
''')
        self.assertEqual([c['sent'] for c in result['counts']], [0, 0, 0, 1, 0])
        self.assertEqual(result['blocked_calls'], 0)
        self.assertEqual(result['resolved'], 200)
        self.assertEqual(result['rows'], 1)
        self.assertIn('Avery Jones', result['body'])
        self.assertNotIn('Changed after deadline', result['body'])

    def test_legacy_mobility_html_escaping_and_extra_attendees(self):
        result = run_case('''
    first.user_name = '<script>unsafe</script>'
    first.mobility_needs = None
    first.mobility_details = ''
    first.accessibility_needs = 'Private sensory preference. Uses crutches and needs the lift.'
    first.bringing_others = True
    first.carer_attending = True
    first.carer_name = 'Jo Jones'
    first.companion_names = 'Jo Jones (carer), Taylor Smith'
    first.other_info = 'Unrelated private detail'
    db.session.commit()
    content = report_content(day, build_snapshot(day))
    print(json.dumps(content))
''')
        self.assertIn('Mobility needs reported: Yes', result['body'])
        self.assertNotIn('Uses crutches', result['body'] + result['html'])
        self.assertNotIn('Private sensory', result['body'])
        self.assertNotIn('<script>', result['html'])
        self.assertIn('&lt;script&gt;', result['html'])
        self.assertEqual(result['body'].count('Jo Jones'), 1)
        self.assertIn('Taylor Smith', result['body'])

    def test_disabled_unpublished_and_outside_hours_never_send(self):
        result = run_case('''
    with patch('building_reports.send_report_email') as send:
        set_setting('building_reports_enabled', 'false')
        disabled = run_building_report_job(datetime(2026, 10, 8, 10, tzinfo=zone))
        set_setting('building_reports_enabled', 'true')
        outside = [run_building_report_job(datetime(2026, 10, 8, hour, tzinfo=zone)) for hour in (8, 9, 11, 12, 14, 16, 18, 19, 20)]
        unpublished = run_building_report_job(datetime(2026, 10, 29, 10, tzinfo=zone))
        friday = [run_building_report_job(datetime(2026, 10, 9, hour, tzinfo=zone)) for hour in (8,10,12,14,16,18)]
        calls = send.call_count
    client = app.test_client()
    private_preview = client.get('/api/admin/building-reports/preview/2026-10-09')
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
    preview = client.get('/api/admin/building-reports/preview/2026-10-09')
    print(json.dumps({'calls': calls, 'private_status': private_preview.status_code,
                     'preview_status': preview.status_code, 'rows': BuildingReportDispatch.query.count()}))
''')
        self.assertEqual(result['calls'], 0)
        self.assertIn(result['private_status'], (302, 401))
        self.assertEqual(result['preview_status'], 200)
        self.assertEqual(result['rows'], 0)

    def test_london_timezone_after_clocks_change(self):
        result = run_case('''
    print(json.dumps({'summer': due_batch(datetime(2026, 10, 8, 9, tzinfo=ZoneInfo('UTC')))[1],
        'winter': due_batch(datetime(2026, 10, 29, 10, tzinfo=ZoneInfo('UTC')))[1],
        'too_early_winter': due_batch(datetime(2026, 10, 29, 9, tzinfo=ZoneInfo('UTC')))}))
''')
        self.assertEqual(result['summer'], '2026-10-08T10:00')
        self.assertEqual(result['winter'], '2026-10-29T10:00')
        self.assertIsNone(result['too_early_winter'])

    def test_overlapping_jobs_claim_one_batch(self):
        result = run_case('''
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    original = build_snapshot
    def snapshot_together(target):
        snapshot = original(target)
        barrier.wait(timeout=10)
        return snapshot
    def job():
        with app.app_context():
            return run_building_report_job(datetime(2026, 10, 8, 10, tzinfo=zone))
    with patch('building_reports.build_snapshot', side_effect=snapshot_together), \
         patch('building_reports.send_report_email', side_effect=lambda content: time.sleep(.1)) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: job(), range(2)))
    print(json.dumps({'sent': send.call_count, 'counts': results,
                     'records': BuildingReportDispatch.query.count()}))
''')
        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['records'], 1)


if __name__ == '__main__':
    unittest.main()
