/*
 * Custom logic for Ubuntu MATE Community Archive
 * By @lah7
*/

// Display date in the user's locale
document.querySelectorAll(".relative-time").forEach(el => {
    const dateStr = el.textContent.trim();
    const date = new Date(dateStr);
    if (!isNaN(date)) {
        el.setAttribute("title", date.toLocaleString(navigator.language, {
            year: "numeric",
            month: "long",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }));
        el.textContent = date.toLocaleDateString(navigator.language, {
            day: "2-digit",
            month: "short"
        });
    }
});

document.querySelectorAll(".relative-time-year, .post-created").forEach(el => {
    const dateStr = el.textContent.trim();
    const date = new Date(dateStr);
    if (!isNaN(date)) {
        el.setAttribute("title", date.toLocaleString(navigator.language, {
            year: "numeric",
            month: "long",
            day: "2-digit",
        }));
        el.textContent = date.toLocaleDateString(navigator.language, {
            day: "2-digit",
            month: "short",
            year: "numeric"
        });
    }
});

// Add support for sorting table columns
document.querySelectorAll("table.users-list").forEach(table => {
    const headers = table.querySelectorAll("thead th");
    const tbody = table.tBodies[0];
    headers.forEach((th, col) => {
        th.style.cursor = "pointer";
        th.addEventListener("click", () => {
            const asc = th.dataset.order === "desc";
            headers.forEach(h => delete h.dataset.order);
            th.dataset.order = asc ? "asc" : "desc";
            const rows = Array.from(tbody.rows);
            const val = r => r.cells[col].dataset.sort;
            rows.sort((a, b) => {
                const x = val(a), y = val(b);
                const cmp = col === 0 ? x.localeCompare(y) : Number(x) - Number(y);
                return asc ? cmp : -cmp;
            });
            rows.forEach(r => tbody.appendChild(r));
        });
    });
});
