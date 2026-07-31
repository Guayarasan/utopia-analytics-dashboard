"""
Scheduler interno de Utopia Analytics.

Antes, `flask refresh-stats` (rachas, Activity Score, estados
automáticos, alertas, logros, global_stats_cache) solo corría si
alguien lo disparaba a mano o configuraba un cron externo (Render
Cron Job, docker-compose). Si el hosting no tenía ese cron
configurado, el job simplemente nunca corría — de ahí paneles con
"0"/"None" aunque el plugin sí estuviera guardando datos reales.

Esto arranca el mismo job DENTRO del proceso del dashboard con
APScheduler, así funciona out-of-the-box en cualquier hosting, sin
pasos manuales. La primera corrida es casi inmediata al arrancar (10s
después), y después cada `REFRESH_STATS_INTERVAL_MINUTES`.

CUIDADO CON MÚLTIPLES WORKERS: si el dashboard corre con más de un
worker de gunicorn (o más de una instancia), cada uno arrancaría su
propio scheduler y el job correría N veces en paralelo cada ciclo.
No rompe nada (las operaciones son upserts idempotentes), pero es
redundante. Con un solo worker (el default de `render.yaml` y del
`Dockerfile` de este proyecto) no hay problema. Si escalás a más
workers, poné `ENABLE_INTERNAL_SCHEDULER=false` y usá el cron externo
(`render.yaml` ya trae uno) en su lugar.
"""

from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


def init_scheduler(app) -> BackgroundScheduler | None:
    if not app.config.get("ENABLE_INTERNAL_SCHEDULER", True):
        app.logger.info(
            "[UtopiaAnalytics] Scheduler interno desactivado "
            "(ENABLE_INTERNAL_SCHEDULER=false) — usá el cron externo."
        )
        return None

    # Bajo `flask run` con debug=True, Flask lanza un proceso recargador
    # que a su vez lanza el proceso real de la app — sin este chequeo,
    # el scheduler arrancaría duplicado (uno por proceso). Con gunicorn
    # (producción) esta env var nunca está seteada, así que arranca normal.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None

    def run_job():
        with app.app_context():
            from .jobs.compute_stats import run as run_compute_stats

            try:
                run_compute_stats()
                app.logger.info("[UtopiaAnalytics] refresh-stats (interno) completado.")
            except Exception:
                # Un fallo del job no debe tumbar el proceso del dashboard.
                app.logger.exception(
                    "[UtopiaAnalytics] refresh-stats (interno) falló, "
                    "se reintenta en el próximo ciclo."
                )

    interval_minutes = app.config.get("REFRESH_STATS_INTERVAL_MINUTES", 5)

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        run_job,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="refresh_stats",
        next_run_time=None,  # se programa el primer disparo manualmente abajo
        replace_existing=True,
        max_instances=1,  # si una corrida se alarga, no se solapa con la siguiente
        coalesce=True,
    )
    # Primera corrida casi inmediata (10s) para no dejar el dashboard
    # en blanco esperando el primer intervalo completo.
    import datetime

    scheduler.modify_job(
        "refresh_stats",
        next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10),
    )
    scheduler.start()

    app.logger.info(
        f"[UtopiaAnalytics] Scheduler interno activo — refresh-stats cada "
        f"{interval_minutes} min (primera corrida en ~10s)."
    )
    return scheduler
