import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esto-en-produccion")

    _db_user = os.environ.get("DB_USER", "utopia_analytics")
    _db_password = os.environ.get("DB_PASSWORD", "")
    _db_host = os.environ.get("DB_HOST", "127.0.0.1")
    _db_port = os.environ.get("DB_PORT", "3306")
    _db_name = os.environ.get("DB_NAME", "utopia_analytics")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"mysql+pymysql://{_db_user}:{_db_password}@{_db_host}:{_db_port}/{_db_name}",
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Pool modesto pero con reciclado de conexiones: MySQL en Render
        # (y en la mayoría de hostings) cierra conexiones inactivas, y
        # sin pool_recycle terminamos con errores "MySQL server has
        # gone away" bajo tráfico bajo.
        "pool_size": int(os.environ.get("DB_POOL_SIZE", 5)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 5)),
        "pool_recycle": 280,
        "pool_pre_ping": True,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    CACHE_TYPE = os.environ.get("CACHE_TYPE", "SimpleCache")
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get("CACHE_DEFAULT_TIMEOUT", 60))

    # Cuánto tiempo se considera "vivo" un jugador conectado sin señales
    # nuevas del plugin (ver player_sessions.disconnected_at IS NULL).
    ONLINE_THRESHOLD_MINUTES = int(os.environ.get("ONLINE_THRESHOLD_MINUTES", 5))
