"""One weekly name list for Pan Macmillan at the Thursday booking deadline.

The report shares deduplicated names and a session-level mobility flag only.
A durable claim prevents duplicate emails; uncertain delivery needs an admin
check. Definite failures can retry the same list only within the 10am dispatch window.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from zoneinfo import ZoneInfo

from flask import render_template
from sqlalchemy.exc import IntegrityError

LONDON = ZoneInfo('Europe/London')
ENABLED_KEY = 'building_reports_enabled'
TO = ('Emma Perez <emma.perez@macmillan.com>',
      'Martha Fisher <martha.fisher@macmillan.com>')
CC = ('Florence Perdriel <florence.perdriel@gmail.com>',)
ENVELOPE = ('emma.perez@macmillan.com', 'martha.fisher@macmillan.com',
            'florence.perdriel@gmail.com')
SCHEDULE = 'Thursday at 10am (London time), when registration closes. One weekly email only; no later updates or Friday emails.'
MOBILITY = re.compile(
    r'\b(?:mobility|wheel\s*chair|crutch\w*|walking (?:stick|aid|frame)|'
    r'cane|zimmer|rollator|scooter|step[ -]?free|stairs?|staircase|steps?|lift|'
    r'elevator|arthritis|physical disabilit\w*|balance|'
    r'(?:back|hip|knee|leg|foot|joint) pain|'
    r'(?:difficulty|trouble|struggle\w*) (?:with )?(?:walk\w*|stand\w*)|'
    r'(?:cannot|can\W?t|unable to) (?:walk|stand))\b', re.I)


def one_line(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def has_mobility_needs(booking):
    if booking.mobility_needs is not None:
        return bool(booking.mobility_needs)
    # Legacy bookings predate the dedicated Yes/No question. Only the flag
    # leaves the app, never the matching words or the person's identity.
    return bool(one_line(booking.mobility_details) or
                MOBILITY.search(booking.accessibility_needs or '') or
                MOBILITY.search(booking.other_info or ''))


def build_snapshot(day):
    from app import Booking, VolunteerAvailability, get_room_schedule_ids
    bookings = Booking.query.filter_by(booking_date=day, cancelled_at=None).order_by(Booking.id).all()
    volunteers = VolunteerAvailability.query.filter_by(booking_date=day, unavailable=False).order_by(VolunteerAvailability.name).all()
    seen = set()

    def add_names(values):
        people = []
        for value in values:
            name = one_line(value)
            key = unicodedata.normalize('NFKC', name).casefold()
            if name and key not in seen:
                seen.add(key)
                people.append({'name': name})
        return sorted(people, key=lambda p: p['name'].casefold())

    volunteer_names = add_names(v.name for v in volunteers)
    attendee_values = []
    for booking in bookings:
        attendee_values.append(booking.user_name)
        if booking.carer_attending:
            attendee_values.append(one_line(' '.join(filter(None, (
                booking.carer_first_name, booking.carer_last_name)))) or booking.carer_name)
        if booking.bringing_others:
            for value in re.split(r'[;,\n]+', booking.companion_names or ''):
                # Older fields included role labels such as "Jo Jones (carer)".
                attendee_values.append(re.sub(r'\([^)]*\)', '', value))
    attendees = add_names(attendee_values)
    return {'date': day.isoformat(),
            'scheduled': bool(get_room_schedule_ids().get(day.isoformat())),
            'volunteers': volunteer_names, 'attendees': attendees,
            'mobility_needs': any(has_mobility_needs(b) for b in bookings),
            'total': len(seen)}


def report_content(day, snapshot):
    from app import reminder_date_display
    date_display = reminder_date_display(day)
    subject = f'Fridays @ Farringdon: attendance list for {date_display}'
    lines = ['Hello Emma and Martha,', '',
             f'Here is the attendance list for {date_display}. Registration is now closed.', '',
             'VOLUNTEERS', *[f'- {v["name"]}' for v in snapshot['volunteers']]]
    if not snapshot['volunteers']:
        lines.append('No volunteers have marked themselves available on the rota.')
    lines.extend(['', 'ATTENDEES (INCLUDING CARERS AND COMPANIONS)',
                  *[f'- {p["name"]}' for p in snapshot['attendees']]])
    if not snapshot['attendees']:
        lines.append('No additional attendee names.')
    lines.extend(['', f'Total names: {snapshot["total"]}',
                  f'Mobility needs reported: {"Yes" if snapshot["mobility_needs"] else "No"}',
                  '', 'Each name appears once across the list.', '',
                  'Many thanks,', 'London Autism Group Charity', 'Fridays @ Farringdon'])
    return {'subject': subject, 'body': '\n'.join(lines),
            'html': render_template('building_report_email.html', snapshot=snapshot, date_display=date_display),
            'to': list(TO), 'cc': list(CC)}


def due_batch(now):
    now = now.astimezone(LONDON) if now.tzinfo else now.replace(tzinfo=LONDON)
    # The existing hourly task targets 10am. Allow a short startup delay,
    # but never send during later hours or on Friday.
    if now.weekday() != 3 or now.hour != 10 or now.minute >= 15:
        return None
    return now.date() + timedelta(days=1), now.strftime('%Y-%m-%dT10:00')


def send_report_email(content):
    from app import app, send_smtp_message
    message = MIMEMultipart('alternative')
    message['From'] = app.config['SMTP_FROM']
    message['To'] = ', '.join(TO)
    message['Cc'] = ', '.join(CC)
    message['Subject'] = content['subject']
    message['Message-ID'] = make_msgid()
    message.attach(MIMEText(content['body'], 'plain', 'utf-8'))
    message.attach(MIMEText(content['html'], 'html', 'utf-8'))
    send_smtp_message(message, recipients=list(ENVELOPE))


def run_building_report_job(now=None):
    from app import (app, db, BuildingReportDispatch, EmailDeliveryUncertain, get_setting,
                     reminders_mail_ready, friendly_smtp_error)
    counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    if get_setting(ENABLED_KEY, 'false') != 'true':
        return counts
    batch = due_batch(now or datetime.now(LONDON))
    if not batch:
        return counts
    day, key = batch
    # Any successful list for this Friday is final, including an older-format
    # list. A change in the rota or a cancellation never triggers another email.
    if BuildingReportDispatch.query.filter_by(session_date=day, status='sent').first():
        counts['skipped'] = 1
        return counts
    if BuildingReportDispatch.query.filter_by(session_date=day, status='sending').first():
        counts['failed'] = 1
        return counts
    dispatch = BuildingReportDispatch.query.filter_by(session_date=day, batch_key=key).first()
    if dispatch and dispatch.status != 'failed':
        counts['skipped'] = 1
        return counts
    snapshot = json.loads(dispatch.snapshot) if dispatch else build_snapshot(day)
    if not snapshot['scheduled']:
        return counts
    if not reminders_mail_ready():
        counts['failed'] = 1
        return counts
    if dispatch:
        # Atomic claim for a definite failure. Reuse the frozen list.
        claimed = BuildingReportDispatch.query.filter_by(id=dispatch.id, status='failed').update(
            {'status': 'sending', 'error': ''}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            counts['skipped'] = 1
            return counts
        db.session.refresh(dispatch)
    else:
        dispatch = BuildingReportDispatch(session_date=day, batch_key=key,
            kind='initial', status='sending', snapshot=json.dumps(snapshot, ensure_ascii=False))
        db.session.add(dispatch)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            counts['skipped'] = 1
            return counts
    try:
        send_report_email(report_content(day, snapshot))
    except Exception as error:
        dispatch.status = 'sending' if isinstance(error, EmailDeliveryUncertain) else 'failed'
        dispatch.error = friendly_smtp_error(error)
        db.session.commit()
        app.logger.warning('Building attendance email failed for %s', day)
        counts['failed'] = 1
        return counts
    dispatch.status = 'sent'
    dispatch.sent_at = datetime.utcnow()
    db.session.commit()
    counts['sent'] = 1
    return counts
