import unittest
from test_attendee_booking_experience import run_isolated


class YogaPauseTest(unittest.TestCase):
    def test_pause_closes_all_registration_and_updates_public_pages(self):
        result = run_isolated("""
            from unittest.mock import patch
            from app import app, db, YogaBooking, YOGA_SESSION_DATES
            client = app.test_client()
            assert client.get('/api/yoga/availability').json == []
            assert '2026-09-18' not in YOGA_SESSION_DATES
            assert '2026-09-25' not in YOGA_SESSION_DATES
            with app.app_context(), patch('app.send_confirmation_email') as send:
                before = YogaBooking.query.count()
                for day in ['2026-09-18', '2026-09-25', '2099-01-02']:
                    response = client.post('/api/yoga/book', json={'session_date': day})
                    assert response.status_code == 409
                    assert 'paused' in response.json['error']
                assert YogaBooking.query.count() == before
                send.assert_not_called()
            page = client.get('/yoga').text
            assert 'Sign-ups are currently closed' in page
            assert 'one hour in the morning' in page
            assert 'See dates &amp; book' not in page
            assert 'Temporarily paused' in client.get('/').text
        """)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
