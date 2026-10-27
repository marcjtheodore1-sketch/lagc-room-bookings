# Student support bookings

## Status and entry points

Built on `af94cd2` in `codex/student-support-bookings`. The existing Student
Support information page (`/peer-support`) links to `/peer-support/book`.
The general site navigation already points to this information page.

The supporter portal is `/peer-support/supporter`. Chris has chosen one separate
shared Student Support password for Sungji, Marilena and himself. It is independent
of the general F@F administrator password. His chosen password has been configured in the local preview and successful
browser sign-in has been verified. No default or temporary password is enabled.

The application reads only `STUDENT_SUPPORT_PASSWORD_HASH`, a Werkzeug password
hash. The local preview loads that hash from the private, untracked file
`/tmp/lagc-student-preview-password.hash`. Never put a plaintext password or its
hash in Git, logs, screenshots or email. Configure the real password only when
Chris supplies it, and keep this feature local until he authorises publication.

All three people using the shared password can manage both calendars and see the
private forms. The general F@F administrator session grants no access to this
portal. Hosting-account owners and people with direct filesystem/database access
retain technical access to stored records. The shared login does not distinguish
which of the three people made a change.

## Agreed behaviour

Sessions last 45 minutes, with one slot each hour. Dates and hours are managed in
the supporter portal, with an explicit publish checkbox. Dates do not recur
implicitly. Supplied October dates are not seeded into production. Before adding
availability, check and move any existing Calendly appointments, so the same time
is not offered twice. Only Friday 30th October 2026 remains in the supplied future
availability; Sunday 1st November in the local preview is fictional test data.

Sungji offers online sessions and, on scheduled F@F Fridays before the deadline,
in-person sessions. Marilena's sessions are online. In-person requests must be
booked **and email-confirmed before Thursday at 10am London time**. After the
deadline, the slot can still be booked online. The server checks this again on
confirmation, including stale forms. In-person sessions use Rose Room 4.4 or a
semi-open green booth, subject to availability. The service does not reserve Rose
Room or promise a private room.

The form collects name, email, study/level, goals and optional questions. In-person
students supply their full name and answer the venue mobility/evacuation-support
question. A random email token reserves the slot for 20 minutes. Opening an email
link alone does not confirm the booking. A POST confirms it; unconfirmed holds
expire. A unique database claim protects slots against simultaneous requests.

Students receive a separate private appointment/cancellation link after confirming.
Cancellation is an explicit POST and releases the slot. Supporters can also cancel
appointments, publish/withdraw availability and set or update online meeting links.
If joining details are added after confirmation, the supporter needs to tell the
student; changing the link does not resend mail automatically. If no link is set,
the confirmation tells the student their supporter will email joining details.

## Privacy and email

Student records are separate from room bookings, general admin lists, CSV exports,
public availability and general mailshots. Written answers are displayed only
inside the supporter portal. Template rendering escapes names and answers.
Notifications omit questionnaire answers. Confirmation and cancellation notices go
separately to the student and the assigned supporter. Friday notifications go to
Sungji; Sunday notifications go to Marilena. No emails go to the other supporter.

Only confirmed in-person student names and Sungji's name feed the existing building
report. They are deduplicated with ordinary attendee and volunteer names. The
existing session-wide Yes/No mobility flag includes student mobility needs without
identifying who needs assistance. Student emails, answers, appointment times and
support-service labels are excluded from that report. Reception delivery remains
at Thursday 10am, with its existing recipients and frozen snapshot. A later
cancellation cannot retract or change an already-sent list.

Supporter sign-in uses the separate shared password, checked against a secure
hash. Sessions expire after eight hours and can be revoked by signing out.
Changing the configured password hash immediately invalidates all previous
supporter sessions. Missing password configuration fails closed. Old supporter
email links and sessions cannot bypass password authentication. Ten attempts per
IP per hour are allowed, using persistent limits that survive worker restarts.
Passwords are never emailed, logged or included in responses.

Session tokens are stored as SHA-256 hashes. A separate server-side CSRF mechanism
avoids relying on the existing shared F@F Flask session secret. Production cookies
use Secure, HttpOnly and SameSite. Private pages have no-store and no-referrer
headers and disallow framing. Booking requests also have persistent rate limits.

Each notification recipient gets a durable unique send claim. Failed, interrupted
or uncertain deliveries are shown to supporters and are not automatically retried.
Check the sender's sent mailbox before contacting someone again. No test emails
were sent during development; local browser checks captured delivery in a fake
mailbox. Live SMTP authentication was checked successfully without sending mail.

Chris chose to keep written answers until manually deleted. Automatic answer
removal is disabled (`STUDENT_ANSWER_RETENTION_DAYS=None`). Supporters can
explicitly erase the written study, goals and question answers through their
private portal; names and appointment details remain. Expired access credentials
are pruned after a day through the existing hourly job and portal/booking visits.
There is no automatic Calendly import or historical email subscription.

## Release and rollback

This shared-password change is authorised for the local preview only. Deployment
requires separate approval from Chris. Deploy only the reviewed source revision to the existing PythonAnywhere
checkout and reload the web app. Do not copy the local preview database, fake
mailbox or preview server. No paid-account scheduler changes are required.

Startup creates four new tables (`student_slot`, `student_booking`,
`student_access`, `student_mail`). Existing room-booking records are unchanged.
The building-report integration uses the new tables; schema setup must succeed
before the next scheduled report. Inspect the new public page, supporter login
page and existing F@F booking page after reloading. Do not create real test
bookings or send test emails.

No dates are published automatically. After checking Calendly, Sungji or Marilena
can add the agreed availability in their portal. Configure in-person availability
only for actual scheduled venue dates. Keep the information-page wording and any
external advert consistent with the 45-minute session and 10am deadline.

Rollback source to `af94cd2` and reload if necessary. The new tables remain, so
bookings already accepted must still be honoured and managed. Do not delete the
tables or lose student records as part of rollback. Switching source back restores
the old Calendly link, so avoid overlapping live availability during any rollback.

## Verification

Run from the `room_booking` directory, against a temporary database and no .env:

```sh
APP_ENV_FILE=/nonexistent ENABLE_EMAIL=false RENDER=1 \
RENDER_DISK_PATH="$(mktemp -d)" venv/bin/python -m unittest discover -s tests -q
```

The updated suite covers 22 student-support tests, including password isolation,
missing configuration, obsolete email links, rotation, rate limits and shared-admin
exclusion. The full updated run had 94 tests: 93 passed and one existing test
was skipped. The other student-support tests cover double-booking races, expiry, confirmation, routing,
CSRF, shared-admin exclusion, cancellation, publication/date restrictions, meeting
links, reception privacy, the aggregate mobility flag and answer retention. Browser checks use only
fictional data in a localhost preview with captured outgoing email.
