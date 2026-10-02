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

## Opt-in email reminders

People can use `/reminders` to request either a weekly booking reminder, a
reminder around 24 hours before their room bookings, or both. They must confirm the
request through an email link. Every reminder has a private link to change or
stop the preferences. Historic bookers are not subscribed automatically.

The reminder job is `send_reminders.py`. When this app runs on a paid host,
run it hourly as a PythonAnywhere scheduled task, using the same
Python virtual environment and database as the web app. On the existing free
host, a separate paid charity account runs an hourly task that POSTs to
`/api/internal/send-reminders` with the `X-Reminder-Token` header. The value
must match `REMINDER_JOB_TOKEN` in the bookings app's ignored `.env` file.
Set `PUBLIC_BASE_URL` to the public site origin if it
differs from the default in `.env.example`. The job uses London dates regardless
of the host timezone. It sends a booking reminder during daytime Monday to Thursday for
that week's Friday and only if rooms for that date appear in
`ROOM_SCHEDULE_BY_NAME`. It sends booked-session reminders on Thursday when
the booking starts within 24 hours, skipping cancelled bookings and withdrawn
rooms. Successful sends are recorded so rerunning the job does not duplicate
emails. An hourly task sends these within roughly 30 minutes of the 24-hour
mark for the site's half-hour booking slots.

## Pan Macmillan attendance reports

Admin → Email Blast includes a preview and an on/off setting for attendance
emails to Emma Perez and Martha Fisher, copying Florence Perdriel. The same
paid-account proxy triggers these reports on the free bookings host,
before the attendee reminder run. Keep the existing hourly task at minute 30
for attendee reminders, and add an hourly task at minute 0 using the same
proxy command for building reports. Repeated attendee checks do not send
duplicate reminders. No external database access is needed.

Registration for each Friday closes on Thursday at 10am London time, including
BST/GMT changes. The date remains visible through Friday with a closed label;
existing bookings and cancellation links remain valid. The booking API enforces
the deadline independently of the browser, including forms opened earlier.

One final list is due at the Thursday deadline, addressed to Emma and Martha,
with Florence copied in. It contains deduplicated volunteer, attendee, carer and
companion names, plus a session-level Yes/No mobility flag. No room timings,
individual mobility flags, written mobility details or contact details are shared.
Name matching ignores case and repeated whitespace; it cannot distinguish two
different people who have identical names.

The existing hourly paid scheduler remains unchanged. The report runs only on
Thursday at 10am, with a 15-minute startup allowance. It never sends in later
hours or on Friday. Definite failures can retry the same frozen snapshot within
that dispatch window only. Successful or uncertain deliveries never cause
another automatic send. `BuildingReportDispatch` preserves the history and
delivery-check controls. Attendee reminder schedules are separate and unchanged.

Kirsty's supplied help sheet is available at `/help-sheet` with PDF and original
Word downloads. The homepage, booking page, volunteer rota, confirmation screen,
confirmation email and booked-session reminder link to it. The source guide is
preserved, including its photographs and emergency information.

## Installation

1. Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. (Optional) Configure email settings to send real confirmation emails:

   Set environment variables, or copy `.env.example` to an untracked `.env`
   file in the project directory and fill in the same values:
   ```bash
   export SMTP_HOST=smtp.gmail.com
   export SMTP_PORT=587
   export SMTP_USER=your-email@gmail.com
   export SMTP_PASSWORD=your-app-password
   export SMTP_FROM=bookings@yourcompany.com
   export ENABLE_EMAIL=true
   ```

   For Gmail, you'll need to create an App Password at: https://myaccount.google.com/apppasswords
   Never commit the app password to Git. On PythonAnywhere, the project `.env`
   file is loaded automatically by the application and is already ignored by
   `.gitignore`.

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

## General emails to past F@F registrants

Admin → Email Blast → Email people from past Fridays provides a general
message independent of the existing availability blast for a single Friday.
Choose all past dates or the past 3, 6 or 12 calendar months. Room and yoga
addresses are normalised and deduplicated; cancelled bookings, recorded
no-shows, blocked addresses and future sessions are excluded. A separate
"Recorded attendance only" filter uses explicit attendance records, since
attendance was not recorded for every session.

The review screen lets admins edit the subject, message and recipients.
Nothing is sent when opening a draft. Sending uses private envelope
recipients (BCC), with a durable unique claim for each draft to prevent
duplicate submission. Recent sends and failed/uncertain outcomes appear in
the general email history. Check an uncertain outcome in the mailbox before
creating another draft; the system never automatically retries a general blast.

The booking page requires registration before Thursday at 10am London time.
It closes registration automatically and keeps closed dates visible. Meeting-room
cards, the review step and confirmation emails explain that a room booking
only gives access to that room, and link back to book any other rooms on
the same Friday separately.

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
