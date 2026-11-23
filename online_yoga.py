"""Standalone scheduling and registration for online Gentle Yoga with Marlijn."""

from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
from hashlib import sha256
import hmac
import os
import re
import secrets
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request,
    session, url_for,
)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select, text, update
from werkzeug.security import check_password_hash

from online_yoga_mail import confirmation_body
from online_yoga_questions import (
    ANSWER_LIMITS, DEFAULT_QUESTIONS, MAX_QUESTIONS, QUESTION_TYPES,
    parse_answers, parse_editor_question,
)

LONDON = ZoneInfo('Europe/London')
CONFIRMED_DATES = ('2026-12-09', '2026-12-16')
MEET_URL = re.compile(r'https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}/?')
EMAIL = re.compile(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+')
CONFIRMATION_SUBJECT = 'Your online Gentle Yoga booking'


def digest(value):
    return sha256(value.encode()).hexdigest()


def today():
    return datetime.now(LONDON).date()


def date_label(day):
    suffix = 'th' if 11 <= day.day % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day.day % 10, 'th')
    return day.strftime('%A ') + str(day.day) + suffix + day.strftime(' %B %Y')


def clock_label(value):
    return (value.strftime('%I.%M') if value.minute else value.strftime('%I')).lstrip('0') + value.strftime('%p').lower()


def meet_link(value):
    if not value:
        return ''
    parts = urlsplit(value)
    canonical = f'{parts.scheme}://{parts.netloc.lower()}{parts.path}'
    if not MEET_URL.fullmatch(canonical):
        raise ValueError('Enter a Google Meet link in the format https://meet.google.com/abc-defg-hij.')
    return canonical.rstrip('/')


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def register_online_yoga(app, db, deliver, delivery_uncertain):
    app.config['ONLINE_YOGA_PASSWORD_HASH'] = os.environ.get('ONLINE_YOGA_PASSWORD_HASH', '')
    app.config['ONLINE_YOGA_ORIGIN'] = os.environ.get(
        'ONLINE_YOGA_ORIGIN', 'https://milestheodore.pythonanywhere.com'
    ).rstrip('/')
    app.config['ONLINE_YOGA_SECURE_COOKIE'] = os.environ.get('ONLINE_YOGA_SECURE_COOKIE', 'true') != 'false'
    yoga = Blueprint('online_yoga', __name__, url_prefix='/online-yoga')
    cookie_name = 'online_yoga_organiser'

    class YogaSession(db.Model):
        __tablename__ = 'online_yoga_session'
        id = db.Column(db.Integer, primary_key=True)
        day = db.Column(db.Date, unique=True, nullable=False)
        start = db.Column(db.Time, nullable=False)
        end = db.Column(db.Time, nullable=False)
        capacity = db.Column(db.Integer, nullable=False)
        public_notes = db.Column(db.Text, nullable=False, default='')
        joining_notes = db.Column(db.Text, nullable=False, default='')
        meet_url = db.Column(db.String(160), nullable=False, default='')
        status = db.Column(db.String(12), nullable=False, default='draft', index=True)

        @property
        def when(self):
            return f'{date_label(self.day)}, {clock_label(self.start)} to {clock_label(self.end)}'

        @property
        def upcoming(self):
            return datetime.combine(self.day, self.start, LONDON) > datetime.now(LONDON)

    class Registration(db.Model):
        __tablename__ = 'online_yoga_registration'
        __table_args__ = (db.UniqueConstraint('session_id', 'email'),)
        id = db.Column(db.Integer, primary_key=True)
        session_id = db.Column(db.Integer, db.ForeignKey('online_yoga_session.id'), nullable=False)
        email = db.Column(db.String(254), nullable=False)
        name = db.Column(db.String(120), nullable=False)
        experience = db.Column(db.String(12), nullable=False, default='')
        adjustments = db.Column(db.Text, nullable=False, default='')
        token_hash = db.Column(db.String(64), unique=True, nullable=False)
        cancelled = db.Column(db.Boolean, nullable=False, default=False)
        yoga_session = db.relationship(YogaSession)

    class FormSettings(db.Model):
        __tablename__ = 'online_yoga_form'
        id = db.Column(db.Integer, primary_key=True)
        revision = db.Column(db.Integer, nullable=False)
        questions = db.Column(db.JSON, nullable=False)

    class FormAnswers(db.Model):
        __tablename__ = 'online_yoga_answers'
        registration_id = db.Column(db.Integer, db.ForeignKey('online_yoga_registration.id'), primary_key=True)
        answers = db.Column(db.JSON, nullable=False)

    class Confirmation(db.Model):
        __tablename__ = 'online_yoga_confirmation'
        id = db.Column(db.Integer, primary_key=True)
        registration_id = db.Column(db.Integer, db.ForeignKey('online_yoga_registration.id'), nullable=False)
        token_hash = db.Column(db.String(64), nullable=False, unique=True)
        token = db.Column(db.String(43), nullable=False)
        status = db.Column(db.String(12), nullable=False, default='queued')
        attempts = db.Column(db.Integer, nullable=False, default=0)
        updated_at = db.Column(db.DateTime, nullable=False, default=utc_now)
        retry_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def form_settings():
        config = db.session.get(FormSettings, 1)
        return (config.revision, config.questions) if config else (1, DEFAULT_QUESTIONS)

    def confirmation_status(item):
        if item and item.status == 'sending' and item.updated_at <= utc_now() - timedelta(minutes=5):
            return 'uncertain'
        return item.status if item else 'untracked'

    def work_confirmations(ids=None):
        # The booking and its jobs are committed together. Claim each attempt
        # before SMTP so parallel requests and the reminder job cannot duplicate it.
        jobs = select(Confirmation.id).where(
            Confirmation.status.in_(('queued', 'failed')),
            Confirmation.attempts < 3, Confirmation.retry_at <= utc_now()
        )
        if ids is not None:
            jobs = jobs.where(Confirmation.id.in_(ids))
        counts = {'sent': 0, 'failed': 0, 'uncertain': 0, 'cancelled': 0}
        for job_id in db.session.scalars(jobs.order_by(Confirmation.id).limit(50)).all():
            now = utc_now()
            claimed = db.session.execute(update(Confirmation).where(
                Confirmation.id == job_id, Confirmation.status.in_(('queued', 'failed')),
                Confirmation.attempts < 3, Confirmation.retry_at <= now,
            ).values(status='sending', attempts=Confirmation.attempts + 1, updated_at=now)).rowcount
            db.session.commit()
            if not claimed:
                continue
            job = db.session.get(Confirmation, job_id)
            booking = db.session.get(Registration, job.registration_id)
            item = booking.yoga_session
            if booking.cancelled or booking.token_hash != job.token_hash or item.status != 'published' or not item.upcoming:
                status = 'cancelled'
            else:
                private_url = app.config['ONLINE_YOGA_ORIGIN'] + '/online-yoga/booking/' + job.token
                message = confirmation_body(booking.name, item.when, item.meet_url, item.joining_notes, private_url)
                try:
                    deliver(booking.email, CONFIRMATION_SUBJECT, message)
                    status = 'sent'
                except delivery_uncertain:
                    status = 'uncertain'
                except Exception:
                    status = 'failed'
            job.status = status
            job.updated_at = utc_now()
            job.retry_at = job.updated_at + timedelta(minutes=5)
            if status in ('sent', 'cancelled'):
                job.token = ''
            db.session.commit()
            counts[status] += 1
            if status in ('failed', 'uncertain'):
                app.logger.warning('Online yoga confirmation %s: %s', job_id, status)
        return counts

    def start_mail_job(job_id):
        def run():
            with app.app_context():
                work_confirmations([job_id])
        try:
            threading.Thread(target=run, daemon=True).start()
        except RuntimeError:
            app.logger.warning('Online yoga confirmation %s remains queued.', job_id)

    def send_session_update(recipients, subject, body):
        if not recipients:
            return

        def run():
            with app.app_context():
                for recipient in recipients:
                    try:
                        deliver(recipient, subject, body)
                    except Exception:
                        app.logger.warning('Could not send online yoga session update.')
        threading.Thread(target=run, daemon=True).start()

    class LoginFailure(db.Model):
        __tablename__ = 'online_yoga_login_failure'
        id = db.Column(db.Integer, primary_key=True)
        client_key = db.Column(db.String(64), nullable=False, index=True)
        recorded_at = db.Column(db.DateTime, nullable=False)

    def seed_sessions():
        # Rerunning startup preserves edits and cancellations, including after a reload.
        db.session.execute(text("""
            INSERT OR IGNORE INTO online_yoga_session
                (day, start, end, capacity, public_notes, joining_notes, meet_url, status)
            VALUES (:day, '09:00:00', '10:00:00', 10, '', '', '', 'published')
        """), [{'day': day} for day in CONFIRMED_DATES])
        db.session.commit()

    def csrf_token():
        if 'online_yoga_csrf' not in session:
            session['online_yoga_csrf'] = secrets.token_urlsafe(32)
        return session['online_yoga_csrf']

    @yoga.before_request
    def verify_post():
        if request.method == 'POST':
            expected = session.get('online_yoga_csrf', '')
            submitted = request.form.get('csrf_token', '')
            if not expected or not submitted.isascii() or not hmac.compare_digest(expected, submitted):
                abort(400, 'Your form expired. Return to the yoga page and try again.')

    @yoga.after_request
    def private_response(response):
        if request.endpoint != 'online_yoga.calendar':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.endpoint in {'online_yoga.receipt', 'online_yoga.login', 'online_yoga.organiser'}:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            response.headers['X-Frame-Options'] = 'DENY'
        return response

    def page(template, **context):
        return render_template('online_yoga/' + template, csrf_token=csrf_token(), **context)

    def scheduled():
        counts = (
            select(Registration.session_id, func.count().label('booked'))
            .where(Registration.cancelled.is_(False))
            .group_by(Registration.session_id)
            .subquery()
        )
        return db.session.execute(
            select(YogaSession, func.coalesce(counts.c.booked, 0))
            .outerjoin(counts, YogaSession.id == counts.c.session_id)
            .where(YogaSession.status == 'published', YogaSession.day >= today())
            .order_by(YogaSession.day)
        ).all()

    def active_bookings(class_session):
        return db.session.scalars(select(Registration).where(
            Registration.session_id == class_session.id, Registration.cancelled.is_(False)
        )).all()

    def begin_write():
        # Reserving a place and changing capacity share the same SQLite write lock.
        db.session.execute(text('BEGIN IMMEDIATE'))

    def booking_page(error='', status=200, values=None):
        day = (values or request.args).get('date', '')
        upcoming = [(item, count) for item, count in scheduled() if item.upcoming]
        bookable = [item for item, count in upcoming if item.meet_url and count < item.capacity]
        revision, questions = form_settings()
        return page('registration.html', upcoming=upcoming, bookable=bookable, selected=day,
                    error=error, values=values or {}, form_revision=revision,
                    questions=[field for field in questions if field['enabled']], answer_limits=ANSWER_LIMITS), status

    @yoga.get('')
    def registration():
        return booking_page()

    def calendar_status(item, count):
        if not item.upcoming:
            return 'closed'
        if not item.meet_url:
            return 'soon'
        return 'full' if count >= item.capacity else 'open'

    @yoga.get('/calendar.json')
    def calendar():
        # Explicit public projection. Joining links, notes and bookings stay private.
        return jsonify([
            {'date': item.day.isoformat(), 'start': item.start.strftime('%H:%M'),
             'end': item.end.strftime('%H:%M'), 'description': item.public_notes,
             'status': calendar_status(item, count)}
            for item, count in scheduled()
        ])

    @yoga.post('/register')
    def book():
        form = request.form
        name = form.get('name', '').strip()
        email = form.get('email', '').strip().lower()
        if not (0 < len(name) <= 120 and len(email) <= 254 and EMAIL.fullmatch(email)):
            return booking_page('Enter your name and a valid email address.', 400, form)
        try:
            day = date.fromisoformat(form.get('date', ''))
        except ValueError:
            return booking_page('Choose a session date.', 400, form)

        begin_write()
        revision, questions = form_settings()
        if form.get('form_revision') != str(revision):
            db.session.rollback()
            return booking_page('The registration questions have changed. Check your answers before booking.', 409, form)
        try:
            answers = parse_answers(questions, form)
        except ValueError as error:
            db.session.rollback()
            return booking_page(str(error), 400, form)
        class_session = db.session.scalar(select(YogaSession).where(YogaSession.day == day))
        if not class_session or class_session.status != 'published' or not class_session.meet_url or not class_session.upcoming:
            db.session.rollback()
            return booking_page('Bookings are closed for that session. Choose another date.', 409, form)
        booking = db.session.scalar(select(Registration).filter_by(session_id=class_session.id, email=email))
        if booking and not booking.cancelled:
            db.session.rollback()
            return booking_page('This email already has a place for that date. Use the link in your confirmation email.', 409, form)
        if len(active_bookings(class_session)) >= class_session.capacity:
            db.session.rollback()
            return booking_page('That session is now full. Choose another date.', 409, form)

        token = secrets.token_urlsafe(32)
        if booking is None:
            booking = Registration(session_id=class_session.id, email=email)
            db.session.add(booking)
        booking.name = name
        booking.experience = ''
        booking.adjustments = ''
        booking.token_hash = digest(token)
        booking.cancelled = False
        db.session.flush()
        db.session.merge(FormAnswers(registration_id=booking.id, answers=answers))
        job = Confirmation(registration_id=booking.id, token_hash=booking.token_hash, token=token)
        db.session.add(job)
        db.session.flush()
        job_id = job.id
        db.session.commit()
        start_mail_job(job_id)
        return redirect(url_for('.receipt', token=token), code=303)

    @yoga.route('/booking/<token>', methods=['GET', 'POST'])
    def receipt(token):
        if len(token) != 43 or not token.isascii():
            abort(404)
        if request.method == 'POST':
            begin_write()
        booking = db.session.scalar(select(Registration).filter_by(token_hash=digest(token)))
        if not booking:
            abort(404)
        class_session = booking.yoga_session
        if request.method == 'POST':
            if class_session.status == 'published' and class_session.upcoming:
                booking.cancelled = True
                db.session.commit()
            return redirect(url_for('.receipt', token=token), code=303)
        can_join = (
            not booking.cancelled and class_session.status == 'published'
            and datetime.combine(class_session.day, class_session.end, LONDON) > datetime.now(LONDON)
        )
        job = db.session.scalar(select(Confirmation).filter_by(token_hash=booking.token_hash))
        return page('receipt.html', booking=booking, item=class_session, can_join=can_join,
                    mail_status=confirmation_status(job))

    def signer():
        return URLSafeTimedSerializer(app.secret_key, salt='online-yoga:' + digest(app.config['ONLINE_YOGA_PASSWORD_HASH']))

    def signed_in():
        if not app.config['ONLINE_YOGA_PASSWORD_HASH']:
            return False
        try:
            return signer().loads(request.cookies.get(cookie_name, ''), max_age=8 * 3600) == 'organiser'
        except BadSignature:
            return False

    def organiser_required(view):
        @wraps(view)
        def protected(*args, **kwargs):
            if not signed_in():
                return redirect(url_for('.login'), code=303)
            return view(*args, **kwargs)
        return protected

    @yoga.route('/admin/login', methods=['GET', 'POST'])
    def login():
        if signed_in():
            return redirect(url_for('.organiser'), code=303)
        if request.method == 'GET':
            return page('login.html')
        if not app.config['ONLINE_YOGA_PASSWORD_HASH']:
            return page('login.html', error='Organiser access has not been set up yet.'), 503
        password = request.form.get('password', '')
        client_key = hmac.new(app.secret_key.encode(), (request.remote_addr or '').encode(), 'sha256').hexdigest()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        begin_write()
        LoginFailure.query.filter(LoginFailure.recorded_at < now - timedelta(hours=1)).delete()
        if LoginFailure.query.filter_by(client_key=client_key).count() >= 10:
            db.session.commit()
            return page('login.html', error='Too many attempts. Try again in an hour.'), 429
        if not (0 < len(password) <= 1024 and check_password_hash(app.config['ONLINE_YOGA_PASSWORD_HASH'], password)):
            db.session.add(LoginFailure(client_key=client_key, recorded_at=now))
            db.session.commit()
            return page('login.html', error='That password did not match.'), 401
        db.session.commit()
        session.pop('online_yoga_csrf', None)
        response = redirect(url_for('.organiser'), code=303)
        response.set_cookie(cookie_name, signer().dumps('organiser'), max_age=8 * 3600,
                            httponly=True, secure=app.config['ONLINE_YOGA_SECURE_COOKIE'],
                            samesite='Lax', path='/online-yoga/admin')
        return response

    @yoga.post('/admin/logout')
    @organiser_required
    def logout():
        response = redirect(url_for('.login'), code=303)
        response.delete_cookie(cookie_name, path='/online-yoga/admin')
        session.pop('online_yoga_csrf', None)
        return response

    def organiser_page(error='', status=200, values=None):
        upcoming = db.session.scalars(select(YogaSession).where(YogaSession.day >= today()).order_by(YogaSession.day)).all()
        revision, questions = form_settings()
        registrations = [(item, active_bookings(item)) for item in upcoming]
        participant_ids = [booking.id for _, rows in registrations for booking in rows]
        snapshots = {entry.registration_id: entry.answers for entry in db.session.scalars(
            select(FormAnswers).where(FormAnswers.registration_id.in_(participant_ids))
        ).all()}
        tokens = [booking.token_hash for _, rows in registrations for booking in rows]
        confirmations = {job.token_hash: (job.id, confirmation_status(job)) for job in db.session.scalars(
            select(Confirmation).where(Confirmation.token_hash.in_(tokens))
        ).all()}
        return page('organiser.html', classes=registrations, snapshots=snapshots,
                    confirmations=confirmations, questions=questions, form_revision=revision,
                    question_types=QUESTION_TYPES, can_add_question=len(questions) < MAX_QUESTIONS,
                    error=error, values=values or {}, saved=request.args.get('saved', '')), status

    @yoga.get('/admin')
    @organiser_required
    def organiser():
        return organiser_page()

    @yoga.post('/admin/questions')
    @organiser_required
    def edit_questions():
        form = request.form
        key = form.get('key', '')
        begin_write()
        revision, questions = form_settings()
        if form.get('form_revision') != str(revision):
            db.session.rollback()
            return organiser_page('The form was updated in another tab. Check the latest questions before saving.', 409)
        try:
            if key == 'new':
                if len(questions) >= MAX_QUESTIONS:
                    raise ValueError('The form already has the maximum number of questions.')
                questions = [*questions, parse_editor_question(form, secrets.token_hex(8))]
            else:
                if not any(q['key'] == key for q in questions):
                    abort(404)
                replacement = parse_editor_question(form, key)
                questions = [replacement if q['key'] == key else q for q in questions]
        except ValueError as error:
            db.session.rollback()
            return organiser_page(str(error), 400, form)
        db.session.merge(FormSettings(id=1, revision=revision + 1, questions=questions))
        db.session.commit()
        return redirect(url_for('.organiser', saved='questions', _anchor='registration-questions'), code=303)

    @yoga.post('/admin/confirmations/<int:job_id>/retry')
    @organiser_required
    def retry_confirmation(job_id):
        begin_write()
        job = db.get_or_404(Confirmation, job_id)
        if confirmation_status(job) not in ('failed', 'uncertain'):
            db.session.rollback()
            return organiser_page('This confirmation has already been sent or is still being handled.', 409)
        job.status = 'queued'
        job.attempts = 0
        job.updated_at = job.retry_at = utc_now()
        db.session.commit()
        start_mail_job(job_id)
        return redirect(url_for('.organiser', saved='email', _anchor='upcoming-sessions'), code=303)

    def shared_details(form):
        start, end = (time.fromisoformat(form.get(key, '')) for key in ('start', 'end'))
        capacity = int(form.get('capacity', ''))
        public_notes, joining_notes = (form.get(key, '').strip() for key in ('public_notes', 'joining_notes'))
        join_url = meet_link(form.get('meet_url', '').strip())
        if start >= end or any(value.tzinfo or value.second or value.microsecond for value in (start, end)):
            raise ValueError('Enter UK start and finish times, with the finish after the start.')
        if not 1 <= capacity <= 100 or len(public_notes) > 500 or len(joining_notes) > 1200:
            raise ValueError('Choose 1 to 100 places and keep notes within the limits shown.')
        if re.search(r'meet\.google\.com', public_notes, re.IGNORECASE):
            raise ValueError('Put the Meet link in the private Google Meet field.')
        return dict(start=start, end=end, capacity=capacity, public_notes=public_notes, joining_notes=joining_notes, meet_url=join_url)

    @yoga.post('/admin/sessions')
    @organiser_required
    def add_sessions():
        form = request.form
        lines = form.get('dates', '').strip().splitlines()
        try:
            details = shared_details(form)
            dates_and_links = {}
            for line in lines:
                if not line.strip():
                    continue
                fields = line.split()
                day = date.fromisoformat(fields[0])
                meet_url = meet_link(fields[1]) if len(fields) > 1 else details['meet_url']
                if len(fields) > 2:
                    raise ValueError('Use one date per line, optionally followed by its Google Meet link.')
                if day in dates_and_links or datetime.combine(day, details['start'], LONDON) <= datetime.now(LONDON):
                    raise ValueError('Enter distinct future dates.')
                dates_and_links[day] = meet_url
            if not 1 <= len(dates_and_links) <= 26:
                raise ValueError('Enter between 1 and 26 dates.')
        except ValueError as exc:
            message = str(exc)
            if message.startswith(('Invalid isoformat', 'invalid literal', 'day is out of range', 'month must')):
                message = 'Use dates in YYYY-MM-DD format and fill in the times and number of places.'
            return organiser_page(message, 400, form)

        begin_write()
        if db.session.scalar(select(YogaSession.id).where(YogaSession.day.in_(dates_and_links)).limit(1)):
            db.session.rollback()
            return organiser_page('One or more dates already exist. Edit those dates in the list below.', 409, form)
        status = 'published' if form.get('publish') == 'yes' else 'draft'
        for day, meet_url in dates_and_links.items():
            db.session.add(YogaSession(day=day, status=status, **{**details, 'meet_url': meet_url}))
        db.session.commit()
        return redirect(url_for('.organiser', saved='dates', _anchor='upcoming-sessions'), code=303)

    @yoga.post('/admin/sessions/<int:class_id>')
    @organiser_required
    def edit_session(class_id):
        begin_write()
        class_session = db.get_or_404(YogaSession, class_id)
        form = request.form
        action = form.get('action')
        if not class_session.upcoming or class_session.status == 'cancelled':
            db.session.rollback()
            return organiser_page('That session can no longer be edited.', 409)
        bookings = active_bookings(class_session)
        class_label = class_session.when
        emails = [booking.email for booking in bookings]
        if action == 'cancel':
            class_session.status = 'cancelled'
            db.session.commit()
            send_session_update(emails, 'Online Gentle Yoga session cancelled',
                                f'The online Gentle Yoga session on {class_label} has been cancelled.\n\nLondon Autism Group Charity')
            return redirect(url_for('.organiser'), code=303)

        new_status = form.get('status', 'draft')
        try:
            if new_status not in ('published', 'draft'):
                raise ValueError('Choose whether the date is a draft or published.')
            details = shared_details(form)
            if datetime.combine(class_session.day, details['start'], LONDON) <= datetime.now(LONDON):
                raise ValueError('Choose a start time that is still in the future.')
            if bookings and (details['capacity'] < len(bookings) or not details['meet_url']):
                raise ValueError('Keep a joining link and enough places for existing registrations.')
            if bookings and new_status == 'draft':
                raise ValueError('This session has bookings. Keep it published or cancel it.')
        except ValueError as exc:
            db.session.rollback()
            return organiser_page(str(exc), 400, {**form.to_dict(), 'session_id': class_id})
        changed_joining = any(getattr(class_session, key) != details[key]
                              for key in ('start', 'end', 'meet_url', 'joining_notes'))
        for key, value in details.items():
            setattr(class_session, key, value)
        class_session.status = new_status
        db.session.commit()
        if changed_joining:
            message = (f'Your online Gentle Yoga session has been updated.\n\n{class_session.when} (UK time)\n'
                       f'Join on Google Meet: {class_session.meet_url}\n{class_session.joining_notes}\n\n'
                       'Your existing booking link will also show the latest details.\n\nLondon Autism Group Charity')
            send_session_update(emails, 'Updated online Gentle Yoga joining details', message)
        return redirect(url_for('.organiser', saved='session', _anchor='session-' + str(class_id)), code=303)

    app.register_blueprint(yoga)
    return seed_sessions, work_confirmations
