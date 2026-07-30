# Utopia Analytics — Dashboard (Flask)

Lee la base de datos que llena el plugin Endstone y la muestra en un
dashboard oscuro, tipo Grafana/GitHub. No hace nada más pesado que
lo estrictamente necesario para pintar la página: los totales de la
portada vienen de `global_stats_cache`, nunca de un `COUNT`/`SUM` al
vuelo sobre toda la tabla de sesiones.

## Inicialización automática del esquema

No hace falta correr `docker/schema.sql` a mano en producción: el
**plugin de Minecraft** crea las 13 tablas automáticamente la primera
vez que se conecta a MySQL (`CREATE TABLE IF NOT EXISTS`). Si abrís
el dashboard antes de que el plugin haya arrancado al menos una vez,
en vez de un error 500 vas a ver una página explicando que el
proyecto todavía se está inicializando, con un botón para reintentar.
Lo mismo si MySQL directamente no es alcanzable — mensaje distinto,
misma página amigable, sin stack traces.

`docker/schema.sql` sigue estando para dos casos: levantar todo con
Docker Compose (que lo aplica solo, ver más abajo) y como fallback
manual si el usuario de MySQL del plugin no tiene permiso
`CREATE TABLE`.

## Correr todo local con Docker (recomendado para probar de punta a punta)

```bash
docker compose up --build
```

Esto levanta MySQL (con el esquema ya aplicado automáticamente desde
`docker/schema.sql` la primera vez que corre), el dashboard en
`http://localhost:5000`, y un servicio que ejecuta `flask refresh-stats`
cada 5 minutos — el equivalente local del Render Cron Job.

Para crear el primer usuario admin:

```bash
docker compose exec web flask create-admin
```

## Correr en local (sin Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # y editá DATABASE_URL con tus credenciales
export FLASK_APP=wsgi.py
flask run
```

Necesitás el esquema (`docker/schema.sql`, el mismo que aplica
docker-compose automáticamente) ya cargado en tu MySQL antes de
levantar la app.

## Subir a GitHub

```bash
git init
git add .
git commit -m "Utopia Analytics dashboard"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/utopia-analytics-dashboard.git
git push -u origin main
```

`.gitignore` ya excluye `.env`, `__pycache__/` y demás — no subas
credenciales reales.

## Desplegar en Render

Necesitás un MySQL accesible desde internet (Render no ofrece MySQL
gestionado directo — usá PlanetScale, un droplet propio, o cualquier
proveedor que dé una cadena de conexión `mysql://`). Aplicale el
esquema (`docker/schema.sql`) antes del primer deploy.

1. Subí este repo a GitHub (ver sección de arriba).
2. En Render: **New > Blueprint**, apuntá al repo. `render.yaml` ya
   define los dos servicios (`web` con gunicorn y `cron` con
   `flask refresh-stats` cada 5 min) — Render los crea juntos.
3. Cuando pida las env vars marcadas `sync: false`, completá
   `DATABASE_URL` (mismo valor en ambos servicios) con la cadena de
   conexión de tu MySQL. `SECRET_KEY` se autogenera sola.
4. Una vez que el servicio `web` esté arriba, entrá a su **Shell**
   (pestaña en el dashboard de Render) y corré:
   ```bash
   flask --app wsgi create-admin
   ```
   para crear tu primer usuario admin.

## Job de cálculo periódico

`flask refresh-stats` recalcula, para cada jugador: racha actual,
mejor racha histórica y Activity Score (0-100, combina recencia,
volumen de horas, consistencia y racha, con penalización por AFK
alto — no depende solo del tiempo jugado). Al final refresca
`global_stats_cache`, que es lo único que lee la página principal.

Corre por fuera de las requests del dashboard — nunca dentro de una
petición web. En Render, `render.yaml` ya define un servicio `cron`
que lo ejecuta cada 5 minutos (`flask --app wsgi refresh-stats`).
En local:

```bash
flask --app wsgi refresh-stats
```

## Actividad (gráficas + heatmap)

`/activity` muestra un heatmap tipo GitHub (365 días, agregando horas
jugadas de todos los jugadores por día), un gráfico de horas jugadas
con selector 7d/30d/90d, y el horario de conexión (conexiones por
hora del día, últimos 30 días). Los tres se alimentan de endpoints
JSON propios (`/activity/api/heatmap`, `/activity/api/daily`,
`/activity/api/hourly`) que leen `player_daily_stats` /
`hourly_activity_stats` — nunca las sesiones crudas — y están
cacheados con Flask-Caching.

## Rankings y comparador

`/rankings` — 8 categorías (actividad, horas, rachas, veteranos,
nuevos, más activos, más inactivos, AFK), top 50 cada una, todo
ordenando sobre columnas ya indexadas de `players` (sin agregaciones
pesadas).

`/rankings/compare?a=<uuid>&b=<uuid>` — comparador de dos jugadores
con buscador con autocompletar (`/rankings/api/search-players`) y un
radar Chart.js normalizado 0-100 por métrica (para que horas, score,
km y bloques convivan en el mismo gráfico sin que una escala tape a
las demás).

## Alertas y logros

El job (`flask refresh-stats`) ahora también:

- Siembra los logros por defecto (100/500/1000 horas, 100 días
  activos, primer año, primer ingreso) si no existen, y los
  auto-desbloquea por jugador según sus stats — visibles en su perfil.
- Dispara alertas: **inactividad** (30+ días sin conectarse — y pasa
  el estado del jugador a `inactive`), **regreso** (jugó hoy tras
  120+ días de ausencia — y lo reactiva si estaba `inactive`/`archived`),
  y **racha récord** (superó su mejor racha histórica).
- Las alertas tienen un cooldown de 7 días por tipo/jugador para no
  duplicarse en cada corrida del job.

`/alerts` lista las alertas (no leídas / todas) con botón para
marcarlas como leídas.

## Permisos por rol

`app/utils/auth.py` define `roles_required(*roles)`, con jerarquía
`readonly < moderator < admin`. Protegidos hoy:

- Marcar alertas como leídas → `moderator` o `admin`.
- Agregar notas administrativas → `moderator` o `admin`.
- Cambiar el estado de un jugador manualmente → solo `admin`.

`flask create-admin` crea (o resetea la contraseña de) el primer
usuario admin, pidiendo usuario/contraseña por consola:

```bash
flask --app wsgi create-admin
```

## Tests

`tests/test_compute_stats.py` cubre la lógica pura del job (rachas y
Activity Score) sin necesitar MySQL — son funciones aisladas a
propósito para poder testearlas así.

```bash
pip install -r requirements-dev.txt
pytest
```

## Qué falta (próximos pasos naturales)

- Notificaciones de alertas hacia Discord (mencionado como expansión
  futura en el documento original).
- Exportación a CSV/Excel/JSON, sistema de temporadas, panel público
  de solo lectura — todas expansiones ya previstas en la arquitectura
  pero no implementadas todavía.

## Estructura

```
app/
  __init__.py          Application factory + comandos CLI (refresh-stats, create-admin)
  config.py             Config (variables de entorno)
  extensions.py         db, login_manager, cache
  models.py             Modelos SQLAlchemy (reflejan el esquema MySQL)
  utils/auth.py         roles_required() — permisos por rol
  jobs/
    compute_stats.py      Rachas, Activity Score, global_stats_cache
    alerts_and_achievements.py   Logros y alertas
  blueprints/
    main/                Página de inicio
    players/              Listado, perfil, notas, cambio de estado
    activity/              Heatmap, gráficas de horas, horario de conexión
    rankings/              Rankings + comparador
    alerts/                Listado de alertas
    auth/                  Login/logout
  templates/             Jinja2, tema oscuro
  static/css/style.css   Tema oscuro propio (paleta diamante/esmeralda/redstone)
tests/                   Tests de la lógica pura del job
wsgi.py                  Entry point para gunicorn
render.yaml              Config de despliegue en Render (web + cron)
```
