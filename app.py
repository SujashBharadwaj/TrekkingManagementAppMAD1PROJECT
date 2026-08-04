import os
from datetime import datetime, date
from flask import Flask
from werkzeug.security import generate_password_hash

from config import Config
from models import (db, User, StaffProfile, Trek, Booking, Itinerary,
                    Announcement, StaffPayout, Expense, DebriefReport)


def create_app(config_class=Config):
    """Application Factory: creates and configures the Flask app instance."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialise extensions
    db.init_app(app)

    # Ensure the upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # --- Register Blueprints ---
    from routes import (auth_bp, admin_bp, admin_finance_bp, admin_ops_bp,
                        staff_bp, staff_ops_bp, trekker_bp, main_bp)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_finance_bp)
    app.register_blueprint(admin_ops_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(staff_ops_bp)
    app.register_blueprint(trekker_bp)

    # --- Context Processors & Filters ---
    from routes.utils import LIMITS

    @app.context_processor
    def inject_globals():
        """Make limits and current_date available in every template."""
        return {'limits': LIMITS, 'current_date': date.today()}

    @app.template_filter('ddmmyyyy')
    def ddmmyyyy_filter(value):
        """Format a date object as DD-MM-YYYY for display."""
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        return value.strftime('%d-%m-%Y')

    return app


def seed_mock_data(app):
    """Seed the database with realistic mock data for demonstration."""
    from datetime import timedelta

    with app.app_context():
        # Check if data already exists
        if User.query.first():
            return

        # --- Admin (password: admin123) ---
        admin_user = User(
            username='admin', email='admin@trekking.com',
            password_hash=generate_password_hash('admin123', method='pbkdf2:sha256'),
            role='admin', status='active'
        )
        db.session.add(admin_user)
        db.session.flush()

        # --- Staff ---
        staff_data = [
            ('staff1', 'staff1@trekking.com', 'Staff Guide 1', '9876543210', 'active', 'North'),
            ('staff2', 'staff2@trekking.com', 'Staff Guide 2', '9876543211', 'active', 'South'),
            ('staff3', 'staff3@trekking.com', 'Staff Guide 3', '9876543212', 'pending', 'East'),
        ]
        staff_users = []
        for uname, email, name, contact, status, region in staff_data:
            u = User(username=uname, email=email,
                     password_hash=generate_password_hash('staff123', method='pbkdf2:sha256'),
                     role='staff', status=status)
            db.session.add(u)
            db.session.flush()
            db.session.add(StaffProfile(id=u.id, name=name, contact_details=contact, home_region=region))
            staff_users.append(u)

        # --- Trekkers ---
        trekker_data = [
            ('user1', 'user1@gmail.com'),
            ('user2', 'user2@gmail.com'),
            ('user3', 'user3@gmail.com'),
            ('user4', 'user4@gmail.com'),
            ('user5', 'user5@gmail.com'),
        ]
        trekkers = []
        for uname, email in trekker_data:
            u = User(username=uname, email=email,
                     password_hash=generate_password_hash('user123', method='pbkdf2:sha256'),
                     role='trekker', status='active')
            db.session.add(u)
            db.session.flush()
            trekkers.append(u)

        # --- Safety Guides removed ---


        # --- Discount Codes removed ---

        # --- Treks (region-tagged Indian treks with new fields) ---
        today = date.today()
        trek_data = [
            # (name, location, region, difficulty, duration, slots, start, end, price,
            #  description, status, staff_id, best_season, route_kms, exit_points, travel_included, base_camp_info,
            #  local_connects)

            # --- NORTH ---
            ('Hampta Pass Trek', 'Manali, Himachal Pradesh', 'North', 'Moderate', 5, 20,
             today + timedelta(days=10), today + timedelta(days=15), 8500.00,
             'A crossover trek from Manali to Spiti Valley through green meadows and snow-covered passes.',
             'Open', staff_users[0].id, 'Summer', 26.0, 'Jobra, Balu Ka Ghera, Shea Goru', True,
             'Direct pickup available from Manali Mall Road at 8:00 AM. Travel to Jobra base camp by taxi.',
             'Local Taxi (Manali): Raju - +91 94180 12345\nHospital: Lady Willingdon Hospital, Manali - +91 1902 252006\nHomestay: Himalayan Cottage, Jagatsukh - +91 98160 55667'),

            ('Kedarkantha Trek', 'Sankri, Uttarakhand', 'North', 'Easy', 4, 30,
             today + timedelta(days=5), today + timedelta(days=9), 5500.00,
             'Winter trek in India with a summit at 12,500 ft offering 360-degree mountain views.',
             'Open', staff_users[1].id, 'Winter', 20.0, 'Juda Ka Talab, KK Base Camp', True,
             'Pick up from Dehradun Railway Station at 6:30 AM. Travel via bus to Sankri base camp.',
             'Local Transport: Sharma Travels Dehradun - +91 99270 45678\nPHC Sankri: +91 1360 272223'),

            # Recurring batch
            ('Kedarkantha Trek', 'Sankri, Uttarakhand', 'North', 'Easy', 4, 30,
             today + timedelta(days=35), today + timedelta(days=39), 5500.00,
             'Winter trek in India with a summit at 12,500 ft offering 360-degree mountain views. (Feb batch)',
             'Open', staff_users[1].id, 'Winter', 20.0, 'Juda Ka Talab, KK Base Camp', True,
             'Pick up from Dehradun Railway Station at 6:30 AM. Travel via bus to Sankri base camp.',
             None),

            ('Valley of Flowers', 'Joshimath, Uttarakhand', 'North', 'Easy', 6, 25,
             today + timedelta(days=15), today + timedelta(days=21), 7200.00,
             'UNESCO World Heritage Site known for its endemic alpine flowers and views of the Himalayas.',
             'Open', staff_users[1].id, 'Monsoon', 38.0, 'Govindghat, Ghangaria', True,
             'Pick up from Rishikesh Railway Station at 6:00 AM. 10 hour drive to Govindghat.',
             None),

            ('Roopkund Trek', 'Lohajung, Uttarakhand', 'North', 'Hard', 8, 15,
             today + timedelta(days=20), today + timedelta(days=28), 12500.00,
             'The famous Skeleton Lake trek at 15,696 ft with views of Trishul and Nanda Ghunti peaks.',
             'Open', staff_users[0].id, 'Summer', 53.0, 'Didna, Bedni Bugyal, Pathar Nachauni', False,
             'Starts at Lohajung base camp. Trekkers must report directly to Lohajung by evening.',
             None),

            ('Chadar Trek', 'Leh, Ladakh', 'North', 'Hard', 9, 12,
             today + timedelta(days=30), today + timedelta(days=39), 18000.00,
             'Walk on the frozen Zanskar River in sub-zero temperatures. An extreme adventure.',
             'Pending', None, 'Winter', 62.0, 'Tilat Sumdo, Nerak', False,
             'Report directly to Leh airport. Rest and acclimatisation in Leh hotel for 2 days.',
             None),

            ('Triund Trek', 'McLeodganj, Himachal Pradesh', 'North', 'Easy', 2, 40,
             today - timedelta(days=10), today - timedelta(days=8), 3500.00,
             'A short weekend trek with views of the Dhauladhar range. Perfect for beginners.',
             'Completed', staff_users[0].id, 'Autumn', 9.0, 'Gallu Devi Temple', True,
             'Meet at McLeodganj Main Square at 9:00 AM. Guide will lead walking trail starting from Dharamkot.',
             'Local Taxi: Dharamshala Cabs - +91 98160 77889\nHospital: Delek Hospital, McLeodganj - +91 1892 222053\nHomestay: Om Tara Guesthouse - +91 94180 33445'),

            ('Brahmatal Trek', 'Lohajung, Uttarakhand', 'North', 'Moderate', 6, 20,
             today + timedelta(days=12), today + timedelta(days=18), 7800.00,
             'Winter wonderland trek with views of Mt. Trishul and Nanda Ghunti reflected in the lake.',
             'Open', staff_users[0].id, 'Winter', 24.0, 'Bekaltal, Brahmatal Campsite, Tilandi', True,
             'Pick up from Kathgodam Railway Station at 6:00 AM. Drive to Lohajung base camp.',
             None),

            ('Kuari Pass Trek', 'Joshimath, Uttarakhand', 'North', 'Easy', 5, 25,
             today + timedelta(days=8), today + timedelta(days=13), 6200.00,
             'Lord Curzon trail offering views of Nanda Devi, Dronagiri, and Kamet peaks.',
             'Open', staff_users[1].id, 'Winter', 33.0, 'Dhak, Tali, Khullara', True,
             'Pick up from Haridwar Railway Station at 6:30 AM. Travel to Dhak Village starting point.',
             None),

            # --- EAST ---
            ('Sandakphu Trek', 'Darjeeling, West Bengal', 'East', 'Moderate', 7, 18,
             today + timedelta(days=18), today + timedelta(days=25), 9200.00,
             'Highest peak in West Bengal with views of Everest and Kanchenjunga.',
             'Open', staff_users[1].id, 'Autumn', 51.0, 'Tumling, Kalipokhri, Sabarkum', True,
             'Pick up from NJP Railway Station / Bagdogra Airport at 8:00 AM. Drive to Manebhanjan.',
             None),

            ('Goechala Trek', 'Yuksom, Sikkim', 'East', 'Hard', 10, 12,
             today + timedelta(days=25), today + timedelta(days=35), 15500.00,
             'Face-to-face with Kanchenjunga. High-altitude trek in India through rhododendron forests.',
             'Open', staff_users[0].id, 'Summer', 90.0, 'Tshoka, Dzongri, Lamuney, Samiti Lake', False,
             'Report to Yuksom base camp directly. Shared jeeps available from Siliguri/NJP.',
             None),

            ('Dzukou Valley Trek', 'Kohima, Nagaland', 'East', 'Moderate', 3, 20,
             today + timedelta(days=14), today + timedelta(days=17), 4800.00,
             'Valley of flowers in the Northeast. Known for rare Dzukou lily blooms and wildlife sightings.',
             'Open', staff_users[1].id, 'Monsoon', 16.0, 'Viswema Village, Dzukou Rest House', True,
             'Pick up from Dimapur Airport/Railway Station at 9:00 AM. Drive to Viswema Village starting point.',
             None),

            # --- WEST ---
            ('Harishchandragad Trek', 'Ahmednagar, Maharashtra', 'West', 'Moderate', 2, 30,
             today + timedelta(days=7), today + timedelta(days=9), 3200.00,
             'Monsoon trek in Maharashtra. Features the stunning Konkan Kada cliff, caves, and Sahyadri valleys.',
             'Open', staff_users[0].id, 'Monsoon', 14.0, 'Pachnai, Tolar Khind, Konkan Kada', True,
             'Meet at Kasara Railway Station at 7:30 AM. Travel via local transport to Pachnai Village base camp.',
             None),

            ('Kalsubai Peak Trek', 'Nashik, Maharashtra', 'West', 'Easy', 1, 40,
             today + timedelta(days=3), today + timedelta(days=4), 1800.00,
             'The highest peak in Maharashtra at 5,400 ft. A quick sunrise trek with laddered sections.',
             'Open', staff_users[1].id, 'Monsoon', 6.0, 'Bari Village', True,
             'Meet at Kasara Railway Station at 10:00 PM (night trek). Travel via jeep to Bari Village starting point.',
             None),

            # --- SOUTH ---
            ('Kumara Parvatha Trek', 'Coorg, Karnataka', 'South', 'Hard', 3, 15,
             today + timedelta(days=11), today + timedelta(days=14), 4500.00,
             'Tough trek in South India through Western Ghats. Shola forests and Pushpagiri peak.',
             'Open', staff_users[0].id, 'Winter', 22.0, 'Kukke Subramanya, Bhattara Mane, Shesha Parvatha', False,
             'Report to Kukke Subramanya temple town directly. Trek begins early morning from Temple Road.',
             'Forest Office Coorg: +91 8272 228305\nLocal Guide: Mohan - +91 97409 12345\nHomestay: Coorg Wilderness - +91 82712 56789'),

            ('Meesapulimala Trek', 'Munnar, Kerala', 'South', 'Moderate', 2, 20,
             today + timedelta(days=9), today + timedelta(days=11), 3800.00,
             'Second highest peak in South India. Rolling grasslands and Nilgiri Tahr sightings.',
             'Open', staff_users[1].id, 'Winter', 16.0, 'Rhodo Valley, Summit Camp', True,
             'Pick up from Munnar KSRTC Bus Stand at 8:30 AM. Drive to Silent Valley / Rhodo Valley base camp.',
             None),
        ]

        trek_objects = []
        for data in trek_data:
            (name, loc, reg, diff, dur, slots, sd, ed, price,
             desc, status, staff_id, season, kms, exits, travel, base_info,
             connects) = data
            t = Trek(name=name, location=loc, region=reg, difficulty=diff, duration=dur,
                     total_slots=slots, available_slots=slots,
                     start_date=sd, end_date=ed, price=price,
                     description=desc, status=status, assigned_staff_id=staff_id,
                     best_season=season, route_kms=kms, exit_points=exits,
                     travel_included=travel, base_camp_info=base_info,
                     local_connects=connects)
            db.session.add(t)
            db.session.flush()
            trek_objects.append(t)

        # --- Bookings (with total_price and insurance) ---
        # user1 booked Hampta Pass (idx 0)
        trek_objects[0].available_slots -= 2
        db.session.add(Booking(user_id=trekkers[0].id, trek_id=trek_objects[0].id,
                               slots_booked=2, status='Booked',
                               total_price=trek_objects[0].price * 2))

        # user2 booked Kedarkantha batch 1 (idx 1)
        trek_objects[1].available_slots -= 1
        db.session.add(Booking(user_id=trekkers[1].id, trek_id=trek_objects[1].id,
                               slots_booked=1, status='Booked',
                               total_price=trek_objects[1].price, has_insurance=True))

        # user3 booked Valley of Flowers (idx 3)
        trek_objects[3].available_slots -= 3
        db.session.add(Booking(user_id=trekkers[2].id, trek_id=trek_objects[3].id,
                               slots_booked=3, status='Booked',
                               total_price=trek_objects[3].price * 3))

        # user4 completed three North region treks (Triund, Hampta, Kedarkantha)
        db.session.add(Booking(user_id=trekkers[3].id, trek_id=trek_objects[6].id,
                               slots_booked=1, status='Completed',
                               total_price=trek_objects[6].price))
        db.session.add(Booking(user_id=trekkers[3].id, trek_id=trek_objects[0].id,
                               slots_booked=1, status='Completed',
                               total_price=trek_objects[0].price))
        db.session.add(Booking(user_id=trekkers[3].id, trek_id=trek_objects[1].id,
                               slots_booked=1, status='Completed',
                               total_price=trek_objects[1].price))

        # user5 booked Roopkund (idx 4) with medical info
        trek_objects[4].available_slots -= 1
        db.session.add(Booking(user_id=trekkers[4].id, trek_id=trek_objects[4].id,
                               slots_booked=1, status='Booked',
                               total_price=trek_objects[4].price, has_insurance=True,
                               medical_info='Mild asthma, carries inhaler',
                               dietary_needs='Vegetarian'))

        # --- Seed sample itineraries for Hampta Pass ---
        itinerary_data = [
            (trek_objects[0].id, 1, 'Manali to Jobra', 'Drive to Jobra and short acclimatisation walk.', 3.0, True),
            (trek_objects[0].id, 2, 'Jobra to Balu Ka Ghera', 'Trek through forests and meadows to riverside campsite.', 10.0, True),
            (trek_objects[0].id, 3, 'Balu Ka Ghera to Shea Goru via Hampta Pass', 'Cross the pass at 14,100 ft. Dramatic landscape change.', 8.0, True),
            (trek_objects[0].id, 4, 'Shea Goru to Chatru', 'Descend to Chatru on the Spiti side.', 5.0, True),
        ]
        for tid, day, title, desc, km, approved in itinerary_data:
            db.session.add(Itinerary(trek_id=tid, day_number=day, title=title,
                                     description=desc, distance_km=km, is_approved=approved))

        # --- Seed sample expenses (Feature #11) ---
        db.session.add(Expense(trek_id=trek_objects[6].id, staff_id=staff_users[0].id,
                               amount=1200.0, description='Emergency rations purchased at base camp',
                               status='Approved'))
        db.session.add(Expense(trek_id=trek_objects[6].id, staff_id=staff_users[0].id,
                               amount=800.0, description='Local transport for medical emergency',
                               status='Paid'))
        db.session.add(Expense(trek_id=trek_objects[0].id, staff_id=staff_users[0].id,
                               amount=500.0, description='Extra water bottles for group',
                               status='Pending'))

        # --- Seed staff payouts (Feature #2/#10) ---
        db.session.add(StaffPayout(trek_id=trek_objects[6].id, staff_id=staff_users[0].id,
                                   payout_type='commission', commission_pct=10.0,
                                   calculated_amount=trek_objects[6].price * 0.10,
                                   is_paid=True))

        # --- Seed announcements (Feature #8) ---
        db.session.add(Announcement(trek_id=trek_objects[0].id,
                                    title='Weather Update - Hampta Pass',
                                    message='Light snowfall expected at the pass. Please carry warm layers and waterproof jackets. Trek is ON as scheduled.'))
        db.session.add(Announcement(trek_id=trek_objects[1].id,
                                    title='Gear Reminder - Kedarkantha',
                                    message='Temperature dropping to -10°C at summit camp. Mandatory: down jacket, thermal inners, and 4-season sleeping bag. Rental gear available at base.'))

        # --- Seed debrief report (Feature #16) ---
        db.session.add(DebriefReport(trek_id=trek_objects[6].id, staff_id=staff_users[0].id,
                                     trail_conditions='Trail in good condition. Minor erosion near Gallu Devi temple section.',
                                     weather_report='Clear skies throughout. Night temp dropped to 2°C.',
                                     general_feedback='All 40 trekkers completed safely. Recommend adding a chai stop at midpoint.'))

        db.session.commit()
        print(' * Mock data seeded successfully!')


# --- Entry Point ---
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    seed_mock_data(app)
    app.run(debug=True, port=4200)
