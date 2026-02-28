"""
Simple Room Booking System
Handles 30-minute booking slots on Fridays from 11am to 5:30pm
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

# Email configuration (configure these for your SMTP server)
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', 587))
app.config['SMTP_USER'] = os.environ.get('SMTP_USER', '')
app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '')
app.config['SMTP_FROM'] = os.environ.get('SMTP_FROM', 'bookings@example.com')
app.config['ENABLE_EMAIL'] = os.environ.get('ENABLE_EMAIL', 'false').lower() == 'true'

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
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Booking(db.Model):
    """Room bookings"""
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_name = db.Column(db.String(100), nullable=False)
    user_email = db.Column(db.String(120), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)  # The Friday being booked
    start_slot = db.Column(db.Integer, nullable=False)  # 0-12 (11:00-17:30 in 30min slots)
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

# Friday time slots: 11:00 - 17:30 (30 min intervals)
# Slot 0 = 11:00, Slot 1 = 11:30, ..., Slot 12 = 17:00, Slot 13 = 17:30 (end)
START_HOUR = 11  # 11 AM
END_HOUR = 17    # 5 PM + 30 min = 17:30
SLOT_MINUTES = 30
MAX_SLOTS = 6    # 3 hours = 6 x 30 min slots

def get_time_slots():
    """Generate all available time slots"""
    slots = []
    current = datetime.strptime(f"{START_HOUR}:00", "%H:%M")
    end = datetime.strptime(f"{END_HOUR}:30", "%H:%M")
    
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
    # Create default rooms if none exist
    if Room.query.count() == 0:
        default_rooms = [
            Room(name='Conference Room A', building_location='Main Building, Floor 2'),
            Room(name='Meeting Room B', building_location='Main Building, Floor 2'),
            Room(name='Discussion Room C', building_location='Annex Building, Floor 1')
        ]
        db.session.add_all(default_rooms)
    
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
        # Clean the password (remove any spaces that might have been copied)
        smtp_password = app.config['SMTP_PASSWORD'].replace(' ', '').replace('-', '')
        
        print(f"[DEBUG] Attempting to send email via {app.config['SMTP_HOST']}:{app.config['SMTP_PORT']}")
        print(f"[DEBUG] Login user: {app.config['SMTP_USER']}")
        print(f"[DEBUG] From address: {app.config['SMTP_FROM']}")
        print(f"[DEBUG] To address: {to_email}")
        
        msg = MIMEMultipart()
        msg['From'] = app.config['SMTP_FROM']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        
        with smtplib.SMTP(app.config['SMTP_HOST'], app.config['SMTP_PORT']) as server:
            server.set_debuglevel(1)  # Enable debug output
            server.starttls()
            print(f"[DEBUG] Logging in...")
            server.login(app.config['SMTP_USER'], smtp_password)
            print(f"[DEBUG] Login successful, sending message...")
            server.send_message(msg)
            print(f"[DEBUG] Message sent!")
        
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
        print(f"[ERROR] Type: {type(e).__name__}")
        return False

def get_upcoming_fridays(count=8):
    """Get upcoming Friday dates"""
    fridays = []
    today = datetime.now().date()
    
    # Find next Friday
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0 and datetime.now().hour >= END_HOUR:
        # If it's Friday past booking hours, start from next Friday
        days_until_friday = 7
    
    next_friday = today + timedelta(days=days_until_friday)
    
    for i in range(count):
        friday = next_friday + timedelta(weeks=i)
        fridays.append({
            'date': friday.isoformat(),
            'display': friday.strftime('%A, %B %d, %Y')
        })
    
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
        'building_location': r.building_location
    } for r in rooms])

@app.route('/api/fridays')
def get_fridays():
    """Get upcoming Fridays"""
    return jsonify(get_upcoming_fridays())

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
    required = ['room_id', 'date', 'name', 'email', 'start_slot', 'end_slot']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    room_id = data['room_id']
    name = data['name'].strip()
    email = data['email'].strip().lower()
    start_slot = data['start_slot']
    end_slot = data['end_slot']
    
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
    
    # Validate slot range
    if start_slot < 0 or end_slot > len(TIME_SLOTS) or start_slot >= end_slot:
        return jsonify({'error': 'Invalid time slot selection'}), 400
    
    # Validate consecutive slots
    num_slots = end_slot - start_slot
    if num_slots > MAX_SLOTS:
        return jsonify({'error': f'Maximum booking duration is 3 hours ({MAX_SLOTS} slots)'}), 400
    
    # Validate slots are consecutive (no gaps allowed)
    # This is automatically enforced by the range
    
    # Check availability
    if not check_availability(room_id, booking_date, start_slot, end_slot):
        return jsonify({'error': 'Selected time slots are no longer available'}), 409
    
    # Get room details
    room = Room.query.get(room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
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
    end_time = TIME_SLOTS[end_slot]['display'] if end_slot < len(TIME_SLOTS) else '17:30'
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
    end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '17:30'
    
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
        end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '17:30'
        
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
        is_active=data.get('is_active', True)
    )
    db.session.add(room)
    db.session.commit()
    
    return jsonify({
        'id': room.id,
        'name': room.name,
        'building_location': room.building_location,
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
    room.is_active = data.get('is_active', room.is_active)
    
    db.session.commit()
    
    return jsonify({
        'id': room.id,
        'name': room.name,
        'building_location': room.building_location,
        'is_active': room.is_active
    })

@app.route('/api/admin/rooms/<int:room_id>', methods=['DELETE'])
@admin_required
def admin_delete_room(room_id):
    """Delete a room (soft delete by deactivating)"""
    room = Room.query.get_or_404(room_id)
    room.is_active = False
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
        end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '17:30'
        
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
    end_time = TIME_SLOTS[booking.end_slot]['display'] if booking.end_slot < len(TIME_SLOTS) else '17:30'
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
    app.run(debug=True, host='0.0.0.0', port=5000)
