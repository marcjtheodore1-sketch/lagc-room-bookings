"""Yoga must stay bookable on Fridays that have no rooms scheduled.

Yoga is booked through the room-booking flow, but yoga sessions and room
availability are separate schedules — September 2026 runs yoga on Fridays with
no rooms at all. Two things in the front end make those dates reachable:

  * the date list merges in yoga dates that the room schedule doesn't have
  * the room step keeps rendering when there are no rooms, so the yoga card
    still appears

If either is removed, yoga silently becomes impossible to book on those dates
while every page still looks fine, so both are pinned here. Source-level
assertions, matching the approach already used in test_august_schedule.py.
"""

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_app_js():
    with open(os.path.join(APP_DIR, 'static', 'js', 'app.js'), encoding='utf-8') as f:
        return f.read()


class YogaBookingReachableTest(unittest.TestCase):
    def test_yoga_only_dates_are_added_to_the_date_list(self):
        source = read_app_js()
        self.assertIn('mergeYogaDatesIntoFridays', source,
                      'yoga-only Fridays must be merged into the date list')
        # ...and actually called during start-up, not just defined
        self.assertRegex(
            source,
            r'await Promise\.all\(\[loadFridays\(\), loadYogaSessions\(\)\]\);\s*\n\s*mergeYogaDatesIntoFridays\(\);',
            'mergeYogaDatesIntoFridays() must run after both loads, before rendering',
        )

    def test_room_step_still_renders_with_no_rooms(self):
        """The old early return hid the yoga card on yoga-only Fridays."""
        source = read_app_js()
        match = re.search(r'function renderRooms\(\)\s*\{(.*?)\n\}', source, re.S)
        self.assertIsNotNone(match, 'renderRooms() not found')
        body = match.group(1)
        self.assertNotIn('No rooms available on this date', body,
                         'renderRooms() must not bail out when a date has no rooms')

    def test_yoga_card_books_in_place_rather_than_leaving_the_flow(self):
        source = read_app_js()
        self.assertIn('onclick="selectYoga()"', source)
        self.assertNotIn("/yoga#yoga-register", source,
                         'yoga is booked in this flow, not on a separate page')

    def test_yoga_sessions_exist_for_dates_without_rooms(self):
        """Guards the real-world case: yoga in September, rooms only to August."""
        with tempfile.TemporaryDirectory() as disk:
            env = {
                **os.environ,
                'RENDER': '1',
                'RENDER_DISK_PATH': disk,
                'ENABLE_EMAIL': 'false',
                'PYTHONPATH': APP_DIR,
            }
            result = subprocess.run(
                [sys.executable, '-c', textwrap.dedent("""
                    import json, app
                    with app.app.app_context():
                        sessions = [s['date'] for s in app.get_yoga_availability()]
                        rooms = set(app.get_room_schedule_ids())
                    print(json.dumps({
                        'yoga_only': sorted(d for d in sessions if d not in rooms),
                        'any_yoga': bool(sessions),
                    }))
                """)],
                cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            import json
            payload = json.loads(result.stdout.strip().splitlines()[-1])

        if not payload['any_yoga']:
            self.skipTest('no upcoming yoga sessions configured')
        # Not a failure if they happen to align, but if they don't, the front
        # end must be the thing making those dates reachable.
        if payload['yoga_only']:
            self.assertIn('mergeYogaDatesIntoFridays', read_app_js())


if __name__ == '__main__':
    unittest.main()
