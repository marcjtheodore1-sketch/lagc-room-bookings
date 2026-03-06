from app import app, db, Room

with app.app_context():
    # Expected rooms with IDs matching ROOM_SCHEDULE
    expected_rooms = {
        1: {'name': 'Room 4.2 "Indigo"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
        2: {'name': 'Room 4.4 "Rose"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'slot'},
        3: {'name': 'Room 4.7 "Clerkenwell"', 'building_location': 'Floor 4 - Pan Macmillan HQ', 'room_type': 'open'},
        4: {'name': 'The Loft', 'building_location': 'Floor 6 - Pan Macmillan HQ', 'room_type': 'open'},
    }
    
    for room_id, room_data in expected_rooms.items():
        room = Room.query.get(room_id)
        if room:
            room.name = room_data['name']
            room.building_location = room_data['building_location']
            room.room_type = room_data['room_type']
            room.is_active = True
            print(f"Updated room {room_id}: {room_data['name']}")
        else:
            room = Room(
                id=room_id,
                name=room_data['name'],
                building_location=room_data['building_location'],
                room_type=room_data['room_type'],
                is_active=True
            )
            db.session.add(room)
            print(f"Created room {room_id}: {room_data['name']}")
    
    db.session.commit()
    print("Done!")
