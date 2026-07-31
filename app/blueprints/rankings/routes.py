from flask import Blueprint, render_template, request, jsonify

from ...models import Player

rankings_bp = Blueprint("rankings", __name__)

# Cada tipo de ranking: (etiqueta, orden, lista opcional de estados a incluir)
RANKING_TYPES = {
    "activity": {"label": "Top actividad", "order": lambda: Player.activity_score.desc()},
    "hours": {"label": "Top horas", "order": lambda: Player.total_playtime_seconds.desc()},
    "streaks": {"label": "Top rachas", "order": lambda: Player.current_streak_days.desc()},
    "veterans": {"label": "Top veteranos", "order": lambda: Player.first_seen.asc()},
    "new": {"label": "Top nuevos", "order": lambda: Player.first_seen.desc()},
    "most_active": {
        "label": "Top jugadores activos",
        "order": lambda: Player.last_seen.desc(),
        "statuses": ["active"],
    },
    "most_inactive": {
        "label": "Top jugadores inactivos/dormidos",
        "order": lambda: Player.last_seen.asc(),
        "statuses": ["inactive", "dormant"],
    },
    "afk": {"label": "Top tiempo AFK", "order": lambda: Player.total_afk_seconds.desc()},
}


@rankings_bp.route("/")
def index():
    ranking_type = request.args.get("type", "activity")
    if ranking_type not in RANKING_TYPES:
        ranking_type = "activity"

    spec = RANKING_TYPES[ranking_type]
    query = Player.query
    if "statuses" in spec:
        query = query.filter(Player.status.in_(spec["statuses"]))

    players = query.order_by(spec["order"]()).limit(50).all()

    return render_template(
        "rankings/index.html",
        players=players,
        ranking_type=ranking_type,
        ranking_types=RANKING_TYPES,
    )


@rankings_bp.route("/compare")
def compare():
    uuid_a = request.args.get("a", "")
    uuid_b = request.args.get("b", "")

    player_a = Player.query.get(uuid_a) if uuid_a else None
    player_b = Player.query.get(uuid_b) if uuid_b else None

    return render_template(
        "rankings/compare.html",
        player_a=player_a,
        player_b=player_b,
    )


@rankings_bp.route("/api/search-players")
def api_search_players():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    players = (
        Player.query.filter(Player.username.ilike(f"%{q}%"))
        .order_by(Player.username.asc())
        .limit(10)
        .all()
    )
    return jsonify([{"uuid": p.uuid, "username": p.username} for p in players])
