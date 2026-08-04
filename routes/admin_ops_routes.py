from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from datetime import timedelta
from models import (db, Trek, Booking, Announcement)
from .utils import login_required, role_required

admin_ops_bp = Blueprint('admin_ops', __name__, url_prefix='/admin')


# =========================================================
# Trek Occupancy Metrics
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
# Trek Clone/Duplicate
# =========================================================
@admin_ops_bp.route('/trek/<int:id>/clone', methods=['POST'])
@login_required
@role_required('admin')
def clone_trek(id):
    """Duplicate an existing trek with dates offset by +30 days."""
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
        gear_checklist=original.gear_checklist,
        local_connects=original.local_connects,
    )
    db.session.add(cloned)
    db.session.commit()
    flash(f'Trek "{original.name}" cloned! New dates: {cloned.start_date.strftime("%d-%m-%Y")} to {cloned.end_date.strftime("%d-%m-%Y")}.', 'success')
    return redirect(url_for('admin.edit_trek', id=cloned.id))


# =========================================================
# Bulk Announcements
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
