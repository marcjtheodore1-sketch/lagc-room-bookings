"""
Simple Room Booking System
Handles 30-minute booking slots on Fridays from 11am to 4pm
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
import json
import os
import secrets
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Database configuration - use persistent disk path if available
if os.environ.get('RENDER'):
    # Running on Render - use persistent disk
    db_path = os.path.join(os.environ.get('RENDER_DISK_PATH', '/var/lib/render'), 'bookings.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
else:
    # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bookings.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Give schema upgrades time to acquire SQLite's write lock when a reload
# overlaps with a booking request or more than one WSGI worker starts at once.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'timeout': 30},
}

# Email configuration (hardcoded for PythonAnywhere deployment)
app.config['SMTP_HOST'] = 'smtp.gmail.com'
app.config['SMTP_PORT'] = 587
app.config['SMTP_USER'] = 'miles.lagc@gmail.com'
app.config['SMTP_PASSWORD'] = 'gidxqeqyvdifqzqs'
app.config['SMTP_FROM'] = 'miles.lagc@gmail.com'
app.config['ENABLE_EMAIL'] = os.environ.get('ENABLE_EMAIL', 'true').lower() not in ('false', '0', 'no')

# Admin password (set via environment variable or use default 'Moonlight')
app.config['ADMIN_PASSWORD'] = os.environ.get('ADMIN_PASSWORD', 'Virtuoso')

db = SQLAlchemy(app)

# ============================================================================
# DATABASE MODELS
# ============================================================================

class Room(db.Model):
    """Meeting rooms that can be booked"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    building_location = db.Column(db.String(200), nullable=False, default='Main Building')
    room_type = db.Column(db.String(20), nullable=False, default='slot')  # 'slot' or 'open'
    is_active = db.Column(db.Boolean, default=True)
    # The room's usual hours ('HH:MM'), applying to every date unless a
    # per-date override exists. None = the global 9:30-5 day.
    default_start = db.Column(db.String(5), nullable=True)
    default_end = db.Column(db.String(5), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Booking(db.Model):
    """Room bookings"""
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    user_email = db.Column(db.String(120), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)  # The Friday being booked
    start_slot = db.Column(db.Integer, nullable=False)  # 0-15 (09:30-17:00 in 30min slots)
    end_slot = db.Column(db.Integer, nullable=False)    # exclusive end slot
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_token = db.Column(db.String(64), unique=True)  # For cancellation link
    attended = db.Column(db.Boolean, nullable=True)  # None = not recorded, True = came, False = no-show

    room = db.relationship('Room', backref='bookings')

class Setting(db.Model):
    """Configurable settings"""
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)

class VolunteerAvailability(db.Model):
    """A volunteer marking their status for a given Friday"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(200), default='')
    unavailable = db.Column(db.Boolean, default=False)  # True = can't make it
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class YogaBooking(db.Model):
    """A registration for a Gentle Yoga with Marlijn session (capacity-limited)"""
    id = db.Column(db.Integer, primary_key=True)
    session_date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    emergency_name = db.Column(db.String(120), nullable=False)
    emergency_phone = db.Column(db.String(50), nullable=False)
    experience = db.Column(db.String(20), default='')        # Yes / No / A little
    health_info = db.Column(db.Text, default='')             # things to adapt for safely
    avoid_info = db.Column(db.Text, default='')              # things to avoid
    accessibility_info = db.Column(db.Text, default='')      # how they experience/communicate
    agreed_safety = db.Column(db.Boolean, default=False)     # required understanding checkbox
    cancel_token = db.Column(db.String(64), unique=True)     # self-cancel link
    attended = db.Column(db.Boolean, nullable=True)          # None = not recorded, True = came, False = no-show
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================================================
# CONSTANTS
# ============================================================================

# Friday time slots: 09:30 - 17:00 (30 min intervals)
# Slot 0 = 09:30, Slot 1 = 10:00, ..., Slot 15 = 17:00 (end marker)
# Rooms are open 9:30am–5pm. This grid was re-based from 11:00 to 09:30 in
# June 2026; existing bookings are shifted +3 slots once (see run_migrations)
# so their real times are preserved.
START_HOUR = 9
START_MINUTE = 30
END_HOUR = 17    # 5 PM
END_MINUTE = 0
SLOT_MINUTES = 30
MAX_SLOTS = 6    # 3 hours = 6 x 30 min slots

def get_time_slots():
    """Generate all available time slots"""
    slots = []
    current = datetime.strptime(f"{START_HOUR:02d}:{START_MINUTE:02d}", "%H:%M")
    end = datetime.strptime(f"{END_HOUR:02d}:{END_MINUTE:02d}", "%H:%M")

    slot_index = 0
    while current <= end:
        slots.append({
            'index': slot_index,
            'time': current.strftime('%H:%M'),
            'display': current.strftime('%I:%M %p').lstrip('0')
        })
        current += timedelta(minutes=SLOT_MINUTES)
        slot_index += 1

    return slots

TIME_SLOTS = get_time_slots()
# Display time used when an open room is booked through to the end of the day.
LAST_SLOT_DISPLAY = TIME_SLOTS[-1]['display']  # '5:00 PM'

# ============================================================================
# ROOM AVAILABILITY SCHEDULE
# Format: 'YYYY-MM-DD': ['Room Name', 'Room Name', ...]
# Room names are matched against the database
# ============================================================================
ROOM_SCHEDULE_BY_NAME = {
    '2026-03-06': ['Room 4.7 "Clerkenwell"', 'Room 4.2 "Indigo"', 'Room 4.4 "Rose"'],
    '2026-03-13': ['The Loft', 'Room 4.2 "Indigo"', 'Room 4.4 "Rose"'],
    '2026-03-20': ['Room 4.7 "Clerkenwell"', 'Room 4.4 "Rose"', 'Room 4.2 "Indigo"'],
    '2026-03-27': ['The Loft', 'Room 4.7 "Clerkenwell"', 'Room 4.2 "Indigo"', 'Room 4.4 "Rose"'],
    '2026-04-17': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-05-01': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-05-08': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-05-15': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-05-22': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-05-29': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-06-05': ['Room 4.4 "Rose"', 'Room 4.2 "Indigo"', 'Room 4.6 "Farringdon"'],
    '2026-06-12': ['Room 4.4 "Rose"', 'Room 4.2 "Indigo"', 'The Loft'],
    # 2026-06-19 removed from booking entirely (LAGC first aid training in the Loft; date withdrawn)
    # 2026-06-26 cancelled — removed from booking
    '2026-07-03': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-07-10': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-07-17': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-07-24': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-07-31': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-08-07': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-08-14': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-08-21': ['Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
    '2026-08-28': ['The Loft', 'Room 5.1'],
}

def get_room_schedule_ids():
    """Convert room name schedule to ID schedule based on current database"""
    schedule = {}
    
    # Build keyword to ID mapping for flexible matching
    # Keywords: "4.2" or "Indigo", "4.4" or "Rose", "4.7" or
    # "Clerkenwell", "Loft", "4.6" or "Farringdon", and "5.1".
    keyword_to_id = {}
    for room in Room.query.all():
        name_lower = room.name.lower()
        if '4.2' in name_lower or 'indigo' in name_lower:
            keyword_to_id['4.2'] = room.id
            keyword_to_id['indigo'] = room.id
        if '4.4' in name_lower or 'rose' in name_lower:
            keyword_to_id['4.4'] = room.id
            keyword_to_id['rose'] = room.id
        if '4.7' in name_lower or 'clerkenwell' in name_lower:
            keyword_to_id['4.7'] = room.id
            keyword_to_id['clerkenwell'] = room.id
        if 'loft' in name_lower:
            keyword_to_id['loft'] = room.id
        if '4.6' in name_lower or 'farringdon' in name_lower:
            keyword_to_id['4.6'] = room.id
            keyword_to_id['farringdon'] = room.id
        if '5.1' in name_lower:
            keyword_to_id['5.1'] = room.id
    
    # Convert schedule using keywords
    for date_str, room_names in ROOM_SCHEDULE_BY_NAME.items():
        schedule[date_str] = []
        for name in room_names:
            name_lower = name.lower()
            room_id = None
            # Try to find matching keyword
            for keyword, rid in keyword_to_id.items():
                if keyword in name_lower:
                    room_id = rid
                    break
            if room_id:
                schedule[date_str].append(room_id)

    return schedule

# ============================================================================
# PER-DATE ROOM TIME OVERRIDES
# Admins can change a room's hours for a specific Friday (e.g. Clerkenwell
# 10:45am–5pm this week because there's no volunteer cover from 9:30am).
# Stored in the Setting table as JSON:
#   {"YYYY-MM-DD": {"<room_id>": {"start": "HH:MM", "end": "HH:MM"}}}
# For OPEN rooms the override is display-only (whole-day booking, custom label).
# For SLOT rooms the window snaps to the 30-min grid and limits which slots
# can be booked.
# ============================================================================
ROOM_TIME_OVERRIDES_KEY = 'room_time_overrides'

def get_room_time_overrides():
    raw = get_setting(ROOM_TIME_OVERRIDES_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}

def get_room_time_override(date_str, room_id):
    """Return {'start': 'HH:MM', 'end': 'HH:MM'} for a room on a date, or None."""
    return get_room_time_overrides().get(date_str, {}).get(str(room_id))

def fmt_hhmm(hhmm):
    """'10:45' -> '10:45 AM'. Returns the input unchanged if unparseable."""
    try:
        return datetime.strptime(hhmm, '%H:%M').strftime('%I:%M %p').lstrip('0')
    except (ValueError, TypeError):
        return hhmm

def _minutes_from_grid_start(hhmm):
    dt = datetime.strptime(hhmm, '%H:%M')
    return (dt.hour * 60 + dt.minute) - (START_HOUR * 60 + START_MINUTE)

def override_start_slot(hhmm):
    """First bookable 30-min slot at/after the override start (rounds up)."""
    mins = _minutes_from_grid_start(hhmm)
    slot = -(-mins // SLOT_MINUTES) if mins > 0 else 0  # ceil, floored at 0
    return max(0, min(slot, len(TIME_SLOTS) - 1))

def override_end_slot(hhmm):
    """Grid boundary slot at/before the override end (rounds down)."""
    mins = _minutes_from_grid_start(hhmm)
    slot = mins // SLOT_MINUTES  # floor
    return max(0, min(slot, len(TIME_SLOTS) - 1))

# ============================================================================
# PER-DATE ROOM NOTES
# Admins can flag something people need to know when booking a specific room
# on a specific Friday (e.g. "no step-free access to the Loft on 28 Aug").
# Shown on the room card, in the booking summary BEFORE confirming, and in
# the confirmation email. Stored in the Setting table as JSON:
#   {"YYYY-MM-DD": {"<room_id>": "note text"}}
# ============================================================================
ROOM_NOTES_KEY = 'room_notes'
ROOM_NOTE_MAX = 500

def get_room_notes():
    raw = get_setting(ROOM_NOTES_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}

def get_room_note(date_str, room_id):
    """Return the admin's note for a room on a date, or '' if there isn't one."""
    return get_room_notes().get(date_str, {}).get(str(room_id), '')

def get_effective_room_hours(date_str, room):
    """Resolve a room's hours for a date: a one-day change (override) wins,
    then the room's own default hours, then the global 9:30-5 day.

    Returns (start_hhmm, end_hhmm, source) with source in
    ('override', 'room', 'global')."""
    ov = get_room_time_override(date_str, room.id)
    if ov and ov.get('start') and ov.get('end'):
        return ov['start'], ov['end'], 'override'
    if room.default_start and room.default_end:
        return room.default_start, room.default_end, 'room'
    return f"{START_HOUR:02d}:{START_MINUTE:02d}", f"{END_HOUR:02d}:{END_MINUTE:02d}", 'global'

def booking_time_display(booking):
    """(start_display, end_display) for a booking, honouring custom hours.

    Slot-room bookings always reflect the actual slots the person chose; only
    open (whole-day) rooms take on the admin's custom hours (per-date change
    or the room's default hours)."""
    if booking.room and booking.room.room_type == 'open':
        start, end, source = get_effective_room_hours(
            booking.booking_date.isoformat(), booking.room)
        if source != 'global':
            return fmt_hhmm(start), fmt_hhmm(end)
    start = TIME_SLOTS[booking.start_slot]['display']
    end = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else LAST_SLOT_DISPLAY
    return start, end

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_setting(key, default=None):
    """Get a setting value"""
    setting = Setting.query.filter_by(key=key).first()
    return setting.value if setting else default

def set_setting(key, value):
    """Set a setting value"""
    setting = Setting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()

def admin_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------------------------------------------------------------------
# Homepage announcements (rotating banner) — admin-managed via the Setting table
# ----------------------------------------------------------------------------
ANNOUNCEMENTS_KEY = 'announcements'

# Seed list used the first time the setting doesn't exist yet. After that the
# admin manages everything from the Notifications tab, so this is never used
# again. (Past-dated items have been left out on purpose.)
DEFAULT_ANNOUNCEMENTS = [
    {
        'emoji': '📅',
        'headline': 'Friday 26th June is open for booking!',
        'details': 'Rooms 4.4 "Rose", 4.2 "Indigo" and 4.7 "Clerkenwell" are all available — and Peer Support sessions for autistic university students are running on the 26th too.',
        'link_url': '',
        'link_text': '',
    },
    {
        'emoji': '📰',
        'headline': 'The June newsletter is out!',
        'details': '',
        'link_url': 'https://www.londonautismgroupcharity.org/so/01Pwi__EK?languageTag=en',
        'link_text': 'Read the latest news →',
    },
    {
        'emoji': '☕',
        'headline': 'Tooting Community Café is now up and running!',
        'details': 'Tooting Grove Community Clubhouse, Effort Street, Tooting, SW17 0QR — 1pm–3pm, every second Sunday of the month. Free and autistic-led, all welcome.',
        'link_url': '',
        'link_text': '',
    },
    {
        'emoji': '💼',
        'headline': 'Autistic Workplace Support Session — 27th June.',
        'details': '1pm–4pm · Kings Square Community Centre, Islington. Please register ahead:',
        'link_url': 'https://docs.google.com/forms/d/e/1FAIpQLScA0qBWyqaxJWuZdTlyexTfxSXxYHuyCBktM8qY-i7bV4IRzw/viewform',
        'link_text': 'register here →',
    },
    {
        'emoji': '☕',
        'headline': 'South Woodford Community Café — Sunday 28th June.',
        'details': "1pm–3pm · St Mary's, Woodford, 207 High Rd, E18 2PA. Free and autistic-led.",
        'link_url': '',
        'link_text': '',
    },
]

def _normalise_announcement(raw, new_id):
    """Coerce a raw dict into a clean announcement with a stable id."""
    return {
        'id': new_id,
        'emoji': (raw.get('emoji') or '').strip()[:8],
        'headline': (raw.get('headline') or '').strip(),
        'details': (raw.get('details') or '').strip(),
        'link_url': (raw.get('link_url') or '').strip(),
        'link_text': (raw.get('link_text') or '').strip(),
    }

def get_announcements():
    """Return the current announcement list, seeding defaults on first use."""
    raw = get_setting(ANNOUNCEMENTS_KEY)
    if raw is None:
        seeded = [_normalise_announcement(a, i + 1) for i, a in enumerate(DEFAULT_ANNOUNCEMENTS)]
        # Persisting the seed is a convenience, not a requirement. If the write
        # fails (database briefly locked or read-only) still return the list —
        # the homepage must not go down over a first-run seed.
        try:
            set_setting(ANNOUNCEMENTS_KEY, json.dumps(seeded))
        except Exception as e:
            db.session.rollback()
            print(f"[announcements] could not persist default announcements: {e}")
        return seeded
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return []
    # Re-id sequentially so ids are always clean/consistent
    return [_normalise_announcement(a, i + 1) for i, a in enumerate(items)]

def save_announcements(items):
    """Persist an announcement list (drops empties) and return the saved list."""
    cleaned = []
    for raw in items:
        ann = _normalise_announcement(raw, len(cleaned) + 1)
        # Skip rows with no visible content at all
        if not ann['headline'] and not ann['details'] and not ann['emoji']:
            continue
        # A link needs both a url and link text to render
        if not ann['link_url'] or not ann['link_text']:
            ann['link_url'] = ''
            ann['link_text'] = ''
        cleaned.append(ann)
    set_setting(ANNOUNCEMENTS_KEY, json.dumps(cleaned))
    return cleaned

def get_default_confirmation_message():
    return """Dear {{name}},

Your booking has been confirmed!

Room: {{room_name}}
Location: {{building_location}}
Date: {{date}}
Time: {{start_time}} - {{end_time}}
Email: {{email}}

Thank you for using our booking system.

To cancel your booking, visit:
{{cancel_url}}
"""

DEFAULT_ROOMS = [
    {'keywords': ('4.2', 'indigo'), 'name': 'Room 4.2 "Indigo"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
    {'keywords': ('4.4', 'rose'), 'name': 'Room 4.4 "Rose"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'slot'},
    {'keywords': ('4.7', 'clerkenwell'), 'name': 'Room 4.7 "Clerkenwell"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
    {'keywords': ('loft',), 'name': 'The Loft', 'building_location': 'Floor 6 - Pan Macmillan HQ', 'room_type': 'open'},
    {'keywords': ('4.6', 'farringdon'), 'name': 'Room 4.6 "Farringdon"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
    {'keywords': ('5.1',), 'name': 'Room 5.1', 'building_location': 'Floor 5 - Pan Macmillan HQ', 'room_type': 'open'},
]


def ensure_default_rooms():
    """Create missing rooms without changing IDs or existing room records."""
    rooms = Room.query.order_by(Room.id).all()
    created = []

    for room_data in DEFAULT_ROOMS:
        matching_room = next(
            (
                room for room in rooms
                if any(keyword in room.name.lower() for keyword in room_data['keywords'])
            ),
            None,
        )
        if matching_room:
            continue

        room = Room(
            name=room_data['name'],
            building_location=room_data['building_location'],
            room_type=room_data['room_type'],
            is_active=True,
        )
        db.session.add(room)
        rooms.append(room)
        created.append(room)

    return created


def init_default_data():
    """Initialize default rooms and settings."""
    ensure_default_rooms()
    
    # Set default confirmation message
    if not get_setting('confirmation_message'):
        set_setting('confirmation_message', get_default_confirmation_message())
    
    db.session.commit()

def format_confirmation_message(template, **kwargs):
    """Format the confirmation message with booking details"""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f'{{{{{key}}}}}', str(value))
    return result

def send_confirmation_email(to_email, subject, message):
    """Send confirmation email to user"""
    if not app.config['ENABLE_EMAIL'] or not app.config['SMTP_USER']:
        # Email not configured, just log it
        print(f"[EMAIL WOULD BE SENT TO {to_email}]")
        print(f"Subject: {subject}")
        print(f"---")
        return True
    
    try:
        # Use password as-is (no cleaning needed for hardcoded password)
        smtp_password = app.config['SMTP_PASSWORD']
        
        print(f"[DEBUG] Attempting to send email via {app.config['SMTP_HOST']}:{app.config['SMTP_PORT']}")
        print(f"[DEBUG] Login user: {app.config['SMTP_USER']}")
        print(f"[DEBUG] From address: {app.config['SMTP_FROM']}")
        print(f"[DEBUG] To address: {to_email}")
        
        msg = MIMEMultipart()
        msg['From'] = app.config['SMTP_FROM']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        # Try SMTP_SSL on port 465 first (often works better on PythonAnywhere)
        try:
            print(f"[DEBUG] Trying SMTP_SSL on port 465...")
            with smtplib.SMTP_SSL(app.config['SMTP_HOST'], 465, timeout=20) as server:
                server.set_debuglevel(1)
                print(f"[DEBUG] Logging in with SSL...")
                server.login(app.config['SMTP_USER'], smtp_password)
                print(f"[DEBUG] Login successful, sending message...")
                server.send_message(msg)
                print(f"[DEBUG] Message sent via SSL!")
                return True
        except Exception as ssl_error:
            print(f"[DEBUG] SSL failed ({ssl_error}), trying STARTTLS on port 587...")
            # Fall back to STARTTLS on port 587
            with smtplib.SMTP(app.config['SMTP_HOST'], 587, timeout=20) as server:
                server.set_debuglevel(1)
                server.starttls()
                print(f"[DEBUG] Logging in with STARTTLS...")
                server.login(app.config['SMTP_USER'], smtp_password)
                print(f"[DEBUG] Login successful, sending message...")
                server.send_message(msg)
                print(f"[DEBUG] Message sent via STARTTLS!")
                return True
        
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
        print(f"[ERROR] Type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

def send_bulk_email(recipients, subject, message):
    """Send one email to many recipients via BCC so addresses stay private.

    Returns (success, error_message)."""
    if not recipients:
        return False, 'No recipients'

    if not app.config['ENABLE_EMAIL'] or not app.config['SMTP_USER']:
        print(f"[BULK EMAIL WOULD BE SENT TO {len(recipients)} RECIPIENTS]")
        print(f"Subject: {subject}")
        print(f"Recipients: {recipients}")
        print(f"---\n{message}\n---")
        return True, None

    try:
        msg = MIMEMultipart()
        msg['From'] = app.config['SMTP_FROM']
        # To: ourselves; real recipients go in the SMTP envelope (BCC)
        msg['To'] = app.config['SMTP_FROM']
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))

        smtp_password = app.config['SMTP_PASSWORD']
        try:
            with smtplib.SMTP_SSL(app.config['SMTP_HOST'], 465, timeout=20) as server:
                server.login(app.config['SMTP_USER'], smtp_password)
                server.send_message(msg, to_addrs=recipients)
                return True, None
        except Exception as ssl_error:
            print(f"[DEBUG] Bulk SSL failed ({ssl_error}), trying STARTTLS on port 587...")
            with smtplib.SMTP(app.config['SMTP_HOST'], 587, timeout=20) as server:
                server.starttls()
                server.login(app.config['SMTP_USER'], smtp_password)
                server.send_message(msg, to_addrs=recipients)
                return True, None
    except Exception as e:
        print(f"[ERROR] Failed to send bulk email: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

def send_emails_async(emails):
    """Send a batch of (to, subject, body) emails in a background thread so
    booking requests return instantly. Email sending was previously inline in
    the request: when Gmail was slow the whole request hung, the person saw no
    confirmation screen, retried, and then hit the duplicate-booking guard."""
    def _worker(batch):
        for to, subject, body in batch:
            try:
                send_confirmation_email(to, subject, body)
            except Exception as e:
                print(f"[ERROR] Async email to {to} failed: {e}")
    threading.Thread(target=_worker, args=(list(emails),), daemon=True).start()

def get_upcoming_fridays(count=8, room_id=None):
    """Get upcoming Friday dates, optionally filtered by room availability"""
    fridays = []
    today = datetime.now().date()
    
    # Get current schedule with IDs
    room_schedule = get_room_schedule_ids()
    
    # Find next Friday
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0 and datetime.now().hour >= END_HOUR:
        # If it's Friday past booking hours, start from next Friday
        days_until_friday = 7
    
    next_friday = today + timedelta(days=days_until_friday)
    
    i = 0
    while len(fridays) < count:
        friday = next_friday + timedelta(weeks=i)
        
        # Check if this date is in our schedule
        date_str = friday.isoformat()
        if date_str in room_schedule:
            # If room_id specified, only include if room is available that day
            if room_id is None or room_id in room_schedule[date_str]:
                fridays.append({
                    'date': date_str,
                    'display': friday.strftime('%A, %B %d, %Y')
                })
        
        # Safety limit - don't search too far ahead
        if i > 52:  # One year max
            break
        i += 1

    return fridays

def get_rota_fridays(count=8):
    """Fridays the rota covers — the actual scheduled, bookable operating
    Fridays (same source as the user booking page), so volunteers only ever
    see dates that are genuinely open for sessions."""
    return get_upcoming_fridays(count=count)

VOLUNTEER_ARCHIVED_KEY = 'volunteer_archived_dates'

def get_archived_volunteer_dates():
    raw = get_setting(VOLUNTEER_ARCHIVED_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []

def set_archived_volunteer_dates(dates):
    set_setting(VOLUNTEER_ARCHIVED_KEY, json.dumps(sorted(set(dates))))

def _friday_display(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A, %B %d, %Y')
    except ValueError:
        return date_str

def get_volunteer_rota(count=8):
    """Build the volunteer rota:
      - fridays/volunteers: upcoming bookable Fridays and who can support them
      - past: Fridays that have passed and still have sign-ups (archivable)
      - archived: past Fridays the admin team has archived (kept for the record)
    """
    fridays = get_rota_fridays(count)
    upcoming_strs = {f['date'] for f in fridays}
    today = datetime.now().date()
    archived_strs = set(get_archived_volunteer_dates())

    rows = VolunteerAvailability.query.all()

    volunteers = {}
    past_map = {}      # date_str -> [{name, note, unavailable}]
    archived_map = {}  # date_str -> [{name, note, unavailable}]
    for r in rows:
        ds = r.booking_date.isoformat()
        is_unavail = bool(getattr(r, 'unavailable', False))
        if ds in upcoming_strs:
            v = volunteers.setdefault(r.name, {
                'name': r.name,
                'dates': [],
                'unavailable_dates': [],
                'date_notes': {},
            })
            if is_unavail:
                v['unavailable_dates'].append(ds)
            else:
                v['dates'].append(ds)
            if r.note:
                v['date_notes'][ds] = r.note
        elif r.booking_date < today:
            entry = {'name': r.name, 'note': r.note or '', 'unavailable': is_unavail}
            if ds in archived_strs:
                archived_map.setdefault(ds, []).append(entry)
            else:
                past_map.setdefault(ds, []).append(entry)

    def build_date_list(date_map, reverse=True):
        out = []
        for ds in sorted(date_map, reverse=reverse):
            people = sorted(date_map[ds], key=lambda p: p['name'].lower())
            out.append({'date': ds, 'display': _friday_display(ds), 'volunteers': people})
        return out

    vol_list = sorted(volunteers.values(), key=lambda v: v['name'].lower())
    return {
        'fridays': fridays,
        'volunteers': vol_list,
        'past': build_date_list(past_map),
        'archived': build_date_list(archived_map),
    }

# ----------------------------------------------------------------------------
# Gentle Yoga with Marlijn — trial sessions, capacity-limited (outdoor terrace)
# ----------------------------------------------------------------------------
YOGA_CAPACITY = 8
YOGA_TIME_DISPLAY = '10:00am'
YOGA_DOORS_DISPLAY = '9:30am'  # the terrace/space is available from this time
YOGA_LOCATION = 'Outdoor terrace, Pan Macmillan, 6 Briset Street, London, EC1M 5NR'
YOGA_NOTIFY_EMAIL = 'miles.lagc@gmail.com'

# Concrete bookable session dates (each capped at YOGA_CAPACITY). The September
# Fridays are included so "Fridays in September" can actually be booked; adjust
# this list as the trial firms up.
YOGA_SESSION_DATES = [
    '2026-07-03', '2026-07-10', '2026-07-24', '2026-07-31',
    '2026-08-07', '2026-08-28',
    '2026-09-04', '2026-09-11', '2026-09-18', '2026-09-25',
]

def _yoga_display(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A %-d %B %Y')
    except ValueError:
        return date_str

def get_yoga_availability(include_past=False):
    """Return upcoming yoga sessions with how many spaces are left in each."""
    today = datetime.now().date()
    counts = {}
    for b in YogaBooking.query.all():
        counts[b.session_date.isoformat()] = counts.get(b.session_date.isoformat(), 0) + 1

    sessions = []
    for ds in YOGA_SESSION_DATES:
        try:
            d = datetime.strptime(ds, '%Y-%m-%d').date()
        except ValueError:
            continue
        if not include_past and d < today:
            continue
        booked = counts.get(ds, 0)
        remaining = max(0, YOGA_CAPACITY - booked)
        sessions.append({
            'date': ds,
            'display': _yoga_display(ds),
            'time': YOGA_TIME_DISPLAY,
            'capacity': YOGA_CAPACITY,
            'booked': booked,
            'remaining': remaining,
            'full': remaining <= 0,
        })
    return sessions

def check_availability(room_id, booking_date, start_slot, end_slot, exclude_booking_id=None):
    """Check if a time range is available for booking"""
    query = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.booking_date == booking_date,
        Booking.cancelled_at.is_(None),
        Booking.start_slot < end_slot,
        Booking.end_slot > start_slot
    )
    
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)

    return query.count() == 0

# Short reminder descriptions used in the availability email blast,
# matched by room name keywords (same pattern as get_room_schedule_ids)
ROOM_EMAIL_DESCRIPTIONS = [
    (('4.2', 'indigo'), 'a calm shared workspace where you can work or study quietly alongside others — great for body-doubling and focused productivity'),
    (('4.4', 'rose'), 'a private room just for you, booked in 30-minute slots (up to 3 hours) for dedicated, interruption-free time'),
    (('4.7', 'clerkenwell'), 'a relaxed social lounge with sofas, board games and sensory items — drop in to socialise, unwind or work casually'),
    (('loft',), 'a stunning large space with panoramic London views — great for group activities or having plenty of room to yourself'),
    (('4.6', 'farringdon'), 'a spacious 12-person meeting room with presentation screens, whiteboard and Wi-Fi — perfect for group work and collaboration'),
]

def get_room_email_description(room_name):
    name_lower = room_name.lower()
    for keywords, desc in ROOM_EMAIL_DESCRIPTIONS:
        if any(k in name_lower for k in keywords):
            return desc
    return 'a comfortable space available on Fridays'

def get_free_time_ranges(room_id, booking_date):
    """Return human-readable free time ranges for a slot room on a date,
    e.g. ['11:00 AM – 1:00 PM', '2:30 PM – 4:00 PM']"""
    bookings = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.booking_date == booking_date,
        Booking.cancelled_at.is_(None)
    ).all()
    booked = set()
    for b in bookings:
        for s in range(b.start_slot, b.end_slot):
            booked.add(s)

    # Bookable half-hour slots run 0..9 (last starts 3:30 PM, day ends 4:00 PM)
    free = [i for i in range(len(TIME_SLOTS) - 1) if i not in booked]

    ranges = []
    start = prev = None
    for i in free:
        if start is None:
            start = i
        elif i != prev + 1:
            ranges.append((start, prev))
            start = i
        prev = i
    if start is not None:
        ranges.append((start, prev))

    return [f"{TIME_SLOTS[a]['display']} – {TIME_SLOTS[b + 1]['display']}" for a, b in ranges]

# ============================================================================
# ROUTES - MAIN PAGES
# ============================================================================

@app.route('/')
def landing():
    """Landing page with information about the initiative"""
    return render_template('landing.html', announcements=get_announcements())

@app.route('/peer-support')
def peer_support():
    """Peer support sessions information page"""
    return render_template('peer_support.html')

@app.route('/spaces')
def spaces():
    """Explore the space — photo gallery of the venue"""
    return render_template('spaces.html')

@app.route('/yoga')
def yoga():
    """Gentle Yoga with Marlijn — info + registration page"""
    return render_template('yoga.html',
                           sessions=get_yoga_availability(),
                           capacity=YOGA_CAPACITY)

@app.route('/yoga/cancel/<token>')
def yoga_cancel_page(token):
    """Participant self-cancellation page for a yoga place."""
    booking = YogaBooking.query.filter_by(cancel_token=token).first()
    if not booking:
        return render_template('yoga_cancel.html', token=token, booking=None)
    return render_template('yoga_cancel.html', token=token, booking={
        'name': booking.name,
        'date_display': _yoga_display(booking.session_date.isoformat()),
        'time': YOGA_TIME_DISPLAY,
    })

@app.route('/book')
def index():
    """Main booking page"""
    return render_template('index.html')

@app.route('/admin')
def admin():
    """Admin configuration page - requires login"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin'))
    
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == app.config['ADMIN_PASSWORD']:
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        else:
            error = 'Invalid password'
    
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))

@app.route('/cancel/<token>')
def cancel_page(token):
    """Cancellation page"""
    return render_template('cancel.html', token=token)

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/rooms')
def get_rooms():
    """Get all active rooms; with ?date=YYYY-MM-DD, only rooms scheduled that
    day (in schedule order) including booking counts for open rooms"""
    date_str = request.args.get('date')
    rooms = Room.query.filter_by(is_active=True).all()

    booking_date = None
    if date_str:
        try:
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        scheduled_ids = get_room_schedule_ids().get(booking_date.isoformat(), [])
        rooms_by_id = {r.id: r for r in rooms}
        rooms = [rooms_by_id[rid] for rid in scheduled_ids if rid in rooms_by_id]

    result = []
    for r in rooms:
        item = {
            'id': r.id,
            'name': r.name,
            'building_location': r.building_location,
            'room_type': r.room_type
        }
        if booking_date and r.room_type == 'open':
            item['booking_count'] = Booking.query.filter(
                Booking.room_id == r.id,
                Booking.booking_date == booking_date,
                Booking.cancelled_at.is_(None)
            ).count()
        # Custom hours set by admin — per-date change or the room's default
        # hours (drives the room card and booking summary)
        if booking_date:
            start, end, source = get_effective_room_hours(booking_date.isoformat(), r)
            if source != 'global':
                item['override_start'] = fmt_hhmm(start)
                item['override_end'] = fmt_hhmm(end)
            # Anything people need to know before booking this room on this date
            note = get_room_note(booking_date.isoformat(), r.id)
            if note:
                item['note'] = note
        result.append(item)
    return jsonify(result)

@app.route('/api/fridays')
def get_fridays():
    """Get upcoming Fridays"""
    room_id = request.args.get('room_id', type=int)
    return jsonify(get_upcoming_fridays(room_id=room_id))

@app.route('/api/slots')
def get_slots():
    """Get time slot definitions"""
    return jsonify(TIME_SLOTS)

@app.route('/api/availability/<date>/<int:room_id>')
def get_availability(date, room_id):
    """Get availability for a specific date and room"""
    try:
        booking_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Get current schedule with IDs
    room_schedule = get_room_schedule_ids()
    
    # Check if this room is available on this date
    date_str = booking_date.isoformat()
    if date_str not in room_schedule or room_id not in room_schedule[date_str]:
        return jsonify({'error': 'Room not available on this date'}), 400
    
    # Get all bookings for this date and room
    bookings = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.booking_date == booking_date,
        Booking.cancelled_at.is_(None)
    ).all()
    
    # Mark booked slots
    booked_slots = set()
    for booking in bookings:
        for slot in range(booking.start_slot, booking.end_slot):
            booked_slots.add(slot)
    
    # Special case: March 20th, 2026 - Room 4.2 "Indigo" only available until 2:30pm
    # Find the ID for Room 4.2 using flexible matching
    room_4_2_id = None
    for room in Room.query.all():
        name_lower = room.name.lower()
        if '4.2' in name_lower or 'indigo' in name_lower:
            room_4_2_id = room.id
            break
    # Slot 7 = 2:30pm, so slots 8, 9, 10 (3:00pm-4:00pm) are unavailable
    if date_str == '2026-03-20' and room_4_2_id and room_id == room_4_2_id:
        for slot_idx in [8, 9, 10]:  # 3:00pm, 3:30pm, 4:00pm
            booked_slots.add(slot_idx)
    
    # Special case: May 8th, 2026 - Rooms 4.2 "Indigo" and 4.7 "Clerkenwell" start at 12:30pm
    # Find the IDs for Room 4.2 and Room 4.7 using flexible matching
    room_4_2_id = None
    room_4_7_id = None
    for room in Room.query.all():
        name_lower = room.name.lower()
        if '4.2' in name_lower or 'indigo' in name_lower:
            room_4_2_id = room.id
        if '4.7' in name_lower or 'clerkenwell' in name_lower:
            room_4_7_id = room.id
    # Slots 0, 1, 2 = 11:00am, 11:30am, 12:00pm are unavailable for these rooms
    if date_str == '2026-05-08' and room_id in (room_4_2_id, room_4_7_id):
        for slot_idx in [0, 1, 2]:  # 11:00am, 11:30am, 12:00pm
            booked_slots.add(slot_idx)

    # Admin custom hours (per-date change or room default): block any slots
    # outside the window
    room_obj = db.session.get(Room, room_id)
    if room_obj:
        win_start_hhmm, win_end_hhmm, source = get_effective_room_hours(date_str, room_obj)
        if source != 'global':
            win_start = override_start_slot(win_start_hhmm)
            win_end = override_end_slot(win_end_hhmm)
            for slot in TIME_SLOTS:
                if slot['index'] < win_start or slot['index'] >= win_end:
                    booked_slots.add(slot['index'])

    # Build availability array
    availability = []
    for slot in TIME_SLOTS:
        availability.append({
            'index': slot['index'],
            'time': slot['time'],
            'display': slot['display'],
            'available': slot['index'] not in booked_slots
        })

    return jsonify(availability)

@app.route('/api/book', methods=['POST'])
def create_booking():
    """Create a new booking"""
    data = request.get_json()
    
    # Validate required fields
    required = ['room_id', 'date', 'name', 'email']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    room_id = data['room_id']
    name = data['name'].strip()
    email = data['email'].strip().lower()
    
    # Validate name
    if not name:
        return jsonify({'error': 'Please enter your name'}), 400
    
    # Validate email
    if '@' not in email or '.' not in email.split('@')[1]:
        return jsonify({'error': 'Invalid email address'}), 400
    
    # Parse date
    try:
        booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Validate it's a Friday
    if booking_date.weekday() != 4:
        return jsonify({'error': 'Bookings are only available on Fridays'}), 400
    
    # Get room details
    room = Room.query.get(room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    # One booking per email, per room, per date — blocks accidental duplicates
    # (e.g. someone clicking "book" twice on a whole-day shared room).
    duplicate = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.booking_date == booking_date,
        db.func.lower(Booking.user_email) == email,
        Booking.cancelled_at.is_(None)
    ).first()
    if duplicate:
        return jsonify({'error': 'You already have a booking for this room on this date. Check "My Bookings" below to view or cancel it.'}), 409

    # Determine slots based on room type
    if room.room_type == 'open':
        # Open rooms: book the entire day (9:30am - 5pm)
        start_slot = 0
        end_slot = len(TIME_SLOTS)  # Exclusive end (covers all slots 0-10)

        # Special case: May 8th, 2026 - Rooms 4.2 and 4.7 start at 12:30pm
        date_str = booking_date.isoformat()
        is_room_4_2 = '4.2' in room.name or 'indigo' in room.name.lower()
        is_room_4_7 = '4.7' in room.name or 'clerkenwell' in room.name.lower()
        if date_str == '2026-05-08' and (is_room_4_2 or is_room_4_7):
            start_slot = 3  # 12:30pm
    else:
        # Slot rooms: require start_slot and end_slot from request
        if 'start_slot' not in data or 'end_slot' not in data:
            return jsonify({'error': 'Missing time slot selection'}), 400
        
        start_slot = data['start_slot']
        end_slot = data['end_slot']
        
        # Validate slot range
        if start_slot < 0 or end_slot > len(TIME_SLOTS) or start_slot >= end_slot:
            return jsonify({'error': 'Invalid time slot selection'}), 400
        
        # Validate consecutive slots
        num_slots = end_slot - start_slot
        if num_slots > MAX_SLOTS:
            return jsonify({'error': f'Maximum booking duration is 3 hours ({MAX_SLOTS} slots)'}), 400

        # Enforce the room's custom hours (per-date change or room default)
        win_start_hhmm, win_end_hhmm, source = get_effective_room_hours(
            booking_date.isoformat(), room)
        if source != 'global':
            win_start = override_start_slot(win_start_hhmm)
            win_end = override_end_slot(win_end_hhmm)
            if start_slot < win_start or end_slot > win_end:
                return jsonify({'error': f'This room is only available {fmt_hhmm(win_start_hhmm)}–{fmt_hhmm(win_end_hhmm)} on this date. Please pick a time within those hours.'}), 400

    # Check availability (only for slot rooms - open rooms allow multiple bookings)
    if room.room_type == 'slot' and not check_availability(room_id, booking_date, start_slot, end_slot):
        return jsonify({'error': 'Selected time slots are no longer available'}), 409
    
    # Create booking
    cancel_token = secrets.token_urlsafe(32)
    booking = Booking(
        room_id=room_id,
        user_name=name,
        user_email=email,
        booking_date=booking_date,
        start_slot=start_slot,
        end_slot=end_slot,
        cancel_token=cancel_token
    )
    
    db.session.add(booking)
    db.session.commit()
    
    # Generate confirmation message
    template = get_setting('confirmation_message', get_default_confirmation_message())
    start_time, end_time = booking_time_display(booking)

    date_display = booking_date.strftime('%A, %B %d, %Y')
    
    confirmation_message = format_confirmation_message(
        template,
        name=name,
        email=email,
        room_name=room.name,
        building_location=room.building_location,
        date=date_display,
        start_time=start_time,
        end_time=end_time,
        cancel_url=f"{request.host_url.rstrip('/')}/cancel/{cancel_token}"
    )

    # Repeat any admin note for this room/date — they saw it before booking,
    # this is their written record of it. Appended rather than templated so
    # existing saved confirmation templates keep working.
    room_note = get_room_note(booking_date.isoformat(), room_id)
    if room_note:
        confirmation_message += (
            f"\n\n---\nPlease note about {room.name} on this date:\n{room_note}\n"
        )

    # Queue all emails in the background so the person sees their on-screen
    # confirmation immediately, even if Gmail is slow or briefly down.
    admin_subject = f"New Booking: {name} booked {room.name}"
    admin_message = f"""A new booking has been made:

Name: {name}
Email: {email}
Room: {room.name}
Date: {date_display}
Time: {start_time} - {end_time}

View all bookings at: {request.host_url.rstrip('/')}/admin
"""
    send_emails_async([
        (email, f"Booking Confirmed: {room.name} on {date_display}", confirmation_message),
        ('londonautismgroupcharity@gmail.com', admin_subject, admin_message),
        ('zara.lagc@gmail.com', admin_subject, admin_message),
    ])

    return jsonify({
        'success': True,
        'booking_id': booking.id,
        'confirmation_message': confirmation_message,
        'cancel_token': cancel_token,
        'email_sent': bool(app.config['ENABLE_EMAIL'] and app.config['SMTP_USER'])
    })

@app.route('/api/testimonial', methods=['POST'])
def submit_testimonial():
    """Receive a testimonial submission and email it to the charity."""
    data = request.get_json(silent=True) or {}
    testimonial = (data.get('testimonial') or '').strip()
    attribution = (data.get('attribution') or 'anonymous').strip()
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    page = (data.get('page') or 'main').strip()

    if not testimonial:
        return jsonify({'success': False, 'error': 'Please enter your experience before submitting.'}), 400

    attribution_labels = {
        'anonymous': 'Anonymously',
        'first_name': 'First name only',
        'full_name': 'Full name',
        'other': 'Something else'
    }
    attribution_label = attribution_labels.get(attribution, attribution)

    if attribution == 'anonymous':
        credited_as = 'Anonymous'
    elif name:
        credited_as = name
    else:
        credited_as = '(not provided)'

    page_labels = {
        'main': 'Fridays @ Farringdon',
        'peer_support': 'Peer Support Sessions',
    }
    page_label = page_labels.get(page, page)

    body = f"""A new testimonial has been submitted via the {page_label} website page.

How they would like to be credited: {attribution_label}
Credit name / label: {credited_as}
Contact email: {email if email else '(not provided)'}

--- Testimonial ---
{testimonial}
"""

    sent = send_confirmation_email(
        'contact@londonautismgroupcharity.org',
        f'New testimonial submission — {page_label}',
        body
    )

    if not sent:
        return jsonify({'success': False, 'error': 'We could not send your message right now. Please try again later.'}), 502

    return jsonify({'success': True})

@app.route('/api/yoga/availability')
def yoga_availability():
    """Public: upcoming yoga sessions with remaining spaces."""
    return jsonify(get_yoga_availability())

@app.route('/api/yoga/book', methods=['POST'])
def yoga_book():
    """Public: register for a yoga session (enforces the per-date capacity)."""
    data = request.get_json(silent=True) or {}

    def clean(key, limit=200):
        return (data.get(key) or '').strip()[:limit]

    date_str = clean('session_date', 20)
    name = clean('name', 120)
    email = clean('email', 120)
    phone = clean('phone', 50)
    emergency_name = clean('emergency_name', 120)
    emergency_phone = clean('emergency_phone', 50)
    experience = clean('experience', 20)
    health_info = clean('health_info', 4000)
    avoid_info = clean('avoid_info', 4000)
    accessibility_info = clean('accessibility_info', 4000)
    agreed_safety = bool(data.get('agreed_safety'))

    # Required fields
    if not all([name, email, phone, emergency_name, emergency_phone, experience, date_str]):
        return jsonify({'success': False, 'error': 'Please fill in all the required fields.'}), 400
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'success': False, 'error': 'Please enter a valid email address.'}), 400
    if not agreed_safety:
        return jsonify({'success': False, 'error': 'Please tick the box to confirm you understand the session is gentle and you can rest at any time.'}), 400

    # Valid, in-date session?
    if date_str not in YOGA_SESSION_DATES:
        return jsonify({'success': False, 'error': 'Please choose a valid session date.'}), 400
    session_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    if session_date < datetime.now().date():
        return jsonify({'success': False, 'error': 'That session date has already passed.'}), 400

    # Capacity check (count current registrations for this date)
    booked = YogaBooking.query.filter_by(session_date=session_date).count()
    if booked >= YOGA_CAPACITY:
        return jsonify({'success': False, 'error': 'Sorry, this session is now full. Please choose another date.', 'full': True}), 409

    # One registration per email per session date
    already = YogaBooking.query.filter(
        YogaBooking.session_date == session_date,
        db.func.lower(YogaBooking.email) == email.lower()
    ).first()
    if already:
        return jsonify({'success': False, 'error': 'You are already registered for this session — your place is safe. If you did not receive a confirmation email, please check your spam folder or contact us at ' + YOGA_NOTIFY_EMAIL + '.'}), 409

    # "Same as last time": returning participants can reuse the answers from
    # their most recent registration. Copied server-side so previous health
    # details are never sent to the browser.
    if data.get('reuse_previous'):
        previous = YogaBooking.query.filter(
            db.func.lower(YogaBooking.email) == email.lower()
        ).order_by(YogaBooking.created_at.desc()).first()
        if not previous:
            return jsonify({'success': False, 'error': "We couldn't find a previous registration under this email address, so we can't reuse earlier answers. Please untick the box and fill in the questions below."}), 400
        if not health_info:
            health_info = previous.health_info or ''
        if not avoid_info:
            avoid_info = previous.avoid_info or ''
        if not accessibility_info:
            accessibility_info = previous.accessibility_info or ''

    cancel_token = secrets.token_urlsafe(32)
    booking = YogaBooking(
        session_date=session_date,
        name=name, email=email, phone=phone,
        emergency_name=emergency_name, emergency_phone=emergency_phone,
        experience=experience,
        health_info=health_info, avoid_info=avoid_info, accessibility_info=accessibility_info,
        agreed_safety=agreed_safety,
        cancel_token=cancel_token,
    )
    db.session.add(booking)
    db.session.commit()

    spaces_left = max(0, YOGA_CAPACITY - (booked + 1))
    date_display = _yoga_display(date_str)

    # Notify the yoga coordinator with every answer
    admin_body = f"""A new Gentle Yoga with Marlijn registration has come in.

Session: {date_display} at {YOGA_TIME_DISPLAY}
Location: {YOGA_LOCATION}
Spaces left after this booking: {spaces_left} of {YOGA_CAPACITY}

--- Participant ---
Name: {name}
Email: {email}
Phone: {phone}
Emergency contact: {emergency_name} — {emergency_phone}
Done yoga before: {experience}

--- Anything the instructor should know (to adapt safely) ---
{health_info or '(nothing provided)'}

--- Anything to definitely avoid ---
{avoid_info or '(nothing provided)'}

--- How they experience / process / communicate / move / learn ---
{accessibility_info or '(nothing provided)'}

Understood the gentle-session statement: {'Yes' if agreed_safety else 'No'}
"""
    # Friendly confirmation to the participant (no health details echoed back)
    confirm_body = f"""Dear {name},

Thank you for registering for Gentle Yoga with Marlijn at Fridays @ Farringdon.

Your session: {date_display}
The space is available from {YOGA_DOORS_DISPLAY}, so you are welcome to arrive any time from {YOGA_DOORS_DISPLAY} to settle in. The yoga session itself begins at {YOGA_TIME_DISPLAY}.
Where: {YOGA_LOCATION}

A few gentle reminders:
- You're welcome to come from {YOGA_DOORS_DISPLAY} — that's when the space opens — and we'll begin the session at {YOGA_TIME_DISPLAY}.
- Please bring your own yoga mat and wear loose, comfortable clothing.
- As we'll be on the outdoor terrace, suncream, a hat or a water bottle may be helpful in sunny weather.
- This is a gentle, low-pressure session — you can choose what to take part in and rest whenever you need to.

Need to cancel your place? You can cancel any time using this link, and it will free your spot for someone else:
{request.host_url.rstrip('/')}/yoga/cancel/{cancel_token}

Warm wishes,
London Autism Group Charity — Fridays @ Farringdon
"""
    # Send both emails in the background so registration confirms instantly
    send_emails_async([
        (YOGA_NOTIFY_EMAIL, f'New yoga registration — {date_display} ({name})', admin_body),
        (email, 'Your Gentle Yoga registration — Fridays @ Farringdon', confirm_body),
    ])

    return jsonify({'success': True, 'date_display': date_display, 'time': YOGA_TIME_DISPLAY})

@app.route('/api/yoga/cancel/<token>', methods=['POST'])
def yoga_cancel(token):
    """Participant cancels their own yoga place: remove it and notify the coordinator."""
    booking = YogaBooking.query.filter_by(cancel_token=token).first()
    if not booking:
        return jsonify({'success': False, 'error': 'This booking could not be found. It may already have been cancelled.'}), 404

    name = booking.name
    email = booking.email
    date_display = _yoga_display(booking.session_date.isoformat())

    db.session.delete(booking)
    db.session.commit()

    # Notify the yoga coordinator
    send_confirmation_email(
        YOGA_NOTIFY_EMAIL,
        f'Yoga place cancelled — {date_display} ({name})',
        f"""{name} has cancelled their place for Gentle Yoga with Marlijn.

Session: {date_display} at {YOGA_TIME_DISPLAY}
Participant: {name} ({email})

Their place is now free again for someone else.
"""
    )

    # Confirm to the participant
    send_confirmation_email(
        email,
        'Your Gentle Yoga place has been cancelled',
        f"""Dear {name},

This confirms that your place for Gentle Yoga with Marlijn on {date_display} at {YOGA_TIME_DISPLAY} has been cancelled.

If you'd like to come along to a future session, you're very welcome to register again at any time.

Warm wishes,
London Autism Group Charity — Fridays @ Farringdon
"""
    )

    return jsonify({'success': True, 'date_display': date_display, 'time': YOGA_TIME_DISPLAY})

@app.route('/api/booking/<token>')
def get_booking(token):
    """Get booking details by cancel token"""
    booking = Booking.query.filter_by(cancel_token=token).first()
    
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    
    if booking.cancelled_at:
        return jsonify({'error': 'This booking has already been cancelled'}), 410
    
    start_time, end_time = booking_time_display(booking)
    
    return jsonify({
        'id': booking.id,
        'room_name': booking.room.name,
        'building_location': booking.room.building_location,
        'name': booking.user_name,
        'email': booking.user_email,
        'date': booking.booking_date.isoformat(),
        'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
        'start_time': start_time,
        'end_time': end_time
    })

@app.route('/api/cancel/<token>', methods=['POST'])
def cancel_booking(token):
    """Cancel a booking"""
    booking = Booking.query.filter_by(cancel_token=token).first()
    
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    
    if booking.cancelled_at:
        return jsonify({'error': 'This booking has already been cancelled'}), 410
    
    # Get booking details before cancelling
    room_name = booking.room.name
    user_name = booking.user_name
    user_email = booking.user_email
    booking_date = booking.booking_date.strftime('%A, %B %d, %Y')
    start_time, end_time = booking_time_display(booking)
    
    booking.cancelled_at = datetime.utcnow()
    db.session.commit()
    
    # Send admin notification about cancellation
    admin_emails = ['londonautismgroupcharity@gmail.com', 'zara.lagc@gmail.com']
    admin_subject = f"Booking Cancelled: {user_name} cancelled {room_name}"
    admin_message = f"""A booking has been cancelled:

Name: {user_name}
Email: {user_email}
Room: {room_name}
Date: {booking_date}
Time: {start_time} - {end_time}

This booking has been cancelled by the user.
"""
    
    for admin_email in admin_emails:
        send_confirmation_email(admin_email, admin_subject, admin_message)
    
    return jsonify({
        'success': True,
        'message': 'Your booking has been cancelled successfully'
    })

@app.route('/api/my-bookings', methods=['POST'])
def get_my_bookings():
    """Get all bookings for an email address"""
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    
    bookings = Booking.query.filter(
        Booking.user_email == email,
        Booking.cancelled_at.is_(None),
        Booking.booking_date >= datetime.now().date()
    ).order_by(Booking.booking_date, Booking.start_slot).all()
    
    result = []
    for booking in bookings:
        start_time, end_time = booking_time_display(booking)
        
        result.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'building_location': booking.room.building_location,
            'name': booking.user_name,
            'date': booking.booking_date.isoformat(),
            'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
            'start_time': start_time,
            'end_time': end_time,
            'cancel_token': booking.cancel_token
        })
    
    return jsonify(result)

# ============================================================================
# ADMIN API ENDPOINTS
# ============================================================================

@app.route('/api/admin/rooms')
@admin_required
def admin_get_rooms():
    """Get all rooms (including inactive)"""
    rooms = Room.query.all()
    return jsonify([{
        'id': r.id,
        'name': r.name,
        'building_location': r.building_location,
        'room_type': r.room_type,
        'is_active': r.is_active
    } for r in rooms])

@app.route('/api/admin/rooms', methods=['POST'])
@admin_required
def admin_create_room():
    """Create a new room"""
    data = request.get_json()
    
    room = Room(
        name=data['name'],
        building_location=data.get('building_location', ''),
        room_type=data.get('room_type', 'slot'),
        is_active=data.get('is_active', True)
    )
    db.session.add(room)
    db.session.commit()
    
    return jsonify({
        'id': room.id,
        'name': room.name,
        'building_location': room.building_location,
        'room_type': room.room_type,
        'is_active': room.is_active
    })

@app.route('/api/admin/rooms/<int:room_id>', methods=['PUT'])
@admin_required
def admin_update_room(room_id):
    """Update a room"""
    room = Room.query.get_or_404(room_id)
    data = request.get_json()
    
    room.name = data.get('name', room.name)
    room.building_location = data.get('building_location', room.building_location)
    room.room_type = data.get('room_type', room.room_type)
    room.is_active = data.get('is_active', room.is_active)
    
    db.session.commit()
    
    return jsonify({
        'id': room.id,
        'name': room.name,
        'building_location': room.building_location,
        'room_type': room.room_type,
        'is_active': room.is_active
    })

@app.route('/api/admin/rooms/<int:room_id>', methods=['DELETE'])
@admin_required
def admin_delete_room(room_id):
    """Delete a room (hard delete - permanently removes from database)"""
    room = Room.query.get_or_404(room_id)
    
    # Check if room has any bookings
    has_bookings = Booking.query.filter_by(room_id=room_id).first() is not None
    if has_bookings:
        return jsonify({'error': 'Cannot delete room with existing bookings. Deactivate it instead.'}), 400
    
    db.session.delete(room)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/announcements')
@admin_required
def admin_get_announcements():
    """Get the homepage announcement list."""
    return jsonify(get_announcements())

@app.route('/api/admin/announcements', methods=['PUT'])
@admin_required
def admin_save_announcements():
    """Replace the whole announcement list with the submitted, ordered list."""
    data = request.get_json(silent=True) or {}
    items = data.get('announcements')
    if not isinstance(items, list):
        return jsonify({'error': 'Expected an "announcements" list.'}), 400
    saved = save_announcements(items)
    return jsonify(saved)

@app.route('/api/admin/volunteers')
@admin_required
def admin_get_volunteers():
    """Get the volunteer availability rota for upcoming Fridays."""
    return jsonify(get_volunteer_rota())

@app.route('/api/admin/volunteers', methods=['POST'])
@admin_required
def admin_set_volunteer():
    """Set one volunteer's status across the upcoming Fridays.

    Body: {name, entries: [{date, status, note}]} where status is
    'available' or 'unavailable'. Replaces that volunteer's rows within
    the upcoming-Friday window."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Please enter your name.'}), 400

    upcoming = {f['date'] for f in get_rota_fridays()}

    # Accept new {entries} format or old {dates, note} for backward compat
    entries = data.get('entries')
    if entries is None:
        # Legacy format: list of available dates with a single note
        legacy_note = (data.get('note') or '').strip()[:200]
        entries = [{'date': ds, 'status': 'available', 'note': legacy_note}
                   for ds in (data.get('dates') or [])]

    # Replace this volunteer's entries within the upcoming window
    today = datetime.now().date()
    existing = VolunteerAvailability.query.filter(
        db.func.lower(VolunteerAvailability.name) == name.lower(),
        VolunteerAvailability.booking_date >= today,
    ).all()
    for row in existing:
        if row.booking_date.isoformat() in upcoming:
            db.session.delete(row)

    seen = set()
    for entry in entries:
        ds = (entry.get('date') or '').strip()
        status = (entry.get('status') or '').strip()
        note = (entry.get('note') or '').strip()[:200]
        if ds not in upcoming or ds in seen or status not in ('available', 'unavailable'):
            continue
        seen.add(ds)
        db.session.add(VolunteerAvailability(
            name=name,
            booking_date=datetime.strptime(ds, '%Y-%m-%d').date(),
            note=note,
            unavailable=(status == 'unavailable'),
        ))
    db.session.commit()

    return jsonify(get_volunteer_rota())

@app.route('/api/admin/volunteers/remove', methods=['POST'])
@admin_required
def admin_remove_volunteer():
    """Remove a volunteer entirely from the upcoming rota."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Missing name.'}), 400

    today = datetime.now().date()
    rows = VolunteerAvailability.query.filter(
        db.func.lower(VolunteerAvailability.name) == name.lower(),
        VolunteerAvailability.booking_date >= today,
    ).all()
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    return jsonify(get_volunteer_rota())

@app.route('/api/admin/volunteers/archive', methods=['POST'])
@admin_required
def admin_archive_volunteer_date():
    """Archive a passed Friday so it drops out of the active rota (kept for the record)."""
    data = request.get_json(silent=True) or {}
    date_str = (data.get('date') or '').strip()
    if not date_str:
        return jsonify({'error': 'Missing date.'}), 400
    archived = get_archived_volunteer_dates()
    if date_str not in archived:
        archived.append(date_str)
        set_archived_volunteer_dates(archived)
    return jsonify(get_volunteer_rota())

@app.route('/api/admin/volunteers/unarchive', methods=['POST'])
@admin_required
def admin_unarchive_volunteer_date():
    """Restore an archived Friday back into the Past list."""
    data = request.get_json(silent=True) or {}
    date_str = (data.get('date') or '').strip()
    archived = [d for d in get_archived_volunteer_dates() if d != date_str]
    set_archived_volunteer_dates(archived)
    return jsonify(get_volunteer_rota())

@app.route('/api/admin/yoga-bookings')
@admin_required
def admin_get_yoga_bookings():
    """All yoga registrations grouped by session date, plus per-date capacity."""
    bookings = YogaBooking.query.order_by(
        YogaBooking.session_date, YogaBooking.created_at
    ).all()

    by_date = {}
    for b in bookings:
        ds = b.session_date.isoformat()
        by_date.setdefault(ds, []).append({
            'id': b.id,
            'name': b.name,
            'email': b.email,
            'phone': b.phone,
            'emergency_name': b.emergency_name,
            'emergency_phone': b.emergency_phone,
            'experience': b.experience,
            'health_info': b.health_info,
            'avoid_info': b.avoid_info,
            'accessibility_info': b.accessibility_info,
            'agreed_safety': b.agreed_safety,
            'attended': b.attended,
            'created_at': b.created_at.strftime('%d %b %Y, %H:%M') if b.created_at else '',
        })

    today = datetime.now().date()
    sessions = []
    # Show every configured date that has bookings or is still upcoming
    seen = set()
    for ds in YOGA_SESSION_DATES:
        d = datetime.strptime(ds, '%Y-%m-%d').date()
        if ds in by_date or d >= today:
            seen.add(ds)
            people = by_date.get(ds, [])
            sessions.append({
                'date': ds,
                'display': _yoga_display(ds),
                'time': YOGA_TIME_DISPLAY,
                'capacity': YOGA_CAPACITY,
                'booked': len(people),
                'remaining': max(0, YOGA_CAPACITY - len(people)),
                'past': d < today,
                'bookings': people,
            })
    # Any bookings on dates not in the configured list (e.g. removed dates)
    for ds, people in by_date.items():
        if ds not in seen:
            d = datetime.strptime(ds, '%Y-%m-%d').date()
            sessions.append({
                'date': ds, 'display': _yoga_display(ds), 'time': YOGA_TIME_DISPLAY,
                'capacity': YOGA_CAPACITY, 'booked': len(people),
                'remaining': max(0, YOGA_CAPACITY - len(people)),
                'past': d < today, 'bookings': people,
            })

    sessions.sort(key=lambda s: s['date'])
    return jsonify({'sessions': sessions, 'capacity': YOGA_CAPACITY})

@app.route('/api/admin/yoga-bookings/<int:booking_id>', methods=['DELETE'])
@admin_required
def admin_delete_yoga_booking(booking_id):
    """Remove a yoga registration (frees a space) and let the participant know."""
    booking = db.session.get(YogaBooking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404

    name = booking.name
    email = booking.email
    date_display = _yoga_display(booking.session_date.isoformat())

    db.session.delete(booking)
    db.session.commit()

    # Let the participant know their place has been cancelled by the team
    send_confirmation_email(
        email,
        f'Your Gentle Yoga place on {date_display} has been cancelled',
        f"""Dear {name},

We're sorry to let you know that your place for Gentle Yoga with Marlijn on {date_display} at {YOGA_TIME_DISPLAY} has been cancelled.

We're sorry for any inconvenience this causes. If you have any questions, or would like to book onto another session, please contact us at {YOGA_NOTIFY_EMAIL} — we'd be very happy to help.

Warm wishes,
London Autism Group Charity — Fridays @ Farringdon
"""
    )

    return jsonify({'success': True})

@app.route('/api/admin/yoga-bookings/export')
@admin_required
def admin_export_yoga_bookings():
    """Download all yoga registrations as a CSV."""
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Session date', 'Time', 'Name', 'Email', 'Phone',
        'Emergency contact name', 'Emergency contact phone', 'Done yoga before',
        'Instructor should know (safety)', 'Definitely avoid',
        'Experience/communication/access needs',
        'Understood gentle-session statement', 'Registered at',
    ])
    for b in YogaBooking.query.order_by(YogaBooking.session_date, YogaBooking.created_at).all():
        writer.writerow([
            b.session_date.isoformat(), YOGA_TIME_DISPLAY, b.name, b.email, b.phone,
            b.emergency_name, b.emergency_phone, b.experience,
            b.health_info, b.avoid_info, b.accessibility_info,
            'Yes' if b.agreed_safety else 'No',
            b.created_at.strftime('%Y-%m-%d %H:%M') if b.created_at else '',
        ])
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=yoga_bookings.csv'},
    )

@app.route('/api/admin/settings')
@admin_required
def admin_get_settings():
    """Get all settings"""
    return jsonify({
        'confirmation_message': get_setting('confirmation_message', get_default_confirmation_message())
    })

@app.route('/api/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    """Update settings"""
    data = request.get_json()
    
    if 'confirmation_message' in data:
        set_setting('confirmation_message', data['confirmation_message'])
    
    return jsonify({'success': True})

@app.route('/api/admin/bookings')
@admin_required
def admin_get_bookings():
    """Get all upcoming bookings"""
    bookings = Booking.query.filter(
        Booking.cancelled_at.is_(None),
        Booking.booking_date >= datetime.now().date()
    ).order_by(Booking.booking_date, Booking.start_slot).all()
    
    result = []
    for booking in bookings:
        start_time, end_time = booking_time_display(booking)
        
        result.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'user_name': booking.user_name,
            'user_email': booking.user_email,
            'date': booking.booking_date.isoformat(),
            'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
            'start_time': start_time,
            'end_time': end_time,
            'room_type': booking.room.room_type,
            'attended': booking.attended
        })

    return jsonify(result)

@app.route('/api/admin/bookings/archive')
@admin_required
def admin_get_bookings_archive():
    """Get all past bookings (archived)"""
    bookings = Booking.query.filter(
        Booking.cancelled_at.is_(None),
        Booking.booking_date < datetime.now().date()
    ).order_by(Booking.booking_date.desc(), Booking.start_slot).all()
    
    result = []
    for booking in bookings:
        start_time, end_time = booking_time_display(booking)
        
        result.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'user_name': booking.user_name,
            'user_email': booking.user_email,
            'date': booking.booking_date.isoformat(),
            'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
            'start_time': start_time,
            'end_time': end_time,
            'room_type': booking.room.room_type,
            'attended': booking.attended
        })

    return jsonify(result)

def _parse_attended(data):
    """Read {attended: true|false|null} from a request body."""
    if 'attended' not in data:
        return None, jsonify({'error': 'Missing attended value'}), 400
    val = data['attended']
    if val not in (True, False, None):
        return None, jsonify({'error': 'attended must be true, false or null'}), 400
    return val, None, None

@app.route('/api/admin/bookings/<int:booking_id>/attendance', methods=['POST'])
@admin_required
def admin_set_booking_attendance(booking_id):
    """Record attendance for a Rose (slot room) booking: true = came,
    false = no-show, null = clear. Agreed to track only the
    capacity-limited spaces (Rose + yoga), not the open rooms."""
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    if booking.room.room_type != 'slot':
        return jsonify({'error': 'Attendance is only tracked for Rose (slot) bookings'}), 400
    val, err, code = _parse_attended(request.get_json(silent=True) or {})
    if err:
        return err, code
    booking.attended = val
    db.session.commit()
    return jsonify({'success': True, 'attended': booking.attended})

@app.route('/api/admin/yoga-bookings/<int:booking_id>/attendance', methods=['POST'])
@admin_required
def admin_set_yoga_attendance(booking_id):
    """Record attendance for a yoga registration (true/false/null)."""
    booking = db.session.get(YogaBooking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    val, err, code = _parse_attended(request.get_json(silent=True) or {})
    if err:
        return err, code
    booking.attended = val
    db.session.commit()
    return jsonify({'success': True, 'attended': booking.attended})

@app.route('/api/admin/attendance-summary')
@admin_required
def admin_attendance_summary():
    """Roll up recorded attendance per person across yoga + Rose, so repeat
    no-shows are easy to spot when capacity is tight."""
    people = {}

    def bump(name, email, kind, attended):
        key = email.lower()
        p = people.setdefault(key, {
            'name': name, 'email': key,
            'attended': 0, 'no_shows': 0,
            'yoga_no_shows': 0, 'rose_no_shows': 0,
        })
        p['name'] = name  # keep the most recent spelling
        if attended:
            p['attended'] += 1
        else:
            p['no_shows'] += 1
            p[f'{kind}_no_shows'] += 1

    for b in YogaBooking.query.filter(YogaBooking.attended.isnot(None)).order_by(YogaBooking.created_at).all():
        bump(b.name, b.email, 'yoga', b.attended)
    rose_rows = Booking.query.join(Room).filter(
        Booking.attended.isnot(None),
        Room.room_type == 'slot'
    ).order_by(Booking.created_at).all()
    for b in rose_rows:
        bump(b.user_name, b.user_email, 'rose', b.attended)

    result = sorted(people.values(), key=lambda p: (-p['no_shows'], p['name'].lower()))
    return jsonify(result)

@app.route('/api/admin/booking-counts')
@admin_required
def admin_get_booking_counts():
    """Get booking counts per room per date"""
    from sqlalchemy import func
    
    counts = db.session.query(
        Booking.booking_date,
        Room.name.label('room_name'),
        func.count(Booking.id).label('count')
    ).join(Room).filter(
        Booking.cancelled_at.is_(None),
        Booking.booking_date >= datetime.now().date()
    ).group_by(Booking.booking_date, Room.name).order_by(Booking.booking_date, Room.name).all()
    
    result = []
    for row in counts:
        result.append({
            'date': row.booking_date.isoformat(),
            'date_display': row.booking_date.strftime('%A, %B %d, %Y'),
            'room_name': row.room_name,
            'count': row.count
        })
    
    return jsonify(result)

def blast_sent_key(date_str):
    """Setting key that records an availability blast was sent for a date"""
    return f'availability_email_sent:{date_str}'

def get_blast_sent_status(date_str):
    """Return the sent record for a date, or None if not yet sent"""
    raw = get_setting(blast_sent_key(date_str))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {'sent_at_display': raw, 'count': None}

@app.route('/api/admin/availability-email-status')
@admin_required
def admin_availability_email_status():
    """Return a map of date -> sent record for dates that have been blasted"""
    records = Setting.query.filter(Setting.key.like('availability_email_sent:%')).all()
    status = {}
    for s in records:
        date_str = s.key.split(':', 1)[1]
        try:
            status[date_str] = json.loads(s.value)
        except (ValueError, TypeError):
            status[date_str] = {'sent_at_display': s.value, 'count': None}
    return jsonify(status)

@app.route('/api/admin/availability-email-draft/<date>')
@admin_required
def admin_availability_email_draft(date):
    """Draft an availability email for a given Friday: subject, body and
    the default recipient list (everyone who has previously booked)"""
    try:
        booking_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    date_str = booking_date.isoformat()

    # Block if a blast has already gone out for this Friday
    sent = get_blast_sent_status(date_str)
    if sent:
        return jsonify({
            'error': 'already_sent',
            'sent': sent
        }), 409
    room_schedule = get_room_schedule_ids()
    if date_str not in room_schedule:
        return jsonify({'error': 'No rooms are scheduled for this date'}), 400

    room_lines = []
    for room_id in room_schedule[date_str]:
        room = Room.query.get(room_id)
        if not room or not room.is_active:
            continue
        desc = get_room_email_description(room.name)
        if room.room_type == 'slot':
            free_ranges = get_free_time_ranges(room.id, booking_date)
            if not free_ranges:
                continue  # fully booked — leave it out of the email
            room_lines.append(f"• {room.name} — {desc}.\n   Times still available: {', '.join(free_ranges)}")
        else:
            start, end, _source = get_effective_room_hours(date_str, room)
            room_lines.append(f"• {room.name} — {desc}.\n   Open {fmt_hhmm(start)} – {fmt_hhmm(end)}")

    if not room_lines:
        return jsonify({'error': 'No rooms with availability on this date'}), 400

    date_display = booking_date.strftime('%A %d %B %Y').replace(' 0', ' ')
    booking_url = f"{request.host_url.rstrip('/')}/"

    subject = f"Spaces available this Friday ({booking_date.strftime('%d %B').lstrip('0')}) — Fridays @ Farringdon"
    rooms_text = '\n\n'.join(room_lines)
    body = f"""Hello,

There are still spaces available at Fridays @ Farringdon this week, on {date_display}.

Here's what's on offer this Friday:

{rooms_text}

If you'd like to join us, you can register here:
{booking_url}

We'd love to see you there!

Best wishes,
London Autism Group Charity
Fridays @ Farringdon
"""

    # Default recipients: everyone who has ever made a booking — room bookings
    # plus yoga registrations (deduplicated)
    seen = set()
    recipients = []
    for (email,) in db.session.query(Booking.user_email).distinct().all():
        email_clean = (email or '').strip().lower()
        if email_clean and email_clean not in seen:
            seen.add(email_clean)
            recipients.append(email_clean)
    for (email,) in db.session.query(YogaBooking.email).distinct().all():
        email_clean = (email or '').strip().lower()
        if email_clean and email_clean not in seen:
            seen.add(email_clean)
            recipients.append(email_clean)
    recipients.sort()

    return jsonify({
        'date': date_str,
        'date_display': date_display,
        'subject': subject,
        'body': body,
        'recipients': recipients
    })

@app.route('/api/admin/availability-email/send', methods=['POST'])
@admin_required
def admin_send_availability_email():
    """Send the (possibly edited) availability email to the recipient list"""
    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or '').strip()
    recipients = data.get('recipients') or []
    date = (data.get('date') or '').strip()

    if not subject or not body:
        return jsonify({'error': 'Subject and message are both required'}), 400

    # Require a valid date and enforce one blast per Friday
    try:
        booking_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid or missing date'}), 400
    date_str = booking_date.isoformat()

    existing = get_blast_sent_status(date_str)
    if existing:
        when = existing.get('sent_at_display', 'earlier')
        return jsonify({
            'error': f'An availability email for this Friday has already been sent ({when}). It can only be sent once per date.',
            'already_sent': True,
            'sent': existing
        }), 409

    seen = set()
    clean = []
    for r in recipients:
        r = (r or '').strip().lower()
        if not r:
            continue
        if '@' not in r or '.' not in r.split('@')[1]:
            return jsonify({'error': f'Invalid email address: {r}'}), 400
        if r not in seen:
            seen.add(r)
            clean.append(r)

    if not clean:
        return jsonify({'error': 'At least one recipient is required'}), 400

    success, error = send_bulk_email(clean, subject, body)
    if not success:
        return jsonify({'error': f'Failed to send email: {error}'}), 502

    # Record that the blast has gone out so it can't be sent again
    sent_at = datetime.now()
    set_setting(blast_sent_key(date_str), json.dumps({
        'sent_at': sent_at.isoformat(),
        'sent_at_display': sent_at.strftime('%d %b %Y at %H:%M').lstrip('0'),
        'count': len(clean)
    }))

    return jsonify({'success': True, 'sent_to': len(clean)})

@app.route('/api/admin/yoga-email/send', methods=['POST'])
@app.route('/api/admin/notify-email/send', methods=['POST'])
@admin_required
def admin_send_yoga_email():
    """Email a list of people directly (yoga attendees, or everyone booked on
    a given Friday) — reminders, timing changes, etc. Unlike the availability
    blast this has no once-per-date lock, since admins may need to contact
    people more than once."""
    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or '').strip()
    recipients = data.get('recipients') or []

    if not subject or not body:
        return jsonify({'error': 'Subject and message are both required'}), 400

    seen = set()
    clean = []
    for r in recipients:
        r = (r or '').strip().lower()
        if not r:
            continue
        if '@' not in r or '.' not in r.split('@')[1]:
            return jsonify({'error': f'Invalid email address: {r}'}), 400
        if r not in seen:
            seen.add(r)
            clean.append(r)

    if not clean:
        return jsonify({'error': 'At least one recipient is required'}), 400

    success, error = send_bulk_email(clean, subject, body)
    if not success:
        return jsonify({'error': f'Failed to send email: {error}'}), 502

    return jsonify({'success': True, 'sent_to': len(clean)})

@app.route('/api/admin/room-times')
@admin_required
def admin_get_room_times():
    """List upcoming Fridays with each scheduled room's current hours, so the
    admin can adjust them. Times are 24h 'HH:MM' for <input type=time>."""
    overrides = get_room_time_overrides()
    schedule = get_room_schedule_ids()
    rooms_by_id = {r.id: r for r in Room.query.all()}
    default_start = f"{START_HOUR:02d}:{START_MINUTE:02d}"
    default_end = f"{END_HOUR:02d}:{END_MINUTE:02d}"

    dates = []
    for f in get_upcoming_fridays(count=8):
        ds = f['date']
        room_ids = schedule.get(ds, [])
        rooms = []
        for rid in room_ids:
            room = rooms_by_id.get(rid)
            if not room or not room.is_active:
                continue
            ov = overrides.get(ds, {}).get(str(rid))
            start, end, source = get_effective_room_hours(ds, room)
            rooms.append({
                'room_id': rid,
                'name': room.name,
                'room_type': room.room_type,
                'start': start,
                'end': end,
                'is_override': bool(ov),
                'source': source,  # 'override' | 'room' | 'global'
                'note': get_room_note(ds, rid),
            })
        if rooms:
            dates.append({'date': ds, 'display': f['display'], 'rooms': rooms})

    # Every active room's default hours, for the "usual hours" editor
    room_defaults = [{
        'room_id': r.id,
        'name': r.name,
        'room_type': r.room_type,
        'start': r.default_start or default_start,
        'end': r.default_end or default_end,
        'is_custom': bool(r.default_start and r.default_end),
    } for r in Room.query.filter_by(is_active=True).order_by(Room.id).all()]

    return jsonify({
        'dates': dates,
        'room_defaults': room_defaults,
        'default_start': default_start,
        'default_end': default_end,
        'grid_note': 'Slot rooms (e.g. Rose) snap to the nearest 30 minutes.',
    })

def _validate_hhmm_window(start, end):
    """Shared validation for custom hours. Returns (error_json, code) or None."""
    try:
        t_start = datetime.strptime(start, '%H:%M')
        t_end = datetime.strptime(end, '%H:%M')
    except ValueError:
        return jsonify({'error': 'Please enter valid start and end times'}), 400
    if t_start >= t_end:
        return jsonify({'error': 'The start time must be before the end time'}), 400
    day_start = datetime.strptime(f"{START_HOUR:02d}:{START_MINUTE:02d}", '%H:%M')
    day_end = datetime.strptime(f"{END_HOUR:02d}:{END_MINUTE:02d}", '%H:%M')
    if t_start < day_start or t_end > day_end:
        return jsonify({'error': f'Times must be between {fmt_hhmm(day_start.strftime("%H:%M"))} and {fmt_hhmm(day_end.strftime("%H:%M"))}.'}), 400
    return None

@app.route('/api/admin/room-notes', methods=['POST'])
@admin_required
def admin_set_room_note():
    """Save or clear a note for one room on one Friday. People see it on the
    room card and in the booking summary before they confirm, and it's
    repeated in their confirmation email.
    Body: {date, room_id, note}. An empty note clears it."""
    data = request.get_json(silent=True) or {}
    date_str = (data.get('date') or '').strip()
    room_id = data.get('room_id')

    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Invalid date'}), 400

    schedule = get_room_schedule_ids()
    if date_str not in schedule or room_id not in schedule[date_str]:
        return jsonify({'error': 'That room is not scheduled on that date'}), 400

    note = (data.get('note') or '').strip()[:ROOM_NOTE_MAX]
    notes = get_room_notes()

    if note:
        notes.setdefault(date_str, {})[str(room_id)] = note
    else:
        if date_str in notes and str(room_id) in notes[date_str]:
            del notes[date_str][str(room_id)]
            if not notes[date_str]:
                del notes[date_str]

    set_setting(ROOM_NOTES_KEY, json.dumps(notes))
    return jsonify({'success': True, 'note': note, 'cleared': not note})

@app.route('/api/admin/room-default-times', methods=['POST'])
@admin_required
def admin_set_room_default_times():
    """Set or clear a room's usual (default) hours, applying to every date
    that has no per-date change.
    Body: {room_id, start, end} to set; {room_id, clear:true} to reset."""
    data = request.get_json(silent=True) or {}
    room = db.session.get(Room, data.get('room_id') or 0)
    if not room or not room.is_active:
        return jsonify({'error': 'Room not found'}), 404

    if data.get('clear'):
        room.default_start = None
        room.default_end = None
        db.session.commit()
        return jsonify({'success': True, 'cleared': True})

    start = (data.get('start') or '').strip()
    end = (data.get('end') or '').strip()
    err = _validate_hhmm_window(start, end)
    if err:
        return err

    room.default_start = start
    room.default_end = end
    db.session.commit()
    return jsonify({
        'success': True,
        'start_display': fmt_hhmm(start),
        'end_display': fmt_hhmm(end),
    })

@app.route('/api/admin/room-times', methods=['POST'])
@admin_required
def admin_set_room_time():
    """Set or clear a room's custom hours for a single Friday.
    Body: {date, room_id, start, end} to set; {date, room_id, clear:true} to reset."""
    data = request.get_json(silent=True) or {}
    date_str = (data.get('date') or '').strip()
    room_id = data.get('room_id')

    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Invalid date'}), 400

    schedule = get_room_schedule_ids()
    if date_str not in schedule or room_id not in schedule[date_str]:
        return jsonify({'error': 'That room is not scheduled on that date'}), 400

    overrides = get_room_time_overrides()

    if data.get('clear'):
        if date_str in overrides and str(room_id) in overrides[date_str]:
            del overrides[date_str][str(room_id)]
            if not overrides[date_str]:
                del overrides[date_str]
        set_setting(ROOM_TIME_OVERRIDES_KEY, json.dumps(overrides))
        return jsonify({'success': True, 'cleared': True})

    start = (data.get('start') or '').strip()
    end = (data.get('end') or '').strip()
    err = _validate_hhmm_window(start, end)
    if err:
        return err

    overrides.setdefault(date_str, {})[str(room_id)] = {'start': start, 'end': end}
    set_setting(ROOM_TIME_OVERRIDES_KEY, json.dumps(overrides))
    return jsonify({
        'success': True,
        'start_display': fmt_hhmm(start),
        'end_display': fmt_hhmm(end),
    })

@app.route('/api/admin/bookings-email/recipients/<date>')
@admin_required
def admin_bookings_email_recipients(date):
    """Unique emails of everyone with a live booking on a given Friday."""
    try:
        booking_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date'}), 400
    seen = set()
    recipients = []
    rows = Booking.query.filter(
        Booking.booking_date == booking_date,
        Booking.cancelled_at.is_(None)
    ).all()
    for b in rows:
        email = (b.user_email or '').strip().lower()
        if email and email not in seen:
            seen.add(email)
            recipients.append(email)
    recipients.sort()
    return jsonify({
        'date': booking_date.isoformat(),
        'date_display': booking_date.strftime('%A, %B %d, %Y'),
        'recipients': recipients,
    })

@app.route('/api/open-booking-counts')
def get_open_booking_counts():
    """Get booking counts for open booking rooms only (public endpoint)"""
    from sqlalchemy import func
    
    # Get all rooms that are "open" type
    open_rooms = Room.query.filter_by(room_type='open', is_active=True).all()
    open_room_ids = [r.id for r in open_rooms]
    
    # Get counts per date for open rooms
    counts = db.session.query(
        Booking.booking_date,
        func.count(Booking.id).label('count')
    ).filter(
        Booking.room_id.in_(open_room_ids),
        Booking.cancelled_at.is_(None),
        Booking.booking_date >= datetime.now().date()
    ).group_by(Booking.booking_date).order_by(Booking.booking_date).all()
    
    result = []
    for row in counts:
        result.append({
            'date': row.booking_date.isoformat(),
            'date_display': row.booking_date.strftime('%A, %B %d, %Y'),
            'count': row.count
        })
    
    return jsonify(result)

@app.route('/api/admin/bookings/<int:booking_id>', methods=['DELETE'])
@admin_required
def admin_delete_booking(booking_id):
    """Delete a booking and notify the user"""
    booking = Booking.query.get_or_404(booking_id)
    
    if booking.cancelled_at:
        return jsonify({'error': 'This booking has already been cancelled'}), 410
    
    # Get booking details before deleting
    room_name = booking.room.name
    user_name = booking.user_name
    user_email = booking.user_email
    booking_date = booking.booking_date
    start_time, end_time = booking_time_display(booking)
    date_display = booking_date.strftime('%A, %B %d, %Y')
    
    # Delete the booking
    db.session.delete(booking)
    db.session.commit()
    
    # Send cancellation email to user
    deletion_message = f"""Dear {user_name},

We are writing to inform you that your room booking has been cancelled by the LAGC Fridays @ Smithson staff team.

Cancelled Booking Details:
- Room: {room_name}
- Date: {date_display}
- Time: {start_time} - {end_time}

If you have any questions or queries about this cancellation, please contact us at:
londonautismgroupcharity@gmail.com

Thank you for your understanding.

Best regards,
London Autism Group Charity - Fridays @ The Smithson Team
"""
    
    send_confirmation_email(
        user_email,
        f"Booking Cancelled: {room_name} on {date_display}",
        deletion_message
    )
    
    return jsonify({
        'success': True,
        'message': 'Booking deleted and user notified'
    })

# ============================================================================
# INITIALIZATION
# ============================================================================

def _column_exists(table, column):
    rows = db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)

def _ensure_column(table, column, definition, attempts=3):
    """Add a required SQLite column safely during a WSGI reload.

    A migration must not be silently skipped: once SQLAlchemy maps a new
    column, every normal model query selects it. Serving requests with the old
    schema therefore turns an otherwise recoverable lock/race into repeated
    HTTP 500 responses. Retry transient locks, tolerate another worker winning
    the ALTER TABLE race, and fail startup if the column is still unavailable.
    """
    if _column_exists(table, column):
        return

    for attempt in range(attempts):
        try:
            db.session.execute(db.text(
                f'ALTER TABLE {table} ADD COLUMN {column} {definition}'
            ))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()

            # Another WSGI worker may have added the column after our initial
            # check but before our ALTER TABLE reached SQLite.
            if _column_exists(table, column):
                return

            is_locked = 'locked' in str(exc).lower() or 'busy' in str(exc).lower()
            if is_locked and attempt < attempts - 1:
                time.sleep(0.25 * (attempt + 1))
                continue
            raise RuntimeError(
                f'Could not add required column {table}.{column}'
            ) from exc

        if _column_exists(table, column):
            return

    raise RuntimeError(f'Required column {table}.{column} is unavailable')

def run_migrations():
    """Lightweight migrations for columns added to existing tables (create_all
    only creates missing tables, it can't add new columns to an existing one)."""
    _ensure_column('yoga_booking', 'cancel_token', 'VARCHAR(64)')
    _ensure_column(
        'volunteer_availability', 'unavailable', 'BOOLEAN DEFAULT 0'
    )

    # Attendance tracking for capacity-limited spaces (Rose + yoga)
    for table in ('booking', 'yoga_booking'):
        _ensure_column(table, 'attended', 'BOOLEAN')

    # Per-room default hours (Room Times tab: "set once, applies every week")
    _ensure_column('room', 'default_start', 'VARCHAR(5)')
    _ensure_column('room', 'default_end', 'VARCHAR(5)')

    # One-time: the time grid was re-based from 11:00 (old slot 0) to 09:30
    # (new slot 0), adding 3 earlier half-hour slots. Shift every existing
    # booking's slot indices by +3 so their real times are unchanged. Guarded
    # by a Setting flag so it only ever runs once.
    try:
        if get_setting('slot_base_0930_migrated') != 'yes':
            db.session.execute(db.text(
                'UPDATE booking SET start_slot = start_slot + 3, end_slot = end_slot + 3'))
            set_setting('slot_base_0930_migrated', 'yes')
            db.session.commit()
    except Exception as e:  # pragma: no cover - defensive, never block startup
        db.session.rollback()
        print(f"[migration] slot base 09:30 reindex: {e}")

# Ensure all tables exist on every startup — including under WSGI on
# PythonAnywhere, where the __main__ block below does NOT run. create_all()
# only creates missing tables, so it never touches existing data. This is what
# makes new tables (e.g. VolunteerAvailability) appear after a plain git pull +
# Reload, with no manual migration. run_migrations() then patches in any new
# columns on tables that already existed.

# Set when startup schema setup did not complete (e.g. SQLite was locked by an
# in-flight request during a reload). We retry on the next request instead of
# letting the failure escape: raising here happens at import time, so it takes
# the WHOLE site down — every page, including ones that never touch the new
# column — until someone reloads the web app by hand. A transient lock must not
# be able to do that.
_schema_ready = False

def ensure_schema(context='startup'):
    """Create tables and apply column migrations. Returns True when the schema
    is up to date. Never raises — callers keep serving either way."""
    global _schema_ready
    if _schema_ready:
        return True
    try:
        with app.app_context():
            if context != 'startup':
                # Drop pooled connections before retrying: a connection opened
                # while the file was unwritable stays unwritable, so reusing it
                # would keep failing even after the problem is resolved.
                db.engine.dispose()
            db.create_all()
            run_migrations()
        _schema_ready = True
        return True
    except Exception as e:
        print(f"[schema] {context}: database setup incomplete: {e}")
        print("[schema] will retry on the next request; "
              "pages using the affected tables may error until then")
        return False

ensure_schema('startup')

@app.before_request
def _retry_schema_setup():
    """Self-heal after a transient failure (e.g. the DB was briefly locked
    while the app reloaded) without needing a manual reload."""
    if not _schema_ready:
        ensure_schema('retry')

if __name__ == '__main__':
    with app.app_context():
        init_default_data()
    app.run(debug=True, host='0.0.0.0', port=5001)
