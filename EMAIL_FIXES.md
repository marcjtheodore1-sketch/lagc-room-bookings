# Email Configuration Fix Documentation

## IMPORTANT: For Future Reference

When email stops working on PythonAnywhere, remember these fixes:

---

## The Problem (2024-04-01)

Email was working, then stopped working after code changes. The error was:
```
[Errno 101] Network is unreachable
```

This happened when running test_email.py from bash, but curl could connect to smtp.gmail.com:587 successfully.

---

## The Solution

### 1. Password Handling Issue
**DON'T strip characters from the password!**

**WRONG:**
```python
smtp_password = app.config['SMTP_PASSWORD'].replace(' ', '').replace('-', '')
```

**CORRECT:**
```python
smtp_password = app.config['SMTP_PASSWORD']
```

The `.replace('-', '')` was corrupting the password by removing hyphens.

---

### 2. SMTP Connection Method

**Use SMTP_SSL on port 465 FIRST, then fallback to STARTTLS on 587.**

PythonAnywhere's free tier handles SSL connections on port 465 better than STARTTLS on 587.

**Current working implementation:**
```python
def send_confirmation_email(to_email, subject, message):
    # ... setup code ...
    
    # Try SMTP_SSL on port 465 first (works better on PythonAnywhere)
    try:
        with smtplib.SMTP_SSL(app.config['SMTP_HOST'], 465) as server:
            server.login(app.config['SMTP_USER'], smtp_password)
            server.send_message(msg)
            return True
    except Exception as ssl_error:
        # Fall back to STARTTLS on port 587
        with smtplib.SMTP(app.config['SMTP_HOST'], 587) as server:
            server.starttls()
            server.login(app.config['SMTP_USER'], smtp_password)
            server.send_message(msg)
            return True
```

---

## Current Hardcoded Settings (Working)

```python
app.config['SMTP_HOST'] = 'smtp.gmail.com'
app.config['SMTP_PORT'] = 587
app.config['SMTP_USER'] = 'miles.lagc@gmail.com'
app.config['SMTP_PASSWORD'] = 'gidxqeqyvdifqzqs'
app.config['SMTP_FROM'] = 'miles.lagc@gmail.com'
app.config['ENABLE_EMAIL'] = True
```

---

## What NOT to Do

1. **Don't use environment variables on PythonAnywhere** - they don't persist well
2. **Don't strip password characters** - use the password exactly as provided
3. **Don't assume SMTP is blocked** - PythonAnywhere free tier DOES allow SMTP
4. **Don't change to HTTP-based email APIs** unless absolutely necessary

---

## Testing Email

Run the test script on PythonAnywhere:
```bash
cd ~/lagc-room-bookings
python test_email.py
```

If curl can connect to smtp.gmail.com:587 but Python can't, check the password handling first.

---

## Account Type

This works on PythonAnywhere **FREE TIER** - no paid account required for SMTP email.

---

Last updated: 2024-04-01
