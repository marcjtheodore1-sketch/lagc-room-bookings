"""Venue room preferences, reviewed before sending. Never publishes availability."""
import hashlib
import json
import secrets
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from html import escape
from zoneinfo import ZoneInfo

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

LONDON = ZoneInfo('Europe/London')
TO = ('emma.perez@macmillan.com', 'martha.fisher@macmillan.com')
CHRIS_EMAIL = 'londonautismgroupcharity@gmail.com'
FLORENCE_EMAIL = 'florence.perdriel@gmail.com'
CC = (FLORENCE_EMAIL, CHRIS_EMAIL)
REPLY_TO = ', '.join(CC)
CONTRACT_TO = 'contact@londonautismgroupcharity.org'
TEST_RECIPIENTS = {
    'florence': ('Florence', 'florence.perdriel@gmail.com'),
    'chris': ('Chris', 'londonautismgroupcharity@gmail.com'),
}


def delivery_details(payload):
    # Older saved requests were real requests. Never reroute their history.
    mode = payload.get('delivery_mode', 'live')
    if mode == 'live':
        # Preserve the actual recipients shown for older saved emails. New
        # previews use the updated routing, and old drafts must be reviewed again.
        copied = list(CC) if payload.get('routing_version') == 2 else [FLORENCE_EMAIL]
        return {'delivery_mode': 'live', 'to': list(TO), 'cc': copied, 'reply_to': ', '.join(copied)}
    recipients = payload.get('test_recipients')
    if (mode != 'test' or not isinstance(recipients, list) or not recipients
            or any(not isinstance(key, str) or key not in TEST_RECIPIENTS for key in recipients)
            or len(set(recipients)) != len(recipients)):
        raise ValueError('Choose Florence, Chris, or both for the test email.')
    addresses = [TEST_RECIPIENTS[key][1] for key in sorted(recipients)]
    return {'delivery_mode': 'test', 'to': addresses, 'cc': [], 'reply_to': ', '.join(addresses)}


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


def room_label(name):
    for token, label in [('indigo', 'Indigo'), ('rose', 'Rose'), ('clerkenwell', 'Clerkenwell'),
                         ('loft', 'Loft'), ('farringdon', 'Farringdon')]:
        if token in name.casefold():
            return label
    return name


def normalise(data):
    if not isinstance(data, dict):
        raise ValueError('Choose the rooms and how many Fridays you would like each one.')
    if set(data) - {'request_id', 'rooms', 'notes', 'subject', 'body', 'delivery_mode', 'test_recipients', 'period'}:
        raise ValueError('This form has changed. Refresh the page to request rooms without dates.')
    request_id = data.get('request_id')
    if (not isinstance(request_id, str) or not 24 <= len(request_id) <= 64
            or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for char in request_id)):
        raise ValueError('Refresh the page to start a new request.')
    options = {room.id: room for room in requestable_rooms()}
    rows = data.get('rooms')
    if not isinstance(rows, list) or not rows or len(rows) > len(options):
        raise ValueError('Choose at least one room by entering how many Fridays you would like it.')
    selected, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'room_id', 'count'}
                or type(row.get('room_id')) is not int or row['room_id'] not in options or row['room_id'] in seen):
            raise ValueError('Choose each available room only once.')
        if type(row.get('count')) is not int or not 1 <= row['count'] <= 52:
            raise ValueError('Enter a whole number between 1 and 52 for each room you want.')
        seen.add(row['room_id'])
        selected.append({'room_id': row['room_id'], 'room_name': room_label(options[row['room_id']].name), 'count': row['count']})
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 2000 or '\x00' in notes:
        raise ValueError('Additional details must be text of up to 2,000 characters.')
    period = data.get('period', '')
    if (not isinstance(period, str) or len(period) > 160
            or any(char in period for char in '\r\n\x00')):
        raise ValueError('Enter a short period on one line, such as January 2027, or leave it blank.')
    mode = data.get('delivery_mode', 'live')
    delivery = {'delivery_mode': mode, 'routing_version': 2}
    if mode == 'test':
        delivery['test_recipients'] = data.get('test_recipients', [])
    elif mode != 'live' or data.get('test_recipients'):
        raise ValueError('Choose a test email or a room request to Emma and Martha.')
    delivery_details(delivery)
    if mode == 'test':
        delivery['test_recipients'] = sorted(delivery['test_recipients'])
    return {'version': 2, 'request_id': request_id, **delivery,
            'rooms': sorted(selected, key=lambda room: room['room_id']),
            'notes': notes.replace('\r\n', '\n').replace('\r', '\n').strip(), 'period': period.strip()}


def compose(payload):
    subject = 'Fridays @ Farringdon: room booking'
    period = payload.get('period', '')
    opening = (f'I am reaching out to agree on what rooms we can have for the {period} period.' if period else
               'I am reaching out to agree on what rooms we can have for the next period.')
    paragraphs = ['Hello Emma and Martha,', opening,
        'If possible, could we get:\n' + '\n'.join(f'- {room["room_name"]}: {room["count"]} Friday' +
            ('s' if room['count'] != 1 else '') for room in payload['rooms'])]
    if payload['notes']:
        paragraphs.append(payload['notes'])
    paragraphs.extend(['If this is all possible, please pick the dates that work for you and share the hire agreement directly with Chris as you usually do.',
        'If there are points we need to align on, please reply to this message.',
        'Many thanks 🙂\nFlorence Perdriel\nLondon Autism Group Charity'])
    if payload['delivery_mode'] == 'test':
        subject = '[TEST] ' + subject
        names = ' and '.join(TEST_RECIPIENTS[key][0] for key in payload['test_recipients'])
        paragraphs.insert(0, f'TEST ONLY: This copy is for {names}. Emma and Martha will not receive it.')
    return subject, '\n\n'.join(paragraphs)


def reviewed_text(data, payload):
    if 'subject' not in data and 'body' not in data:
        return compose(payload)
    subject, body = data.get('subject'), data.get('body')
    if (not isinstance(subject, str) or not subject.strip() or len(subject) > 200
            or any(char in subject for char in '\r\n\x00')):
        raise ValueError('Enter an email subject of up to 200 characters on one line.')
    if not isinstance(body, str) or not body.strip() or len(body) > 12000 or '\x00' in body:
        raise ValueError('Enter an email message of up to 12,000 characters.')
    subject = subject.strip()
    if payload['delivery_mode'] == 'test' and not subject.startswith('[TEST] '):
        subject = '[TEST] ' + subject
    return subject, body.replace('\r\n', '\n').replace('\r', '\n').strip()


def recipient_names(delivery):
    names = {TO[0]: 'Emma', TO[1]: 'Martha', CC[0]: 'Florence',
             TEST_RECIPIENTS['chris'][1]: 'Chris'}
    return {key: [names.get(address, 'Previous recipient') for address in delivery[key]] for key in ('to', 'cc')}


def serialise(record):
    def local_time(value):
        return value.replace(tzinfo=ZoneInfo('UTC')).astimezone(LONDON).isoformat() if value else None
    delivery = delivery_details(json.loads(record.payload))
    return {'review_key': record.review_key, 'subject': record.subject, 'body': record.body,
            'from_email': record.from_email, **delivery, 'recipient_names': recipient_names(delivery),
            'reply_to_names': recipient_names({'to': [address.strip() for address in delivery['reply_to'].split(',')], 'cc': []})['to'],
            'contract_to': CONTRACT_TO, 'status': record.status, 'error': record.error,
            'created_at': local_time(record.created_at), 'sent_at': local_time(record.sent_at)}


def preview(data):
    from app import app, db, RoomRequest
    payload = normalise(data)
    subject, body = reviewed_text(data, payload)
    sender = app.config['SMTP_FROM']
    # One record per request, including its edits. A new form gets a fresh ID,
    # so Florence can request the same room quantities again in future.
    identity = [2, payload['request_id'], sender, TO, CC, REPLY_TO]
    if payload['delivery_mode'] == 'test':
        identity.append(delivery_details(payload))
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    record = RoomRequest.query.filter_by(fingerprint=fingerprint).first()
    # A deliberate new preview may repeat a test. Repeated sends of the same
    # reviewed key remain duplicate-safe, and tests never block a real request.
    while payload['delivery_mode'] == 'test' and record is not None and record.status == 'sent':
        fingerprint = hashlib.sha256((fingerprint + record.review_key).encode()).hexdigest()
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
    # Sent or uncertain requests are immutable. Editing a draft rotates its
    # review key, so an older preview cannot send wording that has changed.
    if record.status in ('draft', 'failed'):
        if record.subject != subject or record.body != body or json.loads(record.payload) != payload or record.status == 'failed':
            RoomRequest.query.filter_by(id=record.id, review_key=record.review_key).filter(
                RoomRequest.status.in_(('draft', 'failed'))).update({
                    'review_key': secrets.token_urlsafe(32), 'payload': json.dumps(payload),
                    'subject': subject, 'body': body, 'status': 'draft', 'error': ''}, synchronize_session=False)
            db.session.commit()
            db.session.refresh(record)
    return serialise(record)


def html_body(body):
    """Natural-width paragraphs and lists, with all user text escaped."""
    blocks = []
    for paragraph in body.split('\n\n'):
        lines = paragraph.split('\n')
        if all(line.startswith('- ') for line in lines):
            blocks.append('<ul>' + ''.join('<li>' + escape(line[2:]) + '</li>' for line in lines) + '</ul>')
        elif len(lines) > 1 and all(line.startswith('- ') for line in lines[1:]):
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
    if payload.get('version') != 2 or payload.get('delivery_mode') not in ('live', 'test'):
        return {'error': 'This is an older preview. Refresh the page and prepare a new room request.'}, 409
    if payload['delivery_mode'] == 'live' and payload.get('routing_version') != 2:
        return {'error': 'The reply settings have changed. Prepare a new preview before sending.'}, 409
    if record.from_email != app.config['SMTP_FROM']:
        return {'error': 'The sender has changed. Preview the request again.'}, 409
    delivery = delivery_details(payload)
    if not reminders_mail_ready():
        return {'error': 'Email sending is unavailable. Nothing has been sent.'}, 503
    claimed = RoomRequest.query.filter_by(id=record.id, status='draft', review_key=key).update(
        {'status': 'sending'}, synchronize_session=False)
    db.session.commit()
    if not claimed:
        return {'error': 'This request is already being sent. Check the history.'}, 409
    message = MIMEMultipart('alternative')
    message['From'] = record.from_email
    message['To'] = ', '.join(delivery['to'])
    if delivery['cc']:
        message['Cc'] = ', '.join(delivery['cc'])
    message['Reply-To'] = delivery['reply_to']
    message['Subject'] = record.subject
    message['Message-ID'] = make_msgid()
    message.attach(MIMEText(record.body, 'plain', 'utf-8'))
    message.attach(MIMEText(html_body(record.body), 'html', 'utf-8'))
    try:
        send_smtp_message(message, recipients=delivery['to'] + delivery['cc'])
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
        return jsonify({'request_id': secrets.token_urlsafe(24),
            'rooms': [{'id': room.id, 'name': room.name, 'label': room_label(room.name)} for room in requestable_rooms()],
            'recipient_names': {'to': ['Emma', 'Martha'], 'cc': ['Florence', 'Chris']},
            'test_recipients': [{'id': key, 'name': person[0]} for key, person in TEST_RECIPIENTS.items()]})

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
