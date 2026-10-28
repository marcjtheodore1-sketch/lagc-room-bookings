"""Student appointments with their own private, shared-password supporter access.

No student record is a room Booking. Only confirmed in-person names are exposed
through reception_names(); answers never enter general admin exports or email.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from functools import wraps
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import abort, g, make_response, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

LONDON = ZoneInfo('Europe/London')
SUPPORTERS = {
    'sungji': {'name': 'Sungji', 'email': 'sungji.lagc@gmail.com'},
    'marilena': {'name': 'Marilena', 'email': 'marilena.eleftheriou@yahoo.com'},
}
COOKIE = 'student_support_session'

def shared_identity():
    return 'shared-' + digest(_app.config.get('STUDENT_SUPPORT_PASSWORD_HASH', ''))[:12]



def now_london():
    return datetime.now(LONDON)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def valid_email(value):
    return len(value) <= 254 and bool(re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value))


def valid_meeting_url(value):
    if not value:
        return True
    try:
        parsed = urlsplit(value)
        return (len(value) <= 1000 and parsed.scheme == 'https' and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not any(c.isspace() for c in value))
    except ValueError:
        return False


def csrf_token():
    """Independent server-side CSRF state, surviving existing app-key changes.

    The existing F@F app can generate a new Flask secret at worker startup. This
    portal deliberately does not depend on that shared administrator session.
    """
    token = request.cookies.get(csrf_cookie_name(), '')
    row = StudentAccess.query.filter_by(token_hash=digest(token), kind='csrf').first() if token else None
    if row and row.expires_at > datetime.utcnow():
        return token
    if not getattr(g, 'student_new_csrf', None):
        g.student_new_csrf = secrets.token_urlsafe(32)
        _db.session.add(StudentAccess(token_hash=digest(g.student_new_csrf), kind='csrf',
            ip_hash='', expires_at=datetime.utcnow() + timedelta(hours=8)))
        _db.session.commit()
    return g.student_new_csrf


def csrf_cookie_name():
    return '__Host-student_support_csrf' if _app.config['STUDENT_COOKIE_SECURE'] else 'student_support_csrf'


def check_csrf():
    expected = request.cookies.get(csrf_cookie_name(), '')
    received = request.form.get('csrf_token', '')
    if not expected or not secrets.compare_digest(expected, received):
        abort(400, 'This form has expired. Reload the page and try again.')
    row = StudentAccess.query.filter_by(token_hash=digest(expected), kind='csrf').first()
    if not row or row.expires_at <= datetime.utcnow():
        abort(400, 'This form has expired. Reload the page and try again.')


def display_time(value):
    hour, minute = map(int, value.split(':'))
    return f'{hour % 12 or 12}' + (f'.{minute:02d}' if minute else '') + ('am' if hour < 12 else 'pm')


def slot_start(slot):
    return datetime.combine(slot.day, datetime.strptime(slot.start_time, '%H:%M').time(), tzinfo=LONDON)


def slot_label(slot):
    from app import reminder_date_display
    end = slot_start(slot) + timedelta(minutes=45)
    return f'{reminder_date_display(slot.day)} {slot.day.year}, {display_time(slot.start_time)} to {display_time(end.strftime("%H:%M"))} (London time), with {SUPPORTERS[slot.supporter]["name"]}'


def in_person_open(slot):
    from app import booking_deadline, get_room_schedule_ids
    return (slot.in_person and slot.supporter == 'sungji' and slot.day.weekday() == 4
            and bool(get_room_schedule_ids().get(slot.day.isoformat()))
            and now_london() < booking_deadline(slot.day))


def release_expired():
    StudentBooking.query.filter(StudentBooking.status == 'pending',
        StudentBooking.expires_at <= datetime.utcnow()).update(
            {'status': 'expired', 'active_slot_id': None}, synchronize_session=False)
    _db.session.commit()


def maintain_student_records():
    """Run from the existing hourly job as well as portal/booking visits."""
    days = _app.config.get('STUDENT_ANSWER_RETENTION_DAYS')
    if days:
        cutoff = now_london().date() - timedelta(days=days)
        old_slots = _db.select(StudentSlot.id).where(StudentSlot.day <= cutoff)
        StudentBooking.query.filter(StudentBooking.slot_id.in_(old_slots),
            StudentBooking.answers_deleted_at.is_(None)).update(
                {'studying': '', 'goals': '', 'questions': '', 'answers_deleted_at': datetime.utcnow()},
                synchronize_session=False)
    StudentAccess.query.filter(StudentAccess.expires_at < datetime.utcnow() - timedelta(days=1)).delete(synchronize_session=False)
    _db.session.commit()


def deliver(recipient, subject, body):
    from app import reminders_mail_ready, is_blocked_email_recipient, send_smtp_message
    if not reminders_mail_ready() or is_blocked_email_recipient(recipient):
        raise RuntimeError('Email is unavailable')
    message = MIMEText(body, 'plain', 'utf-8')
    message['From'] = _app.config['SMTP_FROM']
    message['To'] = recipient
    message['Subject'] = subject
    send_smtp_message(message, recipients=[recipient])


def notify(booking, event, student_token=None):
    """Claim each recipient once before SMTP, including uncertain outcomes.

    An interrupted/failed notification is visible to supporters and is never
    automatically repeated. Questionnaire answers are deliberately omitted.
    """
    from app import reminder_base_url, EmailDeliveryUncertain
    supporter = SUPPORTERS[booking.slot.supporter]
    for audience, recipient in [('student', booking.email), ('supporter', supporter['email'])]:
        key = f'{booking.id}:{event}:{audience}'
        row = StudentMail(key=key, booking_id=booking.id, status='sending')
        _db.session.add(row)
        try:
            _db.session.commit()
        except IntegrityError:
            _db.session.rollback()
            continue
        body = f'Your student support appointment has been {event}.\n\n' if audience == 'student' else f'A student support appointment has been {event}.\n\n'
        body += slot_label(booking.slot) + '\n' + ('Online' if booking.location == 'online' else 'In person at Pan Macmillan, 6 Briset Street, London EC1M 5NR')
        if booking.location == 'in_person':
            body += '\nThe room will be Rose Room 4.4 or a semi-open green booth on the fourth floor, depending on availability. A private room cannot be guaranteed.'
        elif event == 'confirmed':
            body += ('\nJoin online: ' + booking.slot.meeting_url) if booking.slot.meeting_url else '\nYour supporter will email you the online joining details before your session.'
        if audience == 'student' and student_token and event == 'confirmed':
            body += '\n\nView or cancel your appointment: ' + reminder_base_url() + '/peer-support/appointment/' + student_token
        if audience == 'supporter':
            body += '\n\nSign in to view the booking: ' + reminder_base_url() + '/peer-support/supporter'
        body += '\n\nSessions last 45 minutes within a one-hour slot. Private booking-form answers are available only in the admin portal.\n\nLondon Autism Group Charity'
        try:
            deliver(recipient, 'Student support appointment ' + event, body)
            row.status = 'sent'
        except Exception as error:
            row.status = 'uncertain' if isinstance(error, EmailDeliveryUncertain) else 'failed'
            _app.logger.warning('Student support notification %s: %s', row.id, row.status)
        _db.session.commit()


def reception_names(day):
    """Explicit minimal interface to the general reception report."""
    bookings = StudentBooking.query.join(StudentSlot, StudentBooking.slot_id == StudentSlot.id).filter(
        StudentSlot.day == day, StudentBooking.status == 'confirmed',
        StudentBooking.location == 'in_person').all()
    return [b.name for b in bookings], ['Sungji'] if bookings else []


def reception_mobility(day):
    """An aggregate Yes/No only, matching the existing venue report."""
    return StudentBooking.query.join(StudentSlot, StudentBooking.slot_id == StudentSlot.id).filter(
        StudentSlot.day == day, StudentBooking.status == 'confirmed',
        StudentBooking.location == 'in_person', StudentBooking.mobility_needs.is_(True)).first() is not None


def register_student_support(app, db):
    global _app, _db, StudentSlot, StudentBooking, StudentAccess, StudentMail
    _app, _db = app, db
    app.config.setdefault('STUDENT_COOKIE_SECURE', True)
    app.config.setdefault('STUDENT_ANSWER_RETENTION_DAYS', None)
    app.config.setdefault('STUDENT_SUPPORT_PASSWORD_HASH', os.environ.get('STUDENT_SUPPORT_PASSWORD_HASH', ''))

    class StudentSlot(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        supporter = db.Column(db.String(20), nullable=False)
        day = db.Column(db.Date, nullable=False, index=True)
        start_time = db.Column(db.String(5), nullable=False)
        in_person = db.Column(db.Boolean, nullable=False, default=False)
        published = db.Column(db.Boolean, nullable=False, default=False)
        meeting_url = db.Column(db.String(1000), nullable=False, default='')
        __table_args__ = (db.UniqueConstraint('supporter', 'day', 'start_time'),)

    class StudentBooking(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        slot_id = db.Column(db.Integer, db.ForeignKey('student_slot.id'), nullable=False)
        # Unique for both confirmed bookings and unexpired verification holds.
        active_slot_id = db.Column(db.Integer, unique=True, nullable=True)
        name = db.Column(db.String(100), nullable=False)
        email = db.Column(db.String(254), nullable=False, index=True)
        location = db.Column(db.String(20), nullable=False)
        mobility_needs = db.Column(db.Boolean, nullable=False, default=False)
        studying = db.Column(db.Text, nullable=False)
        goals = db.Column(db.Text, nullable=False)
        questions = db.Column(db.Text, nullable=False, default='')
        answers_deleted_at = db.Column(db.DateTime, nullable=True)
        status = db.Column(db.String(20), nullable=False, default='pending')
        confirm_hash = db.Column(db.String(64), unique=True, nullable=True)
        manage_hash = db.Column(db.String(64), unique=True, nullable=False)
        ip_hash = db.Column(db.String(64), nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        slot = db.relationship(StudentSlot, foreign_keys=[slot_id])

    class StudentAccess(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        token_hash = db.Column(db.String(64), nullable=False, unique=True)
        supporter = db.Column(db.String(20), nullable=True)
        kind = db.Column(db.String(20), nullable=False)
        ip_hash = db.Column(db.String(64), nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        expires_at = db.Column(db.DateTime, nullable=False)

    class StudentMail(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        key = db.Column(db.String(100), unique=True, nullable=False)
        booking_id = db.Column(db.Integer, db.ForeignKey('student_booking.id'), nullable=False)
        status = db.Column(db.String(20), nullable=False)

    def page(template, **context):
        return render_template(template, csrf_token=csrf_token(), supporters=SUPPORTERS,
            slot_label=slot_label, display_time=display_time,
            answer_retention_days=app.config['STUDENT_ANSWER_RETENTION_DAYS'],
            password_ready=bool(app.config['STUDENT_SUPPORT_PASSWORD_HASH']), **context)

    def ip_hash():
        return digest(app.config['STUDENT_SUPPORT_PASSWORD_HASH'] + ':' + (request.remote_addr or ''))

    def private_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = request.cookies.get(COOKIE, '')
            access = StudentAccess.query.filter_by(token_hash=digest(token), kind='session').first() if token else None
            if (not app.config['STUDENT_SUPPORT_PASSWORD_HASH'] or not access
                    or access.expires_at <= datetime.utcnow() or access.supporter != shared_identity()):
                return redirect(url_for('student_login'))
            g.student_supporter = access.supporter
            g.student_access = access
            if request.method == 'POST':
                check_csrf()
            return view(*args, **kwargs)
        return wrapped

    @app.after_request
    def student_private_headers(response):
        if request.path.startswith('/peer-support/'):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
            if getattr(g, 'student_new_csrf', None):
                response.set_cookie(csrf_cookie_name(), g.student_new_csrf, max_age=8 * 3600,
                    secure=app.config['STUDENT_COOKIE_SECURE'], httponly=True, samesite='Strict', path='/')
        return response

    def booking_page(**context):
        release_expired()
        maintain_student_records()
        occupied = db.select(StudentBooking.active_slot_id).where(StudentBooking.active_slot_id.isnot(None))
        slots = StudentSlot.query.filter(StudentSlot.published.is_(True),
            StudentSlot.day >= now_london().date(), ~StudentSlot.id.in_(occupied)).order_by(StudentSlot.day, StudentSlot.start_time).all()
        slots = [s for s in slots if slot_start(s) > now_london()]
        return page('student_book.html', slots=slots, in_person_open=in_person_open,
            selected_slot=request.form.get('slot_id', ''),
            selected_location=request.form.get('location', 'online'),
            selected_mobility=request.form.get('mobility_needs', ''), **context)

    @app.route('/peer-support/book', methods=['GET', 'POST'])
    def student_book():
        if request.method == 'GET':
            return booking_page()
        check_csrf()
        from app import reminders_mail_ready, reminder_base_url, is_blocked_email_recipient
        values = {k: request.form.get(k, '').strip() for k in ('name', 'email', 'location', 'studying', 'goals', 'questions')}
        values['email'] = values['email'].lower()
        if (not values['name'] or len(values['name']) > 100 or not valid_email(values['email'])
                or not values['studying'] or not values['goals']
                or any(len(values[k]) > 3000 for k in ('studying', 'goals', 'questions'))
                or request.form.get('privacy') != 'yes'):
            return booking_page(error='Add your name, a valid email, what you study and your session goals. Each answer can be up to 3,000 characters. Read and accept the privacy information.', values=values), 400
        if values['location'] not in ('online', 'in_person'):
            abort(400)
        if values['location'] == 'in_person' and len(values['name'].split()) < 2:
            return booking_page(error='For reception, enter your full name for an in-person appointment.', values=values), 400
        if values['location'] == 'in_person' and request.form.get('mobility_needs') not in ('yes', 'no'):
            return booking_page(error='For an in-person session, answer the mobility question so the venue can plan safe access.', values=values), 400
        values['mobility_needs'] = values['location'] == 'in_person' and request.form.get('mobility_needs') == 'yes'
        slot = db.session.get(StudentSlot, request.form.get('slot_id', type=int))
        if not slot or not slot.published or slot_start(slot) <= now_london():
            return booking_page(error='That appointment is unavailable. Choose another time.', values=values), 409
        if values['location'] == 'in_person' and not in_person_open(slot):
            return booking_page(error='In-person booking closes on Thursday at 10am London time. Choose online or another appointment.', values=values), 409
        now = datetime.utcnow()
        release_expired()
        recent = StudentBooking.query.filter(StudentBooking.created_at > now - timedelta(hours=1),
            (StudentBooking.ip_hash == ip_hash()) | (StudentBooking.email == values['email'])).count()
        if recent >= 6:
            return booking_page(error='Too many booking requests. Try again in an hour.', values=values), 429
        if not reminders_mail_ready() or is_blocked_email_recipient(values['email']):
            return booking_page(error='Booking emails are temporarily unavailable for this address. Try again later.', values=values), 503
        confirm_token, manage_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        booking = StudentBooking(**values, slot_id=slot.id, active_slot_id=slot.id,
            confirm_hash=digest(confirm_token), manage_hash=digest(manage_token), ip_hash=ip_hash(),
            expires_at=now + timedelta(minutes=20))
        db.session.add(booking)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return booking_page(error='Someone has just reserved that appointment. Choose another time.', values=values), 409
        # Separate confirmation and management tokens. The management credential
        # is issued to the student only after their email is verified.
        body = ('Confirm your student support appointment within 20 minutes:\n\n' + slot_label(slot)
            + '\n\n' + reminder_base_url() + '/peer-support/confirm/' + confirm_token
            + '\n\nYour place is reserved temporarily. It is not booked until you confirm. If you did not request this, ignore this message.\n\nLondon Autism Group Charity')
        try:
            deliver(booking.email, 'Confirm your student support appointment', body)
        except Exception:
            # Keep the hold until expiry if SMTP may have accepted the message.
            app.logger.warning('Student verification email could not be verified for request %s', booking.id)
            return page('student_message.html', title='Email delivery could not be verified', message='If the email arrives, use its link within 20 minutes. Otherwise your temporary reservation will expire, and you can try again.'), 503
        return page('student_message.html', title='Check your email to confirm', message='We have held your appointment for 20 minutes. Open the link in your email and press Confirm appointment. Check your spam folder too.')

    @app.route('/peer-support/confirm/<token>', methods=['GET', 'POST'])
    def student_confirm(token):
        release_expired()
        booking = StudentBooking.query.filter_by(confirm_hash=digest(token)).first_or_404()
        if booking.status != 'pending' or booking.expires_at <= datetime.utcnow():
            return page('student_message.html', title='This reservation has expired', message='Choose another appointment to request a new confirmation email.'), 410
        if not booking.slot.published or slot_start(booking.slot) <= now_london() or (booking.location == 'in_person' and not in_person_open(booking.slot)):
            return page('student_message.html', title='This appointment is no longer available', message='The booking deadline has passed or the slot has been withdrawn. Choose another appointment.'), 409
        if request.method == 'GET':
            return page('student_message.html', title='Confirm your appointment', message=slot_label(booking.slot), action='Confirm appointment')
        check_csrf()
        # Only one concurrent POST can transition the reservation.
        manage_token = secrets.token_urlsafe(32)
        claimed = StudentBooking.query.filter_by(id=booking.id, status='pending').update(
            {'status': 'confirmed', 'confirm_hash': None, 'manage_hash': digest(manage_token)}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            abort(409)
        db.session.refresh(booking)
        notify(booking, 'confirmed', manage_token)
        return redirect(url_for('student_appointment', token=manage_token))

    @app.route('/peer-support/appointment/<token>', methods=['GET', 'POST'])
    def student_appointment(token):
        booking = StudentBooking.query.filter_by(manage_hash=digest(token)).first_or_404()
        if request.method == 'POST':
            check_csrf()
            if booking.status == 'confirmed':
                claimed = StudentBooking.query.filter_by(id=booking.id, status='confirmed').update(
                    {'status': 'cancelled', 'active_slot_id': None}, synchronize_session=False)
                db.session.commit()
                db.session.refresh(booking)
                if claimed:
                    notify(booking, 'cancelled')
        return page('student_appointment.html', booking=booking)

    @app.route('/peer-support/supporter/login', methods=['GET', 'POST'])
    def student_login():
        if request.method == 'GET':
            return page('student_login.html')
        check_csrf()
        password_hash = app.config['STUDENT_SUPPORT_PASSWORD_HASH']
        if not password_hash:
            return page('student_login.html', error='The shared password has not been set yet.'), 503
        now = datetime.utcnow()
        recent = StudentAccess.query.filter(StudentAccess.kind == 'password_attempt',
            StudentAccess.ip_hash == ip_hash(), StudentAccess.created_at > now - timedelta(hours=1)).count()
        if recent >= 10:
            return page('student_login.html', error='Too many sign-in attempts. Try again in an hour.'), 429
        db.session.add(StudentAccess(token_hash=digest(secrets.token_urlsafe(32)), kind='password_attempt',
            ip_hash=ip_hash(), expires_at=now + timedelta(hours=1)))
        db.session.commit()
        password = request.form.get('password', '')
        try:
            valid = bool(password) and len(password) <= 1024 and check_password_hash(password_hash, password)
        except ValueError:
            valid = False
        if not valid:
            return page('student_login.html', error='That password is not correct. Try again.'), 401
        raw = secrets.token_urlsafe(32)
        db.session.add(StudentAccess(token_hash=digest(raw), supporter=shared_identity(), kind='session',
            ip_hash=ip_hash(), expires_at=now + timedelta(hours=8)))
        db.session.commit()
        response = make_response(redirect(url_for('student_supporter')))
        response.set_cookie(COOKIE, raw, max_age=8 * 3600, secure=app.config['STUDENT_COOKIE_SECURE'],
            httponly=True, samesite='Lax', path='/peer-support')
        return response

    @app.route('/peer-support/supporter', methods=['GET'])
    @private_required
    def student_supporter():
        release_expired()
        maintain_student_records()
        slots = StudentSlot.query.filter(StudentSlot.day >= now_london().date()).order_by(StudentSlot.day, StudentSlot.start_time).all()
        bookings = StudentBooking.query.filter(StudentBooking.status.in_(['confirmed', 'cancelled'])).order_by(StudentBooking.created_at.desc()).limit(200).all()
        failures = StudentMail.query.filter(StudentMail.status != 'sent').order_by(StudentMail.id.desc()).limit(50).all()
        return page('student_supporter.html', slots=slots, bookings=bookings, failures=failures,
            notice=request.args.get('notice'))

    @app.route('/peer-support/supporter/logout', methods=['POST'])
    @private_required
    def student_logout():
        db.session.delete(g.student_access)
        db.session.commit()
        response = make_response(redirect(url_for('student_login')))
        response.delete_cookie(COOKIE, path='/peer-support')
        return response

    @app.route('/peer-support/supporter/slots', methods=['POST'])
    @private_required
    def student_add_slots():
        supporter = request.form.get('supporter')
        try:
            day = datetime.strptime(request.form.get('day', ''), '%Y-%m-%d').date()
            start = datetime.strptime(request.form.get('start', ''), '%H:%M').time()
            end = datetime.strptime(request.form.get('end', ''), '%H:%M').time()
        except ValueError:
            abort(400, 'Enter a date and valid start and end times.')
        if supporter not in SUPPORTERS:
            abort(400, 'Choose Sungji or Marilena as the supporter.')
        first = datetime.combine(day, start, tzinfo=LONDON)
        last = datetime.combine(day, end, tzinfo=LONDON)
        hours = (last - first).total_seconds() / 3600
        if first <= now_london() or not 1 <= hours <= 8 or hours != int(hours) or start.minute or end.minute:
            abort(400, 'Choose future whole-hour slots, up to eight hours at a time.')
        meeting_url = request.form.get('meeting_url', '').strip()
        if not valid_meeting_url(meeting_url):
            abort(400, 'Online joining links must be HTTPS URLs without spaces.')
        in_person = supporter == 'sungji' and request.form.get('in_person') == 'yes'
        from app import get_room_schedule_ids, booking_deadline
        if in_person and (day.weekday() != 4 or not get_room_schedule_ids().get(day.isoformat()) or now_london() >= booking_deadline(day)):
            abort(400, 'In-person appointments need a scheduled F@F Friday before Thursday at 10am.')
        for hour in range(int(hours)):
            hhmm = (first + timedelta(hours=hour)).strftime('%H:%M')
            if StudentSlot.query.filter_by(supporter=supporter, day=day, start_time=hhmm).first():
                continue
            db.session.add(StudentSlot(supporter=supporter, day=day, start_time=hhmm, in_person=in_person,
                published=request.form.get('published') == 'yes', meeting_url=meeting_url))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            abort(409, 'These slots have just been added. Reload the portal.')
        return redirect(url_for('student_supporter', notice='Availability added.'))

    @app.route('/peer-support/supporter/slots/<int:slot_id>', methods=['POST'])
    @private_required
    def student_edit_slot(slot_id):
        slot = db.session.get(StudentSlot, slot_id) or abort(404)
        if 'meeting_url' in request.form:
            meeting_url = request.form['meeting_url'].strip()
            if not valid_meeting_url(meeting_url):
                abort(400, 'Enter a valid HTTPS meeting link without spaces or account credentials.')
            slot.meeting_url = meeting_url
        slot.published = request.form.get('published') == 'yes'
        # Withdrawing a slot does not cancel a confirmed student's appointment.
        db.session.commit()
        return redirect(url_for('student_supporter', notice='Availability updated. Existing confirmed bookings remain valid.'))

    @app.route('/peer-support/supporter/bookings/<int:booking_id>/cancel', methods=['POST'])
    @private_required
    def student_cancel_booking(booking_id):
        booking = db.session.get(StudentBooking, booking_id) or abort(404)
        claimed = StudentBooking.query.filter_by(id=booking.id, status='confirmed').update(
            {'status': 'cancelled', 'active_slot_id': None}, synchronize_session=False)
        db.session.commit()
        if claimed:
            db.session.refresh(booking)
            notify(booking, 'cancelled')
        return redirect(url_for('student_supporter', notice='Appointment cancelled. Check notification delivery below.'))

    @app.route('/peer-support/supporter/bookings/<int:booking_id>/erase-answers', methods=['POST'])
    @private_required
    def student_erase_answers(booking_id):
        if request.form.get('confirm') != 'erase':
            abort(400, 'Confirm that you want to permanently remove the written answers.')
        booking = db.session.get(StudentBooking, booking_id) or abort(404)
        booking.studying, booking.goals, booking.questions = '', '', ''
        booking.answers_deleted_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('student_supporter', notice='Written answers removed. Appointment and contact details are unchanged.'))
