from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, StaffProfile
from .utils import LIMITS, _truncate, redirect_to_dashboard

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next') or request.form.get('next')
    if 'user_id' in session:
        return redirect(next_url or redirect_to_dashboard(session['role']))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()[:LIMITS['username_max']]
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            if user.status == 'blacklisted':
                flash('Your account is blacklisted. Contact support.', 'danger')
                return render_template('login.html', next_url=next_url)
            if user.role == 'staff' and user.status == 'pending':
                flash('Your registration is pending Admin approval.', 'warning')
                return render_template('login.html', next_url=next_url)

            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Welcome back, {user.username}!', 'success')
            if next_url:
                return redirect(next_url)
            return redirect_to_dashboard(user.role)

        flash('Invalid username or password.', 'danger')
    return render_template('login.html', next_url=next_url)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect_to_dashboard(session['role'])

    if request.method == 'POST':
        username = _truncate(request.form.get('username', '').strip(), LIMITS['username_max'])
        email = _truncate(request.form.get('email', '').strip(), LIMITS['email_max'])
        password = request.form.get('password', '')
        role = 'trekker'
        name = _truncate(request.form.get('name', '').strip(), LIMITS['name_max'])
        contact = _truncate(request.form.get('contact', '').strip(), LIMITS['contact_max'])

        if not username or not email or not password or not name:
            flash('Please fill in all required fields.', 'danger')
            return render_template('register.html')
        if len(password) < LIMITS['password_min']:
            flash(f'Password must be at least {LIMITS["password_min"]} characters.', 'danger')
            return render_template('register.html')
        if len(password) > LIMITS['password_max']:
            flash(f'Password cannot exceed {LIMITS["password_max"]} characters.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('Username is already taken.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Email is already registered.', 'danger')
            return render_template('register.html')

        new_user = User(
            username=username, email=email,
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            role=role, status='active'
        )
        db.session.add(new_user)
        db.session.flush()

        flash('Registration successful! Please log in.', 'success')

        db.session.commit()
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('auth.login'))
