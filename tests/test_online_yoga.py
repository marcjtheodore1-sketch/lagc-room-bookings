import unittest

from test_attendee_booking_experience import run_isolated


class OnlineYogaTest(unittest.TestCase):
    def test_organiser_and_registration_flow(self):
        result = run_isolated("""
            import re
            from concurrent.futures import ThreadPoolExecutor
            from unittest.mock import patch
            from werkzeug.security import generate_password_hash
            from app import app

            app.config.update(
                TESTING=True,
                ONLINE_YOGA_PASSWORD_HASH=generate_password_hash('example organiser password'),
                ONLINE_YOGA_SECURE_COOKIE=False,
            )
            organiser, visitor = app.test_client(), app.test_client()
            root = '/online-yoga'
            link = 'https://meet.google.com/abc-defg-hij'
            other = 'https://meet.google.com/xyz-abcd-efg'

            def csrf(client, url):
                response = client.get(url)
                assert response.status_code == 200, response.status_code
                field = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
                if field:
                    return field[1]
                with client.session_transaction() as browser_session:
                    return browser_session['online_yoga_csrf']

            assert visitor.get(root + '/admin').status_code == 303
            token = csrf(organiser, root + '/admin/login')
            assert organiser.post(root + '/admin/login', data={
                'password': 'example organiser password',
            }).status_code == 400
            assert organiser.post(root + '/admin/login', data={
                'password': 'example organiser password', 'csrf_token': token,
            }).status_code == 303
            assert organiser.get('/admin').location.endswith('/admin/login')
            token = csrf(organiser, root + '/admin')
            details = dict(start='09:00', end='10:00', capacity='1', public_notes='Chair nearby',
                           joining_notes='Private joining notes', meet_url=link)
            edit = root + '/admin/sessions'
            payload = {**details, 'dates': '2099-01-07\\n2099-01-14 ' + other, 'publish': 'yes'}
            assert organiser.post(edit, data={**payload, 'csrf_token': token}).status_code == 303
            assert organiser.post(edit, data={**payload, 'csrf_token': token}).status_code == 409
            assert organiser.post(edit, data={**payload, 'dates': '2099-01-21',
                                              'meet_url': 'https://example.test/',
                                              'csrf_token': token}).status_code == 400
            assert organiser.post(edit, data={**payload, 'dates': '2099-01-21',
                                              'publish': '', 'csrf_token': token}).status_code == 303
            calendar = visitor.get(root + '/calendar.json')
            assert [(row['date'], row['status']) for row in calendar.json if row['date'].startswith('2099')] == [
                ('2099-01-07', 'open'), ('2099-01-14', 'open')]
            for public in (calendar, visitor.get(root + '?date=2099-01-07')):
                assert link not in public.text and other not in public.text
                assert 'Private joining notes' not in public.text
            assert 'value="2099-01-07" selected' in visitor.get(root + '?date=2099-01-07').text
            assert '/online-yoga' in visitor.get('/yoga').text

            def book(client, email, day='2099-01-07'):
                token = csrf(client, root)
                return client.post(root + '/register', data={
                    'csrf_token': token, 'date': day, 'email': email, 'name': 'Example Participant',
                    'experience': 'No', 'adjustments': 'Seated options', 'agree': 'yes',
                })

            with patch('app.send_confirmation_email'):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    submissions = [
                        pool.submit(book, app.test_client(), 'attendee1@example.test'),
                        pool.submit(book, app.test_client(), 'attendee2@example.test'),
                    ]
                    responses = [request.result() for request in submissions]
                assert sorted(response.status_code for response in responses) == [303, 409]
                receipt = next(response.location for response in responses if response.status_code == 303)
                assert link in visitor.get(receipt).text
                assert 'Private joining notes' in visitor.get(receipt).text
                assert visitor.get(root + '/booking/' + 'x' * 43).status_code == 404
                assert visitor.get(receipt).headers['Referrer-Policy'] == 'no-referrer'
                assert 'no-store' in visitor.get(receipt).headers['Cache-Control']
                token = csrf(visitor, receipt)
                assert visitor.post(receipt, data={'csrf_token': token}).status_code == 303
                assert link not in visitor.get(receipt).text
                assert book(visitor, 'attendee3@example.test').status_code == 303
                assert book(visitor, 'attendee3@example.test').status_code == 409
                second = book(visitor, 'attendee3@example.test', '2099-01-14')
                assert other in visitor.get(second.location).text
                assert book(visitor, 'attendee3@example.test', '2099-01-21').status_code == 409
                admin = organiser.get(root + '/admin').text
                assert 'Seated options' in admin
                class_url = re.search(r'action="(/online-yoga/admin/sessions/\\d+)"', admin.split('2099, 9am')[1])[1]
                token = csrf(organiser, root + '/admin')
                assert organiser.post(class_url, data={**details, 'status': 'draft',
                                                       'csrf_token': token}).status_code == 400
                assert organiser.post(class_url, data={**details, 'status': 'published',
                                                       'meet_url': other, 'csrf_token': token}).status_code == 303
                assert organiser.post(class_url, data={'action': 'cancel', 'csrf_token': token}).status_code == 303
                assert '2099-01-07' not in visitor.get(root + '/calendar.json').text
                assert organiser.post(root + '/admin/logout', data={'csrf_token': token}).status_code == 303
                assert organiser.get(root + '/admin').status_code == 303
        """)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
