from datetime import date, timedelta

from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import func

from ...extensions import db, cache
from ...models import PlayerDailyStats, HourlyActivityStats

activity_bp = Blueprint("activity", __name__)


@activity_bp.route("/")
def index():
    return render_template("activity/index.html")


@activity_bp.route("/api/heatmap")
@cache.cached(timeout=300, query_string=True)
def api_heatmap():
    """
    Un valor por día (suma de horas jugadas de TODOS los jugadores ese
    día), para pintar un heatmap tipo GitHub. Rango por defecto: último
    año.
    """
    days = request.args.get("days", 365, type=int)
    start = date.today() - timedelta(days=days)

    rows = (
        db.session.query(
            PlayerDailyStats.stat_date,
            func.sum(PlayerDailyStats.playtime_seconds).label("seconds"),
        )
        .filter(PlayerDailyStats.stat_date >= start)
        .group_by(PlayerDailyStats.stat_date)
        .all()
    )
    data = {r.stat_date.isoformat(): round(r.seconds / 3600, 1) for r in rows}
    return jsonify(data)


@activity_bp.route("/api/daily")
@cache.cached(timeout=180, query_string=True)
def api_daily():
    """
    Serie diaria de horas jugadas + jugadores nuevos, para el gráfico
    de "Actividad diaria" y "Horas jugadas". `days` controla la
    ventana (30 = mensual, 7 = semanal, 1 no aplica — se usa hourly).
    """
    days = request.args.get("days", 30, type=int)
    start = date.today() - timedelta(days=days)

    rows = (
        db.session.query(
            PlayerDailyStats.stat_date,
            func.sum(PlayerDailyStats.playtime_seconds).label("seconds"),
            func.count(func.distinct(PlayerDailyStats.player_uuid)).label("active_players"),
        )
        .filter(PlayerDailyStats.stat_date >= start)
        .group_by(PlayerDailyStats.stat_date)
        .order_by(PlayerDailyStats.stat_date.asc())
        .all()
    )

    return jsonify(
        {
            "labels": [r.stat_date.isoformat() for r in rows],
            "hours": [round(r.seconds / 3600, 2) for r in rows],
            "active_players": [r.active_players for r in rows],
        }
    )


@activity_bp.route("/api/hourly")
@cache.cached(timeout=300, query_string=True)
def api_hourly():
    """
    Distribución de conexiones por hora del día, sumando el rango
    pedido (por defecto, los últimos 30 días) — para el gráfico de
    "horario de actividad".
    """
    days = request.args.get("days", 30, type=int)
    start = date.today() - timedelta(days=days)

    rows = (
        db.session.query(
            HourlyActivityStats.hour_of_day,
            func.sum(HourlyActivityStats.connections_count).label("connections"),
        )
        .filter(HourlyActivityStats.stat_date >= start)
        .group_by(HourlyActivityStats.hour_of_day)
        .all()
    )
    by_hour = {r.hour_of_day: r.connections for r in rows}
    return jsonify([by_hour.get(h, 0) for h in range(24)])
