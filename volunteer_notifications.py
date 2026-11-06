"""Notify Florence about saved rota changes, without retrying uncertain email."""
import json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from html import escape

RECIPIENT = 'florence.perdriel@gmail.com'


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
    changes = [{'date': day, 'before': before.get(day, ('clear', '', '')),
                'after': state} for day, state in sorted(after.items())
               if before.get(day, ('clear', '', '')) != state]
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
        hour, minute = map(int, value.split(':'))
        return f'{hour % 12 or 12}' + (f'.{minute:02}' if minute else '') + ('am' if hour < 12 else 'pm')

    return f'Available ({clock(start)} to {clock(end)})'


def compose_notification(record):
    from app import reminder_base_url, reminder_date_display
    lines = []
    for change in json.loads(record.changes):
        day = datetime.strptime(change['date'], '%Y-%m-%d').date()
        lines.append(f'{reminder_date_display(day)} {day.year}: '
                     f'{state_label(change["before"])} → {state_label(change["after"])}')
    intro = f'The saved availability for {record.name} has changed:'
    link = reminder_base_url() + '/admin'
    closing = 'Open the Volunteer Rota tab to check the latest cover.'
    text = '\n\n'.join(['Hi Florence,', intro, '\n'.join(lines), closing, 'View the rota: ' + link])
    html = ('<html><body><p>Hi Florence,</p><p>' + escape(intro) + '</p><ul>'
            + ''.join('<li>' + escape(line) + '</li>' for line in lines) + '</ul><p>'
            + escape(closing) + '</p><p><a href="' + escape(link, quote=True)
            + '">View the rota</a> (admin sign-in required)</p></body></html>')
    return 'Fridays @ Farringdon: volunteer availability changed', text, html


def deliver_notification(record):
    """Claim once after saving. Report failure without undoing the rota save."""
    from app import (app, db, VolunteerRotaNotification, reminders_mail_ready,
                     send_smtp_message, EmailDeliveryUncertain)
    if record is None:
        return {'status': 'unchanged'}
    claimed = VolunteerRotaNotification.query.filter_by(id=record.id, status='pending').update(
        {'status': 'sending'}, synchronize_session=False)
    db.session.commit()
    db.session.refresh(record)
    if not claimed:
        return {'status': record.status}
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
    db.session.commit()
    result = {'status': record.status}
    if record.status != 'sent':
        result['warning'] = ('Your rota changes are saved, but Florence\'s email notification could not be confirmed. '
                             'Let Florence know directly. Do not save again just to resend the email.')
    return result
