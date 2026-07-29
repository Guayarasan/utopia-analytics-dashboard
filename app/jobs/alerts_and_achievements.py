"""
Logros y alertas de Utopia Analytics.

Se llama desde `jobs/compute_stats.py`, dentro del mismo recorrido de
jugadores que ya calcula rachas y Activity Score — así no hace falta
volver a consultar el historial completo por separado.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..extensions import db
from ..models import (
    Player,
    PlayerDailyStats,
    Achievement,
    PlayerAchievement,
    Alert,
)

# ----------------------------------------------------------------------
# Logros por defecto. `criteria_type` decide qué compara
# `check_player_achievements` — agregar un logro nuevo es agregar una
# fila acá, no tocar código.
# ----------------------------------------------------------------------

DEFAULT_ACHIEVEMENTS = [
    {"code": "first_join", "name": "Primer ingreso", "description": "Se conectó por primera vez.",
     "criteria_type": "first_join", "criteria_value": 0},
    {"code": "100_hours", "name": "100 horas", "description": "Acumuló 100 horas jugadas.",
     "criteria_type": "playtime_hours", "criteria_value": 100},
    {"code": "500_hours", "name": "500 horas", "description": "Acumuló 500 horas jugadas.",
     "criteria_type": "playtime_hours", "criteria_value": 500},
    {"code": "1000_hours", "name": "1000 horas", "description": "Acumuló 1000 horas jugadas.",
     "criteria_type": "playtime_hours", "criteria_value": 1000},
    {"code": "100_days_active", "name": "100 días", "description": "Estuvo activo 100 días distintos.",
     "criteria_type": "active_days_total", "criteria_value": 100},
    {"code": "first_year", "name": "Primer año", "description": "Cumplió un año en el servidor.",
     "criteria_type": "days_since_first_seen", "criteria_value": 365},
]

# Alertas: evita duplicar la misma alerta para el mismo jugador en un
# período corto (spam de una alerta por cada corrida del job).
ALERT_COOLDOWN_DAYS = 7
INACTIVITY_THRESHOLD_DAYS = 30
RETURN_THRESHOLD_DAYS = 120


def ensure_achievements_seeded() -> None:
    existing_codes = {row.code for row in Achievement.query.all()}
    for spec in DEFAULT_ACHIEVEMENTS:
        if spec["code"] not in existing_codes:
            db.session.add(Achievement(**spec))
    db.session.commit()


def _recently_alerted(player_uuid: str, alert_type: str, now: datetime) -> bool:
    cutoff = now - timedelta(days=ALERT_COOLDOWN_DAYS)
    return (
        db.session.query(Alert.id)
        .filter(
            Alert.player_uuid == player_uuid,
            Alert.alert_type == alert_type,
            Alert.triggered_at >= cutoff,
        )
        .first()
        is not None
    )


def check_player_achievements(
    player: Player,
    now: datetime,
    active_days_total: int,
    achievements_by_code: dict[str, Achievement],
) -> None:
    unlocked_codes = {
        pa.achievement.code
        for pa in PlayerAchievement.query.filter_by(player_uuid=player.uuid).all()
    }

    hours = player.total_playtime_seconds / 3600
    days_since_first_seen = (now - player.first_seen).days

    for code, achievement in achievements_by_code.items():
        if code in unlocked_codes:
            continue

        earned = False
        if achievement.criteria_type == "first_join":
            earned = True
        elif achievement.criteria_type == "playtime_hours":
            earned = hours >= achievement.criteria_value
        elif achievement.criteria_type == "active_days_total":
            earned = active_days_total >= achievement.criteria_value
        elif achievement.criteria_type == "days_since_first_seen":
            earned = days_since_first_seen >= achievement.criteria_value

        if earned:
            db.session.add(
                PlayerAchievement(
                    player_uuid=player.uuid, achievement_id=achievement.id, unlocked_at=now
                )
            )


def check_player_alerts(
    player: Player,
    now: datetime,
    previous_best_streak: int,
    new_current_streak: int,
    new_best_streak: int,
    played_today: bool,
    last_active_before_today: "date | None",
) -> None:
    # 1) Inactividad: activo hasta ahora pero sin conectarse hace 30+ días.
    if player.status == "active":
        days_idle = (now - player.last_seen).days
        if days_idle >= INACTIVITY_THRESHOLD_DAYS and not _recently_alerted(
            player.uuid, "inactive_30d", now
        ):
            db.session.add(
                Alert(
                    player_uuid=player.uuid,
                    alert_type="inactive_30d",
                    message=f"{player.username} lleva {days_idle} días sin conectarse.",
                    triggered_at=now,
                )
            )
            player.status = "inactive"

    # 2) Retorno tras una ausencia larga: SOLO si jugó hoy (played_today) y
    #    su día activo anterior fue hace 120+ días. Sin el chequeo de
    #    played_today, esto dispararía "regresó" para cualquier jugador
    #    inactivo cada vez que corre el job, aunque nunca haya vuelto.
    today = now.date()
    if played_today and last_active_before_today is not None:
        gap_days = (today - last_active_before_today).days
        if gap_days >= RETURN_THRESHOLD_DAYS and not _recently_alerted(
            player.uuid, "returned", now
        ):
            db.session.add(
                Alert(
                    player_uuid=player.uuid,
                    alert_type="returned",
                    message=f"{player.username} regresó tras {gap_days} días de ausencia.",
                    triggered_at=now,
                )
            )
            if player.status in ("inactive", "archived"):
                player.status = "active"

    # 3) Nueva racha récord.
    if new_best_streak > previous_best_streak and new_current_streak == new_best_streak:
        db.session.add(
            Alert(
                player_uuid=player.uuid,
                alert_type="new_streak",
                message=f"{player.username} alcanzó una nueva racha récord: {new_best_streak} días.",
                triggered_at=now,
            )
        )
