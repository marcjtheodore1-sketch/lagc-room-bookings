"""Notify Florence about saved rota changes, without retrying uncertain email."""
import json
import unicodedata
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from html import escape
from sqlalchemy.exc import SQLAlchemyError

RECIPIENT = 'florence.perdriel@gmail.com'
DELIVERY_WARNING = ("Your rota changes are saved, but Florence's email notification could not be confirmed. "
                    'Let Florence know directly. Do not save again just to resend the email.')


def name_key(name):
    return unicodedata.normalize('NFC', name.strip()).casefold()


def matching_availability(name, query=None):
    """SQLite lower() is ASCII-only; use one Unicode-aware comparison."""
    from app import VolunteerAvailability
    query = query if query is not None else VolunteerAvailability.query
    return [row for row in query.order_by(VolunteerAvailability.id).all()
            if name_key(row.name) == name_key(name)]


def availability_snapshot(rows):
    """Keep all distinct states when legacy names have duplicate dates."""
    before = {}
    for row in rows:
        states = before.setdefault(row.booking_date.isoformat(), [])
        state = availability_state(row)
        if state not in states:
            states.append(state)
    return before


def availability_state(row):
    if row is None:
        return ('clear', '', '')
    if row.unavailable:
        return ('unavailable', '', '')
    return ('available', row.start_time or '', row.end_time or '')


def entry_state(entry):
    status = entry['status']
    return (status, entry.get('start_time', '') if status == 'available' else '',
            entry.get('end_time', '') if status == 'available' else '')


def prepare_notification(name, before, after):
    """Add the delivery record to the same transaction as the availability."""
    from app import db, VolunteerRotaNotification
    changes = []
    for day, state in sorted(after.items()):
        old_states = before.get(day, [('clear', '', '')])
        if old_states == [state]:
            continue
        change = {'date': day, 'before': old_states[0], 'after': state}
        if len(old_states) > 1:
            change['before_states'] = old_states
        changes.append(change)
    if not changes:
        return None
    record = VolunteerRotaNotification(name=name, changes=json.dumps(changes), status='pending')
    db.session.add(record)
    return record


def state_label(state):
    status, start, end = state
    if status == 'clear':
        return 'Not recorded'
    if status == 'unavailable':
        return 'Not available'
    if not start or not end:
        return 'Available (times not recorded)'

    def clock(value):
        try:
            hour, minute = map(int, value.split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return value
        except (ValueError, TypeError, AttributeError):
            return str(value)
        return f'{hour % 12 or 12}' + (f'.{minute:02}' if minute else '') + ('am' if hour < 12 else 'pm')

    return f'Available ({clock(start)} to {clock(end)})'


def compose_notification(record):
    from app import reminder_base_url, reminder_date_display
    lines = []
    for change in json.loads(record.changes):
        day = datetime.strptime(change['date'], '%Y-%m-%d').date()
        previous = (('Conflicting saved entries: ' + '; '.join(state_label(s) for s in change['before_states']))
                    if change.get('before_states') else state_label(change['before']))
        lines.append(f'{reminder_date_display(day)} {day.year}: '
                     f'{previous} → {state_label(change["after"])}')
    intro = f'The saved availability for {record.name} has changed:'
    link = reminder_base_url() + '/admin'
    closing = 'Open the Volunteer Rota tab to check the latest cover.'
    text = '\n\n'.join(['Hi Florence,', intro, '\n'.join(lines), closing, 'View the rota: ' + link])
    html = ('<html><body><p>Hi Florence,</p><p>' + escape(intro) + '</p><ul>'
            + ''.join('<li>' + escape(line) + '</li>' for line in lines) + '</ul><p>'
            + escape(closing) + '</p><p><a href="' + escape(link, quote=True)
            + '">View the rota</a> (admin sign-in required)</p></body></html>')
    return 'Fridays @ Farringdon: volunteer availability changed', text, html


def delivery_result(status, record_id=None):
    result = {'status': status}
    if record_id is not None:
        result['id'] = record_id
    if status not in ('sent', 'unchanged'):
        result['warning'] = DELIVERY_WARNING
    return result


def deliver_notification(record_id):
    """Claim once after saving. Report failure without undoing the rota save."""
    from app import (app, db, VolunteerRotaNotification, reminders_mail_ready,
                     send_smtp_message, EmailDeliveryUncertain)
    if record_id is None:
        return {'status': 'unchanged'}
    # Do not access an expired ORM object before this guard. Even a SELECT
    # after the rota commit can fail, and must not invalidate that saved result.
    try:
        claimed = VolunteerRotaNotification.query.filter_by(id=record_id, status='pending').update(
            {'status': 'sending'}, synchronize_session=False)
        db.session.commit()
        record = db.session.get(VolunteerRotaNotification, record_id)
    except SQLAlchemyError as error:
        db.session.rollback()
        app.logger.warning('Rota notification %s claim could not be confirmed: %s. Check delivery history.',
                           record_id, type(error).__name__)
        return delivery_result('uncertain', record_id)
    if record is None:
        return delivery_result('uncertain', record_id)
    if not claimed:
        return delivery_result(record.status, record_id)
    if not reminders_mail_ready():
        record.status = 'unavailable'
    else:
        try:
            subject, text, html = compose_notification(record)
            message = MIMEMultipart('alternative')
            message['From'] = app.config['SMTP_FROM']
            message['To'] = RECIPIENT
            message['Subject'] = subject
            message['Message-ID'] = make_msgid()
            message.attach(MIMEText(text, 'plain', 'utf-8'))
            message.attach(MIMEText(html, 'html', 'utf-8'))
            send_smtp_message(message, recipients=[RECIPIENT])
        except Exception as error:
            record.status = 'uncertain' if isinstance(error, EmailDeliveryUncertain) else 'failed'
            record.error = type(error).__name__
            app.logger.warning('Rota notification %s: %s', record.id, record.error)
        else:
            record.status = 'sent'
            record.sent_at = datetime.utcnow()
    status = record.status
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        app.logger.warning('Rota notification %s outcome could not be recorded: %s. Check delivery before retrying.',
                           record_id, type(error).__name__)
        return delivery_result('uncertain', record_id)
    return delivery_result(status, record_id)


def saved_rota_response(notification):
    """Snapshot before committing so delivery errors require no further reads."""
    from app import db, get_volunteer_rota
    db.session.flush()
    record_id = notification.id if notification is not None else None
    rota = get_volunteer_rota()
    db.session.commit()
    return {**rota, 'notification': deliver_notification(record_id)}
