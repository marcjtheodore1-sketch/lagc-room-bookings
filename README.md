# Room Booking System

A simple web application for booking meeting rooms in 30-minute slots on Fridays from 11:00 AM to 5:30 PM.

## Features

- **30-minute time slots** on Fridays from 11:00 AM to 5:30 PM
- **Maximum 3 hours** (6 slots) per booking
- **Consecutive slots only** - no gaps allowed in bookings
- **Email-based booking** with confirmation message
- **Cancellation** via secure token link
- **Admin panel** for managing rooms and confirmation messages
- **No double booking** - booked slots are automatically unavailable

## Installation

1. Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. (Optional) Configure email settings to send real confirmation emails:

   Set environment variables:
   ```bash
   export SMTP_HOST=smtp.gmail.com
   export SMTP_PORT=587
   export SMTP_USER=your-email@gmail.com
   export SMTP_PASSWORD=your-app-password
   export SMTP_FROM=bookings@yourcompany.com
   export ENABLE_EMAIL=true
   ```

   For Gmail, you'll need to create an App Password at: https://myaccount.google.com/apppasswords

3. Run the application:
```bash
python app.py
```

4. Open your browser and go to: `http://localhost:5000`

## Usage

### Making a Booking

1. Select a room from the available options
2. Choose a Friday date
3. Click and drag to select consecutive time slots (max 3 hours)
4. Enter your email address
5. Click "Confirm Booking" to receive your confirmation

### Viewing/Managing Your Bookings

1. Enter your email in the "My Bookings" section on the home page
2. Click "View My Bookings" to see all your upcoming bookings
3. Click "Cancel" to cancel a specific booking

### Admin Configuration

Navigate to `/admin` to:

1. **Manage Rooms**: Add, edit, or delete rooms
2. **Customize Confirmation Message**: Edit the template sent to users after booking
3. **View All Bookings**: See all upcoming bookings across all rooms

#### Confirmation Message Variables

The following variables can be used in the confirmation message template:

- `{{email}}` - User's email address
- `{{room_name}}` - Name of the booked room
- `{{building_location}}` - Building location
- `{{date}}` - Booking date
- `{{start_time}}` - Start time
- `{{end_time}}` - End time
- `{{cancel_url}}` - URL to cancel the booking

## Project Structure

```
room_booking/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── static/
│   ├── css/
│   │   └── style.css     # Main stylesheet
│   └── js/
│       ├── app.js        # Main booking page JavaScript
│       ├── admin.js      # Admin panel JavaScript
│       └── cancel.js     # Cancellation page JavaScript
└── templates/
    ├── base.html         # Base template
    ├── index.html        # Booking page
    ├── admin.html        # Admin panel
    └── cancel.html       # Cancellation page
```

## Database

The application uses SQLite (via SQLAlchemy) with the following tables:

- **rooms** - Meeting rooms available for booking
- **bookings** - All bookings (including cancelled ones)
- **settings** - Configuration settings (confirmation message template)

The database file (`bookings.db`) is created automatically on first run.

## Default Data

On first run, the system creates:
- 3 sample rooms (Conference Room A, Meeting Room B, Discussion Room C)
- Default confirmation message template

## Security Notes

- The cancellation system uses secure random tokens
- No authentication system - anyone with the cancellation link can cancel a booking
- Email validation is basic (checks for @ and .)
- For production use, consider adding:
  - Email verification
  - User authentication
  - HTTPS
  - Rate limiting
