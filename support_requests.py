"""Date-specific requests for more than one support person. Never reserves a room."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from flask import abort, render_template, request, session


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def normal_name(value):
    return ' '.join(value.split()).casefold()


def approved_request(token):
    from app import SupportRequest, booking_registration_closed
    if not isinstance(token, str) or not 30 <= len(token) <= 100:
        return None
    row = SupportRequest.query.filter_by(token_hash=digest(token), status='approved').first()
    if row and not booking_registration_closed(row.session_date):
        return row
    return None


def approved_supporters(token, email, name, day, lead_name):
    row = approved_request(token)
    if (not row or row.email != email or normal_name(row.name) != normal_name(name)
            or row.session_date != day):
        raise ValueError('This support approval is not valid for this person and Friday. Use the link in your approval email.')
    people = json.loads(row.supporters_json)
    if normal_name(people[0]) != normal_name(lead_name):
        raise ValueError('Enter the first approved support person as the lead carer, as listed in your approval email.')
    return people


def register_routes(app, admin_required):
    def page(**context):
        from app import get_upcoming_fridays
        dates = [day for day in get_upcoming_fridays() if not day['registration_closed']]
        return render_template('support_request.html', dates=dates, **context)

    @app.after_request
    def private_support_pages(response):
        if request.path.startswith(('/support-requests', '/admin/support-requests')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.route('/support-requests', methods=['GET', 'POST'])
    def support_request_page():
        from app import (db, SupportRequest, get_room_schedule_ids, booking_registration_closed,
                         reminder_base_url, reminder_date_display, send_emails_async)
        if request.method == 'GET':
            return page(selected=request.args.get('date', ''))
        name = ' '.join(request.form.get('name', '').split())
        email = request.form.get('email', '').strip().lower()
        reason = request.form.get('reason', '').strip()
        raw_people = request.form.get('supporters', '').strip().splitlines()
        people = [' '.join(person.split()) for person in raw_people if person.strip()]
        selected = request.form.get('date', '')
        values = dict(request.form)
        try:
            day = datetime.strptime(selected, '%Y-%m-%d').date()
            if (day.weekday() != 4 or not get_room_schedule_ids().get(selected)
                    or booking_registration_closed(day)):
                raise ValueError('Choose a Friday that is still open for booking.')
            if not 3 <= len(name) <= 120 or len(name.split()) < 2:
                raise ValueError('Enter the attending person\'s full first and last names.')
            if (len(email) > 120 or email.count('@') != 1 or '.' not in email.rsplit('@', 1)[-1]
                    or any(c.isspace() for c in email)):
                raise ValueError('Enter a valid email address.')
            if not 2 <= len(people) <= 34 or any(len(p) > 120 or len(p.split()) < 2 for p in people):
                raise ValueError('List the full first and last names of each support person, one per line. Include at least two.')
            if len({normal_name(p) for p in people + [name]}) != len(people) + 1:
                raise ValueError('List each support person once, separately from the attending person.')
            if not 10 <= len(reason) <= 2000:
                raise ValueError('Explain briefly why more than one support person is needed (10 to 2,000 characters).')
        except ValueError as error:
            return page(error=str(error), selected=selected, values=values), 400
        now = datetime.utcnow()
        ip_hash = digest(str(app.secret_key) + ':' + (request.remote_addr or ''))
        duplicate = SupportRequest.query.filter_by(email=email, session_date=day).filter(
            SupportRequest.status.in_(['pending', 'approved']),
            db.func.lower(SupportRequest.name) == name.lower()).first()
        if duplicate:
            return page(notice='A request for this person and Friday is already recorded. Check your email or contact LAGC for help. This does not book a place.')
        recent = SupportRequest.query.filter(SupportRequest.created_at > now - timedelta(hours=1),
            db.or_(SupportRequest.ip_hash == ip_hash, SupportRequest.email == email)).count()
        if recent >= 5:
            return page(error='Too many recent requests. Contact LAGC if you need help.'), 429
        row = SupportRequest(name=name, email=email, session_date=day,
            supporters_json=json.dumps(people), reason=reason, ip_hash=ip_hash)
        db.session.add(row)
        db.session.commit()
        # Keep support explanations out of email; staff read them after signing in.
        send_emails_async([
            (email, 'Your additional support request: Fridays @ Farringdon',
             f'Hello {name},\n\nWe have received your request for {len(people)} support people on '
             f'{reminder_date_display(day)}. LAGC will review it and email the decision.\n\n'
             'No place has been booked. If approved, use the link in the decision email to complete '
             'your room booking before Thursday at 10am (London time).\n\nLondon Autism Group Charity'),
            ('chris.papadopoulos@londonautismgroupcharity.org', 'Additional support request to review: Farringdon',
             'A request for more than one support person is awaiting review. Sign in to read it and approve or decline:\n'
             f'{reminder_base_url()}/admin/support-requests\n\nApproval does not reserve a room or bypass the booking deadline.')
        ])
        return page(notice='Request received. We will email our decision. No place has been booked; if approved, you must still complete your booking before Thursday at 10am (London time).')

    @app.route('/admin/support-requests')
    @admin_required
    def admin_support_requests():
        from app import SupportRequest, reminder_date_display
        csrf = session.setdefault('support_request_csrf', secrets.token_urlsafe(32))
        rows = SupportRequest.query.order_by(SupportRequest.created_at.desc()).all()
        return render_template('admin_support_requests.html', requests=rows, csrf=csrf,
            date_display=reminder_date_display, people=lambda row: json.loads(row.supporters_json))

    @app.route('/admin/support-requests/<int:request_id>/decision', methods=['POST'])
    @admin_required
    def decide_support_request(request_id):
        from app import (db, SupportRequest, booking_registration_closed, get_room_schedule_ids,
                         reminder_base_url, reminder_date_display, send_confirmation_email)
        supplied = request.form.get('csrf', '')
        expected = session.get('support_request_csrf', '')
        if not expected or not secrets.compare_digest(supplied, expected):
            abort(403)
        decision = request.form.get('decision')
        if decision not in ('approved', 'declined'):
            abort(400)
        row = db.session.get(SupportRequest, request_id)
        if not row:
            abort(404)
        if (decision == 'approved' and (booking_registration_closed(row.session_date)
                or not get_room_schedule_ids().get(row.session_date.isoformat()))):
            return 'This Friday is closed or withdrawn. Approval cannot bypass the deadline.', 409
        note = request.form.get('note', '').strip()[:1000]
        if decision == 'declined' and not note:
            return 'Add a short explanation so the person understands the decision.', 400
        token = secrets.token_urlsafe(32) if decision == 'approved' else None
        # Only one administrator can decide a pending request. A repeated POST
        # cannot send another decision or revive a rejected request.
        changed = SupportRequest.query.filter_by(id=row.id, status='pending').update({
            'status': decision, 'decision_note': note, 'decided_at': datetime.utcnow(),
            'token_hash': digest(token) if token else None}, synchronize_session=False)
        db.session.commit()
        if not changed:
            return 'This request has already been decided. Refresh the review page.', 409
        date_label = reminder_date_display(row.session_date)
        message = f'Hello {row.name},\n\nYour request for additional support people on {date_label} has been {decision}.\n'
        if note:
            message += f'\n{note}\n'
        approval_link = ''
        if token:
            names = json.loads(row.supporters_json)
            approval_link = f'{reminder_base_url()}/book?date={row.session_date.isoformat()}&support={token}'
            message += ('\nApproved support people:\n' + '\n'.join(names) +
                '\n\nComplete your room booking using this private link:\n' + approval_link +
                '\n\nThis approval is for the named person, support people and Friday only. '
                'It does not reserve a room. Complete booking before Thursday at 10am (London time). '
                'Enter the first support person listed above as the lead carer, with their contact details.\n')
        else:
            message += '\nContact us if you would like to discuss another way to attend safely.\n'
        message += '\nLondon Autism Group Charity'
        delivered = send_confirmation_email(row.email, 'Your additional support request: ' + decision, message)
        row = db.session.get(SupportRequest, request_id)
        row.decision_email_sent = delivered
        db.session.commit()
        return render_template('support_decision.html', delivered=delivered, approval_link=approval_link)
