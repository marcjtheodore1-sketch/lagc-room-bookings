import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import app


BLOCKED = 'zara.lagc@gmail.com'
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EmailBlocklistTest(unittest.TestCase):
    def setUp(self):
        self.original_config = {
            key: app.app.config[key]
            for key in (
                'ENABLE_EMAIL', 'SMTP_HOST', 'SMTP_USER',
                'SMTP_PASSWORD', 'SMTP_FROM',
            )
        }
        app.app.config.update(
            ENABLE_EMAIL=True,
            SMTP_HOST='smtp.example.com',
            SMTP_USER='sender@example.com',
            SMTP_PASSWORD='password',
            SMTP_FROM='sender@example.com',
        )
        self.addCleanup(app.app.config.update, self.original_config)

    @patch('app.smtplib.SMTP_SSL')
    @patch('app.smtplib.SMTP')
    def test_single_email_to_blocked_address_never_reaches_smtp(
            self, smtp, smtp_ssl):
        sent = app.send_confirmation_email(
            f'  {BLOCKED.upper()}  ', 'Subject', 'Message'
        )

        self.assertTrue(sent)
        smtp_ssl.assert_not_called()
        smtp.assert_not_called()

    @patch('app.smtplib.SMTP_SSL')
    def test_bulk_email_removes_blocked_address_from_smtp_envelope(
            self, smtp_ssl):
        server = smtp_ssl.return_value.__enter__.return_value

        success, error = app.send_bulk_email(
            ['allowed@example.com', BLOCKED, BLOCKED.upper()],
            'Subject',
            'Message',
        )

        self.assertTrue(success)
        self.assertIsNone(error)
        server.send_message.assert_called_once()
        self.assertEqual(
            server.send_message.call_args.kwargs['to_addrs'],
            ['allowed@example.com'],
        )

    @patch('app.smtplib.SMTP_SSL')
    @patch('app.smtplib.SMTP')
    def test_bulk_email_with_only_blocked_address_never_reaches_smtp(
            self, smtp, smtp_ssl):
        success, error = app.send_bulk_email(
            [BLOCKED], 'Subject', 'Message'
        )

        self.assertFalse(success)
        self.assertEqual(error, 'No recipients')
        smtp_ssl.assert_not_called()
        smtp.assert_not_called()

    @patch('app.smtplib.SMTP_SSL')
    @patch('app.smtplib.SMTP')
    def test_enabled_email_requires_a_password(self, smtp, smtp_ssl):
        app.app.config['SMTP_PASSWORD'] = ''

        success, error = app.send_bulk_email(
            ['allowed@example.com'], 'Subject', 'Message'
        )

        self.assertFalse(success)
        self.assertIn('SMTP_PASSWORD', error)
        smtp_ssl.assert_not_called()
        smtp.assert_not_called()

    @patch('app.smtplib.SMTP_SSL')
    @patch('app.smtplib.SMTP')
    def test_authentication_failure_is_clear_and_not_retried(
            self, smtp, smtp_ssl):
        ssl_server = smtp_ssl.return_value.__enter__.return_value
        ssl_server.login.side_effect = app.smtplib.SMTPAuthenticationError(
            535, b'Username and Password not accepted'
        )

        success, error = app.send_bulk_email(
            ['allowed@example.com'], 'Subject', 'Message'
        )

        self.assertFalse(success)
        self.assertIn('app password', error.lower())
        self.assertIn('expired or been revoked', error)
        smtp.assert_not_called()

    def test_smtp_settings_load_from_untracked_env_file(self):
        with tempfile.TemporaryDirectory() as disk:
            env_file = os.path.join(disk, '.env')
            with open(env_file, 'w', encoding='utf-8') as handle:
                handle.write(textwrap.dedent("""
                    SMTP_HOST=smtp.example.test
                    SMTP_PORT=2525
                    SMTP_USER=configured@example.test
                    SMTP_PASSWORD=abcd efgh ijkl mnop
                    SMTP_FROM=sender@example.test
                    ENABLE_EMAIL=true
                """))

            env = {
                **os.environ,
                'APP_ENV_FILE': env_file,
                'RENDER': '1',
                'RENDER_DISK_PATH': disk,
                'PYTHONPATH': APP_DIR,
            }
            for key in (
                'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD',
                'SMTP_FROM', 'ENABLE_EMAIL',
            ):
                env.pop(key, None)

            result = subprocess.run(
                [sys.executable, '-c', textwrap.dedent("""
                    import json
                    from app import app
                    print(json.dumps({
                        key: app.config[key]
                        for key in (
                            'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER',
                            'SMTP_PASSWORD', 'SMTP_FROM', 'ENABLE_EMAIL',
                        )
                    }))
                """)],
                cwd=APP_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), {
            'SMTP_HOST': 'smtp.example.test',
            'SMTP_PORT': 2525,
            'SMTP_USER': 'configured@example.test',
            'SMTP_PASSWORD': 'abcdefghijklmnop',
            'SMTP_FROM': 'sender@example.test',
            'ENABLE_EMAIL': True,
        })


if __name__ == '__main__':
    unittest.main()
