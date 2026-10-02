"""Admin-reviewed general messages to past F@F room and yoga registrants."""
import calendar
import json
import re
import secrets
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

PERIODS = {'all': 'All past dates', '3': 'Past 3 months',
           '6': 'Past 6 months', '12': 'Past 12 months'}
AUDIENCES = {'bookings': 'Past bookings', 'attended': 'Recorded attendance only'}
EMAIL = re.compile(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+\Z')


def past_recipients(period, audience, today=None):
    from app import db, Booking, YogaBooking, is_blocked_email_recipient
    if period not in PERIODS or audience not in AUDIENCES:
        raise ValueError('Choose a valid booking period and recipient group.')
    today = today or datetime.now(ZoneInfo('Europe/London')).date()
    since = None
    if period != 'all':
        total = today.year * 12 + today.month - 1 - int(period)
        year, month = divmod(total, 12)
        month += 1
        since = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    recipients = set()
    for model, email, day in ((Booking, Booking.user_email, Booking.booking_date),
                              (YogaBooking, YogaBooking.email, YogaBooking.session_date)):
        query = db.session.query(email).filter(day < today)
        if model is Booking:
            query = query.filter(Booking.cancelled_at.is_(None))
        query = query.filter(model.attended.is_(True) if audience == 'attended'
                             else model.attended.isnot(False))
        if since:
            query = query.filter(day >= since)
        for (value,) in query.distinct().all():
            value = (value or '').strip().lower()
            if EMAIL.fullmatch(value) and not is_blocked_email_recipient(value):
                recipients.add(value)
    return sorted(recipients)


def draft(period, audience, booking_url):
    return {'request_key': secrets.token_hex(16), 'period': period, 'audience': audience,
            'label': f'{AUDIENCES.get(audience, "")} / {PERIODS.get(period, "")}',
            'recipients': past_recipients(period, audience),
            'subject': 'Booking ahead for Fridays @ Farringdon',
            'body': f'''Hello,

If you are planning to join us at Fridays @ Farringdon, please book by 8am on Thursday wherever possible. This helps us prepare the attendee list for the building team. Bookings remain open afterwards, and we will send the building team updates about later bookings.

Book your space here:
{booking_url}

A meeting-room booking gives you access to that room only. If you would also like to join the social space, you will need to book that space separately.

We look forward to seeing you!

Many thanks,
London Autism Group Charity
Fridays @ Farringdon'''}


def send(data):
    from app import (app, db, GeneralEmailBlast, is_blocked_email_recipient,
                     reminders_mail_ready, send_smtp_message, EmailDeliveryUncertain,
                     friendly_smtp_error)
    key = data.get('request_key')
    subject, body = data.get('subject'), data.get('body')
    period, audience = data.get('period'), data.get('audience')
    values = data.get('recipients')
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key):
        return {'error': 'Open a new general email draft before sending.'}, 400
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or '\n' in subject or '\r' in subject:
        return {'error': 'Enter a subject of up to 200 characters on one line.'}, 400
    if not isinstance(body, str) or not body.strip() or len(body) > 50000:
        return {'error': 'Enter a message of up to 50,000 characters.'}, 400
    if not isinstance(period, str) or not isinstance(audience, str) or period not in PERIODS or audience not in AUDIENCES or not isinstance(values, list):
        return {'error': 'Choose a valid recipient group and period.'}, 400
    recipients = set()
    for value in values:
        if not isinstance(value, str) or not EMAIL.fullmatch(value.strip()):
            return {'error': 'The recipient list contains an invalid email address.'}, 400
        value = value.strip().lower()
        if not is_blocked_email_recipient(value):
            recipients.add(value)
    recipients = sorted(recipients)
    if not recipients:
        return {'error': 'At least one recipient is required.'}, 400
    existing = GeneralEmailBlast.query.filter_by(request_key=key).first()
    if existing:
        if existing.status == 'sent':
            return {'success': True, 'already_sent': True,
                    'sent_to': len(json.loads(existing.recipients))}, 200
        return {'error': 'This send was already attempted. Check the email history and mailbox before creating a new draft.',
                'retry_blocked': True}, 409
    if not reminders_mail_ready():
        return {'error': 'Email sending is not configured. No email has been sent.'}, 503
    record = GeneralEmailBlast(request_key=key, subject=subject.strip(), body=body.strip(),
        recipients=json.dumps(recipients), period=period, audience=audience, status='sending')
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {'error': 'This draft is already being sent. Check the history before retrying.', 'retry_blocked': True}, 409
    message = MIMEMultipart('alternative')
    message['From'] = app.config['SMTP_FROM']
    message['To'] = app.config['SMTP_FROM']
    message['Subject'] = record.subject
    message.attach(MIMEText(record.body, 'plain', 'utf-8'))
    paragraphs = ''.join('<p>' + escape(p).replace('\n', '<br>') + '</p>'
                         for p in record.body.split('\n\n'))
    message.attach(MIMEText('<html><body>' + paragraphs + '</body></html>', 'html', 'utf-8'))
    try:
        # Envelope recipients act as BCC, without exposing addresses in headers.
        send_smtp_message(message, recipients=recipients)
    except Exception as error:
        record.status = 'uncertain' if isinstance(error, EmailDeliveryUncertain) else 'failed'
        record.error = friendly_smtp_error(error)
        db.session.commit()
        return {'error': record.error + ' Check the email history before creating another draft.', 'retry_blocked': True}, 502
    record.status = 'sent'
    record.sent_at = datetime.utcnow()
    db.session.commit()
    return {'success': True, 'sent_to': len(recipients)}, 200
