"""Hourly task on the charity's paid PythonAnywhere account.

The free bookings host cannot run its own scheduled tasks. Install this script
on the charity account and put the matching trigger token in a mode-600 file
at ~/.farringdon-reminder-token. It does not access booking data directly.
"""
from pathlib import Path
from urllib.request import Request, urlopen


token_path = Path.home() / '.farringdon-reminder-token'
token = token_path.read_text(encoding='utf-8').strip()
if not token:
    raise RuntimeError('The Farringdon reminder token file is empty')

request = Request(
    'https://milestheodore.pythonanywhere.com/api/internal/send-reminders',
    data=b'',
    headers={'X-Reminder-Token': token},
    method='POST',
)
with urlopen(request, timeout=120) as response:
    print(response.read().decode('utf-8'))
