"""Build the individual online-yoga emails sent through the booking Gmail account."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from booking_emails import html_message


YOGA_SENDER = 'miles.lagc@gmail.com'


def make_message(recipient, subject, body):
    message = MIMEMultipart('alternative')
    message['From'] = f'London Autism Group Charity <{YOGA_SENDER}>'
    message['Reply-To'] = YOGA_SENDER
    message['To'] = recipient
    message['Subject'] = subject
    message.attach(MIMEText(body, 'plain', 'utf-8'))
    message.attach(MIMEText(html_message(body, room_cancellation_button=False), 'html', 'utf-8'))
    return message


def confirmation_body(name, when, meet_url, joining_notes, booking_url):
    instructions = f'{joining_notes}\n\n' if joining_notes else ''
    return (
        f'Hi {name},\n\nYour place for online Gentle Yoga with Marlijn is confirmed.\n\n'
        f'When: {when} (UK time)\n'
        f'Join on Google Meet: {meet_url}\n\n'
        f'{instructions}'
        'You can choose how much to take part and rest whenever you like. '
        'Have a little space to move comfortably and a stable chair nearby if you’d like to practise seated.\n\n'
        f'View your booking or cancel your place: {booking_url}\n\n'
        'If you can’t come, please cancel to free your place for someone else.\n\n'
        'London Autism Group Charity'
    )
