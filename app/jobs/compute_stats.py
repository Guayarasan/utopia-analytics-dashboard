"""
Job de cálculo periódico de Utopia Analytics.

Corre por fuera de las requests del dashboard (cron / Render Cron Job /
APScheduler) porque hace exactamente lo que NO debe pasar dentro de una
petición web: mirar el historial completo de cada jugador para calcular
rachas y Activity Score, y agregar toda la base para refrescar
`global_stats_cache`.

Uso:
    flask refresh-stats            # corre todo (rachas + score + cache global)
    python -m app.jobs.compute_stats   # equivalente, fuera del contexto CLI de Flask
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from ..extensions import db
from ..models import Player, PlayerDailyStats, GlobalStatsCache, Achievement
from .alerts_and_achievements import (
    ensure_achievements_seeded,
    check_player_achievements,
    check_player_alerts,
)

# ----------------------------------------------------------------------
# Parámetros del algoritmo de Activity Score. Documentados acá porque
# son la parte más "de producto" del job — si el criterio de negocio
# cambia, cambia solo esto.
# ----------------------------------------------------------------------

SCORE_WINDOW_DAYS = 30          # ventana de "actividad reciente"
RECENCY_HALF_LIFE_DAYS = 10     # a los N días sin conectarse, el componente de recencia cae a la mitad
VOLUME_TARGET_HOURS = 40        # horas/mes que valen el 100% del componente de volumen
STREAK_TARGET_DAYS = 14         # racha que vale el 100% del componente de racha
AFK_PENALTY_MAX_POINTS = 15     # máximo que resta el componente de AFK

WEIGHT_RECENCY = 0.25
WEIGHT_VOLUME = 0.25
WEIGHT_CONSISTENCY = 0.25
WEIGHT_STREAK = 0.15
# El AFK no suma peso propio: es una resta directa sobre el resultado.
# 0.25 + 0.25 + 0.25 + 0.15 = 0.90 → dejamos 10% de piso por
# participación básica (estar registrado ya vale algo).
BASE_FLOOR = 10


def _round2(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_streaks(daily_stats_dates: list[date], today: date) -> tuple[int, int]:
    """
    daily_stats_dates: fechas (ya ordenadas ascendente) en las que el
    jugador tuvo playtime_seconds > 0.
    Devuelve (racha_actual, mejor_racha_histórica).
    """
    if not daily_stats_dates:
        return 0, 0

    days_set = set(daily_stats_dates)

    # Mejor racha histórica: recorre el set de días activos.
    best_streak = 0
    current_run = 0
    prev_day = None
    for day in daily_stats_dates:
        if prev_day is not None and (day - prev_day).days == 1:
            current_run += 1
        else:
            current_run = 1
        best_streak = max(best_streak, current_run)
        prev_day = day

    # Racha actual: cuenta hacia atrás desde hoy (o ayer, si hoy
    # todavía no hay datos porque el jugador no se conectó aún hoy).
    current_streak = 0
    cursor = today
    if cursor not in days_set:
        cursor = today - timedelta(days=1)
    while cursor in days_set:
        current_streak += 1
        cursor -= timedelta(days=1)

    return current_streak, best_streak


def compute_activity_score(
    *,
    last_seen: datetime,
    now: datetime,
    hours_last_30d: float,
    active_days_last_30d: int,
    current_streak_days: int,
    afk_ratio_last_30d: float,
) -> Decimal:
    """
    Devuelve un score 0-100. No depende únicamente de horas jugadas:
    combina recencia, volumen, consistencia y racha, y penaliza AFK
    alto.
    """
    days_since_last_seen = max(0.0, (now - last_seen).total_seconds() / 86400)
    recency_component = 100 * (0.5 ** (days_since_last_seen / RECENCY_HALF_LIFE_DAYS))

    volume_component = min(100.0, (hours_last_30d / VOLUME_TARGET_HOURS) * 100)

    consistency_component = min(100.0, (active_days_last_30d / SCORE_WINDOW_DAYS) * 100)

    streak_component = min(100.0, (current_streak_days / STREAK_TARGET_DAYS) * 100)

    weighted = (
        BASE_FLOOR
        + WEIGHT_RECENCY * recency_component
        + WEIGHT_VOLUME * volume_component
        + WEIGHT_CONSISTENCY * consistency_component
        + WEIGHT_STREAK * streak_component
    )

    afk_penalty = min(AFK_PENALTY_MAX_POINTS, afk_ratio_last_30d * AFK_PENALTY_MAX_POINTS * 2)
    score = max(0.0, min(100.0, weighted - afk_penalty))

    return _round2(score)


def refresh_player_stats(player: Player, now: datetime, achievements_by_code: dict) -> None:
    today = now.date()
    window_start = today - timedelta(days=SCORE_WINDOW_DAYS)

    rows = (
        db.session.query(PlayerDailyStats.stat_date, PlayerDailyStats.playtime_seconds, PlayerDailyStats.afk_seconds)
        .filter(
            PlayerDailyStats.player_uuid == player.uuid,
            PlayerDailyStats.stat_date >= window_start,
        )
        .order_by(PlayerDailyStats.stat_date.asc())
        .all()
    )

    active_dates = [r.stat_date for r in rows if r.playtime_seconds > 0]
    hours_last_30d = sum(r.playtime_seconds for r in rows) / 3600
    afk_seconds_30d = sum(r.afk_seconds for r in rows)
    playtime_seconds_30d = sum(r.playtime_seconds for r in rows)
    afk_ratio = (afk_seconds_30d / playtime_seconds_30d) if playtime_seconds_30d > 0 else 0.0

    # Para la racha histórica y los logros por "días activos totales"
    # hace falta todo el historial, no solo la ventana de 30 días.
    all_active_dates = [
        r[0]
        for r in db.session.query(PlayerDailyStats.stat_date)
        .filter(PlayerDailyStats.player_uuid == player.uuid, PlayerDailyStats.playtime_seconds > 0)
        .order_by(PlayerDailyStats.stat_date.asc())
        .all()
    ]

    current_streak, best_streak_from_history = compute_streaks(all_active_dates, today)

    score = compute_activity_score(
        last_seen=player.last_seen,
        now=now,
        hours_last_30d=hours_last_30d,
        active_days_last_30d=len(active_dates),
        current_streak_days=current_streak,
        afk_ratio_last_30d=afk_ratio,
    )

    previous_best_streak = player.best_streak_days
    new_best_streak = max(player.best_streak_days, best_streak_from_history)

    # Último día activo estrictamente antes de hoy (para detectar
    # "regresó tras N días de ausencia"), y si jugó hoy mismo — el
    # regreso solo cuenta si efectivamente volvió a jugar hoy.
    active_before_today = [d for d in all_active_dates if d < today]
    last_active_before_today = active_before_today[-1] if active_before_today else None
    played_today = today in all_active_dates

    player.current_streak_days = current_streak
    player.best_streak_days = new_best_streak
    player.activity_score = score
    player.activity_score_updated_at = now

    check_player_alerts(
        player,
        now=now,
        previous_best_streak=previous_best_streak,
        new_current_streak=current_streak,
        new_best_streak=new_best_streak,
        played_today=played_today,
        last_active_before_today=last_active_before_today,
    )
    check_player_achievements(
        player,
        now=now,
        active_days_total=len(all_active_dates),
        achievements_by_code=achievements_by_code,
    )


def refresh_global_stats(now: datetime) -> None:
    today = now.date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    total_registered = db.session.query(func.count(Player.uuid)).scalar() or 0
    suspended = db.session.query(func.count(Player.uuid)).filter(Player.status == "suspended").scalar() or 0
    archived = db.session.query(func.count(Player.uuid)).filter(Player.status == "archived").scalar() or 0
    banned = db.session.query(func.count(Player.uuid)).filter(Player.status == "banned").scalar() or 0

    # "Conectados ahora" se aproxima con last_seen reciente, ya que el
    # plugin actualiza last_seen en cada join y el dashboard no tiene
    # visibilidad directa de sesiones TCP abiertas.
    online_threshold = now - timedelta(minutes=5)
    players_online = (
        db.session.query(func.count(Player.uuid)).filter(Player.last_seen >= online_threshold).scalar() or 0
    )

    active_today = (
        db.session.query(func.count(func.distinct(PlayerDailyStats.player_uuid)))
        .filter(PlayerDailyStats.stat_date == today, PlayerDailyStats.playtime_seconds > 0)
        .scalar()
        or 0
    )
    active_week = (
        db.session.query(func.count(func.distinct(PlayerDailyStats.player_uuid)))
        .filter(PlayerDailyStats.stat_date >= week_ago, PlayerDailyStats.playtime_seconds > 0)
        .scalar()
        or 0
    )
    active_month = (
        db.session.query(func.count(func.distinct(PlayerDailyStats.player_uuid)))
        .filter(PlayerDailyStats.stat_date >= month_ago, PlayerDailyStats.playtime_seconds > 0)
        .scalar()
        or 0
    )

    hours_today = (
        db.session.query(func.coalesce(func.sum(PlayerDailyStats.playtime_seconds), 0))
        .filter(PlayerDailyStats.stat_date == today)
        .scalar()
        or 0
    ) / 3600
    hours_month = (
        db.session.query(func.coalesce(func.sum(PlayerDailyStats.playtime_seconds), 0))
        .filter(PlayerDailyStats.stat_date >= month_ago)
        .scalar()
        or 0
    ) / 3600

    avg_daily = (hours_month / 30) if total_registered else 0
    avg_weekly = avg_daily * 7
    avg_monthly = hours_month

    avg_score = db.session.query(func.coalesce(func.avg(Player.activity_score), 0)).scalar() or 0
    avg_afk = (
        db.session.query(func.coalesce(func.avg(PlayerDailyStats.afk_seconds), 0))
        .filter(PlayerDailyStats.stat_date >= month_ago)
        .scalar()
        or 0
    )

    cache_row = GlobalStatsCache.query.filter_by(snapshot_date=None).first()
    if cache_row is None:
        cache_row = GlobalStatsCache(snapshot_date=None)
        db.session.add(cache_row)

    cache_row.players_online = players_online
    cache_row.active_today = active_today
    cache_row.active_this_week = active_week
    cache_row.active_this_month = active_month
    cache_row.hours_played_today = _round2(hours_today)
    cache_row.hours_played_month = _round2(hours_month)
    cache_row.avg_daily_hours = _round2(avg_daily)
    cache_row.avg_weekly_hours = _round2(avg_weekly)
    cache_row.avg_monthly_hours = _round2(avg_monthly)
    cache_row.avg_activity_score = _round2(float(avg_score))
    cache_row.avg_afk_seconds = int(avg_afk)
    cache_row.total_registered_players = total_registered
    cache_row.suspended_count = suspended
    cache_row.archived_count = archived
    cache_row.banned_count = banned
    cache_row.computed_at = now


def run(batch_size: int = 200) -> None:
    now = datetime.utcnow()

    ensure_achievements_seeded()
    achievements_by_code = {a.code: a for a in Achievement.query.all()}

    query = Player.query.filter(Player.status.in_(["active", "inactive", "suspended"]))
    offset = 0
    while True:
        batch = query.order_by(Player.uuid).offset(offset).limit(batch_size).all()
        if not batch:
            break
        for player in batch:
            refresh_player_stats(player, now, achievements_by_code)
        db.session.commit()
        offset += batch_size

    refresh_global_stats(now)
    db.session.commit()
