from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from datetime import datetime, date
from models import (db, User, Trek, Booking, SafetyGuide, DiscountCode,
                    Announcement, StaffAvailability)
from .utils import login_required, role_required

admin_ops_bp = Blueprint('admin_ops', __name__, url_prefix='/admin')


# =========================================================
# Feature #3: Staff Region Tracking
# =========================================================
@admin_ops_bp.route('/staff-regions')
@login_required
@role_required('admin')
def staff_regions():
    """Show how many treks each staff has led and in which regions."""
    staff_users = User.query.filter_by(role='staff', status='active').all()
    staff_data = []

    for staff in staff_users:
        treks_led = Trek.query.filter_by(assigned_staff_id=staff.id).all()
        regions = set()
        status_counts = {'Completed': 0, 'Open': 0, 'Other': 0}
        for t in treks_led:
            if t.region:
                regions.add(t.region)
            if t.status == 'Completed':
                status_counts['Completed'] += 1
            elif t.status == 'Open':
                status_counts['Open'] += 1
            else:
                status_counts['Other'] += 1

        blocks = StaffAvailability.query.filter_by(staff_id=staff.id).filter(
            StaffAvailability.unavailable_to >= date.today()
        ).all()

        staff_data.append({
            'staff': staff,
            'profile': staff.staff_profile,
            'total_treks': len(treks_led),
            'regions': sorted(regions),
            'status_counts': status_counts,
            'availability_blocks': blocks,
        })

    return render_template('admin/staff_regions.html', staff_data=staff_data)


# =========================================================
# Feature #4: Trek Occupancy Metrics
# =========================================================
@admin_ops_bp.route('/occupancy')
@login_required
@role_required('admin')
def occupancy():
    """Visual occupancy metrics for all treks."""
    treks = Trek.query.filter(Trek.status.in_(['Open', 'Closed', 'Completed'])).order_by(Trek.start_date).all()
    occupancy_data = []

    for trek in treks:
        booked = trek.total_slots - trek.available_slots
        pct = (booked / trek.total_slots * 100) if trek.total_slots > 0 else 0
        occupancy_data.append({
            'trek': trek,
            'booked': booked,
            'total': trek.total_slots,
            'available': trek.available_slots,
            'pct': round(pct, 1),
        })

    return render_template('admin/occupancy.html', occupancy_data=occupancy_data)


# =========================================================
# Feature #5: Trek Clone/Duplicate
# =========================================================
@admin_ops_bp.route('/trek/<int:id>/clone', methods=['POST'])
@login_required
@role_required('admin')
def clone_trek(id):
    """Duplicate an existing trek with dates offset by +30 days."""
    from datetime import timedelta
    original = db.session.get(Trek, id) or abort(404)

    cloned = Trek(
        name=original.name,
        location=original.location,
        region=original.region,
        difficulty=original.difficulty,
        duration=original.duration,
        best_season=original.best_season,
        route_kms=original.route_kms,
        exit_points=original.exit_points,
        travel_included=original.travel_included,
        total_slots=original.total_slots,
        available_slots=original.total_slots,
        assigned_staff_id=original.assigned_staff_id,
        status='Pending',
        start_date=original.start_date + timedelta(days=30),
        end_date=original.end_date + timedelta(days=30),
        description=original.description,
        base_camp_info=original.base_camp_info,
        price=original.price,
        staff_commission_pct=original.staff_commission_pct,
        staff_flat_salary=original.staff_flat_salary,
        safety_guide_id=original.safety_guide_id,
        gear_checklist=original.gear_checklist,
        local_connects=original.local_connects,
    )
    db.session.add(cloned)
    db.session.commit()
    flash(f'Trek "{original.name}" cloned! New dates: {cloned.start_date.strftime("%d-%m-%Y")} to {cloned.end_date.strftime("%d-%m-%Y")}.', 'success')
    return redirect(url_for('admin.edit_trek', id=cloned.id))


# =========================================================
# Feature #6: Safety Guide CRUD
# =========================================================
@admin_ops_bp.route('/safety-guides')
@login_required
@role_required('admin')
def safety_guides():
    guides = SafetyGuide.query.order_by(SafetyGuide.created_at.desc()).all()
    return render_template('admin/safety_guides.html', guides=guides)


@admin_ops_bp.route('/safety-guide/add', methods=['POST'])
@login_required
@role_required('admin')
def add_safety_guide():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    emergency_contacts = request.form.get('emergency_contacts', '').strip()
    exit_points = request.form.get('exit_points', '').strip()

    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(url_for('admin_ops.safety_guides'))

    guide = SafetyGuide(title=title, content=content,
                        emergency_contacts=emergency_contacts or None,
                        exit_points=exit_points or None)
    db.session.add(guide)
    db.session.commit()
    flash(f'Safety guide "{title}" created.', 'success')
    return redirect(url_for('admin_ops.safety_guides'))


@admin_ops_bp.route('/safety-guide/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_safety_guide(id):
    guide = db.session.get(SafetyGuide, id) or abort(404)

    if request.method == 'POST':
        guide.title = request.form.get('title', '').strip()
        guide.content = request.form.get('content', '').strip()
        guide.emergency_contacts = request.form.get('emergency_contacts', '').strip() or None
        guide.exit_points = request.form.get('exit_points', '').strip() or None
        guide.updated_at = datetime.utcnow()

        if not guide.title or not guide.content:
            flash('Title and content are required.', 'danger')
            return redirect(url_for('admin_ops.edit_safety_guide', id=id))

        db.session.commit()
        flash('Safety guide updated.', 'success')
        return redirect(url_for('admin_ops.safety_guides'))

    linked_treks = Trek.query.filter_by(safety_guide_id=guide.id).all()
    return render_template('admin/safety_guide_edit.html', guide=guide, linked_treks=linked_treks)


@admin_ops_bp.route('/safety-guide/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_safety_guide(id):
    guide = db.session.get(SafetyGuide, id) or abort(404)
    Trek.query.filter_by(safety_guide_id=guide.id).update({'safety_guide_id': None})
    db.session.delete(guide)
    db.session.commit()
    flash('Safety guide deleted.', 'success')
    return redirect(url_for('admin_ops.safety_guides'))


# =========================================================
# Feature #7: Discount Codes / Coupons
# =========================================================
@admin_ops_bp.route('/discount-codes')
@login_required
@role_required('admin')
def discount_codes():
    codes = DiscountCode.query.order_by(DiscountCode.created_at.desc()).all()
    return render_template('admin/discount_codes.html', codes=codes)


@admin_ops_bp.route('/discount-code/add', methods=['POST'])
@login_required
@role_required('admin')
def add_discount_code():
    code = request.form.get('code', '').strip().upper()
    discount_type = request.form.get('discount_type', 'percent')
    value = request.form.get('value', type=float)
    max_uses = request.form.get('max_uses', type=int)
    expiry_str = request.form.get('expiry_date', '').strip()

    if not code or value is None or value <= 0:
        flash('Code and value are required.', 'danger')
        return redirect(url_for('admin_ops.discount_codes'))

    if DiscountCode.query.filter_by(code=code).first():
        flash(f'Code "{code}" already exists.', 'danger')
        return redirect(url_for('admin_ops.discount_codes'))

    expiry = None
    if expiry_str:
        try:
            expiry = datetime.strptime(expiry_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid expiry date.', 'danger')
            return redirect(url_for('admin_ops.discount_codes'))

    dc = DiscountCode(code=code, discount_type=discount_type, value=value,
                       max_uses=max_uses if max_uses and max_uses > 0 else None,
                       expiry_date=expiry)
    db.session.add(dc)
    db.session.commit()
    flash(f'Discount code "{code}" created.', 'success')
    return redirect(url_for('admin_ops.discount_codes'))


@admin_ops_bp.route('/discount-code/<int:id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_discount_code(id):
    dc = db.session.get(DiscountCode, id) or abort(404)
    dc.is_active = not dc.is_active
    db.session.commit()
    status = 'activated' if dc.is_active else 'deactivated'
    flash(f'Code "{dc.code}" {status}.', 'success')
    return redirect(url_for('admin_ops.discount_codes'))


# =========================================================
# Feature #8: Bulk Announcements
# =========================================================
@admin_ops_bp.route('/trek/<int:id>/announce', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def announce(id):
    trek = db.session.get(Trek, id) or abort(404)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        if not title or not message:
            flash('Title and message are required.', 'danger')
            return redirect(url_for('admin_ops.announce', id=id))

        ann = Announcement(trek_id=trek.id, title=title, message=message)
        db.session.add(ann)
        db.session.commit()

        booked_count = Booking.query.filter_by(trek_id=trek.id, status='Booked').count()
        flash(f'Announcement sent! {booked_count} trekker(s) will see it on their dashboard.', 'success')
        return redirect(url_for('admin_ops.announce', id=id))

    announcements = Announcement.query.filter_by(trek_id=trek.id).order_by(Announcement.created_at.desc()).all()
    booked_count = Booking.query.filter_by(trek_id=trek.id, status='Booked').count()
    return render_template('admin/announce.html', trek=trek, announcements=announcements,
                           booked_count=booked_count)
