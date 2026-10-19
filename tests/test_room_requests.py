"""Venue preferences and deliberate, duplicate-safe sending with mocked SMTP."""
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
    dates=['2099-01-23','2099-01-30','2099-02-06','2099-02-13']
    payload=dict(start_date='2099-01-23',end_date='2099-02-13',rooms=[
        dict(room_id=rooms[0].id,mode='exact',dates=dates),
        dict(room_id=rooms[1].id,mode='flexible',count=3),
        dict(room_id=rooms[2].id,mode='flexible',count=1)],notes='')
'''


class RoomRequestTest(unittest.TestCase):
    def check_case(self, code):
        result=run_isolated(FIXTURE+code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_preview_supports_cross_month_exact_and_flexible_preferences_without_booking_or_mail(self):
        self.check_case('''
    before=get_room_schedule_ids()
    with patch('app.send_smtp_message') as smtp:
        options=client.get('/api/admin/room-requests/options').json
        assert len(options['rooms'])==3 and options['contract_to']==CONTRACT_TO
        response=client.post('/api/admin/room-requests/preview',json=payload)
        assert response.status_code==200,response.json
        preview=response.json
        assert preview['status']=='draft'
        assert preview['to']==list(TO) and preview['cc']==list(CC)
        assert 'Friday 23rd January 2099' in preview['body'] and 'Friday 13th February 2099' in preview['body']
        assert 'Clerkenwell: 3 of the 4 Fridays.' in preview['body']
        assert 'Loft: 1 of the 4 Fridays.' in preview['body']
        assert CONTRACT_TO in preview['body'] and 'subject to availability' in preview['body']
        again=client.post('/api/admin/room-requests/preview',json=payload).json
        assert again['review_key']==preview['review_key'] and RoomRequest.query.count()==1
        assert Booking.query.count()==0 and get_room_schedule_ids()==before
        assert client.get('/api/admin/room-requests/history').json[0]['body']==preview['body']
        assert 'Room Requests' in client.get('/admin').text
        smtp.assert_not_called()
        stranger=app.test_client()
        for path in ['options','history']:
            assert stranger.get('/api/admin/room-requests/'+path).status_code==302
        for path in ['preview','send']:
            assert stranger.post('/api/admin/room-requests/'+path,json=payload).status_code==302
''')

    def test_validation_rejects_impossible_dates_counts_rooms_and_cross_origin_requests(self):
        self.check_case('''
    invalid=[]
    for changes in [dict(start_date='bad'),dict(start_date='2000-01-01'),dict(end_date='2099-01-01'),dict(end_date='2101-01-01'),dict(rooms=[]),dict(rooms=None),dict(notes='a'*2001)]:
        invalid.append(dict(payload,**changes))
    for row in [dict(room_id=999,mode='flexible',count=1),dict(room_id=True,mode='flexible',count=1),dict(room_id=rooms[0].id,mode='flexible',count=True),dict(room_id=rooms[0].id,mode='flexible',count=5),dict(room_id=rooms[0].id,mode='exact',dates=['2099-01-24']),dict(room_id=rooms[0].id,mode='exact',dates=['2099-01-23']*2),dict(room_id=rooms[0].id,mode='exact',dates=[]),dict(room_id=rooms[0].id,mode='flexible',count=1,dates=['2099-01-23'])]:
        invalid.append(dict(payload,rooms=[row]))
    invalid.append(dict(payload,rooms=[payload['rooms'][0]]*2))
    with patch('app.send_smtp_message') as smtp:
        for item in invalid:
            response=client.post('/api/admin/room-requests/preview',json=item)
            assert response.status_code==400,(item,response.json)
        assert client.post('/api/admin/room-requests/preview',json=payload,headers={'Origin':'https://evil.example'}).status_code==400
        assert client.post('/api/admin/room-requests/preview',data={'start_date':'2099-01-23'}).status_code==400
        assert RoomRequest.query.count()==0
        smtp.assert_not_called()
''')

    def test_only_reviewed_content_can_send_and_concurrent_or_repeated_sends_do_not_duplicate(self):
        self.check_case('''
    payload['notes']='Tea & access <details> for the venue.'
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    send_data=dict(review_key=preview['review_key'],confirmed=True)
    assert client.post('/api/admin/room-requests/send',json=dict(send_data,body='changed')).status_code==400
    assert client.post('/api/admin/room-requests/send',json=dict(send_data,confirmed=False)).status_code==400
    assert client.post('/api/admin/room-requests/send',json=dict(send_data,review_key='missing-preview-key-123')).status_code==404
    def inspect(message,recipients):
        nested=client.post('/api/admin/room-requests/send',json=send_data)
        assert nested.status_code==409,nested.json
        assert recipients==list(TO+CC)
        assert message['From']==preview['from_email'] and message['To']==', '.join(TO)
        assert message['Cc']==', '.join(CC) and message['Reply-To']==CC[0]
        assert message['Subject']==preview['subject']
        plain=message.get_payload(0).get_payload(decode=True).decode('utf-8')
        html=message.get_payload(1).get_payload(decode=True).decode('utf-8')
        assert plain==preview['body']
        assert '&lt;details&gt;' in html and '&amp;' in html and '<details>' not in html
        assert '&nbsp;' not in html and '<br>' not in html and 'width=' not in html
    with patch('app.send_smtp_message',side_effect=inspect) as smtp:
        sent=client.post('/api/admin/room-requests/send',json=send_data)
        assert sent.status_code==200,sent.json
        assert sent.json['request']['status']=='sent' and sent.json['request']['sent_at']
        again=client.post('/api/admin/room-requests/send',json=send_data)
        assert again.status_code==200 and again.json['already_sent']
        assert client.post('/api/admin/room-requests/preview',json=payload).json['status']=='sent'
        assert smtp.call_count==1
    assert Booking.query.count()==0
''')

    def test_definite_failure_needs_fresh_review_and_uncertain_delivery_never_retries(self):
        self.check_case('''
    import smtplib
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.send_smtp_message',side_effect=smtplib.SMTPAuthenticationError(535,b'no')) as smtp:
        failed=client.post('/api/admin/room-requests/send',json=data)
        assert failed.status_code==502 and failed.json['request']['status']=='failed'
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        assert smtp.call_count==1
    reviewed=client.post('/api/admin/room-requests/preview',json=payload).json
    assert reviewed['status']=='draft' and reviewed['review_key']==preview['review_key']
    with patch('app.send_smtp_message') as smtp:
        assert client.post('/api/admin/room-requests/send',json=data).status_code==200
        assert smtp.call_count==1
    payload['notes']='Different request'
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.send_smtp_message',side_effect=EmailDeliveryUncertain('unknown')) as smtp:
        uncertain=client.post('/api/admin/room-requests/send',json=data)
        assert uncertain.status_code==502 and uncertain.json['request']['status']=='uncertain'
        assert client.post('/api/admin/room-requests/preview',json=payload).json['status']=='uncertain'
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        assert smtp.call_count==1
''')

    def test_disabled_email_and_stale_period_never_send(self):
        self.check_case('''
    from datetime import datetime
    preview=client.post('/api/admin/room-requests/preview',json=payload).json
    data=dict(review_key=preview['review_key'],confirmed=True)
    with patch('app.reminders_mail_ready',return_value=False),patch('app.send_smtp_message') as smtp:
        assert client.post('/api/admin/room-requests/send',json=data).status_code==503
        smtp.assert_not_called()
    with patch('room_requests.datetime') as clock,patch('app.send_smtp_message') as smtp:
        clock.now.return_value=datetime(2100,1,1)
        assert client.post('/api/admin/room-requests/send',json=data).status_code==409
        smtp.assert_not_called()
    assert RoomRequest.query.one().status=='draft'
''')

    def test_legacy_room_aliases_do_not_create_duplicate_choices_or_requests(self):
        self.check_case('''
    duplicate=Room(name='Room 4.7 "Clerkenwell"',room_type='open')
    db.session.add(duplicate);db.session.commit()
    options=client.get('/api/admin/room-requests/options').json['rooms']
    assert len(options)==3 and duplicate.id in [r['id'] for r in options]
    assert rooms[1].id not in [r['id'] for r in options]
    assert Room.query.count()==4
    response=client.post('/api/admin/room-requests/preview',json=payload)
    assert response.status_code==400
    payload['rooms'][1]['room_id']=duplicate.id
    assert client.post('/api/admin/room-requests/preview',json=payload).status_code==200
''')


if __name__=='__main__':
    unittest.main()
