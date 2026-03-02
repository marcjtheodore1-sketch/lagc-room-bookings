from app import app, db
from sqlalchemy import text, inspect

with app.app_context():
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('room')]
    print('Current columns:', columns)
    
    if 'room_type' not in columns:
        db.session.execute(text('ALTER TABLE room ADD COLUMN room_type VARCHAR(20) DEFAULT "slot"'))
        db.session.commit()
        print('room_type column added successfully!')
    else:
        print('room_type column already exists')
