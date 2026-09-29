"""Run once each morning using a PythonAnywhere scheduled task.

Use the same virtual environment as the web app. Its actual path must be
checked on the host before configuring the scheduled task.
"""
from app import app, run_reminder_job


if __name__ == '__main__':
    with app.app_context():
        result = run_reminder_job()
        print(result)
        if result['failed']:
            raise SystemExit(1)
