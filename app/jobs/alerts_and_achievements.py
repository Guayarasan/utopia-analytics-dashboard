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

# Umbrales de la máquina de estados automática. Solo se aplican a
# jugadores en un estado "auto-gestionado" (AUTO_MANAGED_STATUSES) —
# suspended/banned son decisiones manuales del admin y esta lógica
# nunca las toca ni las revierte.
INACTIVITY_THRESHOLD_DAYS = 30   # active   -> inactive
DORMANT_THRESHOLD_DAYS = 90      # inactive -> dormant
ARCHIVE_THRESHOLD_DAYS = 180     # dormant  -> archived (automático; no es un borrado, solo cambia el estado)
RETURN_THRESHOLD_DAYS = 120      # a partir de acá, "volver a jugar" genera la alerta 'returned' (además de reactivar igual con cualquier ausencia)

AUTO_MANAGED_STATUSES = {"active", "inactive", "dormant", "archived"}


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


def _target_status_for_idle_days(days_idle: int) -> str:
    """A qué estado 'debería' estar un jugador auto-gestionado según
    cuántos días lleva sin conectarse — se recalcula desde cero en cada
    corrida, así que cascadea active -> archived en un solo pase del
    job aunque el job no haya corrido en mucho tiempo."""
    if days_idle >= ARCHIVE_THRESHOLD_DAYS:
        return "archived"
    if days_idle >= DORMANT_THRESHOLD_DAYS:
        return "dormant"
    if days_idle >= INACTIVITY_THRESHOLD_DAYS:
        return "inactive"
    return "active"


_TRANSITION_ALERTS = {
    "inactive": ("inactive_30d", "{name} lleva {days} días sin conectarse."),
    "dormant": ("dormant_90d", "{name} lleva {days} días sin conectarse — pasó a dormido."),
    "archived": ("archived_auto", "{name} lleva {days} días sin conectarse — se archivó automáticamente."),
}


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
    today = now.date()

    if played_today:
        # Volvió a jugar hoy: reactivación inmediata si estaba en
        # cualquier estado de ausencia auto-gestionado. No hace falta
        # esperar al próximo ciclo del job para que se refleje.
        if player.status in AUTO_MANAGED_STATUSES and player.status != "active":
            player.status = "active"

        # Alerta de "regreso" reservada para ausencias largas y
        # notables — sin este chequeo de played_today, dispararía para
        # cualquier jugador inactivo en cada corrida del job, sin que
        # hubiera vuelto realmente (bug ya corregido antes).
        if last_active_before_today is not None:
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

    elif player.status in AUTO_MANAGED_STATUSES:
        # No jugó hoy: revisa si le toca bajar de nivel según cuánto
        # lleva sin conectarse (active -> inactive -> dormant -> archived).
        days_idle = (now - player.last_seen).days
        target_status = _target_status_for_idle_days(days_idle)

        if target_status != player.status:
            alert_spec = _TRANSITION_ALERTS.get(target_status)
            if alert_spec is not None:
                alert_type, template = alert_spec
                if not _recently_alerted(player.uuid, alert_type, now):
                    db.session.add(
                        Alert(
                            player_uuid=player.uuid,
                            alert_type=alert_type,
                            message=template.format(name=player.username, days=days_idle),
                            triggered_at=now,
                        )
                    )
            player.status = target_status

    # Nueva racha récord — independiente del estado.
    if new_best_streak > previous_best_streak and new_current_streak == new_best_streak:
        db.session.add(
            Alert(
                player_uuid=player.uuid,
                alert_type="new_streak",
                message=f"{player.username} alcanzó una nueva racha récord: {new_best_streak} días.",
                triggered_at=now,
            )
        )
