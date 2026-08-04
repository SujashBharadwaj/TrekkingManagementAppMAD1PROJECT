# pyrefly: ignore [missing-import]
from flask import Blueprint, render_template, request, session, abort, flash
from models import Trek, Booking, Itinerary
from collections import OrderedDict
from datetime import datetime, date

main_bp = Blueprint('main', __name__)

# Region display order and labels
REGION_META = OrderedDict([
    ('North', {'label': 'North India - Himalayas & Beyond'}),
    ('East',  {'label': 'East & North-East India - Wildlife & Valleys'}),
    ('West',  {'label': 'West India - Sahyadri & Monsoon Trails'}),
    ('South', {'label': 'South India - Western Ghats'}),
])


@main_bp.route('/')
def index():
    # --- Grab filter params ---
    region_filter = request.args.get('region', '')
    difficulty = request.args.get('difficulty', '')
    season = request.args.get('season', '')
    duration = request.args.get('duration', '', type=int)
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    # --- Base query: only Open treks ---
    query = Trek.query.filter(Trek.status == 'Open')

    # Date filters validation
    today = date.today()
    start_date = None
    end_date = None

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            if start_date < today:
                flash('Start date cannot be in the past.', 'danger')
                start_date = None
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    if start_date and end_date:
        if end_date < start_date:
            flash('End date cannot be before start date.', 'danger')
            end_date = None
        elif (end_date - start_date).days > 14:
            flash('Date range cannot exceed 2 weeks (14 days).', 'danger')
            end_date = None

    # Apply filters
    if region_filter:
        query = query.filter(Trek.region == region_filter)
    if difficulty:
        query = query.filter(Trek.difficulty == difficulty)
    if season:
        query = query.filter(Trek.best_season == season)
    if duration:
        query = query.filter(Trek.duration == duration)
    if start_date:
        query = query.filter(Trek.start_date >= start_date)
    if end_date:
        query = query.filter(Trek.end_date <= end_date)

    treks = query.order_by(Trek.start_date.asc()).all()

    # --- Group by region ---
    grouped = OrderedDict()
    for key, meta in REGION_META.items():
        if region_filter and key != region_filter:
            continue
        region_treks = [t for t in treks if t.region == key]
        if region_treks:
            grouped[key] = {'meta': meta, 'treks': region_treks}

    # --- Personalised greeting for returning trekkers ---
    welcome_msg = None
    if session.get('role') == 'trekker':
        completed = Booking.query.filter_by(
            user_id=session['user_id'], status='Completed'
        ).count()
        if completed > 0:
            welcome_msg = f"Welcome back, {session['username']}! You've completed {completed} trek{'s' if completed != 1 else ''}."
        else:
            welcome_msg = f"Hey {session['username']}! Find your first adventure below."

    return render_template('index.html', grouped=grouped,
                           welcome_msg=welcome_msg,
                           region=region_filter, difficulty=difficulty, season=season,
                           duration=duration, start_date=start_date_str, end_date=end_date_str)


@main_bp.route('/trek/<int:id>')
def trek_detail(id):
    """Detailed view of a single trek - itinerary, booking modal, etc."""
    trek = Trek.query.get_or_404(id)
    items = Itinerary.query.filter_by(trek_id=id, is_approved=True).order_by(Itinerary.day_number).all()

    # Filter approved photos only for public display
    approved_photos = [p for p in trek.photos if p.is_approved]

    # For "Change Date" - find other open instances of the same trek name
    alternate_dates = Trek.query.filter(
        Trek.name == trek.name,
        Trek.id != trek.id,
        Trek.status == 'Open'
    ).order_by(Trek.start_date.asc()).all()

    return render_template('trek_detail.html', trek=trek, items=items,
                           approved_photos=approved_photos,
                           alternate_dates=alternate_dates)
