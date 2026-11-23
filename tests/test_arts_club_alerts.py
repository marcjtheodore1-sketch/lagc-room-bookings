import base64
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask

from arts_club_alerts import RECIPIENT, SUBJECT, enqueue, format_alert, process_alerts, register_arts_club_alerts


RESPONSE = {'id': 'a' * 32, 'name': 'Example Person', 'email': 'artist@example.invalid',
            'interests': ['Take part', 'Volunteer', 'Lead an activity'],
            'receivedAt': '2026-11-23T19:08:00.000Z', 'note': 'Paper collage'}


class Uncertain(Exception):
    pass


class ArtsClubAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'alerts.sqlite3'
        self.sent = []

    def send(self, *args):
        self.sent.append(args)

    def state(self):
        with sqlite3.connect(self.db) as connection:
            return connection.execute('SELECT state,payload FROM alerts').fetchone()

    def test_formats_details_for_the_fixed_charity_inbox(self):
        recipient, subject, message = format_alert(RESPONSE)
        self.assertEqual(recipient, RECIPIENT)
        self.assertEqual(subject, SUBJECT)
        for phrase in ['Example Person', 'artist@example.invalid', 'Take part, Volunteer, Lead an activity',
                       'Paper collage', '23rd November 2026, 7.08pm', '/autistic-arts-club/admin']:
            self.assertIn(phrase, message)

    def test_repeat_handoff_does_not_resend(self):
        enqueue(self.db, [RESPONSE])
        process_alerts(self.db, self.send, Uncertain)
        enqueue(self.db, [RESPONSE])
        process_alerts(self.db, self.send, Uncertain)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state(), ('sent', None))

    def test_known_mail_failure_is_retried_next_run(self):
        def fail(*args):
            raise OSError('known failure before SMTP acceptance')

        enqueue(self.db, [RESPONSE])
        process_alerts(self.db, fail, Uncertain)
        self.assertEqual(self.state()[0], 'pending')
        process_alerts(self.db, self.send, Uncertain)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state(), ('sent', None))

    def test_uncertain_smtp_result_does_not_send_again(self):
        def fail(*args):
            self.send(*args)
            raise Uncertain()

        enqueue(self.db, [RESPONSE])
        process_alerts(self.db, fail, Uncertain)
        process_alerts(self.db, fail, Uncertain)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state()[0], 'uncertain')

    def test_relay_accepts_only_fresh_signed_registrations(self):
        private = self.root / 'test-private.pem'
        public = self.root / 'wix-public.pem'
        subprocess.run(['openssl', 'genrsa', '-out', str(private), '2048'],
                       capture_output=True, check=True)
        subprocess.run(['openssl', 'rsa', '-in', str(private), '-pubout', '-out', str(public)],
                       capture_output=True, check=True)
        app = Flask(__name__)
        with patch('arts_club_alerts.PRIVATE', self.root):
            run = register_arts_club_alerts(app, self.send, Uncertain)

        def sign(body, age=0):
            timestamp = str(int(time.time() * 1000) - age)
            signed = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(private)],
                                    input=timestamp.encode() + b'.' + body, capture_output=True, check=True)
            return {'X-LAGC-Alert-Time': timestamp,
                    'X-LAGC-Alert-Signature': base64.urlsafe_b64encode(signed.stdout).decode().rstrip('=')}

        path = '/api/arts-club-alerts/receive'
        client = app.test_client()
        health = b'{"action":"health"}'
        post = lambda body, headers=None: client.post(path, data=body, headers=headers)
        self.assertEqual(post(health).status_code, 403)
        self.assertEqual(post(health, sign(health, 600000)).status_code, 403)
        self.assertEqual(post(health + b' ', sign(health)).status_code, 403)
        self.assertEqual(post(health, sign(health)).status_code, 200)
        self.assertFalse(self.db.exists())
        invalid = json.dumps({'alerts': [{**RESPONSE, 'recipient': 'other@example.invalid'}]}).encode()
        self.assertEqual(post(invalid, sign(invalid)).status_code, 400)
        submission = json.dumps({'alerts': [RESPONSE]}).encode()
        with patch('arts_club_alerts.threading.Thread') as thread:
            self.assertEqual(post(submission, sign(submission)).json, {'queued': 1})
            thread.return_value.start.assert_called_once()
        run()
        self.assertEqual(self.sent[0][0], RECIPIENT)
        self.assertEqual(self.state(), ('sent', None))
