from app import app, db, Room

with app.app_context():
    print("Current rooms in database:")
    print("-" * 50)
    for room in Room.query.all():
        print(f"ID: {room.id}, Name: {room.name}, Active: {room.is_active}")
    print("-" * 50)
    print("\nExpected schedule mapping:")
    print("Room 4.2 'Indigo' should have ID: 1")
    print("Room 4.4 'Rose' should have ID: 2")
    print("Room 4.7 'Clerkenwell' should have ID: 3")
    print("The Loft should have ID: 4")
