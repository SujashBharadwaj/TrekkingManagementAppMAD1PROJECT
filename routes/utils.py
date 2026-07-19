import os
import functools
from flask import session, flash, redirect, url_for, abort, current_app
from werkzeug.utils import secure_filename
from models import db, User

# Centralised limits so backend + templates stay in sync
LIMITS = {
    'username_max': 80,
    'email_max': 120,
    'password_min': 4,
    'password_max': 128,
    'name_max': 100,
    'contact_max': 200,
    'trek_name_max': 100,
    'location_max': 100,
    'description_max': 500,
    'slots_max': 999,
    'duration_max': 365,
    'price_max': 99999.99,
    'review_comment_max': 500,
}


def login_required(f):
    """Restrict access to logged-in users."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            from flask import request
            return redirect(url_for('auth.login', next=request.full_path))
        user = db.session.get(User, session['user_id'])
        if not user:
            session.clear()
            flash('Session invalid. Please log in again.', 'danger')
            return redirect(url_for('auth.login'))
        if user.status == 'blacklisted':
            session.clear()
            flash('Your account has been blacklisted.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


def role_required(roles):
    """Restrict access based on user role."""
    if isinstance(roles, str):
        roles = [roles]
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if 'role' not in session or session['role'] not in roles:
                flash('You do not have permission to view this page.', 'danger')
                return abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate(text, max_len):
    if text and len(text) > max_len:
        return text[:max_len]
    return text


def redirect_to_dashboard(role):
    if role == 'admin':
        return redirect(url_for('admin.admin_dashboard'))
    elif role == 'staff':
        return redirect(url_for('staff.staff_dashboard'))
    return redirect(url_for('trekker.user_dashboard'))


def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def save_photo(file):
    """Securely save an uploaded photo and return the filename."""
    filename = secure_filename(file.filename)
    # Add timestamp prefix to avoid collisions
    from datetime import datetime
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S_')
    filename = timestamp + filename
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    file.save(os.path.join(upload_folder, filename))
    return filename
