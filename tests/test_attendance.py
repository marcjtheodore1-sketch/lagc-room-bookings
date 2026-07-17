import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date


# Build the two affected tables exactly as they existed before attendance was
# introduced. Importing the application must upgrade this database through the
# same module-level path used by PythonAnywhere's WSGI process.
_temp_dir = tempfile.TemporaryDirectory()
os.environ['RENDER'] = '1'
os.environ['RENDER_DISK_PATH'] = _temp_dir.name
os.environ['ENABLE_EMAIL'] = 'false'

_db_path = os.path.join(_temp_dir.name, 'bookings.db')
with closing(sqlite3.connect(_db_path)) as connection:
    connection.executescript(
        """
        CREATE TABLE booking (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            user_name VARCHAR(100) NOT NULL,
            user_email VARCHAR(120) NOT NULL,
            booking_date DATE NOT NULL,
            start_slot INTEGER NOT NULL,
            end_slot INTEGER NOT NULL,
            created_at DATETIME,
            cancelled_at DATETIME,
            cancel_token VARCHAR(64) UNIQUE
        );

        CREATE TABLE yoga_booking (
            id INTEGER PRIMARY KEY,
            session_date DATE NOT NULL,
            name VARCHAR(120) NOT NULL,
            email VARCHAR(120) NOT NULL,
            phone VARCHAR(50) NOT NULL,
            emergency_name VARCHAR(120) NOT NULL,
            emergency_phone VARCHAR(50) NOT NULL,
            experience VARCHAR(20),
            health_info TEXT,
            avoid_info TEXT,
            accessibility_info TEXT,
            agreed_safety BOOLEAN,
            cancel_token VARCHAR(64) UNIQUE,
            created_at DATETIME
        );
        """
    )

from app import Booking, Room, YogaBooking, app, db  # noqa: E402


class AttendanceMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        with app.app_context():
            rose = Room(
                id=101,
                name='Room 4.4 (Rose)',
                building_location='Floor 4',
                room_type='slot',
            )
            clerkenwell = Room(
                id=102,
                name='Room 4.7 (Clerkenwell)',
                building_location='Floor 4',
                room_type='open',
            )
            db.session.add_all([rose, clerkenwell])
            db.session.add_all([
                Booking(
                    id=201,
                    room_id=rose.id,
                    user_name='Rose Person',
                    user_email='rose@example.com',
                    booking_date=date(2099, 1, 2),
                    start_slot=3,
                    end_slot=4,
                ),
                Booking(
                    id=202,
                    room_id=clerkenwell.id,
                    user_name='Open Person',
                    user_email='open@example.com',
                    booking_date=date(2099, 1, 2),
                    start_slot=3,
                    end_slot=4,
                ),
                YogaBooking(
                    id=301,
                    session_date=date(2099, 1, 2),
                    name='Yoga Person',
                    email='yoga@example.com',
                    phone='07000000000',
                    emergency_name='Emergency Contact',
                    emergency_phone='07000000001',
                    agreed_safety=True,
                ),
            ])
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        _temp_dir.cleanup()

    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True

    def test_wsgi_import_adds_attendance_columns(self):
        with closing(sqlite3.connect(_db_path)) as connection:
            booking_columns = {
                row[1] for row in connection.execute('PRAGMA table_info(booking)')
            }
            yoga_columns = {
                row[1]
                for row in connection.execute('PRAGMA table_info(yoga_booking)')
            }

        self.assertIn('attended', booking_columns)
        self.assertIn('attended', yoga_columns)

    def test_admin_bookings_load_and_only_rose_accepts_attendance(self):
        response = self.client.get('/api/admin/bookings')
        self.assertEqual(response.status_code, 200)
        bookings = {row['id']: row for row in response.get_json()}
        self.assertIsNone(bookings[201]['attended'])
        self.assertEqual(bookings[201]['room_type'], 'slot')

        response = self.client.post(
            '/api/admin/bookings/201/attendance', json={'attended': True}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['attended'])

        response = self.client.post(
            '/api/admin/bookings/202/attendance', json={'attended': False}
        )
        self.assertEqual(response.status_code, 400)

    def test_yoga_no_show_appears_in_summary(self):
        response = self.client.post(
            '/api/admin/yoga-bookings/301/attendance', json={'attended': False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['attended'])

        response = self.client.get('/api/admin/attendance-summary')
        self.assertEqual(response.status_code, 200)
        summary = {row['email']: row for row in response.get_json()}
        self.assertEqual(summary['yoga@example.com']['no_shows'], 1)
        self.assertEqual(summary['yoga@example.com']['yoga_no_shows'], 1)


if __name__ == '__main__':
    unittest.main()
