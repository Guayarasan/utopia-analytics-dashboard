from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user

from ...extensions import db
from ...models import Player
from ...utils.auth import roles_required

players_bp = Blueprint("players", __name__)


@players_bp.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    query = request.args.get("q", "", type=str).strip()
    status = request.args.get("status", "", type=str).strip()

    q = Player.query
    if query:
        q = q.filter(Player.username.ilike(f"%{query}%"))
    if status:
        q = q.filter(Player.status == status)

    pagination = q.order_by(Player.activity_score.desc()).paginate(
        page=page, per_page=25, error_out=False
    )

    return render_template(
        "players/index.html",
        players=pagination.items,
        pagination=pagination,
        query=query,
        status=status,
    )


@players_bp.route("/<uuid>")
def profile(uuid: str):
    from ...models import PlayerSession, PlayerTimelineEvent, AdminNote

    player = Player.query.get_or_404(uuid)
    recent_sessions = (
        player.sessions.order_by(PlayerSession.connected_at.desc()).limit(20).all()
    )
    timeline = (
        player.timeline_events.order_by(PlayerTimelineEvent.occurred_at.desc()).limit(50).all()
    )
    notes = player.notes.order_by(AdminNote.created_at.desc()).all()

    return render_template(
        "players/profile.html",
        player=player,
        recent_sessions=recent_sessions,
        timeline=timeline,
        notes=notes,
    )


@players_bp.route("/<uuid>/notes", methods=["POST"])
@login_required
@roles_required("admin", "moderator")
def add_note(uuid: str):
    from ...models import AdminNote

    player = Player.query.get_or_404(uuid)
    text = request.form.get("note", "").strip()
    if text:
        db.session.add(
            AdminNote(player_uuid=player.uuid, author_user_id=current_user.id, note=text)
        )
        db.session.commit()
    return redirect(url_for("players.profile", uuid=uuid))


@players_bp.route("/<uuid>/status", methods=["POST"])
@login_required
@roles_required("admin")
def change_status(uuid: str):
    from ...models import PlayerTimelineEvent

    player = Player.query.get_or_404(uuid)
    new_status = request.form.get("status", "")
    valid_statuses = {"active", "inactive", "dormant", "suspended", "archived", "banned"}
    if new_status in valid_statuses and new_status != player.status:
        event_type = {
            "suspended": "suspended",
            "banned": "banned",
            "archived": "archived",
            "active": "unsuspended" if player.status == "suspended" else "unbanned",
        }.get(new_status, "other")

        player.status = new_status
        db.session.add(
            PlayerTimelineEvent(
                player_uuid=player.uuid,
                event_type=event_type if event_type in {
                    "suspended", "banned", "archived", "unsuspended", "unbanned"
                } else "other",
                event_data={"changed_by": current_user.username, "new_status": new_status},
            )
        )
        db.session.commit()
    return redirect(url_for("players.profile", uuid=uuid))
