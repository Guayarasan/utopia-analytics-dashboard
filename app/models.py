from datetime import datetime

from .extensions import db


class Player(db.Model):
    __tablename__ = "players"

    uuid = db.Column(db.String(36), primary_key=True)
    username = db.Column(db.String(16), nullable=False, index=True)
    status = db.Column(
        db.Enum("active", "inactive", "suspended", "archived", "banned"),
        nullable=False,
        default="active",
        index=True,
    )
    first_seen = db.Column(db.DateTime, nullable=False)
    last_seen = db.Column(db.DateTime, nullable=False, index=True)

    total_playtime_seconds = db.Column(db.BigInteger, nullable=False, default=0)
    total_afk_seconds = db.Column(db.BigInteger, nullable=False, default=0)

    current_streak_days = db.Column(db.Integer, nullable=False, default=0)
    best_streak_days = db.Column(db.Integer, nullable=False, default=0)

    activity_score = db.Column(db.Numeric(5, 2), nullable=False, default=0, index=True)
    activity_score_updated_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    name_history = db.relationship(
        "PlayerNameHistory", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    sessions = db.relationship(
        "PlayerSession", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    daily_stats = db.relationship(
        "PlayerDailyStats", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    timeline_events = db.relationship(
        "PlayerTimelineEvent", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    notes = db.relationship(
        "AdminNote", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    achievements = db.relationship(
        "PlayerAchievement", backref="player", lazy="dynamic",
        cascade="all, delete-orphan",
    )
    game_stats = db.relationship(
        "PlayerGameStats", backref="player", uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def total_playtime_hours(self) -> float:
        return round(self.total_playtime_seconds / 3600, 1)

    def __repr__(self) -> str:
        return f"<Player {self.username} ({self.status})>"


class PlayerNameHistory(db.Model):
    __tablename__ = "player_name_history"

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False, index=True)
    old_name = db.Column(db.String(16), nullable=True)
    new_name = db.Column(db.String(16), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class PlayerGameStats(db.Model):
    __tablename__ = "player_game_stats"

    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), primary_key=True)
    deaths = db.Column(db.Integer, nullable=False, default=0)
    blocks_placed = db.Column(db.BigInteger, nullable=False, default=0)
    blocks_broken = db.Column(db.BigInteger, nullable=False, default=0)
    distance_traveled_cm = db.Column(db.BigInteger, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PlayerSession(db.Model):
    __tablename__ = "player_sessions"

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False, index=True)
    connected_at = db.Column(db.DateTime, nullable=False, index=True)
    disconnected_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    afk_seconds = db.Column(db.Integer, nullable=False, default=0)

    @property
    def is_open(self) -> bool:
        return self.disconnected_at is None


class PlayerDailyStats(db.Model):
    __tablename__ = "player_daily_stats"
    __table_args__ = (db.UniqueConstraint("player_uuid", "stat_date"),)

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False)
    stat_date = db.Column(db.Date, nullable=False, index=True)

    playtime_seconds = db.Column(db.Integer, nullable=False, default=0)
    afk_seconds = db.Column(db.Integer, nullable=False, default=0)
    activity_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    connections_count = db.Column(db.Integer, nullable=False, default=0)
    disconnections_count = db.Column(db.Integer, nullable=False, default=0)


class HourlyActivityStats(db.Model):
    __tablename__ = "hourly_activity_stats"
    __table_args__ = (db.UniqueConstraint("stat_date", "hour_of_day"),)

    id = db.Column(db.BigInteger, primary_key=True)
    stat_date = db.Column(db.Date, nullable=False, index=True)
    hour_of_day = db.Column(db.SmallInteger, nullable=False)
    connections_count = db.Column(db.Integer, nullable=False, default=0)


class PlayerTimelineEvent(db.Model):
    __tablename__ = "player_timeline_events"

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False, index=True)
    event_type = db.Column(
        db.Enum(
            "first_join", "whitelisted", "removed", "returned",
            "banned", "unbanned", "suspended", "unsuspended",
            "archived", "anniversary", "streak_record", "other",
        ),
        nullable=False,
    )
    event_data = db.Column(db.JSON, nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class AdminNote(db.Model):
    __tablename__ = "admin_notes"

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False, index=True)
    author_user_id = db.Column(db.BigInteger, db.ForeignKey("dashboard_users.id"), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Achievement(db.Model):
    __tablename__ = "achievements"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(100), nullable=True)
    criteria_type = db.Column(db.String(50), nullable=True)
    criteria_value = db.Column(db.BigInteger, nullable=True)


class PlayerAchievement(db.Model):
    __tablename__ = "player_achievements"
    __table_args__ = (db.UniqueConstraint("player_uuid", "achievement_id"),)

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey("achievements.id"), nullable=False)
    unlocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    achievement = db.relationship("Achievement")


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.BigInteger, primary_key=True)
    player_uuid = db.Column(db.String(36), db.ForeignKey("players.uuid"), nullable=True, index=True)
    alert_type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    triggered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)

    player = db.relationship("Player")


class DashboardUser(db.Model):
    __tablename__ = "dashboard_users"

    id = db.Column(db.BigInteger, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("admin", "moderator", "readonly"), nullable=False, default="readonly")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    is_active_ = db.Column("is_active", db.Boolean, nullable=False, default=True)

    # --- Flask-Login ---
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return self.is_active_

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)


class GlobalStatsCache(db.Model):
    __tablename__ = "global_stats_cache"

    id = db.Column(db.BigInteger, primary_key=True)
    snapshot_date = db.Column(db.Date, nullable=True, unique=True)

    players_online = db.Column(db.Integer, nullable=False, default=0)
    active_today = db.Column(db.Integer, nullable=False, default=0)
    active_this_week = db.Column(db.Integer, nullable=False, default=0)
    active_this_month = db.Column(db.Integer, nullable=False, default=0)
    hours_played_today = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    hours_played_month = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    avg_daily_hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    avg_weekly_hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    avg_monthly_hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    avg_activity_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    avg_afk_seconds = db.Column(db.Integer, nullable=False, default=0)
    total_registered_players = db.Column(db.Integer, nullable=False, default=0)
    suspended_count = db.Column(db.Integer, nullable=False, default=0)
    archived_count = db.Column(db.Integer, nullable=False, default=0)
    banned_count = db.Column(db.Integer, nullable=False, default=0)
    computed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
