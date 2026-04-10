#!/usr/bin/env python3
"""
Test email sending on PythonAnywhere
Run this to check if email configuration is working
"""

import smtplib
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuration
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USER = 'miles.lagc@gmail.com'
SMTP_PASSWORD = 'gidxqeqyvdifqzqs'
SMTP_FROM = 'miles.lagc@gmail.com'

def test_email():
    test_recipient = input("Enter email address to send test to: ").strip()
    
    print("\n" + "="*60)
    print("Testing Email Configuration")
    print("="*60)
    print(f"SMTP Host: {SMTP_HOST}:{SMTP_PORT}")
    print(f"SMTP User: {SMTP_USER}")
    print(f"From: {SMTP_FROM}")
    print(f"To: {test_recipient}")
    print("="*60 + "\n")
    
    try:
        print("1. Creating message...")
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM
        msg['To'] = test_recipient
        msg['Subject'] = 'Test Email from LAGC Booking System'
        body = """This is a test email from the LAGC Room Booking System.

If you received this email, the email configuration is working correctly!

Time sent: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        msg.attach(MIMEText(body, 'plain'))
        
        print("2. Connecting to SMTP server...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.set_debuglevel(2)  # Verbose output
        
        print("3. Starting TLS...")
        server.starttls()
        
        print("4. Logging in...")
        password = SMTP_PASSWORD.replace(' ', '').replace('-', '')
        server.login(SMTP_USER, password)
        
        print("5. Sending email...")
        server.send_message(msg)
        
        print("6. Closing connection...")
        server.quit()
        
        print("\n" + "="*60)
        print("✅ SUCCESS! Email sent successfully!")
        print("="*60)
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ AUTHENTICATION ERROR: {e}")
        print("\nPossible causes:")
        print("- App password is incorrect")
        print("- Less secure app access is disabled")
        print("- 2-Factor Authentication is not enabled")
        return False
        
    except smtplib.SMTPException as e:
        print(f"\n❌ SMTP ERROR: {e}")
        print(f"Error type: {type(e).__name__}")
        return False
        
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_email()
    sys.exit(0 if success else 1)
