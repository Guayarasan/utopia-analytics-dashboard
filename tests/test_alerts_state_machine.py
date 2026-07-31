"""
Tests de app/jobs/alerts_and_achievements.py — la máquina de estados
automática (active/inactive/dormant/archived) y las alertas que
dispara. `db.session` se mockea porque esta lógica sí llama a
db.session.add()/query() — no hace falta MySQL real para probar las
transiciones, solo interceptar esas dos llamadas.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jobs import alerts_and_achievements as aa
from app.models import Player


NOW = datetime(2026, 7, 30)


def _make_player(status: str, days_idle: int) -> Player:
    return Player(
        uuid="u1",
        username="Musashi",
        status=status,
        first_seen=NOW - timedelta(days=400),
        last_seen=NOW - timedelta(days=days_idle),
    )


def _run_check_player_alerts(player, played_today=False, last_active_before_today=None):
    """Corre check_player_alerts con db.session mockeado y devuelve los
    alert_type de las alertas que se hubieran agregado."""
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None  # nunca "recién alertado"

    added = []
    mock_session.add.side_effect = lambda obj: added.append(obj)

    with patch.object(aa.db, "session", mock_session):
        aa.check_player_alerts(
            player,
            now=NOW,
            previous_best_streak=5,
            new_current_streak=1,
            new_best_streak=5,
            played_today=played_today,
            last_active_before_today=last_active_before_today,
        )

    return player.status, [a.alert_type for a in added]


def test_stays_active_under_inactivity_threshold():
    player = _make_player("active", days_idle=10)
    status, alerts = _run_check_player_alerts(player)
    assert status == "active"
    assert alerts == []


def test_active_to_inactive_past_30_days():
    player = _make_player("active", days_idle=45)
    status, alerts = _run_check_player_alerts(player)
    assert status == "inactive"
    assert "inactive_30d" in alerts


def test_cascades_directly_to_archived_in_one_pass():
    """Si el job no corrió en mucho tiempo, un jugador marcado 'active'
    con 200 días de inactividad debe llegar directo a 'archived' — no
    quedarse a mitad de camino en 'inactive' o 'dormant' esperando
    varios ciclos del job."""
    player = _make_player("active", days_idle=200)
    status, alerts = _run_check_player_alerts(player)
    assert status == "archived"
    assert "archived_auto" in alerts


def test_dormant_stays_dormant_before_archive_threshold():
    player = _make_player("dormant", days_idle=100)
    status, alerts = _run_check_player_alerts(player)
    assert status == "dormant"
    assert alerts == []


def test_manual_statuses_are_never_touched():
    """suspended/banned son decisiones del admin — la máquina de
    estados automática nunca las cambia, sin importar la inactividad."""
    player = _make_player("suspended", days_idle=300)
    status, alerts = _run_check_player_alerts(player)
    assert status == "suspended"
    assert alerts == []


def test_playing_today_reactivates_immediately_with_returned_alert():
    player = _make_player("dormant", days_idle=100)
    status, alerts = _run_check_player_alerts(
        player, played_today=True, last_active_before_today=date(2026, 3, 1)
    )
    assert status == "active"
    assert "returned" in alerts


def test_playing_today_reactivates_without_returned_alert_for_short_gap():
    """Reactiva igual, pero la alerta 'returned' es solo para ausencias
    largas (120+ días) — no cualquier regreso menor genera ruido."""
    player = _make_player("inactive", days_idle=35)
    status, alerts = _run_check_player_alerts(
        player, played_today=True, last_active_before_today=date(2026, 7, 1)
    )
    assert status == "active"
    assert "returned" not in alerts


def test_returned_alert_never_fires_without_playing_today():
    """Regresión del bug original: sin played_today=True, nunca debe
    generarse 'returned', sin importar cuántos días pasaron."""
    player = _make_player("inactive", days_idle=150)
    status, alerts = _run_check_player_alerts(
        player, played_today=False, last_active_before_today=date(2026, 2, 1)
    )
    assert "returned" not in alerts
