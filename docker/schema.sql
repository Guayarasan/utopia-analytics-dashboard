-- =====================================================================
-- UTOPIA ANALYTICS — Esquema de base de datos MySQL
-- Plugin Endstone (Minecraft Bedrock) + Dashboard Flask
-- =====================================================================
--
-- PRINCIPIOS DE DISEÑO
-- ---------------------------------------------------------------------
-- 1. El plugin SOLO escribe (INSERT/UPDATE simples, sin joins pesados).
--    Todo lo que implique agregación, ranking o cálculo pesado vive
--    en tablas *_stats / *_cache que el dashboard mantiene o refresca
--    (job programado o al vuelo con caché), nunca en tiempo real
--    desde el plugin.
-- 2. Nunca se borra un jugador. Los estados (status) reemplazan el
--    borrado. Todo el historial se conserva indefinidamente salvo
--    borrado manual explícito por un administrador.
-- 3. Las tablas *_daily_stats y hourly_activity_stats son
--    "pre-agregadas": el plugin (o un job) las va rellenando conforme
--    ocurren eventos, así el dashboard nunca tiene que escanear
--    player_sessions completo para pintar un heatmap o un gráfico de
--    horas pico.
-- 4. InnoDB en todas las tablas (transacciones + FKs). utf8mb4 para
--    soportar nombres con caracteres especiales/emoji en notas.
-- 5. Pensado para particionar por fecha en el futuro (player_sessions,
--    player_daily_stats, hourly_activity_stats) sin cambiar el
--    esquema lógico — ver notas al final.
--
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- 1. JUGADORES (núcleo)
-- =====================================================================

CREATE TABLE players (
    uuid                    CHAR(36)        NOT NULL,
    username                VARCHAR(16)     NOT NULL,
    status                  ENUM('active','inactive','dormant','suspended','archived','banned')
                                            NOT NULL DEFAULT 'active',

    first_seen              DATETIME        NOT NULL,
    last_seen               DATETIME        NOT NULL,

    -- Acumulados de bajo costo que el plugin actualiza directamente
    -- en cada desconexión (evita tener que sumar player_sessions
    -- entero cada vez que el dashboard pide "horas totales").
    total_playtime_seconds  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    total_afk_seconds       BIGINT UNSIGNED NOT NULL DEFAULT 0,

    current_streak_days     INT UNSIGNED    NOT NULL DEFAULT 0,
    best_streak_days        INT UNSIGNED    NOT NULL DEFAULT 0,

    -- Recalculado periódicamente por el dashboard (no por el plugin),
    -- ya que el algoritmo de Activity Score es "pesado" a propósito.
    activity_score           DECIMAL(5,2)   NOT NULL DEFAULT 0.00,
    activity_score_updated_at DATETIME      NULL,

    created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (uuid),
    KEY idx_players_status (status),
    KEY idx_players_last_seen (last_seen),
    KEY idx_players_activity_score (activity_score),
    KEY idx_players_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Historial de nombres (Minecraft permite cambiar de nombre)
CREATE TABLE player_name_history (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid     CHAR(36)        NOT NULL,
    old_name        VARCHAR(16)     NULL,
    new_name        VARCHAR(16)     NOT NULL,
    changed_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    KEY idx_pnh_player (player_uuid, changed_at),
    CONSTRAINT fk_pnh_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Estadísticas de juego extensibles (muertes, bloques, distancia...)
-- separadas de `players` para no ensuciar la tabla núcleo y poder
-- añadir columnas nuevas sin tocar lo crítico para el rendimiento.
CREATE TABLE player_game_stats (
    player_uuid             CHAR(36)        NOT NULL,
    deaths                  INT UNSIGNED    NOT NULL DEFAULT 0,
    blocks_placed           BIGINT UNSIGNED NOT NULL DEFAULT 0,
    blocks_broken           BIGINT UNSIGNED NOT NULL DEFAULT 0,
    distance_traveled_cm    BIGINT UNSIGNED NOT NULL DEFAULT 0, -- cm para evitar decimales
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (player_uuid),
    CONSTRAINT fk_pgs_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 2. SESIONES (fuente cruda de conexión/desconexión)
-- =====================================================================
-- El plugin hace UN insert al conectar y UN update al desconectar.
-- Nada más. Todo lo demás (heatmap, horario de actividad, promedios)
-- se deriva de aquí hacia las tablas pre-agregadas de abajo.

CREATE TABLE player_sessions (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid         CHAR(36)        NOT NULL,
    connected_at        DATETIME        NOT NULL,
    disconnected_at     DATETIME        NULL,
    duration_seconds    INT UNSIGNED    NULL,   -- se rellena al desconectar
    afk_seconds         INT UNSIGNED    NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    KEY idx_sessions_player (player_uuid, connected_at),
    KEY idx_sessions_open (player_uuid, disconnected_at), -- para hallar sesión abierta rápido
    CONSTRAINT fk_sessions_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 3. ESTADÍSTICAS DIARIAS PRE-CALCULADAS (heatmap, calendario, gráficos)
-- =====================================================================
-- Una fila por jugador por día. El plugin (o un job ligero que corre
-- tras cada desconexión / cada X minutos) hace UPSERT aquí. El
-- dashboard NUNCA agrega player_sessions en crudo para pintar
-- heatmaps o calendarios: siempre lee esta tabla, que es pequeña
-- comparada con las sesiones crudas.

CREATE TABLE player_daily_stats (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid             CHAR(36)        NOT NULL,
    stat_date               DATE            NOT NULL,

    playtime_seconds        INT UNSIGNED    NOT NULL DEFAULT 0,
    afk_seconds              INT UNSIGNED   NOT NULL DEFAULT 0,
    activity_score           DECIMAL(5,2)   NOT NULL DEFAULT 0.00,
    connections_count        INT UNSIGNED   NOT NULL DEFAULT 0,
    disconnections_count     INT UNSIGNED   NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    UNIQUE KEY uq_pds_player_date (player_uuid, stat_date),
    KEY idx_pds_date (stat_date),
    CONSTRAINT fk_pds_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Distribución de conexiones por hora del día (para el gráfico de
-- "horario de actividad"). Granularidad diaria para poder filtrar
-- por rango de fechas y sumar; el dashboard agrupa por hour_of_day.

CREATE TABLE hourly_activity_stats (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    stat_date           DATE            NOT NULL,
    hour_of_day         TINYINT UNSIGNED NOT NULL, -- 0-23
    connections_count   INT UNSIGNED    NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    UNIQUE KEY uq_has_date_hour (stat_date, hour_of_day),
    KEY idx_has_hour (hour_of_day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 4. TIMELINE / EVENTOS ADMINISTRATIVOS
-- =====================================================================

CREATE TABLE player_timeline_events (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid     CHAR(36)        NOT NULL,
    event_type      ENUM(
                        'first_join', 'whitelisted', 'removed', 'returned',
                        'banned', 'unbanned', 'suspended', 'unsuspended',
                        'archived', 'anniversary', 'streak_record', 'other'
                    )               NOT NULL,
    event_data      JSON            NULL,   -- ej. {"reason": "spam", "by": "admin1"}
    occurred_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    KEY idx_pte_player (player_uuid, occurred_at),
    KEY idx_pte_type (event_type),
    CONSTRAINT fk_pte_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 5. NOTAS ADMINISTRATIVAS (privadas)
-- =====================================================================

CREATE TABLE admin_notes (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid         CHAR(36)        NOT NULL,
    author_user_id      BIGINT UNSIGNED NOT NULL,
    note                TEXT            NOT NULL,
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    KEY idx_notes_player (player_uuid, created_at),
    CONSTRAINT fk_notes_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE,
    CONSTRAINT fk_notes_author FOREIGN KEY (author_user_id)
        REFERENCES dashboard_users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 6. LOGROS
-- =====================================================================

CREATE TABLE achievements (
    id              INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    code            VARCHAR(50)     NOT NULL,   -- '100_hours', 'first_year'...
    name            VARCHAR(100)    NOT NULL,
    description     VARCHAR(255)    NULL,
    icon            VARCHAR(100)    NULL,
    criteria_type   VARCHAR(50)     NULL,       -- 'playtime_hours','days_since_join'...
    criteria_value  BIGINT          NULL,       -- valor numérico del criterio

    PRIMARY KEY (id),
    UNIQUE KEY uq_achievements_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE player_achievements (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid         CHAR(36)        NOT NULL,
    achievement_id      INT UNSIGNED    NOT NULL,
    unlocked_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_pa_player_achievement (player_uuid, achievement_id),
    CONSTRAINT fk_pa_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE,
    CONSTRAINT fk_pa_achievement FOREIGN KEY (achievement_id)
        REFERENCES achievements(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 7. ALERTAS
-- =====================================================================

CREATE TABLE alerts (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    player_uuid     CHAR(36)        NULL,       -- NULL = alerta global
    alert_type      VARCHAR(50)     NOT NULL,   -- 'inactive_30d','returned','new_streak',...
    message         VARCHAR(255)    NOT NULL,
    triggered_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_read         TINYINT(1)      NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    KEY idx_alerts_player (player_uuid, triggered_at),
    KEY idx_alerts_unread (is_read, triggered_at),
    CONSTRAINT fk_alerts_player FOREIGN KEY (player_uuid)
        REFERENCES players(uuid) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 8. AUTENTICACIÓN DEL DASHBOARD
-- =====================================================================

CREATE TABLE dashboard_users (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username        VARCHAR(50)     NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,   -- bcrypt/argon2, nunca texto plano
    role            ENUM('admin','moderator','readonly') NOT NULL DEFAULT 'readonly',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   DATETIME        NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,

    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================
-- 9. CACHÉ DE ESTADÍSTICAS GLOBALES
-- =====================================================================
-- Una sola fila "viva" (o una por snapshot diario si se quiere
-- histórico) que el dashboard refresca con un job periódico en vez
-- de recalcular todo en cada carga de la página principal.

CREATE TABLE global_stats_cache (
    id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_date               DATE            NULL,  -- NULL = snapshot "actual"
    players_online              INT UNSIGNED    NOT NULL DEFAULT 0,
    active_today                INT UNSIGNED    NOT NULL DEFAULT 0,
    active_this_week            INT UNSIGNED    NOT NULL DEFAULT 0,
    active_this_month           INT UNSIGNED    NOT NULL DEFAULT 0,
    hours_played_today          DECIMAL(10,2)   NOT NULL DEFAULT 0,
    hours_played_month          DECIMAL(12,2)   NOT NULL DEFAULT 0,
    avg_daily_hours             DECIMAL(10,2)   NOT NULL DEFAULT 0,
    avg_weekly_hours            DECIMAL(10,2)   NOT NULL DEFAULT 0,
    avg_monthly_hours           DECIMAL(10,2)   NOT NULL DEFAULT 0,
    avg_activity_score          DECIMAL(5,2)    NOT NULL DEFAULT 0,
    avg_afk_seconds             INT UNSIGNED    NOT NULL DEFAULT 0,
    total_registered_players    INT UNSIGNED    NOT NULL DEFAULT 0,
    suspended_count             INT UNSIGNED    NOT NULL DEFAULT 0,
    archived_count              INT UNSIGNED    NOT NULL DEFAULT 0,
    banned_count                INT UNSIGNED    NOT NULL DEFAULT 0,
    computed_at                 DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_gsc_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;

-- =====================================================================
-- NOTAS DE ESCALABILIDAD (no forman parte del esquema lógico, son
-- recomendaciones de operación cuando el proyecto crezca)
-- =====================================================================
--
-- 1. Particionado por rango de fecha (RANGE en columna de fecha) para
--    player_sessions, player_daily_stats y hourly_activity_stats
--    cuando superen varios millones de filas. MySQL soporta
--    particionar por año/mes sin cambiar las consultas de la app.
--
-- 2. player_daily_stats + hourly_activity_stats existen precisamente
--    para que el heatmap tipo GitHub y el gráfico de horas pico NUNCA
--    tengan que hacer GROUP BY sobre player_sessions en crudo.
--
-- 3. global_stats_cache se refresca con un job (APScheduler en Flask
--    o un cron) cada pocos minutos — la página principal siempre lee
--    esta tabla, nunca calcula los totales al vuelo.
--
-- 4. Si el volumen de jugadores concurrentes crece mucho, considerar
--    mover player_sessions a un motor optimizado para escritura
--    (o un buffer en memoria en el propio plugin que hace flush cada
--    N segundos) para no golpear MySQL en cada tick.
--
-- 5. Índices ya cubren los accesos más comunes: por estado, por
--    última conexión, por activity_score (rankings) y por fecha
--    (calendario/heatmap). Revisar con EXPLAIN cuando se implementen
--    las consultas reales del dashboard y añadir índices compuestos
--    si algún filtro combinado (ej. status + last_seen) resulta lento.
-- =====================================================================
