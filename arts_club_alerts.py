"""Durable, signed Arts Club alerts sent with the existing Miles booking mailbox."""
import base64
from contextlib import closing
from datetime import datetime
import fcntl
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from tempfile import NamedTemporaryFile
import threading
import time
from zoneinfo import ZoneInfo

from flask import jsonify, request


RECIPIENT = 'contact@londonautismgroupcharity.org'
SUBJECT = 'New Autistic Arts Club expression of interest'
ADMIN_URL = 'https://www.londonautismgroupcharity.org/autistic-arts-club/admin'
PRIVATE = Path.home() / '.config' / 'lagc-arts-alerts'
ALLOWED_INTERESTS = {'Take part', 'Volunteer', 'Lead an activity'}


def format_alert(row):
    received = datetime.fromisoformat(row['receivedAt'].replace('Z', '+00:00')).astimezone(ZoneInfo('Europe/London'))
    day = received.day
    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    hour = received.strftime('%I').lstrip('0')
    minutes = '' if received.minute == 0 else received.strftime('.%M')
    when = f'{day}{suffix} {received:%B %Y}, {hour}{minutes}{received.strftime("%p").lower()}'
    interests = ', '.join(row['interests'])
    body = (
        'A new expression of interest was submitted for the Autistic Arts Club.\n\n'
        f"Name: {row['name']}\nEmail address: {row['email']}\nInterested in: {interests}\n"
        f"Received: {when} (UK time)\n\n"
        f"Message:\n{row['note'] or 'No message left.'}\n\n"
        'This is an expression of interest.\n'
        f'View responses in the private admin area: {ADMIN_URL}'
    )
    return RECIPIENT, SUBJECT, body


def verify_signature(public_key_file, body, headers):
    stamp = headers.get('X-LAGC-Alert-Time', '')
    signature = headers.get('X-LAGC-Alert-Signature', '')
    if not re.fullmatch(r'[0-9]{13}', stamp) or abs(int(time.time() * 1000) - int(stamp)) > 300000:
        return False
    if not re.fullmatch(r'[A-Za-z0-9_-]{342}', signature):
        return False
    with NamedTemporaryFile() as signature_file:
        signature_file.write(base64.urlsafe_b64decode(signature + '=='))
        signature_file.flush()
        verified = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-verify', str(public_key_file), '-signature', signature_file.name],
            input=stamp.encode() + b'.' + body, capture_output=True, timeout=3, check=False,
        )
    return verified.returncode == 0


def open_queue(database):
    connection = sqlite3.connect(database, timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, payload TEXT, state TEXT NOT NULL)')
    return connection


def enqueue(database, rows):
    with closing(open_queue(database)) as connection, connection:
        connection.executemany("INSERT OR IGNORE INTO alerts VALUES (?, ?, 'pending')",
                               ((row['id'], json.dumps(row)) for row in rows))


def valid_alert(row):
    if not isinstance(row, dict) or set(row) != {'id', 'receivedAt', 'name', 'email', 'note', 'interests'}:
        return False
    if not all(isinstance(row[key], str) for key in ('id', 'receivedAt', 'name', 'email', 'note')):
        return False
    if not re.fullmatch('[0-9a-f]{32}', row['id']) or not 0 < len(row['name']) <= 120 or len(row['email']) > 254 or len(row['note']) > 750:
        return False
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', row['email']) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', row['receivedAt']):
        return False
    if not isinstance(row['interests'], list) or not 1 <= len(row['interests']) <= 3:
        return False
    try:
        datetime.fromisoformat(row['receivedAt'].replace('Z', '+00:00'))
    except ValueError:
        return False
    return all(isinstance(role, str) and role in ALLOWED_INTERESTS for role in row['interests'])


def process_alerts(database, deliver, delivery_uncertain):
    """A single worker retries pending mail and clears details after SMTP acceptance."""
    with closing(open_queue(database)) as connection:
        # A worker that died after SMTP accepted a message may already have sent it.
        with connection:
            connection.execute("UPDATE alerts SET state='uncertain' WHERE state='sending'")
        pending = connection.execute("SELECT id,payload FROM alerts WHERE state='pending' ORDER BY rowid LIMIT 30").fetchall()
        for identifier, payload in pending:
            mail = format_alert(json.loads(payload))
            with connection:
                connection.execute("UPDATE alerts SET state='sending' WHERE id=?", (identifier,))
            try:
                deliver(*mail)
            except delivery_uncertain:
                with connection:
                    connection.execute("UPDATE alerts SET state='uncertain' WHERE id=?", (identifier,))
            except Exception:
                with connection:
                    connection.execute("UPDATE alerts SET state='pending' WHERE id=?", (identifier,))
                continue
            else:
                with connection:
                    connection.execute("UPDATE alerts SET state='sent',payload=NULL WHERE id=?", (identifier,))


def register_arts_club_alerts(app, deliver, delivery_uncertain):
    database = PRIVATE / 'alerts.sqlite3'
    public_file = PRIVATE / 'wix-public.pem'
    worker_lock = PRIVATE / 'worker.lock'

    def run():
        if not database.is_file():
            return
        with worker_lock.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            process_alerts(database, deliver, delivery_uncertain)

    def wake():
        with app.app_context():
            try:
                run()
            except Exception:
                app.logger.warning('Arts Club mail queue processing failed. The hourly job will retry.')

    @app.post('/api/arts-club-alerts/receive')
    def receive_arts_club_alerts():
        if not public_file.is_file() or not request.headers.get('X-LAGC-Alert-Signature'):
            return jsonify(error='Unavailable'), 403
        if request.content_length is None or request.content_length > 60000:
            return jsonify(error='Invalid request'), 400
        body = request.get_data()
        if not verify_signature(public_file, body, request.headers):
            return jsonify(error='Unavailable'), 403
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            return jsonify(error='Invalid request'), 400
        if data == {'action': 'health'}:
            return jsonify(ok=True)
        rows = data.get('alerts') if isinstance(data, dict) else None
        if not isinstance(rows, list) or not 1 <= len(rows) <= 12 or not all(valid_alert(row) for row in rows):
            return jsonify(error='Invalid request'), 400
        enqueue(database, rows)
        threading.Thread(target=wake, daemon=True).start()
        return jsonify(queued=len(rows)), 202

    return run
