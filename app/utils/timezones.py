"""
Todo en la base de datos se guarda en UTC — el job usa
`datetime.utcnow()` en Python y el plugin fuerza `time_zone='+00:00'`
en cada conexión MySQL (ver db.py del plugin), así que no hay ambigüedad
a la hora de calcular "días desde la última conexión", rachas, etc.

Esto solo afecta cómo se MUESTRAN esas fechas en el dashboard — se
convierten a `DISPLAY_TIMEZONE` (Bogotá por defecto) justo antes de
renderizar, nunca antes.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def register_timezone_filter(app) -> None:
    display_tz = ZoneInfo(app.config.get("DISPLAY_TIMEZONE", "America/Bogota"))

    def local(value: datetime | None) -> datetime | None:
        """Convierte un datetime naive (asumido UTC) a la zona de despliegue."""
        if value is None:
            return None
        # Los datetimes que vienen de MySQL/SQLAlchemy llegan "naive"
        # (sin tzinfo) pero representan UTC — hay que decírselo
        # explícitamente antes de convertir, si no Python asume que ya
        # están en la zona local y el corrimiento sale mal.
        aware_utc = value.replace(tzinfo=ZoneInfo("UTC"))
        return aware_utc.astimezone(display_tz)

    app.jinja_env.filters["local"] = local
