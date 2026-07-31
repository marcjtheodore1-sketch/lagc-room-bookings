import unittest
from unittest.mock import patch

import app


BLOCKED = 'zara.lagc@gmail.com'


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


if __name__ == '__main__':
    unittest.main()
