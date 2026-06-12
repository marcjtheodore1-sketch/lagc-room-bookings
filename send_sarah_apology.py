"""
One-off script: apologise to Sarah Hill about her Friday 19 June 2026 booking
in The Loft, which was listed in error (LAGC team have first-aid training in
The Loft that day, so the space is taken).

Run this ONCE on the server, from the room_booking folder:

    cd ~/lagc-room-bookings/room_booking
    venv/bin/python send_sarah_apology.py          # dry run: shows who it found, sends nothing
    venv/bin/python send_sarah_apology.py --send    # actually send the email + cancel the booking

(If your virtualenv lives elsewhere, use whichever python/venv you normally use
 to run app.py — e.g. ../venv/bin/python.)

It is safe to run the dry run as many times as you like. The --send step will
not re-send if the booking has already been cancelled by this script.
"""

import sys
from datetime import date, datetime

from app import app, db, Booking, Room, send_confirmation_email

TARGET_DATE = date(2026, 6, 19)

# Optional: a link for Sarah to book a different room. Leave as None to omit the
# link from the email, or set it to your live booking page, e.g.
# BOOKING_URL = "https://yourname.pythonanywhere.com/book"
BOOKING_URL = None


def find_sarah(bookings):
    """Pick the booking that looks like Sarah Hill's."""
    for b in bookings:
        name = (b.user_name or "").lower()
        if "sarah" in name and "hill" in name:
            return b
    # Fallback: just "sarah" if "hill" wasn't entered
    for b in bookings:
        if "sarah" in (b.user_name or "").lower():
            return b
    return None


def build_email(name, room_name):
    subject = "An apology about your Friday 19th June booking"

    lines = [
        f"Dear {name},",
        "",
        "I'm really sorry, but I need to let you know about a mix-up with your "
        f"booking for {room_name} on Friday 19th June.",
        "",
        "The Loft was listed as available that day by mistake. Some of our LAGC "
        "team are doing first aid training in The Loft on the 19th, so the space "
        "is taken and we aren't able to offer it for booking that day. I've had "
        "to cancel your booking for The Loft, and I'm sorry for the confusion "
        "and any inconvenience this causes.",
        "",
        "The good news is that Fridays @ Farringdon is still running as normal on "
        "the 19th, and our other rooms are open that day:",
        "",
        '  - Room 4.4 "Rose" — your own private individual focus room (30-minute slots)',
        '  - Room 4.2 "Indigo" — a quiet shared workspace',
        "",
    ]

    if BOOKING_URL:
        lines.append(f"You're very welcome to book one of these instead here: {BOOKING_URL}")
    else:
        lines.append(
            "You're very welcome to book one of these instead on the same booking "
            "page you used before, and of course you're welcome to just come along "
            "and use the shared community space."
        )

    lines += [
        "",
        "Thank you so much for your understanding, and apologies again.",
        "",
        "Warm wishes,",
        "The LAGC Fridays @ Farringdon team",
    ]
    return subject, "\n".join(lines)


def main():
    do_send = "--send" in sys.argv

    with app.app_context():
        bookings = (
            Booking.query.filter(
                Booking.booking_date == TARGET_DATE,
                Booking.cancelled_at.is_(None),
            ).all()
        )

        print(f"Active bookings on {TARGET_DATE.isoformat()}: {len(bookings)}")
        for b in bookings:
            room = db.session.get(Room, b.room_id)
            room_name = room.name if room else f"room #{b.room_id}"
            print(f"  - {b.user_name} <{b.user_email}> in {room_name}")

        sarah = find_sarah(bookings)
        if not sarah:
            print("\nCould not find an active booking for Sarah Hill on this date.")
            print("Nothing sent. (Has it already been cancelled, or is the name spelled differently?)")
            return

        room = db.session.get(Room, sarah.room_id)
        room_name = room.name if room else "The Loft"
        first_name = (sarah.user_name or "Sarah").split()[0]

        subject, body = build_email(first_name, room_name)

        print("\n" + "=" * 60)
        print(f"To:      {sarah.user_name} <{sarah.user_email}>")
        print(f"Room:    {room_name}")
        print(f"Subject: {subject}")
        print("-" * 60)
        print(body)
        print("=" * 60)

        if not do_send:
            print("\nDRY RUN — nothing sent. Re-run with --send to email Sarah and cancel her booking.")
            return

        ok = send_confirmation_email(sarah.user_email, subject, body)
        if not ok:
            print("\n[ERROR] Email failed to send. Booking NOT cancelled. Check the SMTP output above.")
            return

        sarah.cancelled_at = datetime.utcnow()
        db.session.commit()
        print(f"\nDone. Apology emailed to {sarah.user_email} and the Loft booking has been cancelled.")


if __name__ == "__main__":
    main()
