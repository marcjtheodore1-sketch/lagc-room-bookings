"""Isolated privacy, booking, access and reception-report regression tests."""
import json
import unittest
from test_reminders import run_isolated

FIXTURE = r'''
import json, re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
from app import app, db
from werkzeug.security import generate_password_hash
from student_support import (StudentSlot, StudentBooking, StudentAccess, StudentMail,
    digest, slot_label, in_person_open, reception_names)
app.config.update(TESTING=True, STUDENT_COOKIE_SECURE=False,
    STUDENT_SUPPORT_PASSWORD_HASH=generate_password_hash('preview-test-only', method='pbkdf2:sha256:1000'))
client = app.test_client()
sent = []
patch('student_support.deliver', side_effect=lambda *args: sent.append(args)).start()
clock = patch('student_support.now_london', return_value=datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('Europe/London'))).start()
patch('app.get_room_schedule_ids', return_value={'2026-10-30': [1]}).start()
def csrf(c=client):
    html = c.get('/peer-support/supporter/login').get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
def request_booking(slot_id=1, location='online', email='student@example.test', name='Alex Student', **changes):
    values = dict(csrf_token=csrf(), slot_id=slot_id, location=location, email=email,
        name=name, studying='PRIVATE engineering BA', goals='PRIVATE adjustments',
        questions='PRIVATE question', privacy='yes', mobility_needs='no')
    values.update(changes)
    return client.post('/peer-support/book', data=values)
def confirm_booking():
    token = re.search(r'/confirm/(\S+)', sent[-1][2]).group(1)
    return client.post('/peer-support/confirm/' + token, data={'csrf_token': csrf()})
def login(supporter='sungji'):
    from student_support import COOKIE, shared_identity
    raw = 'test-private-session-' + supporter
    identity = shared_identity() if supporter in ('sungji', 'marilena', 'chris') else supporter
    db.session.add(StudentAccess(token_hash=digest(raw), supporter=identity, kind='session',
        ip_hash='test', expires_at=datetime.utcnow() + timedelta(hours=1)))
    db.session.commit()
    client.set_cookie(COOKIE, raw, path='/peer-support')
with app.app_context():
    db.session.add_all([
        StudentSlot(supporter='sungji', day=date(2026,10,30), start_time='11:00', published=True, in_person=True),
        StudentSlot(supporter='marilena', day=date(2026,11,1), start_time='10:00', published=True),
        StudentSlot(supporter='sungji', day=date(2026,10,30), start_time='12:00', published=False)])
    db.session.commit()
'''


def run_case(code):
    result = run_isolated(FIXTURE + code)
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


class StudentSupportTest(unittest.TestCase):
    def test_confirmation_holds_slot_and_routes_friday_notification_without_answers(self):
        result = run_case(r'''
    first = request_booking(location='in_person')
    before = reception_names(date(2026,10,30))
    duplicate = request_booking(email='other@example.test')
    confirmed = confirm_booking()
    booking = StudentBooking.query.one()
    view = client.get(confirmed.location)
    print(json.dumps(dict(first=first.status_code, duplicate=duplicate.status_code,
        confirm=confirmed.status_code, status=booking.status, active=booking.active_slot_id,
        sent=sent, before=before, after=reception_names(date(2026,10,30)),
        page=view.get_data(as_text=True), mails=StudentMail.query.count())))
''')
        self.assertEqual((result['first'], result['duplicate'], result['confirm']), (200, 409, 302))
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['before'], [[], []])
        self.assertEqual(result['after'], [['Alex Student'], ['Sungji']])
        self.assertEqual([s[0] for s in result['sent']], ['student@example.test', 'student@example.test', 'sungji.lagc@gmail.com'])
        self.assertNotIn('PRIVATE', str(result['sent']) + result['page'])
        self.assertEqual(result['mails'], 2)

    def test_sunday_online_only_and_assigned_recipient(self):
        result = run_case(r'''
    bad = request_booking(slot_id=2, location='in_person')
    good = request_booking(slot_id=2)
    confirmed = confirm_booking()
    print(json.dumps(dict(bad=bad.status_code, good=good.status_code,
        confirmed=confirmed.status_code, recipients=[m[0] for m in sent], names=reception_names(date(2026,11,1)))))
''')
        self.assertEqual((result['bad'], result['good'], result['confirmed']), (409, 200, 302))
        self.assertEqual(result['recipients'][-1], 'marilena.eleftheriou@yahoo.com')
        self.assertEqual(result['names'], [[], []])

    def test_deadline_at_10am_rechecked_on_confirmation_and_stale_form(self):
        result = run_case(r'''
    clock.return_value = datetime(2026,10,29,9,59,tzinfo=ZoneInfo('Europe/London'))
    request_booking(location='in_person')
    token = re.search(r'/confirm/(\S+)', sent[-1][2]).group(1)
    clock.return_value = datetime(2026,10,29,10,0,tzinfo=ZoneInfo('Europe/London'))
    confirm = client.post('/peer-support/confirm/' + token, data={'csrf_token': csrf()})
    stale = request_booking(location='in_person')
    online = request_booking(slot_id=2)
    print(json.dumps(dict(confirm=confirm.status_code, stale=stale.status_code, online=online.status_code)))
''')
        self.assertEqual(result, {'confirm': 409, 'stale': 409, 'online': 200})

    def test_expiry_releases_pending_slot_and_get_never_confirms(self):
        result = run_case(r'''
    request_booking()
    token = re.search(r'/confirm/(\S+)', sent[-1][2]).group(1)
    opened = client.get('/peer-support/confirm/' + token)
    before = StudentBooking.query.one().status
    StudentBooking.query.one().expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    expired = client.post('/peer-support/confirm/' + token, data={'csrf_token': csrf()})
    retry = request_booking(email='second@example.test')
    print(json.dumps(dict(opened=opened.status_code, before=before,
        expired=expired.status_code, retry=retry.status_code, statuses=[b.status for b in StudentBooking.query.order_by(StudentBooking.id)])))
''')
        self.assertEqual(result['before'], 'pending')
        self.assertEqual((result['expired'], result['retry']), (410, 200))
        self.assertEqual(result['statuses'], ['expired', 'pending'])

    def test_shared_admin_has_no_student_access_and_public_data_is_minimal(self):
        result = run_case(r'''
    request_booking()
    confirm_booking()
    with client.session_transaction() as state:
        state['admin_logged_in'] = True
    portal = client.get('/peer-support/supporter')
    admin = client.get('/api/admin/bookings')
    public = client.get('/peer-support/book')
    print(json.dumps(dict(portal=portal.status_code, where=portal.location,
        admin=admin.get_data(as_text=True), public=public.get_data(as_text=True),
        cache=public.headers.get('Cache-Control'), referrer=public.headers.get('Referrer-Policy'))))
''')
        self.assertEqual(result['portal'], 302)
        self.assertIn('/supporter/login', result['where'])
        self.assertNotIn('PRIVATE', result['admin'] + result['public'])
        self.assertNotIn('student@example.test', result['admin'] + result['public'])
        self.assertEqual(result['cache'], 'no-store, private')
        self.assertEqual(result['referrer'], 'no-referrer')

    def test_shared_password_login_rejects_other_password_and_logout_revokes(self):
        result = run_case(r'''
    get = client.get('/peer-support/supporter/login')
    bad = client.post('/peer-support/supporter/login', data={'csrf_token': csrf(), 'password':app.config['ADMIN_PASSWORD']})
    still_private = client.get('/peer-support/supporter')
    good = client.post('/peer-support/supporter/login', data={'csrf_token': csrf(), 'password':'preview-test-only'})
    portal = client.get('/peer-support/supporter')
    logout = client.post('/peer-support/supporter/logout', data={'csrf_token':csrf()})
    after = client.get('/peer-support/supporter')
    print(json.dumps(dict(get=get.status_code, bad=bad.status_code, still_private=still_private.status_code,
        good=good.status_code, portal=portal.status_code, after=after.status_code, sent=len(sent),
        rendered=get.get_data(as_text=True))))
''')
        html = result.pop('rendered')
        self.assertNotIn('preview-test-only', html)
        self.assertIn('type="password"', html)
        self.assertIn('Chris', html)
        self.assertEqual(result, {'get':200, 'bad':401, 'still_private':302, 'good':302, 'portal':200, 'after':302, 'sent':0})

    def test_csrf_cookie_expiry_and_unknown_identity_fail_closed(self):
        result = run_case(r'''
    missing = client.post('/peer-support/book', data={})
    login()
    badcsrf = client.post('/peer-support/supporter/slots', data={})
    StudentAccess.query.filter_by(kind='session').one().expires_at = datetime.utcnow()-timedelta(seconds=1)
    db.session.commit()
    expired = client.get('/peer-support/supporter')
    login('outsider')
    unknown = client.get('/peer-support/supporter')
    print(json.dumps(dict(missing=missing.status_code, badcsrf=badcsrf.status_code, expired=expired.status_code, unknown=unknown.status_code)))
''')
        self.assertEqual(result, {'missing': 400, 'badcsrf': 400, 'expired': 302, 'unknown': 302})

    def test_cancel_is_explicit_idempotent_and_releases_venue_name(self):
        result = run_case(r'''
    request_booking(location='in_person')
    confirmed = confirm_booking()
    client.get(confirmed.location)
    before = StudentBooking.query.one().status
    cancelled = client.post(confirmed.location, data={'csrf_token':csrf()})
    client.post(confirmed.location, data={'csrf_token':csrf()})
    print(json.dumps(dict(before=before, status=StudentBooking.query.one().status,
        active=StudentBooking.query.one().active_slot_id, names=reception_names(date(2026,10,30)), recipients=[m[0] for m in sent])))
''')
        self.assertEqual(result['before'], 'confirmed')
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(result['active'])
        self.assertEqual(result['names'], [[], []])
        self.assertEqual(result['recipients'][-2:], ['student@example.test', 'sungji.lagc@gmail.com'])
        self.assertEqual(len(result['recipients']), 5)

    def test_supporter_availability_date_rules_and_draft_publication(self):
        result = run_case(r'''
    login('marilena')
    data = dict(csrf_token=csrf(), supporter='marilena', day='2026-11-08', start='10:00', end='13:00', in_person='yes')
    added = client.post('/peer-support/supporter/slots', data=data)
    drafts = StudentSlot.query.filter_by(day=date(2026,11,8)).all()
    otherday = client.post('/peer-support/supporter/slots', data={**data, 'day':'2026-11-09'})
    unknown = client.post('/peer-support/supporter/slots', data={**data, 'supporter':'unknown'})
    half = client.post('/peer-support/supporter/slots', data={**data, 'start':'10:30'})
    unsafe = client.post('/peer-support/supporter/slots', data={**data, 'meeting_url':'javascript:alert(1)'})
    print(json.dumps(dict(added=added.status_code, slots=[(s.start_time,s.in_person,s.published) for s in drafts], otherday=otherday.status_code, unknown=unknown.status_code, half=half.status_code, unsafe=unsafe.status_code)))
''')
        self.assertEqual(result['added'], 302)
        self.assertEqual(result['slots'], [['10:00', False, False], ['11:00', False, False], ['12:00', False, False]])
        self.assertEqual(result['otherday'], 302)
        self.assertEqual((result['unknown'], result['half'], result['unsafe']), (400, 400, 400))

    def test_both_supporters_can_publish_any_weekday_and_receive_own_notifications(self):
        result = run_case(r'''
    login()
    responses = []
    for supporter in ('sungji', 'marilena'):
        for offset in range(7):
            day = date(2026,11,2) + timedelta(days=offset)
            response = client.post('/peer-support/supporter/slots', data=dict(
                csrf_token=csrf(), supporter=supporter, day=day.isoformat(),
                start='14:00', end='15:00', published='yes'))
            responses.append(response.status_code)
    page = client.get('/peer-support/book').get_data(as_text=True)
    admin = client.get('/peer-support/supporter').get_data(as_text=True)
    recipients = []
    for supporter, day in [('marilena', date(2026,11,6)), ('sungji', date(2026,11,2))]:
        slot = StudentSlot.query.filter_by(supporter=supporter, day=day).one()
        assert f'value="{slot.id}"' in page
        assert request_booking(slot_id=slot.id).status_code == 200
        assert confirm_booking().status_code == 302
        recipients.append(sent[-1][0])
    print(json.dumps(dict(responses=responses, recipients=recipients,
        names=reception_names(date(2026,11,6)),
        old_labels=('Sungji (Fridays)' in admin or 'Marilena (Sundays)' in admin))))
''')
        self.assertEqual(result['responses'], [302] * 14)
        self.assertEqual(result['recipients'], ['marilena.eleftheriou@yahoo.com', 'sungji.lagc@gmail.com'])
        self.assertEqual(result['names'], [[], []])
        self.assertFalse(result['old_labels'])

    def test_in_person_still_requires_sungji_and_a_scheduled_friday(self):
        result = run_case(r'''
    login()
    data = dict(csrf_token=csrf(), supporter='sungji', day='2026-11-02',
        start='10:00', end='11:00', in_person='yes', published='yes')
    with patch('app.get_room_schedule_ids', return_value={'2026-11-02':[1]}):
        monday = client.post('/peer-support/supporter/slots', data=data)
    unscheduled = client.post('/peer-support/supporter/slots', data={**data, 'day':'2026-11-06'})
    marilena = client.post('/peer-support/supporter/slots', data={**data, 'supporter':'marilena', 'day':'2026-10-30'})
    slot = StudentSlot.query.filter_by(supporter='marilena', day=date(2026,10,30)).one()
    rejected = request_booking(slot_id=slot.id, location='in_person')
    print(json.dumps(dict(monday=monday.status_code, unscheduled=unscheduled.status_code,
        marilena=marilena.status_code, in_person=slot.in_person, rejected=rejected.status_code)))
''')
        self.assertEqual(result, {'monday':400, 'unscheduled':400, 'marilena':302, 'in_person':False, 'rejected':409})

    def test_report_deduplicates_names_without_answers_or_contact_details(self):
        result = run_case(r'''
    from app import Booking, Room, VolunteerAvailability
    from building_reports import build_snapshot, report_content
    request_booking(location='in_person')
    confirm_booking()
    room = Room(name='Room', building_location='Floor 4')
    db.session.add(room)
    db.session.flush()
    db.session.add(Booking(room_id=room.id, user_name='alex student', user_email='ordinary@example.test', booking_date=date(2026,10,30), start_slot=0,end_slot=1,cancel_token='room-token'))
    db.session.commit()
    snap = build_snapshot(date(2026,10,30))
    content = report_content(date(2026,10,30), snap)
    print(json.dumps(dict(snapshot=snap, content=content)))
''')
        content = str(result)
        self.assertNotIn('PRIVATE', content)
        self.assertNotIn('student@example.test', content)
        self.assertEqual(result['snapshot']['total'], 2)
        self.assertEqual(result['snapshot']['attendees'], [{'name': 'Alex Student'}])
        self.assertEqual(result['snapshot']['volunteers'], [{'name': 'Sungji'}])

    def test_failed_notifications_recorded_without_repeated_sends(self):
        result = run_case(r'''
    from student_support import notify
    from app import EmailDeliveryUncertain
    request_booking()
    with patch('student_support.deliver', side_effect=EmailDeliveryUncertain('uncertain')):
        confirmed = confirm_booking()
    booking = StudentBooking.query.one()
    with patch('student_support.deliver') as delivery:
        notify(booking, 'confirmed')
        calls = delivery.call_count
    login()
    portal = client.get('/peer-support/supporter')
    print(json.dumps(dict(status=booking.status, mails=[m.status for m in StudentMail.query.all()], calls=calls, portal=portal.get_data(as_text=True))))
''')
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['mails'], ['uncertain', 'uncertain'])
        self.assertEqual(result['calls'], 0)
        self.assertIn('Notification delivery needs checking', result['portal'])

    def test_malformed_past_withdrawn_and_full_name_validation(self):
        result = run_case(r'''
    bad = [request_booking(slot_id=999).status_code, request_booking(slot_id=3).status_code,
        request_booking(email='a@b').status_code, request_booking(privacy='').status_code,
        request_booking(name='Alex', location='in_person').status_code,
        request_booking(goals='x'*3001).status_code]
    clock.return_value = datetime(2026,11,2,10,tzinfo=ZoneInfo('Europe/London'))
    bad.append(request_booking(slot_id=1).status_code)
    print(json.dumps(dict(bad=bad, rows=StudentBooking.query.count(), mails=len(sent))))
''')
        self.assertEqual(result, {'bad': [409, 409, 400, 400, 400, 400, 409], 'rows': 0, 'mails': 0})

    def test_concurrent_requests_can_only_hold_one_slot(self):
        result = run_case(r'''
    import threading
    barrier = threading.Barrier(2)
    results = []
    def submit(index):
        with app.test_client() as concurrent:
            token = csrf(concurrent)
            barrier.wait()
            response = concurrent.post('/peer-support/book', data=dict(csrf_token=token,
                slot_id=1, location='online', email=f'race{index}@example.test', name='Test Student',
                studying='BA', goals='Talk', privacy='yes'))
            results.append(response.status_code)
    workers = [threading.Thread(target=submit, args=(i,)) for i in range(2)]
    for worker in workers: worker.start()
    for worker in workers: worker.join()
    print(json.dumps(dict(results=sorted(results), active=StudentBooking.query.filter(StudentBooking.active_slot_id.isnot(None)).count())))
''')
        self.assertEqual(result, {'results': [200, 409], 'active': 1})

    def test_mobility_aggregates_without_identifying_student_or_written_details(self):
        result = run_case(r'''
    from building_reports import build_snapshot, report_content
    request_booking(location='in_person', mobility_needs='yes')
    confirm_booking()
    snapshot = build_snapshot(date(2026,10,30))
    content = report_content(date(2026,10,30), snapshot)
    print(json.dumps(dict(snapshot=snapshot, body=content['body'], html=content['html'])))
''')
        self.assertTrue(result['snapshot']['mobility_needs'])
        self.assertIn('Mobility needs reported: Yes', result['body'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('student@example.test', str(result))
        self.assertEqual(result['snapshot']['attendees'], [{'name': 'Alex Student'}])

    def test_csrf_does_not_depend_on_shared_flask_session_key(self):
        result = run_case(r'''
    token = csrf()
    app.secret_key = 'different-worker-secret'
    posted = client.post('/peer-support/supporter/login', data={'csrf_token':token, 'password':'preview-test-only'})
    print(json.dumps(dict(posted=posted.status_code, sent=len(sent))))
''')
        self.assertEqual(result, {'posted': 302, 'sent': 0})

    def test_slot_withdrawal_preserves_booking_and_link_can_be_updated(self):
        result = run_case(r'''
    request_booking()
    confirm_booking()
    login()
    updated = client.post('/peer-support/supporter/slots/1', data=dict(csrf_token=csrf(), published='no', meeting_url='https://example.test/meeting'))
    slot = db.session.get(StudentSlot,1)
    bad = client.post('/peer-support/supporter/slots/1', data=dict(csrf_token=csrf(), published='yes', meeting_url='https://'))
    print(json.dumps(dict(updated=updated.status_code, published=slot.published, url=slot.meeting_url, status=StudentBooking.query.one().status, bad=bad.status_code)))
''')
        self.assertEqual(result, {'updated': 302, 'published': False, 'url': 'https://example.test/meeting', 'status': 'confirmed', 'bad': 400})

    def test_required_mobility_answer_and_staff_cancel_authorisation(self):
        result = run_case(r'''
    missing = request_booking(location='in_person', mobility_needs='')
    request_booking(location='in_person')
    confirm_booking()
    csrf_value=csrf()
    denied = client.post('/peer-support/supporter/bookings/1/cancel', data={'csrf_token':csrf_value})
    login('marilena')
    cancelled = client.post('/peer-support/supporter/bookings/1/cancel', data={'csrf_token':csrf()})
    print(json.dumps(dict(missing=missing.status_code, denied=denied.status_code, cancelled=cancelled.status_code, status=StudentBooking.query.one().status)))
''')
        self.assertEqual(result, {'missing': 400, 'denied': 302, 'cancelled': 302, 'status': 'cancelled'})

    def test_retention_erases_only_old_written_answers_and_keeps_appointments(self):
        result = run_case(r'''
    from student_support import maintain_student_records
    app.config['STUDENT_ANSWER_RETENTION_DAYS']=90
    request_booking(location='in_person', mobility_needs='yes')
    confirm_booking()
    booking = StudentBooking.query.one()
    booking.slot.day=date(2026,7,1)
    db.session.commit()
    maintain_student_records()
    db.session.refresh(booking)
    print(json.dumps(dict(name=booking.name, email=booking.email, status=booking.status,
        answers=[booking.studying, booking.goals, booking.questions], deleted=bool(booking.answers_deleted_at), mobility=booking.mobility_needs)))
''')
        self.assertEqual(result, {'name': 'Alex Student', 'email': 'student@example.test', 'status': 'confirmed', 'answers': ['', '', ''], 'deleted': True, 'mobility': True})

    def test_recent_answers_and_manual_retention_are_preserved(self):
        result = run_case(r'''
    from student_support import maintain_student_records
    request_booking()
    confirm_booking()
    booking=StudentBooking.query.one()
    maintain_student_records()
    recent=booking.goals
    booking.slot.day=date(2026,7,1)
    db.session.commit()
    app.config['STUDENT_ANSWER_RETENTION_DAYS']=None
    maintain_student_records()
    db.session.refresh(booking)
    print(json.dumps(dict(recent=recent, manual=booking.goals, deleted=bool(booking.answers_deleted_at))))
''')
        self.assertEqual(result, {'recent':'PRIVATE adjustments', 'manual':'PRIVATE adjustments', 'deleted':False})

    def test_explicit_private_erasure_requires_confirmation_and_keeps_booking(self):
        result = run_case(r'''
    request_booking()
    confirm_booking()
    login()
    missing=client.post('/peer-support/supporter/bookings/1/erase-answers', data={'csrf_token':csrf()})
    good=client.post('/peer-support/supporter/bookings/1/erase-answers', data={'csrf_token':csrf(), 'confirm':'erase'})
    booking=StudentBooking.query.one()
    print(json.dumps(dict(missing=missing.status_code, good=good.status_code, status=booking.status, name=booking.name, answers=[booking.studying,booking.goals,booking.questions])))
''')
        self.assertEqual(result, {'missing':400, 'good':302, 'status':'confirmed', 'name':'Alex Student', 'answers':['','','']})

    def test_unset_password_and_old_email_links_cannot_grant_access(self):
        result = run_case(r'''
    login()
    app.config['STUDENT_SUPPORT_PASSWORD_HASH']=''
    portal=client.get('/peer-support/supporter')
    post=client.post('/peer-support/supporter/login', data={'csrf_token':csrf(), 'password':'preview-test-only'})
    legacy=client.get('/peer-support/supporter/access/old-email-token')
    print(json.dumps(dict(portal=portal.status_code, post=post.status_code, legacy=legacy.status_code, sent=len(sent))))
''')
        self.assertEqual(result, {'portal':302,'post':503,'legacy':404,'sent':0})

    def test_password_rotation_revokes_sessions_and_attempt_limit_survives_worker_key_change(self):
        result = run_case(r'''
    login()
    app.config['STUDENT_SUPPORT_PASSWORD_HASH']=generate_password_hash('different-test-password', method='pbkdf2:sha256:1000')
    revoked=client.get('/peer-support/supporter')
    for index in range(10):
        app.secret_key='worker-'+str(index)
        reply=client.post('/peer-support/supporter/login', data={'csrf_token':csrf(), 'password':'wrong'})
    blocked=client.post('/peer-support/supporter/login', data={'csrf_token':csrf(), 'password':'different-test-password'})
    print(json.dumps(dict(revoked=revoked.status_code, last=reply.status_code, blocked=blocked.status_code)))
''')
        self.assertEqual(result, {'revoked':302, 'last':401, 'blocked':429})
