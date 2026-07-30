from flask import Flask, render_template
from sqlalchemy.exc import ProgrammingError, OperationalError

from .config import Config
from .extensions import db, login_manager, cache


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    cache.init_app(app)

    from .models import DashboardUser

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(DashboardUser, int(user_id))

    from .blueprints.main.routes import main_bp
    from .blueprints.players.routes import players_bp
    from .blueprints.auth.routes import auth_bp
    from .blueprints.activity.routes import activity_bp
    from .blueprints.rankings.routes import rankings_bp
    from .blueprints.alerts.routes import alerts_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(players_bp, url_prefix="/players")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(activity_bp, url_prefix="/activity")
    app.register_blueprint(rankings_bp, url_prefix="/rankings")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")

    @app.cli.command("refresh-stats")
    def refresh_stats_command():
        """Recalcula rachas, Activity Score y global_stats_cache (cron)."""
        from .jobs.compute_stats import run

        run()
        print("Utopia Analytics — stats recalculadas.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Crea (o resetea la contraseña de) el primer usuario admin."""
        import getpass
        from werkzeug.security import generate_password_hash
        from .models import DashboardUser

        username = input("Usuario: ").strip()
        password = getpass.getpass("Contraseña: ")

        user = DashboardUser.query.filter_by(username=username).first()
        if user is None:
            user = DashboardUser(username=username, role="admin")
            db.session.add(user)
        user.password_hash = generate_password_hash(password)
        user.role = "admin"
        user.is_active_ = True
        db.session.commit()
        print(f"Utopia Analytics — usuario admin '{username}' listo.")

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(ProgrammingError)
    @app.errorhandler(OperationalError)
    def database_not_ready(error):
        # Deja la sesión limpia para el próximo request — si no se
        # revierte, SQLAlchemy sigue arrastrando el error en la misma
        # conexión y todo lo demás también empieza a fallar.
        db.session.rollback()

        # 1146 = "Table '...' doesn't exist" (MySQL/pymysql). Cualquier
        # otro código lo tratamos como "no se pudo conectar" — mismo
        # mensaje al usuario, pero nos sirve para el log del servidor.
        orig_args = getattr(getattr(error, "orig", None), "args", ())
        is_missing_table = bool(orig_args) and orig_args[0] == 1146

        app.logger.warning(f"[UtopiaAnalytics] Base de datos no lista: {error}")
        return (
            render_template(
                "errors/not_initialized.html", is_missing_table=is_missing_table
            ),
            503,
        )

    return app
