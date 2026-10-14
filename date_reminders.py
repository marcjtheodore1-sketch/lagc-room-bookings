"""Optional reminders to book one Friday. Never reserves a place or subscribes weekly."""
import hashlib
import secrets
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from flask import render_template, request
from sqlalchemy.exc import IntegrityError

LONDON = ZoneInfo('Europe/London')
REQUEST_NOTICE = 'If this request can be processed, a confirmation email will arrive shortly. Follow its link to start this one-off reminder. No place has been booked.'


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def reminder_due(day):
    return datetime.combine(day - timedelta(days=2), datetime.min.time(), tzinfo=LONDON).replace(hour=9)


def register_routes(app):
    def page(**context):
        from app import get_upcoming_fridays
        dates = [day for day in get_upcoming_fridays() if not day['registration_closed']]
        return render_template('date_reminder.html', dates=dates, **context)

    @app.route('/reminders/date', methods=['GET'])
    def date_reminder_page():
        return page(selected=request.args.get('date', ''))

    @app.route('/reminders/date/request', methods=['POST'])
    def request_date_reminder():
        from app import (db, DateBookingReminder, get_room_schedule_ids, booking_registration_closed,
                         is_blocked_email_recipient, reminders_mail_ready, reminder_base_url,
                         reminder_date_display, send_confirmation_email)
        email = request.form.get('email', '').strip().lower()
        selected = request.form.get('date', '')
        if (len(email) > 254 or email.count('@') != 1 or '.' not in email.rsplit('@', 1)[-1]
                or any(character.isspace() for character in email)):
            return page(error='Enter a valid email address.', selected=selected), 400
        try:
            day = datetime.strptime(selected, '%Y-%m-%d').date()
        except ValueError:
            return page(error='Choose one of the available Fridays.'), 400
        if (day.weekday() != 4 or not get_room_schedule_ids().get(selected)
                or booking_registration_closed(day)):
            return page(error='Booking is closed or unavailable for that date. Choose another Friday.'), 409
        if is_blocked_email_recipient(email):
            return page(notice=REQUEST_NOTICE)
        now = datetime.utcnow()
        ip_hash = hashlib.sha256((str(app.secret_key) + ':' + (request.remote_addr or '')).encode()).hexdigest()
        record = DateBookingReminder.query.filter_by(email=email, session_date=day).first()
        if record and (record.confirmed_at or record.status != 'pending'
                       or record.requested_at > now - timedelta(minutes=10)):
            return page(notice=REQUEST_NOTICE)
        recent = DateBookingReminder.query.filter(
            DateBookingReminder.ip_hash == ip_hash,
            DateBookingReminder.requested_at > now - timedelta(hours=1)).count()
        if recent >= 20:
            return page(notice=REQUEST_NOTICE)
        if not reminders_mail_ready():
            return page(error='Email reminders are temporarily unavailable. You can still book normally.'), 503
        token = secrets.token_urlsafe(32)
        if record is None:
            record = DateBookingReminder(email=email, session_date=day)
            db.session.add(record)
        record.token_hash = token_hash(token)
        record.ip_hash = ip_hash
        record.requested_at = now
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return page(notice=REQUEST_NOTICE)
        body = (
            f'Hello,\n\nSomeone requested a one-off reminder to book Fridays @ Farringdon on {reminder_date_display(day)}.\n\n'
            'The reminder is due on Wednesday at 9am, London time. If you confirm after that, it is sent '
            'on the next scheduled check while booking is still open. It is skipped if a booking already '
            'exists for that Friday under this email address.\n\n'
            'This does not book a place or sign you up for weekly emails.\n\n'
            f'Confirm your request:\n{reminder_base_url()}/reminders/date/confirm/{token}\n\n'
            'If you did not request this, ignore this email. No reminder will start.\n\n'
            'Many thanks,\nLondon Autism Group Charity'
        )
        if not send_confirmation_email(email, 'Confirm your one-off Farringdon booking reminder', body):
            # Allow an immediate retry after a definite request-email failure.
            record.requested_at = now - timedelta(minutes=11)
            db.session.commit()
            return page(error='We could not send the confirmation email. Try again later, or book normally.'), 503
        return page(notice=REQUEST_NOTICE)

    def lookup(token):
        from app import DateBookingReminder
        return DateBookingReminder.query.filter_by(token_hash=token_hash(token)).first_or_404()

    @app.route('/reminders/date/confirm/<token>', methods=['GET', 'POST'])
    def confirm_date_reminder(token):
        from app import db, booking_registration_closed, reminder_date_display, get_room_schedule_ids
        record = lookup(token)
        closed = (booking_registration_closed(record.session_date)
                  or not get_room_schedule_ids().get(record.session_date.isoformat()))
        if request.method == 'POST' and not closed and record.status == 'pending':
            record.confirmed_at = record.confirmed_at or datetime.utcnow()
            db.session.commit()
        return render_template('date_reminder_confirm.html', token=token,
            date_display=reminder_date_display(record.session_date), closed=closed,
            confirmed=record.confirmed_at is not None, status=record.status)

    @app.route('/reminders/date/stop/<token>', methods=['GET', 'POST'])
    def stop_date_reminder(token):
        from app import db, reminder_date_display
        record = lookup(token)
        if request.method == 'POST':
            record.status = 'stopped'
            db.session.commit()
        return render_template('date_reminder_confirm.html', token=token, stopping=True,
            date_display=reminder_date_display(record.session_date), status=record.status)


def send_date_reminder(email, subject, body):
    from app import app, send_smtp_message
    if not app.config['ENABLE_EMAIL']:
        raise RuntimeError('Email sending is disabled')
    message = MIMEText(body, 'plain', 'utf-8')
    message['From'] = app.config['SMTP_FROM']
    message['To'] = email
    message['Subject'] = subject
    send_smtp_message(message, recipients=[email])


def run_date_reminders(now):
    from app import (db, DateBookingReminder, Booking, EmailDeliveryUncertain,
                     get_room_schedule_ids, booking_registration_closed,
                     is_blocked_email_recipient, reminder_base_url, reminder_date_display,
                     BOOKING_DEADLINE_NOTICE, COMMUNITY_GUIDELINES_NOTICE,
                     ACCESS_PLANNING_NOTICE, ATTENDANCE_NOTICE)
    now = now.astimezone(LONDON) if now.tzinfo else now.replace(tzinfo=LONDON)
    schedule = get_room_schedule_ids()
    counts = {'sent': 0, 'failed': 0}
    records = DateBookingReminder.query.filter(
        DateBookingReminder.confirmed_at.isnot(None),
        DateBookingReminder.status.in_(('pending', 'failed'))).all()
    for record in records:
        if (booking_registration_closed(record.session_date, now)
                or not schedule.get(record.session_date.isoformat())
                or is_blocked_email_recipient(record.email)):
            record.status = 'closed'
            db.session.commit()
            continue
        if now < reminder_due(record.session_date):
            continue
        booked = Booking.query.filter(
            Booking.booking_date == record.session_date, Booking.cancelled_at.is_(None),
            db.func.lower(Booking.user_email) == record.email).first()
        if booked:
            record.status = 'booked'
            db.session.commit()
            continue
        # Claim before SMTP: overlapping scheduler runs cannot send the same reminder.
        claimed = DateBookingReminder.query.filter(
            DateBookingReminder.id == record.id,
            DateBookingReminder.status.in_(('pending', 'failed'))).update(
                {'status': 'sending'}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        date_display = reminder_date_display(record.session_date)
        body = (
            f'Hello,\n\nYou asked for a reminder to book Fridays @ Farringdon on {date_display}.\n\n'
            f'Book here:\n{reminder_base_url()}/book?date={record.session_date.isoformat()}\n\n'
            f'{BOOKING_DEADLINE_NOTICE}\n\n'
            'This reminder does not reserve a place. Complete the booking form to book. '
            'If you have already booked using a different email address, there is no need to book again.\n\n'
            f'{COMMUNITY_GUIDELINES_NOTICE}\n\n'
            f'{ACCESS_PLANNING_NOTICE}\n\n'
            f'{ATTENDANCE_NOTICE}\n\n'
            'This is your only reminder for this request. You have not been subscribed to weekly emails.\n\n'
            'Many thanks,\nLondon Autism Group Charity'
        )
        try:
            send_date_reminder(record.email, f'Reminder to book Farringdon: {date_display}', body)
        except Exception as error:
            record.status = 'uncertain' if isinstance(error, EmailDeliveryUncertain) else 'failed'
            db.session.commit()
            counts['failed'] += 1
        else:
            record.status = 'sent'
            record.sent_at = datetime.utcnow()
            db.session.commit()
            counts['sent'] += 1
    return counts
