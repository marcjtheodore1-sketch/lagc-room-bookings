from app import app, Room, DEFAULT_ROOMS

with app.app_context():
    print("Current rooms in database:")
    print("-" * 50)
    for room in Room.query.all():
        print(f"ID: {room.id}, Name: {room.name}, Active: {room.is_active}")
    print("-" * 50)
    print("\nSchedule room matches:")
    rooms = Room.query.order_by(Room.id).all()
    for room_data in DEFAULT_ROOMS:
        matching_ids = [
            room.id for room in rooms
            if any(keyword in room.name.lower() for keyword in room_data['keywords'])
        ]
        print(f"{room_data['name']}: {matching_ids or 'MISSING'}")
