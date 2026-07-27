from app import app, db, ensure_default_rooms

with app.app_context():
    created_rooms = ensure_default_rooms()
    db.session.commit()

    if created_rooms:
        for room in created_rooms:
            print(f"Created room {room.id}: {room.name}")
    else:
        print("All expected rooms already exist; no changes made.")
