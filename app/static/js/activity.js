(function () {
    const root = getComputedStyle(document.documentElement);
    const colors = {
        border: root.getPropertyValue("--border").trim(),
        diamond: root.getPropertyValue("--accent-diamond").trim(),
        emerald: root.getPropertyValue("--accent-emerald").trim(),
        textSecondary: root.getPropertyValue("--text-secondary").trim(),
        surfaceRaised: root.getPropertyValue("--surface-raised").trim(),
    };

    const chartDefaults = {
        color: colors.textSecondary,
        gridColor: "rgba(255,255,255,0.05)",
    };

    // ------------------------------------------------------------------
    // Heatmap (estilo GitHub) — un cuadro por día, 7 filas (días de la
    // semana), columnas = semanas. La intensidad viene de horas jugadas
    // agregadas de TODOS los jugadores ese día.
    // ------------------------------------------------------------------

    function levelFor(hours, max) {
        if (hours <= 0) return 0;
        const ratio = hours / max;
        if (ratio < 0.25) return 1;
        if (ratio < 0.5) return 2;
        if (ratio < 0.75) return 3;
        return 4;
    }

    // Clave de fecha en hora LOCAL (no UTC). toISOString() convierte a
    // UTC y puede correr la fecha un día para cualquiera que no esté en
    // UTC+0 — justo la zona horaria del servidor no necesariamente
    // coincide con la de quien mira el dashboard.
    function localDateKey(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
    }

    const levelColors = ["var(--surface-raised)", "#0f3d33", "#166a4e", "#1fa868", "#3fcb6e"];

    async function renderHeatmap() {
        const res = await fetch("/activity/api/heatmap?days=365");
        const data = await res.json(); // { "2026-07-01": 12.5, ... }

        const container = document.getElementById("heatmap");
        const today = new Date();
        const days = [];
        for (let i = 364; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            days.push(d);
        }

        const maxHours = Math.max(1, ...Object.values(data));

        // Rellena huecos al inicio para que la primera columna empiece
        // en domingo, como en GitHub.
        const leadingEmpty = days[0].getDay();
        for (let i = 0; i < leadingEmpty; i++) {
            const cell = document.createElement("div");
            cell.className = "ua-heatmap-cell";
            cell.style.background = "transparent";
            container.appendChild(cell);
        }

        days.forEach((d) => {
            const key = localDateKey(d);
            const hours = data[key] || 0;
            const level = levelFor(hours, maxHours);
            const cell = document.createElement("div");
            cell.className = "ua-heatmap-cell";
            cell.style.background = levelColors[level];
            cell.title = `${key} — ${hours}h`;
            container.appendChild(cell);
        });
    }

    // ------------------------------------------------------------------
    // Horas jugadas por día (con tabs 7d / 30d / 90d)
    // ------------------------------------------------------------------

    let dailyChart = null;

    async function renderDailyChart(days) {
        const res = await fetch(`/activity/api/daily?days=${days}`);
        const data = await res.json();

        const ctx = document.getElementById("dailyChart").getContext("2d");
        const config = {
            type: "line",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Horas jugadas",
                        data: data.hours,
                        borderColor: colors.diamond,
                        backgroundColor: "rgba(77, 216, 230, 0.12)",
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: chartDefaults.color, maxRotation: 0 }, grid: { display: false } },
                    y: { ticks: { color: chartDefaults.color }, grid: { color: chartDefaults.gridColor } },
                },
            },
        };

        if (dailyChart) {
            dailyChart.data = config.data;
            dailyChart.update();
        } else {
            dailyChart = new Chart(ctx, config);
        }
    }

    document.querySelectorAll("#daily-range-tabs .ua-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            document.querySelectorAll("#daily-range-tabs .ua-tab").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            renderDailyChart(tab.dataset.days);
        });
    });

    // ------------------------------------------------------------------
    // Horario de actividad (conexiones por hora del día, últimos 30 días)
    // ------------------------------------------------------------------

    async function renderHourlyChart() {
        const res = await fetch("/activity/api/hourly?days=30");
        const data = await res.json(); // array de 24 valores

        const ctx = document.getElementById("hourlyChart").getContext("2d");
        new Chart(ctx, {
            type: "bar",
            data: {
                labels: [...Array(24).keys()].map((h) => String(h).padStart(2, "0")),
                datasets: [
                    {
                        label: "Conexiones",
                        data: data,
                        backgroundColor: colors.emerald,
                        borderRadius: 3,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: chartDefaults.color, maxRotation: 0 }, grid: { display: false } },
                    y: { ticks: { color: chartDefaults.color }, grid: { color: chartDefaults.gridColor } },
                },
            },
        });
    }

    renderHeatmap();
    renderDailyChart(30);
    renderHourlyChart();
})();
