#!/usr/bin/env python3
"""
Email Configuration Setup Script for PythonAnywhere

Run this script to set up email environment variables on PythonAnywhere.
"""

import os

def setup_email_config():
    print("=" * 60)
    print("Email Configuration Setup for LAGC Room Bookings")
    print("=" * 60)
    print()
    
    print("This will help you configure email notifications.")
    print()
    
    # Check current status
    smtp_user = os.environ.get('SMTP_USER', '')
    enable_email = os.environ.get('ENABLE_EMAIL', 'false')
    
    if smtp_user and enable_email.lower() == 'true':
        print(f"✅ Email is currently ENABLED")
        print(f"   SMTP_USER: {smtp_user}")
        print()
        print("If you need to update settings, you can run this script again.")
        return
    else:
        print("⚠️  Email is currently DISABLED")
        print()
    
    print("To enable email notifications, you need to set these environment variables")
    print("in your PythonAnywhere Web app configuration:")
    print()
    print("1. Log into PythonAnywhere")
    print("2. Go to the 'Web' tab")
    print("3. Click on your web app (e.g., 'londonautismgroupcharity.pythonanywhere.com')")
    print("4. Scroll down to 'Environment variables'")
    print("5. Add the following variables:")
    print()
    print("   Variable Name          | Value")
    print("   ---------------------- | ----------------------------------------")
    print("   SMTP_HOST              | smtp.gmail.com")
    print("   SMTP_PORT              | 587")
    print("   SMTP_USER              | miles.lagc@gmail.com")
    print("   SMTP_PASSWORD          | [your-app-password]")
    print("   SMTP_FROM              | miles.lagc@gmail.com")
    print("   ENABLE_EMAIL           | true")
    print()
    print("IMPORTANT: For Gmail, you must use an App Password, not your regular password.")
    print("Generate one at: https://myaccount.google.com/apppasswords")
    print()
    print("After setting these variables, click 'Reload' on your web app.")
    print()

if __name__ == '__main__':
    setup_email_config()
