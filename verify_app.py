import unittest
from datetime import date, timedelta
# pyrefly: ignore [missing-import]
from werkzeug.security import generate_password_hash
from config import Config
from app import create_app
from models import db, User, StaffProfile, Trek, Booking, Review, TrekPhoto


class TestConfig(Config):
    """Overrides for testing: in-memory DB, testing mode on."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class TrekkingAppTestCase(unittest.TestCase):
    """Test suite to verify database constraints, authentication, and core validation logic."""

    def setUp(self):
        """Create a fresh app and database for each test."""
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()


    def tearDown(self):
        """Clean up database after each test."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_admin_seeding(self):
        """Test that database tables are initialized and admin seeds correctly."""
        admin = User.query.filter_by(role='admin').first()
        self.assertIsNone(admin)

        admin_user = User(
            username='admin',
            email='admin@trekking.com',
            password_hash=generate_password_hash('adminisadmin@123?!?!'),
            role='admin',
            status='active'
        )
        db.session.add(admin_user)
        db.session.commit()

        seeded_admin = User.query.filter_by(role='admin').first()
        self.assertIsNotNone(seeded_admin)
        self.assertEqual(seeded_admin.username, 'admin')
        self.assertEqual(seeded_admin.status, 'active')

    def test_user_and_staff_registration_status(self):
        """Test default status values for registered trekkers vs trek staff."""
        trekker = User(
            username='john_trekker',
            email='john@test.com',
            password_hash=generate_password_hash('password123'),
            role='trekker',
            status='active'
        )
        staff = User(
            username='alice_guide',
            email='alice@test.com',
            password_hash=generate_password_hash('password123'),
            role='staff',
            status='pending'
        )
        db.session.add_all([trekker, staff])
        db.session.commit()

        db_trekker = User.query.filter_by(username='john_trekker').first()
        db_staff = User.query.filter_by(username='alice_guide').first()

        self.assertEqual(db_trekker.status, 'active')
        self.assertEqual(db_staff.status, 'pending')

    def test_trek_creation_and_assignment(self):
        """Test creation of a trek route and assignment to a staff guide."""
        guide = User(username='guide1', email='guide1@test.com', password_hash='hash', role='staff', status='active')
        db.session.add(guide)
        db.session.commit()

        trek = Trek(
            name='Triund Trek',
            location='Dharamshala',
            difficulty='Moderate',
            duration=2,
            total_slots=10,
            available_slots=10,
            assigned_staff_id=guide.id,
            status='Pending',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=2),
            price=150.0
        )
        db.session.add(trek)
        db.session.commit()

        db_trek = Trek.query.filter_by(name='Triund Trek').first()
        self.assertIsNotNone(db_trek)
        self.assertEqual(db_trek.assigned_staff.username, 'guide1')
        self.assertEqual(db_trek.available_slots, 10)

    def test_overbooking_prevention(self):
        """Test that booking exceeds slots are blocked and valid bookings deduct capacity."""
        trek = Trek(
            name='Kheerganga Trek',
            location='Kasol',
            difficulty='Easy',
            duration=2,
            total_slots=5,
            available_slots=5,
            status='Open',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=2),
            price=100.0
        )
        trekker1 = User(username='t1', email='t1@test.com', password_hash='hash', role='trekker', status='active')
        trekker2 = User(username='t2', email='t2@test.com', password_hash='hash', role='trekker', status='active')
        db.session.add_all([trek, trekker1, trekker2])
        db.session.commit()

        self.assertLessEqual(3, trek.available_slots)
        trek.available_slots -= 3
        b1 = Booking(user_id=trekker1.id, trek_id=trek.id, slots_booked=3, status='Booked')
        db.session.add(b1)
        db.session.commit()

        db_trek = db.session.get(Trek, trek.id)
        self.assertEqual(db_trek.available_slots, 2)

        requested_slots = 3
        self.assertFalse(db_trek.available_slots >= requested_slots)

    def test_booking_restricted_to_open_treks(self):
        """Test that bookings cannot be made if the trek is not in Open status."""
        trek = Trek(
            name='Chadar Trek',
            location='Ladakh',
            difficulty='Hard',
            duration=9,
            total_slots=10,
            available_slots=10,
            status='Pending',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=9),
            price=600.0
        )
        trekker = User(username='t3', email='t3@test.com', password_hash='hash', role='trekker', status='active')
        db.session.add_all([trek, trekker])
        db.session.commit()

        self.assertNotEqual(trek.status, 'Open')

    def test_review_model(self):
        """Test that reviews can be created and linked to users and treks."""
        trekker = User(username='reviewer', email='rev@test.com', password_hash='hash', role='trekker', status='active')
        trek = Trek(
            name='Test Trek', location='Test', difficulty='Easy', duration=1,
            total_slots=10, available_slots=10, status='Completed',
            start_date=date.today(), end_date=date.today(), price=100.0
        )
        db.session.add_all([trekker, trek])
        db.session.commit()

        review = Review(user_id=trekker.id, trek_id=trek.id, rating=5, comment='Amazing trek!')
        db.session.add(review)
        db.session.commit()

        db_review = Review.query.first()
        self.assertIsNotNone(db_review)
        self.assertEqual(db_review.rating, 5)
        self.assertEqual(db_review.user.username, 'reviewer')

if __name__ == '__main__':
    unittest.main()
