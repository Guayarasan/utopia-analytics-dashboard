from datetime import datetime

from flask import Blueprint, render_template

from ...extensions import cache
from ...models import GlobalStatsCache, Player

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    stats = _get_global_stats()
    recent_connections = (
        Player.query.order_by(Player.last_seen.desc()).limit(8).all()
    )
    recent_registrations = (
        Player.query.order_by(Player.first_seen.desc()).limit(8).all()
    )
    return render_template(
        "index.html",
        stats=stats,
        recent_connections=recent_connections,
        recent_registrations=recent_registrations,
    )


@cache.cached(timeout=30, key_prefix="global_stats")
def _get_global_stats() -> GlobalStatsCache:
    """
    Lee siempre la fila "viva" (snapshot_date IS NULL) que un job
    periódico mantiene actualizada. La página principal JAMÁS agrega
    datos de player_sessions/player_daily_stats al vuelo — ver notas
    de rendimiento en el esquema.
    """
    stats = GlobalStatsCache.query.filter_by(snapshot_date=None).first()
    if stats is None:
        # Primer arranque: aún no corrió el job de refresco. Se muestra
        # una fila vacía en vez de romper la página.
        stats = GlobalStatsCache(computed_at=datetime.utcnow())
    return stats
