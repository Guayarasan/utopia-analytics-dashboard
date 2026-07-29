"""
Tests de app/jobs/compute_stats.py — solo las funciones puras
(compute_streaks, compute_activity_score). No requieren MySQL: son
lógica de negocio aislada a propósito para poder testearla así.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jobs.compute_stats import compute_streaks, compute_activity_score


# ----------------------------------------------------------------------
# compute_streaks
# ----------------------------------------------------------------------

def test_streaks_no_activity():
    assert compute_streaks([], date(2026, 7, 28)) == (0, 0)


def test_streaks_current_consecutive_up_to_today():
    today = date(2026, 7, 28)
    dates = [today - timedelta(days=i) for i in range(5)][::-1]  # 5 días seguidos hasta hoy
    current, best = compute_streaks(dates, today)
    assert current == 5
    assert best == 5


def test_streaks_current_counts_from_yesterday_if_not_played_today():
    today = date(2026, 7, 28)
    dates = [today - timedelta(days=i) for i in range(1, 4)][::-1]  # ayer, antes de ayer, hace 3 días
    current, best = compute_streaks(dates, today)
    assert current == 3
    assert best == 3


def test_streaks_broken_streak_resets_current_but_keeps_best():
    today = date(2026, 7, 28)
    # Racha larga hace tiempo (10 días), después un hueco, y solo 1 día activo reciente (ayer).
    old_run = [date(2026, 7, 1) + timedelta(days=i) for i in range(10)]
    recent = [today - timedelta(days=1)]
    dates = old_run + recent
    current, best = compute_streaks(dates, today)
    assert current == 1
    assert best == 10


def test_streaks_no_activity_today_or_yesterday_gives_zero_current():
    today = date(2026, 7, 28)
    dates = [today - timedelta(days=10)]
    current, best = compute_streaks(dates, today)
    assert current == 0
    assert best == 1


# ----------------------------------------------------------------------
# compute_activity_score
# ----------------------------------------------------------------------

def test_score_is_bounded_between_0_and_100():
    now = datetime(2026, 7, 28)
    score = compute_activity_score(
        last_seen=now,
        now=now,
        hours_last_30d=1000,       # muy por encima del target
        active_days_last_30d=30,
        current_streak_days=100,   # muy por encima del target
        afk_ratio_last_30d=0.0,
    )
    assert Decimal("0") <= score <= Decimal("100")
    assert score == Decimal("100.00")  # todo maximizado, sin penalización


def test_score_decays_with_days_since_last_seen():
    now = datetime(2026, 7, 28)
    recent = compute_activity_score(
        last_seen=now, now=now,
        hours_last_30d=40, active_days_last_30d=30,
        current_streak_days=14, afk_ratio_last_30d=0.0,
    )
    stale = compute_activity_score(
        last_seen=now - timedelta(days=60), now=now,
        hours_last_30d=40, active_days_last_30d=30,
        current_streak_days=14, afk_ratio_last_30d=0.0,
    )
    assert stale < recent


def test_score_never_negative_with_high_afk_ratio():
    now = datetime(2026, 7, 28)
    score = compute_activity_score(
        last_seen=now - timedelta(days=200),
        now=now,
        hours_last_30d=0,
        active_days_last_30d=0,
        current_streak_days=0,
        afk_ratio_last_30d=1.0,  # 100% del tiempo AFK
    )
    assert score >= Decimal("0")


def test_score_is_not_pure_function_of_hours_alone():
    """
    Dos jugadores con las mismas horas totales pero distinta
    consistencia/recencia no deben terminar con el mismo score — es
    justamente el requisito de que el score "no dependa únicamente
    del tiempo jugado".
    """
    now = datetime(2026, 7, 28)
    # Jugador A: jugó 20 horas en un solo día, hace 25 días, sin racha.
    player_a = compute_activity_score(
        last_seen=now - timedelta(days=25), now=now,
        hours_last_30d=20, active_days_last_30d=1,
        current_streak_days=0, afk_ratio_last_30d=0.0,
    )
    # Jugador B: las mismas 20 horas repartidas en 20 días distintos, activo hoy.
    player_b = compute_activity_score(
        last_seen=now, now=now,
        hours_last_30d=20, active_days_last_30d=20,
        current_streak_days=10, afk_ratio_last_30d=0.0,
    )
    assert player_b > player_a
