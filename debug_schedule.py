from app import app, db, Room

with app.app_context():
    print("=" * 60)
    print("ROOMS IN DATABASE:")
    print("=" * 60)
    for room in Room.query.all():
        print(f"ID: {room.id} | Name: '{room.name}' | Active: {room.is_active}")
    
    print("\n" + "=" * 60)
    print("EXPECTED ROOM NAMES IN SCHEDULE:")
    print("=" * 60)
    from app import ROOM_SCHEDULE_BY_NAME
    for date, names in ROOM_SCHEDULE_BY_NAME.items():
        print(f"{date}: {names}")
    
    print("\n" + "=" * 60)
    print("MAPPING RESULT:")
    print("=" * 60)
    name_to_id = {}
    for room in Room.query.all():
        name_to_id[room.name] = room.id
    
    for date, names in ROOM_SCHEDULE_BY_NAME.items():
        ids = []
        for name in names:
            if name in name_to_id:
                ids.append(name_to_id[name])
                print(f"✓ '{name}' -> ID {name_to_id[name]}")
            else:
                print(f"✗ '{name}' -> NOT FOUND")
