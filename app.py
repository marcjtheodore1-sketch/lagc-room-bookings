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

# Email configuration (hardcoded for PythonAnywhere deployment)
app.config['SMTP_HOST'] = 'smtp.gmail.com'
app.config['SMTP_PORT'] = 587
app.config['SMTP_USER'] = 'miles.lagc@gmail.com'
app.config['SMTP_PASSWORD'] = 'gidxqeqyvdifqzqs'
app.config['SMTP_FROM'] = 'miles.lagc@gmail.com'
app.config['ENABLE_EMAIL'] = True

# Admin password (set via environment variable or use default 'Moonlight')
app.config['ADMIN_PASSWORD'] = os.environ.get('ADMIN_PASSWORD', 'Moonlight')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Booking(db.Model):
    """Room bookings"""
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    user_email = db.Column(db.String(120), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)  # The Friday being booked
    start_slot = db.Column(db.Integer, nullable=False)  # 0-10 (11:00-16:00 in 30min slots)
    end_slot = db.Column(db.Integer, nullable=False)    # exclusive end slot
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_token = db.Column(db.String(64), unique=True)  # For cancellation link
    
    room = db.relationship('Room', backref='bookings')

class Setting(db.Model):
    """Configurable settings"""
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)

# ============================================================================
# CONSTANTS
# ============================================================================

# Friday time slots: 11:00 - 16:00 (30 min intervals)
# Slot 0 = 11:00, Slot 1 = 11:30, ..., Slot 10 = 16:00 (end)
START_HOUR = 11  # 11 AM
END_HOUR = 16    # 4 PM
SLOT_MINUTES = 30
MAX_SLOTS = 6    # 3 hours = 6 x 30 min slots

def get_time_slots():
    """Generate all available time slots"""
    slots = []
    current = datetime.strptime(f"{START_HOUR}:00", "%H:%M")
    end = datetime.strptime(f"{END_HOUR}:00", "%H:%M")
    
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
    '2026-04-24': [],  # No rooms available
    '2026-05-01': ['Room 4.2 "Indigo"', 'Room 4.4 "Rose"', 'Room 4.7 "Clerkenwell"'],
}

def get_room_schedule_ids():
    """Convert room name schedule to ID schedule based on current database"""
    schedule = {}
    
    # Build keyword to ID mapping for flexible matching
    # Keywords: "4.2" or "Indigo", "4.4" or "Rose", "4.7" or "Clerkenwell", "Loft"
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

def init_default_data():
    """Initialize default rooms and settings"""
    # Define expected rooms with their IDs matching ROOM_SCHEDULE
    expected_rooms = {
        1: {'name': 'Room 4.2 "Indigo"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
        2: {'name': 'Room 4.4 "Rose"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'slot'},
        3: {'name': 'Room 4.7 "Clerkenwell"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
        4: {'name': 'The Loft', 'building_location': 'Floor 6 - Pan Macmillan HQ', 'room_type': 'open'},
    }
    
    # Create rooms if they don't exist, or update existing ones to match
    for room_id, room_data in expected_rooms.items():
        room = Room.query.get(room_id)
        if not room:
            room = Room(
                id=room_id,
                name=room_data['name'],
                building_location=room_data['building_location'],
                room_type=room_data['room_type'],
                is_active=True
            )
            db.session.add(room)
    
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
            with smtplib.SMTP_SSL(app.config['SMTP_HOST'], 465) as server:
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
            with smtplib.SMTP(app.config['SMTP_HOST'], 587) as server:
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

# ============================================================================
# ROUTES - MAIN PAGES
# ============================================================================

@app.route('/')
def landing():
    """Landing page with information about the initiative"""
    return render_template('landing.html')

@app.route('/peer-support')
def peer_support():
    """Peer support sessions information page"""
    return render_template('peer_support.html')

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
    """Get all active rooms"""
    rooms = Room.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': r.id,
        'name': r.name,
        'building_location': r.building_location,
        'room_type': r.room_type
    } for r in rooms])

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
    
    # Determine slots based on room type
    if room.room_type == 'open':
        # Open rooms: book the entire day (11am - 4pm)
        start_slot = 0
        end_slot = len(TIME_SLOTS)  # Exclusive end (covers all slots 0-10)
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
    start_time = TIME_SLOTS[start_slot]['display']
    
    # Special cases for Room 4.2 "Indigo" on specific dates
    is_march_20th = booking_date.isoformat() == '2026-03-20'
    is_room_4_2 = '4.2' in room.name or 'indigo' in room.name.lower()
    if is_march_20th and is_room_4_2:
        end_time = '2:30 PM'
    else:
        end_time = TIME_SLOTS[end_slot]['display'] if end_slot < len(TIME_SLOTS) else '16:00'
    
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
    
    # Send confirmation email
    email_sent = send_confirmation_email(
        email,
        f"Booking Confirmed: {room.name} on {date_display}",
        confirmation_message
    )
    
    # Send admin notification email
    admin_emails = ['londonautismgroupcharity@gmail.com', 'zara.lagc@gmail.com']
    admin_subject = f"New Booking: {name} booked {room.name}"
    admin_message = f"""A new booking has been made:

Name: {name}
Email: {email}
Room: {room.name}
Date: {date_display}
Time: {start_time} - {end_time}

View all bookings at: {request.host_url.rstrip('/')}/admin
"""
    
    for admin_email in admin_emails:
        send_confirmation_email(admin_email, admin_subject, admin_message)
    
    return jsonify({
        'success': True,
        'booking_id': booking.id,
        'confirmation_message': confirmation_message,
        'cancel_token': cancel_token,
        'email_sent': email_sent
    })

@app.route('/api/booking/<token>')
def get_booking(token):
    """Get booking details by cancel token"""
    booking = Booking.query.filter_by(cancel_token=token).first()
    
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    
    if booking.cancelled_at:
        return jsonify({'error': 'This booking has already been cancelled'}), 410
    
    start_time = TIME_SLOTS[booking.start_slot]['display']
    end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '16:00'
    
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
    
    booking.cancelled_at = datetime.utcnow()
    db.session.commit()
    
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
        start_time = TIME_SLOTS[booking.start_slot]['display']
        end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '16:00'
        
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
        start_time = TIME_SLOTS[booking.start_slot]['display']
        end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '16:00'
        
        result.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'user_name': booking.user_name,
            'user_email': booking.user_email,
            'date': booking.booking_date.isoformat(),
            'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
            'start_time': start_time,
            'end_time': end_time
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
        start_time = TIME_SLOTS[booking.start_slot]['display']
        end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '16:00'
        
        result.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'user_name': booking.user_name,
            'user_email': booking.user_email,
            'date': booking.booking_date.isoformat(),
            'date_display': booking.booking_date.strftime('%A, %B %d, %Y'),
            'start_time': start_time,
            'end_time': end_time
        })
    
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
    start_time = TIME_SLOTS[booking.start_slot]['display']
    end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '16:00'
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_default_data()
    app.run(debug=True, host='0.0.0.0', port=5001)
