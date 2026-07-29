from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required

from ...extensions import db
from ...models import Alert
from ...utils.auth import roles_required

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.route("/")
def index():
    show = request.args.get("show", "unread")
    query = Alert.query.order_by(Alert.triggered_at.desc())
    if show == "unread":
        query = query.filter(Alert.is_read.is_(False))

    alerts = query.limit(100).all()
    return render_template("alerts/index.html", alerts=alerts, show=show)


@alerts_bp.route("/<int:alert_id>/read", methods=["POST"])
@login_required
@roles_required("admin", "moderator")
def mark_read(alert_id: int):
    alert = Alert.query.get_or_404(alert_id)
    alert.is_read = True
    db.session.commit()
    return redirect(url_for("alerts.index", show=request.args.get("show", "unread")))
