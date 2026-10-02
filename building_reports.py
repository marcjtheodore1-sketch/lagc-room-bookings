"""Attendance reports for Pan Macmillan, using the existing paid scheduler.

Only names, rooms, times and reported physical mobility needs leave the app.
Batch claims are committed before sending so overlapping jobs cannot duplicate
the email. An interrupted send needs an admin check before further batches.
"""
import json
import re
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
SCHEDULE = 'Thursday: 10am, 12pm, 2pm, 4pm and 6pm. Friday: 8am, 10am, 12pm, 2pm, 4pm and 6pm. London time.'
MOBILITY = re.compile(
    r'\b(?:mobility|wheel\s*chair|crutch\w*|walking (?:stick|aid|frame)|'
    r'cane|zimmer|rollator|scooter|step[ -]?free|stairs?|staircase|steps?|lift|'
    r'elevator|arthritis|physical disabilit\w*|balance|'
    r'(?:back|hip|knee|leg|foot|joint) pain|'
    r'(?:difficulty|trouble|struggle\w*) (?:with )?(?:walk\w*|stand\w*)|'
    r'(?:cannot|can\W?t|unable to) (?:walk|stand))\b', re.I)


def one_line(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def report_time(value):
    match = re.fullmatch(r'(\d{1,2}):(\d{2})\s*(AM|PM)', value, re.I)
    if not match:
        return value
    hour, minute, period = match.groups()
    return f'{int(hour)}{("." + minute) if minute != "00" else ""}{period.lower()}'


def mobility_notes(booking):
    """Keep explicit answers and matching clauses from older free-text fields.

    This flags the attendee's own words, without inferring a diagnosis or
    forwarding unrelated general accessibility or private notes.
    """
    notes = []
    explicit = one_line(booking.mobility_details)
    if explicit:
        notes.append(explicit)
    elif booking.mobility_needs:
        notes.append('Mobility needs reported; details not supplied.')
    for text in (booking.accessibility_needs, booking.other_info):
        for clause in re.split(r'[\n.!?;,]+', text or ''):
            clause = one_line(clause)
            if MOBILITY.search(clause) and clause.casefold() not in {n.casefold() for n in notes}:
                notes.append(clause)
    return notes


def build_snapshot(day):
    from app import (Booking, VolunteerAvailability, attendee_count,
                     booking_time_display, get_room_schedule_ids, fmt_hhmm)
    scheduled = get_room_schedule_ids().get(day.isoformat(), [])
    bookings = []
    for b in Booking.query.filter_by(booking_date=day, cancelled_at=None).order_by(Booking.id).all():
        start, end = map(report_time, booking_time_display(b))
        extra = []
        carer_name = ''
        if b.carer_attending:
            name = one_line(' '.join(filter(None, (b.carer_first_name, b.carer_last_name)))) or one_line(b.carer_name)
            carer_name = name.casefold()
            extra.append({'name': name or 'Name not supplied', 'role': 'Carer'})
        if b.bringing_others:
            names = [one_line(n) for n in re.split(r'[;,\n]+', b.companion_names or '') if one_line(n)]
            names = [n for n in names if one_line(re.sub(r'\([^)]*\)', '', n)).casefold() != carer_name]
            extra.extend({'name': name, 'role': 'Companion'} for name in names)
            if not names and not b.carer_attending:
                extra.append({'name': 'Name not supplied', 'role': 'Companion'})
        bookings.append({'id': b.id, 'name': one_line(b.user_name), 'others': extra,
                         'room': one_line(b.room.name), 'start': start, 'end': end,
                         'open_room': b.room.room_type == 'open',
                         'room_scheduled': b.room.is_active and b.room_id in scheduled,
                         'mobility': mobility_notes(b), 'places': attendee_count(b)})
    volunteers = []
    for v in VolunteerAvailability.query.filter_by(booking_date=day, unavailable=False).order_by(VolunteerAvailability.name, VolunteerAvailability.id).all():
        times = (f'{report_time(fmt_hhmm(v.start_time))} to {report_time(fmt_hhmm(v.end_time))}'
                 if v.start_time and v.end_time else 'Times not specified; coordinator to check')
        volunteers.append({'id': v.id, 'name': one_line(v.name), 'times': times})
    return {'date': day.isoformat(), 'scheduled': bool(scheduled),
            'bookings': bookings, 'volunteers': volunteers,
            'places': sum(b['places'] for b in bookings)}


def changed_rows(previous, current, field):
    old = {row['id']: row for row in previous.get(field, [])}
    new = {row['id']: row for row in current[field]}
    return {'added': [v for k, v in new.items() if k not in old],
            'changed': [v for k, v in new.items() if k in old and old[k] != v],
            'removed': [v for k, v in old.items() if k not in new]}


def report_content(day, snapshot, previous=None):
    from app import reminder_date_display
    changes = {key: changed_rows(previous, snapshot, key) for key in ('bookings', 'volunteers')} if previous else None
    date_display = reminder_date_display(day)
    subject = f'Fridays @ Farringdon: {"updated attendance list" if previous else "attendance list"} for {date_display}'
    lines = ['Hello Emma and Martha,', '',
             f'Here is the {"updated " if previous else ""}attendance list for {date_display}.']
    if changes:
        lines.extend(['', 'Changes since the previous email:'])
        for field, label in (('bookings', 'Booking'), ('volunteers', 'Volunteer')):
            for category, action in (('added', 'Added'), ('changed', 'Updated'), ('removed', 'Cancelled / removed')):
                for row in changes[field][category]:
                    detail = f' - {row["room"]}, {row["start"]} to {row["end"]}' if field == 'bookings' else f' - {row["times"]}'
                    others = ''.join(f'; {p["role"]}: {p["name"]}' for p in row.get('others', []))
                    lines.append(f'- {action} {label.lower()}: {row["name"]}{others}{detail}')
    if not snapshot['scheduled']:
        lines.extend(['', 'Please note: this Friday is no longer in the published room schedule.'])
    lines.extend(['', 'VOLUNTEERS', *[f'- {v["name"]}: {v["times"]}' for v in snapshot['volunteers']]])
    if not snapshot['volunteers']:
        lines.append('No volunteers have marked themselves available on the rota.')
    lines.extend(['', 'CURRENT ROOM BOOKINGS'])
    for b in snapshot['bookings']:
        others = ''.join(f'; {p["role"]}: {p["name"]}' for p in b['others'])
        lines.append(f'- {b["name"]}{others}: {b["room"]}, {b["start"]} to {b["end"]}')
        if not b['room_scheduled']:
            lines.append('  Room no longer in the published schedule; coordinator to check.')
        for note in b['mobility']:
            lines.append(f'  Reported mobility / physical access need: {note}')
    if not snapshot['bookings']:
        lines.append('No active room bookings.')
    lines.extend(['', f'{len(snapshot["bookings"])} room bookings; {snapshot["places"]} places across those bookings, including carers and companions.',
                  'Open-room times are the room opening hours, rather than individual arrival times.',
                  '', 'Further changes are grouped into scheduled updates through Friday at 6pm.',
                  '', 'Many thanks,', 'London Autism Group Charity', 'Fridays @ Farringdon'])
    body = '\n'.join(lines)
    html = render_template('building_report_email.html', snapshot=snapshot,
                           changes=changes, date_display=date_display)
    return {'subject': subject, 'body': body, 'html': html, 'to': list(TO), 'cc': list(CC)}


def due_batch(now):
    now = now.astimezone(LONDON) if now.tzinfo else now.replace(tzinfo=LONDON)
    hours = (10, 12, 14, 16, 18) if now.weekday() == 3 else (8, 10, 12, 14, 16, 18) if now.weekday() == 4 else ()
    # The hourly scheduler runs at :00. Allow a small startup delay. Each
    # batch is still permanently claimed, including when nothing changed.
    if now.hour not in hours or now.minute >= 15:
        return None
    day = now.date() + timedelta(days=1) if now.weekday() == 3 else now.date()
    return day, now.strftime('%Y-%m-%dT%H:00')


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
    # A unique row is a permanent claim, including no-change checks and errors.
    if BuildingReportDispatch.query.filter_by(session_date=day, batch_key=key).first():
        counts['skipped'] = 1
        return counts
    if BuildingReportDispatch.query.filter_by(session_date=day, status='sending').first():
        counts['failed'] = 1
        return counts  # interrupted/overlapping send: do not guess its outcome
    previous_send = BuildingReportDispatch.query.filter_by(session_date=day, status='sent').order_by(BuildingReportDispatch.id.desc()).first()
    previous = json.loads(previous_send.snapshot) if previous_send else None
    snapshot = build_snapshot(day)
    if not snapshot['scheduled'] and not previous:
        return counts  # rooms not yet released, or no session this week
    unchanged = snapshot == previous
    if not unchanged and not reminders_mail_ready():
        counts['failed'] = 1
        return counts  # never pretend an email was sent with mail disabled
    dispatch = BuildingReportDispatch(session_date=day, batch_key=key,
        kind='update' if previous else 'initial', status='skipped' if unchanged else 'sending',
        snapshot=json.dumps(snapshot, ensure_ascii=False))
    db.session.add(dispatch)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        counts['skipped'] = 1
        return counts
    if unchanged:
        counts['skipped'] = 1
        return counts
    try:
        send_report_email(report_content(day, snapshot, previous))
    except Exception as error:
        dispatch.status = 'sending' if isinstance(error, EmailDeliveryUncertain) else 'failed'
        dispatch.error = friendly_smtp_error(error)
        db.session.commit()
        app.logger.warning('Building report email failed for %s batch %s', day, key)
        counts['failed'] = 1
        return counts
    dispatch.status = 'sent'
    dispatch.sent_at = datetime.utcnow()
    db.session.commit()
    counts['sent'] = 1
    return counts
