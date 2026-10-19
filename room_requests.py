"""Venue room preferences, reviewed before sending. Never publishes availability."""
import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from html import escape
from zoneinfo import ZoneInfo

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

LONDON = ZoneInfo('Europe/London')
TO = ('emma.perez@macmillan.com', 'martha.fisher@macmillan.com')
CC = ('florence.perdriel@gmail.com',)
REPLY_TO = 'florence.perdriel@gmail.com'
CONTRACT_TO = 'contact@londonautismgroupcharity.org'


def requestable_rooms():
    """Use one choice per physical venue room, preserving historical DB rows."""
    from app import Room
    grouped = {}
    aliases = (('4.2', 'indigo'), ('4.4', 'rose'), ('4.7', 'clerkenwell'),
               ('loft',), ('4.6', 'farringdon'), ('5.1',))
    for room in Room.query.filter_by(is_active=True).order_by(Room.id).all():
        name = room.name.casefold()
        key = next((tokens[0] for tokens in aliases if any(token in name for token in tokens)),
                   (name.strip(), room.building_location.casefold().strip()))
        # The existing schedule mapping also favours the latest matching row.
        grouped[key] = room
    return list(grouped.values())


def date_display(day):
    suffix = 'th' if 11 <= day.day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day.day % 10, 'th')
    return f'{day:%A} {day.day}{suffix} {day:%B %Y}'


def period_fridays(start, end):
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    return [first + timedelta(days=7 * i) for i in range(max(0, (end - first).days // 7 + 1))]


def normalise(data, today=None):
    if not isinstance(data, dict):
        raise ValueError('Choose a period and at least one room.')
    try:
        start, end = (date.fromisoformat(data[key]) for key in ('start_date', 'end_date'))
    except (KeyError, TypeError, ValueError):
        raise ValueError('Enter a valid start and end date.')
    today = today or datetime.now(LONDON).date()
    if start < today or end < start or (end - start).days > 366:
        raise ValueError('Choose a future period of up to one year, with the end after the start.')
    fridays = period_fridays(start, end)
    if not fridays:
        raise ValueError('The period must include at least one Friday.')
    options = {r.id: r for r in requestable_rooms()}
    rows = data.get('rooms')
    if not isinstance(rows, list) or not rows or len(rows) > len(options):
        raise ValueError('Choose at least one room.')
    selected, seen = [], set()
    available_dates = {day.isoformat() for day in fridays}
    for row in rows:
        if not isinstance(row, dict) or type(row.get('room_id')) is not int:
            raise ValueError('Choose a valid room.')
        room_id = row['room_id']
        if room_id not in options or room_id in seen:
            raise ValueError('Choose each available room only once.')
        seen.add(room_id)
        mode = row.get('mode')
        item = {'room_id': room_id, 'room_name': options[room_id].name, 'mode': mode}
        if mode == 'exact':
            days = row.get('dates')
            if (not isinstance(days, list) or not days or any(not isinstance(d, str) for d in days)
                    or len(set(days)) != len(days) or not set(days) <= available_dates):
                raise ValueError(f'Choose Fridays within the period for {options[room_id].name}.')
            item.update(dates=sorted(days), count=len(days))
        elif mode == 'flexible':
            count = row.get('count')
            if type(count) is not int or not 1 <= count <= len(fridays) or row.get('dates'):
                raise ValueError(f'Choose how many of the {len(fridays)} Fridays you want {options[room_id].name}.')
            item.update(dates=[], count=count)
        else:
            raise ValueError('Choose exact Fridays or flexible dates for each room.')
        selected.append(item)
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 2000 or '\x00' in notes:
        raise ValueError('Additional details must be text of up to 2,000 characters.')
    return {'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'fridays': sorted(available_dates), 'rooms': sorted(selected, key=lambda r: r['room_id']),
            'notes': notes.replace('\r\n', '\n').replace('\r', '\n').strip()}


def compose(payload):
    start, end = (date.fromisoformat(payload[key]) for key in ('start_date', 'end_date'))
    subject = f'F@F room request: {date_display(start)} to {date_display(end)}'
    paragraphs = ['Hello Emma and Martha,',
        f'Could you help us arrange rooms for Fridays @ Farringdon for the period {date_display(start)} to {date_display(end)}?',
        'Fridays covered: ' + '; '.join(date_display(date.fromisoformat(d)) for d in payload['fridays']) + '.']
    exact = [r for r in payload['rooms'] if r['mode'] == 'exact']
    flexible = [r for r in payload['rooms'] if r['mode'] == 'flexible']
    if exact:
        paragraphs.append('Our preferred dates for these rooms are:\n' + '\n'.join(
            '- ' + r['room_name'] + ': ' + '; '.join(date_display(date.fromisoformat(d)) for d in r['dates']) + '.'
            for r in exact))
    if flexible:
        paragraphs.append('We are flexible about the dates for these rooms, within the Fridays listed above:\n' + '\n'.join(
            f'- {r["room_name"]}: {r["count"]} of the {len(payload["fridays"])} Fridays.' for r in flexible))
    if payload['notes']:
        paragraphs.append('Additional details:\n' + payload['notes'])
    paragraphs.extend([
        'These are our preferences, subject to availability. Could you let us know which rooms and dates are available?',
        f'Once agreed, could you send the hire agreement to Chris Papadopoulos at {CONTRACT_TO}?',
        'Many thanks,\nFridays @ Farringdon\nLondon Autism Group Charity'])
    return subject, '\n\n'.join(paragraphs)


def serialise(record):
    def local_time(value):
        return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(LONDON).isoformat() if value else None
    return {'review_key': record.review_key, 'subject': record.subject, 'body': record.body,
            'from_email': record.from_email, 'to': list(TO), 'cc': list(CC), 'reply_to': REPLY_TO,
            'contract_to': CONTRACT_TO, 'status': record.status, 'error': record.error,
            'created_at': local_time(record.created_at), 'sent_at': local_time(record.sent_at)}


def preview(data):
    from app import app, db, RoomRequest
    payload = normalise(data)
    subject, body = compose(payload)
    sender = app.config['SMTP_FROM']
    fingerprint = hashlib.sha256(json.dumps([payload, subject, body, sender, TO, CC, REPLY_TO],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    record = RoomRequest.query.filter_by(fingerprint=fingerprint).first()
    if record is None:
        record = RoomRequest(review_key=secrets.token_urlsafe(32), fingerprint=fingerprint,
            payload=json.dumps(payload), subject=subject, body=body, from_email=sender, status='draft')
        db.session.add(record)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            record = RoomRequest.query.filter_by(fingerprint=fingerprint).one()
    elif record.status == 'failed':
        # A definite failure may be explicitly reviewed and attempted again.
        RoomRequest.query.filter_by(id=record.id, status='failed').update({'status': 'draft', 'error': ''})
        db.session.commit()
        db.session.refresh(record)
    return serialise(record)


def html_body(body):
    """Natural-width paragraphs and lists, with all user text escaped."""
    blocks = []
    for paragraph in body.split('\n\n'):
        lines = paragraph.split('\n')
        if len(lines) > 1 and all(line.startswith('- ') for line in lines[1:]):
            blocks.append('<p>' + escape(lines[0]) + '</p><ul>' + ''.join(
                '<li>' + escape(line[2:]) + '</li>' for line in lines[1:]) + '</ul>')
        else:
            blocks.append('<p>' + escape(' '.join(lines)) + '</p>')
    return '<html><body>' + ''.join(blocks) + '</body></html>'


def send(data):
    from app import (app, db, RoomRequest, reminders_mail_ready, send_smtp_message,
                     EmailDeliveryUncertain)
    if not isinstance(data, dict) or data.get('confirmed') is not True:
        return {'error': 'Preview the request and confirm you want to send it.'}, 400
    key = data.get('review_key')
    if not isinstance(key, str) or not 20 <= len(key) <= 64:
        return {'error': 'Open a request preview first.'}, 400
    if set(data) - {'review_key', 'confirmed'}:
        return {'error': 'The email must match its preview. Go back and preview any changes.'}, 400
    record = RoomRequest.query.filter_by(review_key=key).first()
    if record is None:
        return {'error': 'That preview was not found. Preview the request again.'}, 404
    if record.status == 'sent':
        return {'success': True, 'already_sent': True, 'request': serialise(record)}, 200
    if record.status != 'draft':
        return {'error': 'This send was already attempted. Check the history and sent mailbox before trying anything further.',
                'request': serialise(record)}, 409
    payload = json.loads(record.payload)
    if date.fromisoformat(payload['start_date']) < datetime.now(LONDON).date():
        return {'error': 'The request period has started. Choose a future period and preview again.'}, 409
    if record.from_email != app.config['SMTP_FROM']:
        return {'error': 'The sender has changed. Preview the request again.'}, 409
    if not reminders_mail_ready():
        return {'error': 'Email sending is unavailable. Nothing has been sent.'}, 503
    claimed = RoomRequest.query.filter_by(id=record.id, status='draft').update(
        {'status': 'sending'}, synchronize_session=False)
    db.session.commit()
    if not claimed:
        return {'error': 'This request is already being sent. Check the history.'}, 409
    message = MIMEMultipart('alternative')
    message['From'] = record.from_email
    message['To'] = ', '.join(TO)
    message['Cc'] = ', '.join(CC)
    message['Reply-To'] = REPLY_TO
    message['Subject'] = record.subject
    message['Message-ID'] = make_msgid()
    message.attach(MIMEText(record.body, 'plain', 'utf-8'))
    message.attach(MIMEText(html_body(record.body), 'html', 'utf-8'))
    try:
        send_smtp_message(message, recipients=list(TO + CC))
    except Exception as error:
        record.status = 'uncertain' if isinstance(error, EmailDeliveryUncertain) else 'failed'
        record.error = ('Delivery could not be confirmed. Check the sent mailbox before sending anything again.'
                        if record.status == 'uncertain' else 'The email could not be sent. Preview it again to retry.')
        db.session.commit()
        app.logger.warning('Room request %s email failed: %s', record.id, type(error).__name__)
        return {'error': record.error, 'request': serialise(record)}, 502
    record.status, record.sent_at = 'sent', datetime.utcnow()
    db.session.commit()
    return {'success': True, 'request': serialise(record)}, 200


def register_routes(app, admin_required):
    @app.after_request
    def protect_room_request_responses(response):
        if request.path.startswith('/api/admin/room-requests/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    def input_data():
        if not request.is_json:
            raise ValueError('Send a JSON request.')
        origin = request.headers.get('Origin')
        if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
            # PythonAnywhere terminates HTTPS before the Flask worker.
            if origin.rstrip('/') != 'https://' + request.host:
                raise ValueError('Open this form from the booking site.')
        return request.get_json(silent=True)

    @app.get('/api/admin/room-requests/options')
    @admin_required
    def room_request_options():
        today = datetime.now(LONDON).date()
        first = today + timedelta(days=(4 - today.weekday()) % 7)
        return jsonify({'rooms': [{'id': r.id, 'name': r.name} for r in requestable_rooms()],
            'start_date': first.isoformat(), 'end_date': (first + timedelta(days=21)).isoformat(),
            'min_date': today.isoformat(), 'to': list(TO), 'cc': list(CC), 'contract_to': CONTRACT_TO})

    @app.post('/api/admin/room-requests/preview')
    @admin_required
    def room_request_preview():
        try:
            return jsonify(preview(input_data()))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

    @app.post('/api/admin/room-requests/send')
    @admin_required
    def room_request_send():
        try:
            result, status = send(input_data())
            return jsonify(result), status
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

    @app.get('/api/admin/room-requests/history')
    @admin_required
    def room_request_history():
        from app import RoomRequest
        return jsonify([serialise(r) for r in RoomRequest.query.order_by(RoomRequest.created_at.desc()).limit(30).all()])
