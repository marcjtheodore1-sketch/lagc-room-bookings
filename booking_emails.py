"""Short participant emails with cancellation before guidance, without duplicate footers."""
import re
from html import escape


def visit_guidance(base_url):
    return (
        'Before you visit\n'
        f'Building guide and emergency procedures: {base_url}/help-sheet\n'
        'During a fire alarm, follow the building team\'s evacuation instructions. Do not use lifts.\n\n'
        'Tell LAGC about mobility needs when booking. Pan Macmillan needs at least 24 hours\' '
        'notice to plan access, evacuation and cover from fire wardens. If your needs change, contact us promptly.\n\n'
        'Volunteers are hosts, not carers. Bring your own support if you need personal care or supervision.\n\n'
        'Be kind, respect the space and follow our community guidelines (a condition of attending):\n'
        'https://www.londonautismgroupcharity.org/community-guidelines\n'
        'Repeated missed bookings without cancelling, or repeated breaches of booking rules or guidelines, '
        'may lead to suspension or a ban. There is no automatic three-strikes rule.'
    )


def extra_venue_information(template, values, base_url):
    """Retain custom venue instructions/links, removing known repeated boilerplate.

    The saved template is never overwritten. In particular, health/safety/privacy
    links and date-specific access notes must not disappear during this change.
    """
    from app import format_confirmation_message
    lines = format_confirmation_message(template, **values).splitlines()
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.search(r'^(dear |hello |hi |room:|location:|date:|time:|email:|your booking|to cancel|'
                     r'thank you for|book again|warm wishes|best wishes|london autism group charity$)', line, re.I):
            continue
        if line == values['cancel_url'] or line.startswith(base_url + '/cancel/'):
            continue
        if any(part in line for part in (base_url + '/book', base_url + '/help-sheet', '/community-guidelines')):
            continue
        if re.search(r'Kirsty|community guidelines|cancell?ation|cancel your booking|Thursday.*10|'
                     r'fire.warden|three.strikes|suspension or a ban|repeated.*missing|'
                     r'following them is a condition|treating.*kindness|booking has been confirmed', line, re.I):
            continue
        # Known venue copy can be shorter without losing its instructions.
        if line.startswith('The location of the Smithson Building'):
            url = re.search(r'https?://\S+', line)
            line = 'Map: ' + url[0] if url else line
        if line.startswith('Upon arrival, please sign in at reception'):
            line = 'On arrival: sign in at reception. A LAGC volunteer will meet you and take you upstairs.'
        if line.startswith('Please read the Smithson Building health and safety guidelines:'):
            line = line.replace('Please read the Smithson Building health and safety guidelines:', 'Smithson health and safety:')
        if line.startswith('The closest tube station is Farringdon'):
            continue  # Already in the address above.
        if line not in result:
            result.append(line)
    return '\n'.join(result)


def confirmation_text(booking, base_url):
    from app import (booking_time_display, reminder_date_display, get_room_note,
                     get_setting, get_default_confirmation_message)
    start, end = booking_time_display(booking)
    def british_time(value):
        return re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM)',
                      lambda m: str(int(m[1])) + ('.' + m[2] if m[2] != '00' else '') + m[3].lower(), value)
    start, end = british_time(start), british_time(end)
    room = booking.room
    cancel_url = f'{base_url}/cancel/{booking.cancel_token}'
    values = dict(name=booking.user_name, email=booking.user_email, room_name=room.name,
                  building_location=room.building_location, date=reminder_date_display(booking.booking_date),
                  start_time=start, end_time=end, cancel_url=cancel_url)
    message = (
        f'Hi {booking.user_name},\n\nYour Fridays @ Farringdon booking is confirmed.\n\n'
        f'{values["date"]}, {start} to {end}\n{room.name} - {room.building_location}\n'
        'The Smithson, 6 Briset Street, London EC1M 5NR (Farringdon station, about 5 minutes on foot).\n\n'
        f'CAN\'T COME? CANCEL HERE\n{cancel_url}\n'
        'Cancel as soon as you know. This frees the place and avoids unnecessary fire-warden arrangements, '
        'helping protect our agreement and relationship with Pan Macmillan.\n'
    )
    if booking.companion_names:
        message += f'\nComing with you: {booking.companion_names}\n'
    note = get_room_note(booking.booking_date.isoformat(), room.id)
    if note:
        message += f'\nImportant for this room and date\n{note}\n'
    if room.room_type == 'slot':
        message += f'\nThis booking is for {room.name} only. Book any other room separately.\n'
    extra = extra_venue_information(get_setting('confirmation_message', get_default_confirmation_message()), values, base_url)
    if extra:
        message += f'\nVenue information\n{extra}\n'
    message += '\n' + visit_guidance(base_url)
    message += (f'\n\nBook another room or Friday: {base_url}/book\n'
                'Complete new bookings before Thursday at 10am (London time).\n\n'
                'London Autism Group Charity')
    return message


def html_message(message):
    """Ordinary spaces, fluid paragraphs and one clear cancellation button."""
    def links(text):
        def label(url):
            if '/help-sheet' in url:
                return 'Read the building guide'
            if 'drive.google.com' in url:
                return 'Read the guidelines'
            if '/community-guidelines' in url:
                return 'Read our community guidelines'
            if 'maps.app.goo.gl' in url:
                return 'View map'
            if '/reminders/manage/' in url:
                return 'Manage reminders'
            if url.endswith('/book'):
                return 'Book now'
            return url
        chunks = re.split(r'(https?://[^\s<>]+)', text)
        return ''.join('<a style="overflow-wrap:anywhere" href="' + escape(chunk, quote=True) + '">' + escape(label(chunk)) + '</a>'
                       if chunk.startswith(('https://', 'http://')) else escape(chunk)
                       for chunk in chunks)
    blocks = []
    for paragraph in message.split('\n\n'):
        lines = paragraph.splitlines()
        if not lines:
            continue
        if "CAN'T COME? CANCEL HERE" in lines[0]:
            url = lines[1]
            blocks.append('<p><a href="' + escape(url, quote=True) + '" style="display:inline-block;padding:12px 18px;'
                          'background:#315ea8;color:white;text-decoration:none;border-radius:6px;font-weight:bold">'
                          'View or cancel your booking</a></p>')
            if len(lines) > 2:
                blocks.append('<p>' + links(' '.join(lines[2:])) + '</p>')
        else:
            blocks.append('<p>' + '<br>'.join(links(line) for line in lines) + '</p>')
    return '<div style="font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#222">' + ''.join(blocks) + '</div>'
