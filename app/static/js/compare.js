(function () {
    function setupAutocomplete(inputId, boxId, paramName) {
        const input = document.getElementById(inputId);
        const box = document.getElementById(boxId);
        if (!input) return;

        let debounceTimer = null;

        input.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                box.style.display = "none";
                return;
            }
            debounceTimer = setTimeout(async () => {
                const res = await fetch(`/rankings/api/search-players?q=${encodeURIComponent(q)}`);
                const players = await res.json();
                box.innerHTML = "";
                if (players.length === 0) {
                    box.style.display = "none";
                    return;
                }
                players.forEach((p) => {
                    const item = document.createElement("div");
                    item.className = "ua-autocomplete-item";
                    item.textContent = p.username;
                    item.addEventListener("click", () => {
                        const url = new URL(window.location.href);
                        url.searchParams.set(paramName, p.uuid);
                        window.location.href = url.toString();
                    });
                    box.appendChild(item);
                });
                box.style.display = "block";
            }, 250);
        });

        document.addEventListener("click", (e) => {
            if (!box.contains(e.target) && e.target !== input) {
                box.style.display = "none";
            }
        });
    }

    setupAutocomplete("search-a", "autocomplete-a", "a");
    setupAutocomplete("search-b", "autocomplete-b", "b");

    if (window.UA_COMPARE_DATA) {
        const root = getComputedStyle(document.documentElement);
        const diamond = root.getPropertyValue("--accent-diamond").trim();
        const gold = root.getPropertyValue("--accent-gold").trim();

        const { labels, a, b, name_a, name_b } = window.UA_COMPARE_DATA;

        // Normaliza cada métrica 0-100 relativo al máximo entre ambos
        // jugadores, para que el radar sea legible aunque las escalas
        // originales sean muy distintas (horas vs. km vs. score).
        const normalized = (values) =>
            values.map((v, i) => {
                const max = Math.max(a[i], b[i], 1);
                return Math.round((v / max) * 100);
            });

        const ctx = document.getElementById("compareChart").getContext("2d");
        new Chart(ctx, {
            type: "radar",
            data: {
                labels,
                datasets: [
                    {
                        label: name_a,
                        data: normalized(a),
                        borderColor: diamond,
                        backgroundColor: "rgba(77, 216, 230, 0.15)",
                        pointBackgroundColor: diamond,
                    },
                    {
                        label: name_b,
                        data: normalized(b),
                        borderColor: gold,
                        backgroundColor: "rgba(230, 184, 63, 0.15)",
                        pointBackgroundColor: gold,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        angleLines: { color: "rgba(255,255,255,0.08)" },
                        grid: { color: "rgba(255,255,255,0.08)" },
                        pointLabels: { color: root.getPropertyValue("--text-secondary").trim(), font: { size: 11 } },
                        ticks: { display: false },
                        suggestedMin: 0,
                        suggestedMax: 100,
                    },
                },
                plugins: {
                    legend: { labels: { color: root.getPropertyValue("--text-secondary").trim() } },
                },
            },
        });
    }
})();
