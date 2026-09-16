import unittest
from test_attendee_booking_experience import run_isolated


class HomeRoomScheduleTest(unittest.TestCase):
    def test_cards_follow_booking_schedule(self):
        result = run_isolated('''
            from unittest.mock import patch
            from app import app, db, Room
            with app.app_context():
                rose = Room(name='Room 4.4 "Rose"', room_type='slot')
                loft = Room(name='The Loft', room_type='open')
                db.session.add_all([rose, loft])
                db.session.commit()
                client = app.test_client()
                with patch('app.get_upcoming_fridays', return_value=[{'date': '2099-09-25'}]), patch('app.get_room_schedule_ids', return_value={'2099-09-25': [rose.id, loft.id]}):
                    html = client.get('/').text
                    current = html.split('id="rooms-current"')[1].split('<!-- Box 2')[0]
                    other = html.split('id="rooms-other"')[1].split('<!-- Box 3')[0]
                    assert 'The Loft' in current and '25th September' in current
                    assert 'The Loft' not in other and 'Indigo' in other
                with patch('app.get_upcoming_fridays', return_value=[]):
                    html = client.get('/').text
                    current = html.split('id="rooms-current"')[1].split('<!-- Box 2')[0]
                    other = html.split('id="rooms-other"')[1].split('<!-- Box 3')[0]
                    assert 'The Loft' not in current and 'The Loft' in other
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
