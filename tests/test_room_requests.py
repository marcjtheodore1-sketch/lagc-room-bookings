"""Room quantities, editable previews and deliberate sending with mocked SMTP."""
import unittest
from test_attendee_booking_experience import run_isolated

FIXTURE = '''
from copy import deepcopy
from unittest.mock import patch
from app import app,db,Room,Booking,RoomRequest,EmailDeliveryUncertain,get_room_schedule_ids
from room_requests import TO,CC,CONTRACT_TO
app.config.update(ENABLE_EMAIL=True,SMTP_USER='sender@example.test',SMTP_PASSWORD='dummy',SMTP_FROM='sender@example.test')
client=app.test_client()
with client.session_transaction() as session: session['admin_logged_in']=True
with app.app_context():
    rooms=[Room(name=name,room_type='open') for name in ('Rose','Clerkenwell','Loft')]
    db.session.add_all(rooms);db.session.commit()
    payload=dict(request_id='a-new-room-request-1234567890',rooms=[
        dict(room_id=rooms[0].id,count=4),dict(room_id=rooms[1].id,count=3),
        dict(room_id=rooms[2].id,count=1)],notes='')
'''


class RoomRequestTest(unittest.TestCase):
    def check_case(self, code):
        result=run_isolated(FIXTURE+code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_counts_without_dates_generate_personal_email_and_do_not_book_or_send(self):
        self.check_case('''
    before=get_room_schedule_ids()
    with patch('app.send_smtp_message') as smtp:
        options=client.get('/api/admin/room-requests/options').json
        assert len(options['rooms'])==3 and len(options['request_id'])>=24
        assert options['recipient_names']=={'to':['Emma','Martha'],'cc':['Florence']}
        assert not {'start_date','end_date'} & set(options)
        assert all(set(person)=={'id','name'} for person in options['test_recipients'])
        preview=client.post('/api/admin/room-requests/preview',json=payload).json
        assert preview['status']=='draft' and preview['delivery_mode']=='live'
        assert preview['to']==list(TO) and preview['cc']==list(CC)
        assert 'Rose: 4 Fridays' in preview['body'] and 'Clerkenwell: 3 Fridays' in preview['body']
        assert 'Loft: 1 Friday' in preview['body'] and 'Fridays covered' not in preview['body']
        assert 'what alternatives we can consider please?' in preview['body']
        assert preview['body'].endswith('Florence Perdriel\\nLondon Autism Group Charity')
        assert CONTRACT_TO not in preview['body'] and 'Chris Papadopoulos' not in preview['body']
        assert 'share the hire agreement with Chris as you usually do' in preview['body']
        assert preview['subject']=='Fridays @ Farringdon: room booking'
        again=client.post('/api/admin/room-requests/preview',json=payload).json
        assert again['review_key']==preview['review_key'] and RoomRequest.query.count()==1
        assert Booking.query.count()==0 and get_room_schedule_ids()==before
        html=client.get('/admin').text
        assert 'Preview email' in html and 'Check before sending' in html and 'rr-test-target' in html
        smtp.assert_not_called()
        stranger=app.test_client()
        for path in ['options','history']:
            assert stranger.get('/api/admin/room-requests/'+path).status_code==302
        for path in ['preview','send']:
            assert stranger.post('/api/admin/room-requests/'+path,json=payload).status_code==302
''')

    def test_validation_blocks_bad_counts_old_date_or_test_forms_and_recipient_overrides(self):
        self.check_case('''
    invalid=[dict(payload,rooms=[]),dict(payload,rooms=None),dict(payload,notes='x'*2001),
        dict(payload,request_id='bad'),dict(payload,start_date='2099-01-01'),
        dict(payload,period='x'*161),dict(payload,period='two\\nlines'),dict(payload,period=123),
        dict(payload,delivery_mode='test',test_recipients=['emma']),dict(payload,to=list(TO)),
        dict(payload,subject='Only subject'),dict(payload,subject='bad\\r\\nBcc: someone',body='text'),
        dict(payload,subject='Okay',body=' '),dict(payload,subject='Okay',body='x'*12001)]
    for row in [dict(room_id=999,count=1),dict(room_id=True,count=1),dict(room_id=rooms[0].id,count=True),
        dict(room_id=rooms[0].id,count=0),dict(room_id=rooms[0].id,count=53),dict(room_id=rooms[0].id,count=1.5),
        dict(room_id=rooms[0].id,count=1,dates=['2099-01-01'])]: invalid.append(dict(payload,rooms=[row]))
    invalid.append(dict(payload,rooms=[payload['rooms'][0]]*2))
    with patch('app.send_smtp_message') as smtp:
        for item in invalid:
            response=client.post('/api/admin/room-requests/preview',json=item)
            assert response.status_code==400,(item,response.json)
        assert client.post('/api/admin/room-requests/preview',json=payload,headers={'Origin':'https://evil.example'}).status_code==400
        assert client.post('/api/admin/room-requests/preview',data={'notes':'x'}).status_code==400
        smtp.assert_not_called()
    assert RoomRequest.query.count()==0
''')

    def test_edited_email_gets_new_key_old_preview_cannot_send_and_exact_reviewed_text_is_sent(self):
        self.check_case('''
    original=client.post('/api/admin/room-requests/preview',json=payload).json
    edited=dict(payload,subject='Our next room request',body='Hello Emma and Martha,\\n\\nCould we have tea & access <details>?\\n\\nMany thanks,\\nFlorence Perdriel')
    preview=client.post('/api/admin/room-requests/preview',json=edited).json
    assert preview['review_key']!=original['review_key'] and RoomRequest.query.count()==1
    assert preview['body']==edited['body'] and preview['subject']==edited['subject']
    with patch('app.send_smtp_message') as smtp:
        assert client.post('/api/admin/room-requests/send',json=dict(review_key=original['review_key'],confirmed=True)).status_code==404
        smtp.assert_not_called()
    def inspect(message,recipients):
        assert recipients==list(TO+CC)
        assert message['To']==', '.join(TO) and message['Cc']==', '.join(CC)
        assert message['Reply-To']==CC[0] and message['Subject']==edited['subject']
        assert message.get_payload(0).get_payload(decode=True).decode('utf-8')==edited['body']
        html=message.get_payload(1).get_payload(decode=True).decode('utf-8')
        assert '&amp;' in html and '&lt;details&gt;' in html
        assert '&nbsp;' not in html and '<br>' not in html and 'width=' not in html
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.send_smtp_message',side_effect=inspect) as smtp:
        for change in [dict(body='changed'),dict(to=['other@example.test']),dict(confirmed=False)]:
            assert client.post('/api/admin/room-requests/send',json=dict(data,**change)).status_code==400
        response=client.post('/api/admin/room-requests/send',json=data)
        assert response.status_code==200,response.json
        assert response.json['request']['status']=='sent' and smtp.call_count==1
''')

    def test_duplicate_clicks_and_concurrent_sends_send_only_once(self):
        self.check_case('''
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    def inspect(message,recipients):
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        changed=client.post('/api/admin/room-requests/preview',json=dict(payload,subject='Changed',body='New text')).json
        assert changed['status']=='sending' and changed['body']==preview['body']
    with patch('app.send_smtp_message',side_effect=inspect) as smtp:
        assert client.post('/api/admin/room-requests/send',json=data).status_code==200
        again=client.post('/api/admin/room-requests/send',json=data)
        assert again.json['already_sent'] and smtp.call_count==1
    unchanged=client.post('/api/admin/room-requests/preview',json=dict(payload,subject='Changed',body='New text')).json
    assert unchanged['status']=='sent' and unchanged['body']==preview['body']
''')

    def test_fresh_request_can_use_same_quantities_again_without_resending_the_old_one(self):
        self.check_case('''
    first=client.post('/api/admin/room-requests/preview',json=payload).json
    with patch('app.send_smtp_message') as smtp:
        assert client.post('/api/admin/room-requests/send',json=dict(review_key=first['review_key'],confirmed=True)).status_code==200
        next_payload=dict(payload,request_id='another-room-request-1234567890')
        second=client.post('/api/admin/room-requests/preview',json=next_payload).json
        assert second['review_key']!=first['review_key'] and second['status']=='draft'
        assert second['body']==first['body']
        assert client.post('/api/admin/room-requests/send',json=dict(review_key=second['review_key'],confirmed=True)).status_code==200
        assert smtp.call_count==2
    assert RoomRequest.query.count()==2 and Booking.query.count()==0
''')

    def test_definite_failure_needs_new_review_and_uncertain_delivery_never_retries(self):
        self.check_case('''
    import smtplib
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.send_smtp_message',side_effect=smtplib.SMTPAuthenticationError(535,b'no')) as smtp:
        response=client.post('/api/admin/room-requests/send',json=data)
        assert response.status_code==502 and response.json['request']['status']=='failed'
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        assert smtp.call_count==1
    reviewed=client.post('/api/admin/room-requests/preview',json=payload).json
    assert reviewed['status']=='draft' and reviewed['review_key']!=preview['review_key']
    data=dict(review_key=reviewed['review_key'],confirmed=True)
    with patch('app.send_smtp_message',side_effect=EmailDeliveryUncertain('unknown')) as smtp:
        response=client.post('/api/admin/room-requests/send',json=data)
        assert response.status_code==502 and response.json['request']['status']=='uncertain'
        assert client.post('/api/admin/room-requests/preview',json=dict(payload,subject='Changed',body='New')).json['status']=='uncertain'
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        assert smtp.call_count==1
''')

    def test_disabled_mail_and_old_saved_test_or_date_previews_cannot_send(self):
        self.check_case('''
    import json
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.reminders_mail_ready',return_value=False),patch('app.send_smtp_message') as smtp:
        assert client.post('/api/admin/room-requests/send',json=data).status_code==503
        smtp.assert_not_called()
    record=RoomRequest.query.one()
    for old in [dict(delivery_mode='test',test_recipients=['chris'],start_date='2099-01-01'),dict(start_date='2099-01-01')]:
        record.payload=json.dumps(old);db.session.commit()
        with patch('app.send_smtp_message') as smtp:
            assert client.post('/api/admin/room-requests/send',json=data).status_code==409
            history=client.get('/api/admin/room-requests/history').json
            assert len(history)==1 and history[0]['status']=='draft'
            smtp.assert_not_called()
''')

    def test_legacy_room_aliases_do_not_create_duplicate_room_choices(self):
        self.check_case('''
    duplicate=Room(name='Room 4.7 "Clerkenwell"',room_type='open')
    db.session.add(duplicate);db.session.commit()
    options=client.get('/api/admin/room-requests/options').json['rooms']
    assert len(options)==3 and duplicate.id in [room['id'] for room in options]
    assert rooms[1].id not in [room['id'] for room in options] and Room.query.count()==4
    assert client.post('/api/admin/room-requests/preview',json=payload).status_code==400
    payload['rooms'][1]['room_id']=duplicate.id
    assert client.post('/api/admin/room-requests/preview',json=payload).status_code==200
''')

    def test_tests_go_only_to_selected_names_and_never_copy_the_venue(self):
        self.check_case('''
    from room_requests import TEST_RECIPIENTS
    for people in [['chris'],['florence'],['chris','florence']]:
        test_payload=dict(payload,delivery_mode='test',test_recipients=people)
        preview=client.post('/api/admin/room-requests/preview',json=test_payload).json
        expected=[TEST_RECIPIENTS[key][1] for key in sorted(people)]
        assert preview['to']==expected and preview['cc']==[] and preview['subject'].startswith('[TEST] ')
        assert preview['recipient_names']=={'to':[TEST_RECIPIENTS[key][0] for key in sorted(people)],'cc':[]}
        def inspect(message,recipients):
            assert recipients==expected
            assert message['To']==', '.join(expected) and message['Cc'] is None and message['Bcc'] is None
            assert message['Reply-To']==', '.join(expected)
            assert all(address not in str(message) for address in TO)
            assert message.get_payload(0).get_payload(decode=True).decode('utf-8')==preview['body']
        with patch('app.send_smtp_message',side_effect=inspect) as smtp:
            data=dict(review_key=preview['review_key'],confirmed=True)
            assert client.post('/api/admin/room-requests/send',json=data).status_code==200
            assert client.post('/api/admin/room-requests/send',json=data).json['already_sent']
            assert smtp.call_count==1
        again=client.post('/api/admin/room-requests/preview',json=test_payload).json
        assert again['status']=='draft' and again['review_key']!=preview['review_key']
    live=client.post('/api/admin/room-requests/preview',json=payload).json
    assert live['delivery_mode']=='live' and live['status']=='draft' and live['to']==list(TO)
    assert not live['subject'].startswith('[TEST]') and 'TEST ONLY:' not in live['body']
''')

    def test_edited_test_subject_is_labelled_and_recipient_changes_invalidate_the_old_selection(self):
        self.check_case('''
    test_payload=dict(payload,delivery_mode='test',test_recipients=['chris'],subject='Edited subject',body='Edited sample')
    preview=client.post('/api/admin/room-requests/preview',json=test_payload).json
    assert preview['subject']=='[TEST] Edited subject' and preview['body']=='Edited sample'
    switched=client.post('/api/admin/room-requests/preview',json=dict(test_payload,test_recipients=['florence'])).json
    assert switched['review_key']!=preview['review_key'] and switched['recipient_names']['to']==['Florence']
    invalid=[dict(delivery_mode='test',test_recipients=[]),dict(delivery_mode='test',test_recipients=['chris','chris']),
        dict(delivery_mode='test',test_recipients=['someone@example.test']),dict(delivery_mode='test',test_recipients=[{}]),
        dict(delivery_mode='live',test_recipients=['chris']),dict(delivery_mode='unknown')]
    with patch('app.send_smtp_message') as smtp:
        for changes in invalid:
            assert client.post('/api/admin/room-requests/preview',json=dict(payload,**changes)).status_code==400
        assert client.post('/api/admin/room-requests/send',json=dict(review_key=preview['review_key'],confirmed=True,test_recipients=['florence'])).status_code==400
        smtp.assert_not_called()
''')

    def test_florences_wording_optional_period_and_independent_room_quantities(self):
        self.check_case('''
    chosen=dict(payload,period='January 2027',rooms=[dict(room_id=rooms[0].id,count=4),
        dict(room_id=rooms[1].id,count=6),dict(room_id=rooms[2].id,count=7)])
    with patch('app.send_smtp_message') as smtp:
        response=client.post('/api/admin/room-requests/preview',json=chosen)
        assert response.status_code==200,response.json
        preview=response.json
        assert 'I am reaching out to agree on what rooms we can have for the January 2027 period.' in preview['body']
        assert 'If possible, could we get:' in preview['body']
        assert 'Clerkenwell: 6 Fridays' in preview['body'] and 'Loft: 7 Fridays' in preview['body']
        assert 'Fridays covered' not in preview['body'] and CONTRACT_TO not in preview['body']
        assert 'Chris Papadopoulos' not in preview['body'] and 'Many thanks 🙂' in preview['body']
        assert preview['subject']=='Fridays @ Farringdon: room booking'
        blank=client.post('/api/admin/room-requests/preview',json=dict(chosen,period='')).json
        assert 'for the next period.' in blank['body'] and '[date range]' not in blank['body']
        smtp.assert_not_called()
''')


if __name__=='__main__':
    unittest.main()
