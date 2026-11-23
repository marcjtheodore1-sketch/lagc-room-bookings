import unittest

from test_attendee_booking_experience import run_isolated


class YogaEditorMailTest(unittest.TestCase):
    def test_form_updates_and_confirmation_uses_current_session_details(self):
        result = run_isolated(r"""
            import re
            import smtplib
            from unittest.mock import patch
            from werkzeug.security import generate_password_hash
            from app import app, run_online_yoga_mail_job

            app.config.update(
                TESTING=True, ONLINE_YOGA_PASSWORD_HASH=generate_password_hash('sample only'),
                ONLINE_YOGA_SECURE_COOKIE=False, ENABLE_EMAIL=True,
                SMTP_USER='miles.lagc@gmail.com', SMTP_PASSWORD='simulated',
                SMTP_FROM='other@example.test',
            )
            organiser = app.test_client()
            member = app.test_client()
            root = '/online-yoga'
            original_link = 'https://meet.google.com/abc-defg-hij'
            new_link = 'https://meet.google.com/xyz-abcd-efg'

            def token(client, path):
                response = client.get(path)
                return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]

            login = root + '/admin/login'
            admin = root + '/admin'
            editor = admin + '/questions'
            assert organiser.post(login, data={
                'csrf_token': token(organiser, login), 'password': 'sample only',
            }).status_code == 303
            csrf = token(organiser, admin)
            assert 'Please tell us anything Marlijn should know' in organiser.get(admin).text
            date = '2099-01-06'
            defaults = dict(start='09:00', end='10:00', capacity='5', public_notes='Have water nearby',
                            joining_notes='Join 5 minutes early', meet_url=original_link+'?authuser=1&hs=12')
            assert organiser.post(admin+'/sessions', data={**defaults,'csrf_token':csrf,'dates':date}).status_code == 303
            assert date not in member.get(root+'/calendar.json').text
            html = organiser.get(admin).text
            exact = re.search(r'id="session-(\d+)"[^>]*>\s*<summary>[^<]*January 2099',html)[1]
            assert organiser.post(admin+'/sessions/'+exact, data={**defaults,'csrf_token':csrf,'status':'published'}).status_code == 303
            public = member.get(root+'?date='+date)
            assert date in member.get(root+'/calendar.json').text
            assert original_link not in public.text and 'Join 5 minutes early' not in public.text
            member_csrf=token(member,root)

            edit = dict(csrf_token=csrf, key='adapt', form_revision=1, label='What would make movement easier?',
                        kind='long', enabled='yes', help_text='Think about seated options')
            assert member.post(editor,data={**edit,'csrf_token':member_csrf}).status_code == 303
            assert organiser.post(editor,data=edit).status_code == 303
            assert organiser.post(editor,data=edit).status_code == 409
            added=dict(csrf_token=csrf,key='new',form_revision=2,label='How will you take part?',
                       kind='choice',choices='Seated\nStanding',required='yes',enabled='yes')
            assert organiser.post(editor,data={**added,'choices':'Same\nSame'}).status_code == 400
            assert organiser.post(editor,data=added).status_code == 303
            public = member.get(root).text
            assert 'What would make movement easier?' in public and 'Think about seated options' in public
            assert 'How will you take part?' in public and 'Phone number' not in public
            new_field=re.search(r'<select name="(answer_[a-f0-9]+)" required>', public)[1]
            submitted=dict(csrf_token=member_csrf,date=date,name='Example Participant',
                           email='example@example.test',form_revision=3,answer_agree='yes',
                           answer_adapt='Seated options only')
            assert member.post(root+'/register',data=submitted).status_code == 400
            assert member.post(root+'/register',data={**submitted,new_field:'Other'}).status_code == 400
            assert member.post(root+'/register',data={**submitted,'form_revision':2,new_field:'Seated'}).status_code == 409
            with patch('online_yoga.threading.Thread') as launch:
                response=member.post(root+'/register',data={**submitted,new_field:'Seated'})
                assert response.status_code == 303
                assert launch.called
            receipt=response.location
            assert original_link in member.get(receipt).text

            # Rename a question after the booking. Its original wording and answer
            # remain attached to the booking and never appear in its email.
            assert organiser.post(editor,data={**edit,'form_revision':3,'label':'Any movement notes?'}).status_code == 303
            admin_html=organiser.get(admin).text
            assert 'Seated options only' in admin_html and 'What would make movement easier?' in admin_html
            assert 'What would make movement easier?' not in member.get(root).text
            # Simulate a worker seeing the job after the organiser changed its link.
            with patch('online_yoga.threading.Thread'):
                assert organiser.post(admin+'/sessions/'+exact,
                    data={**defaults,'meet_url':new_link,'csrf_token':csrf,'status':'published'}).status_code==303
            with app.app_context(), patch('app.send_smtp_message',side_effect=smtplib.SMTPRecipientsRefused({})) as smtp:
                assert run_online_yoga_mail_job()['failed']==1
                assert smtp.call_count==1
                assert run_online_yoga_mail_job()['failed']==0
            retry=re.search(r'action="(/online-yoga/admin/confirmations/\d+/retry)"',organiser.get(admin).text)[1]
            with patch('online_yoga.threading.Thread'):
                assert organiser.post(retry,data={'csrf_token':csrf}).status_code==303
            with app.app_context(), patch('app.send_smtp_message') as smtp:
                assert run_online_yoga_mail_job()['sent']==1
                assert run_online_yoga_mail_job()['sent']==0
                assert smtp.call_count==1
                mime = smtp.call_args.args[0]
                assert str(mime['From']) == 'London Autism Group Charity <miles.lagc@gmail.com>'
                assert mime['Reply-To'] == 'miles.lagc@gmail.com'
                assert mime['To'] == 'example@example.test'
                plain, html = [part.get_payload(decode=True).decode('utf-8') for part in mime.get_payload()]
                for content in (plain,html):
                    assert '9am to 10am' in content and 'Join 5 minutes early' in content
                    assert new_link in content and original_link not in content
                    assert receipt in content and 'cancel your place' in content
                    assert 'Seated options only' not in content
            assert 'We sent your confirmation from miles.lagc@gmail.com' in member.get(receipt).text
            assert member.post(receipt,data={'csrf_token':member_csrf}).status_code==303
            assert 'Your place has been cancelled' in member.get(receipt).text
        """)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
