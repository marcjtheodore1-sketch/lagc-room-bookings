import unittest

from test_attendee_booking_experience import run_isolated


class OnlineYogaRebookingTest(unittest.TestCase):
    def test_private_link_copies_unchanged_answers_and_requests_fresh_agreement(self):
        result = run_isolated(r"""
            import re
            from unittest.mock import patch
            from werkzeug.security import generate_password_hash
            from app import app
            from online_yoga_questions import DEFAULT_QUESTIONS, reusable_answers

            root = '/online-yoga'
            admin = root + '/admin'
            organiser = app.test_client()
            member = app.test_client()
            unrelated = app.test_client()
            app.config.update(TESTING=True, ONLINE_YOGA_SECURE_COOKIE=False,
                              ONLINE_YOGA_PASSWORD_HASH=generate_password_hash('example only'))

            def csrf(client, path):
                page = client.get(path)
                assert page.status_code == 200, page.status_code
                return re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]

            login = admin + '/login'
            assert organiser.post(login, data={'csrf_token':csrf(organiser,login),
                                               'password':'example only'}).status_code == 303
            authorised = csrf(organiser, admin)
            assert organiser.post(admin + '/sessions', data={
                'csrf_token':authorised, 'dates':'2099-01-07\n2099-01-14',
                'start':'09:00','end':'10:00','capacity':'4','publish':'yes',
                'meet_url':'https://meet.google.com/abc-defg-hij',
            }).status_code == 303
            original = dict(csrf_token=csrf(member,root), date='2099-01-07', name='Example Person',
                            email='example@example.test', form_revision='1',
                            answer_experience='A little', answer_adapt='Offer a seated option',
                            answer_avoid='Avoid long standing sequences', answer_access='Speak a little slower',
                            answer_agree='yes')
            with patch('online_yoga.threading.Thread'):
                book = member.post(root+'/register', data=original)
            assert book.status_code == 303, book.text
            private_path = book.location + '/book-again'
            receipt = member.get(book.location)
            assert private_path in receipt.text and 'Book another class using my previous answers' in receipt.text
            invalid = root + '/booking/' + 'x'*43 + '/book-again'
            assert unrelated.get(invalid).status_code==404
            public = unrelated.get(root+'?email=example@example.test&date=2099-01-14')
            assert 'Offer a seated option' not in public.text
            # A browser starting from the email link can use the exact previous
            # booking, even if there is no cookie from the first registration.
            page = unrelated.get(private_path+'?date=2099-01-14')
            assert 'Offer a seated option' in page.text and 'Speak a little slower' in page.text
            assert 'Avoid long standing sequences' in page.text
            assert 'value="A little" selected' in page.text
            assert 'value="2099-01-14" selected' in page.text
            assert 'value="example@example.test" readonly' in page.text
            assert 'no-store' in page.headers['Cache-Control']
            assert page.headers['Referrer-Policy']=='no-referrer'
            assert 'noindex' in page.headers['X-Robots-Tag']
            assert 'checked' not in re.search(r'<input type="checkbox" name="answer_agree"[^>]+>',page.text)[0]
            payload = {**original, 'csrf_token':csrf(unrelated,private_path), 'date':'2099-01-14'}
            assert unrelated.post(private_path,data={**payload,'email':'another@example.test'}).status_code==400
            assert unrelated.post(private_path,data={**payload,'answer_agree':''}).status_code==400

            assert organiser.post(admin+'/questions',data={
                'key':'adapt','csrf_token':authorised,'form_revision':1,'kind':'long','enabled':'yes',
                'label':'What equipment would you like to use?',
            }).status_code == 303
            changed = unrelated.get(private_path)
            assert 'What equipment would you like to use?' in changed.text
            assert 'Offer a seated option' not in changed.text and 'Speak a little slower' in changed.text
            stale = unrelated.post(private_path,data=payload)
            assert stale.status_code==409 and 'Offer a seated option' not in stale.text
            with patch('online_yoga.threading.Thread'):
                next_booking = unrelated.post(private_path,data={
                    **payload, 'form_revision':'2', 'answer_adapt':'A chair', 'answer_access':'Short instructions',
                })
            assert next_booking.status_code==303
            renewed = unrelated.get(next_booking.location+'/book-again')
            assert 'A chair' in renewed.text and 'Short instructions' in renewed.text and 'Speak a little slower' not in renewed.text
            assert 'Speak a little slower' in unrelated.get(private_path).text
            archived = reusable_answers(DEFAULT_QUESTIONS, [
                {'question':DEFAULT_QUESTIONS[0]['label'], 'value':'A little'},
                {'question':DEFAULT_QUESTIONS[4]['label'], 'value':'Yes'},
            ])
            assert archived=={'answer_experience':'A little'}
        """)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
