// Quick date ranges for the expense list (Expenses.jsx). Dates are YYYY-MM-DD.

export const PERIODS = [
  { id: "month", label: "This month" },
  { id: "last-month", label: "Last month" },
  { id: "year", label: "This year" },
  { id: "all", label: "All time" },
  { id: "custom", label: "Custom" },
];

const iso = (y, m, d) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
const lastDay = (y, m) => new Date(y, m, 0).getDate(); // m is 1-12

/** {date_from, date_to} for a quick period; custom / all leave both empty. `today` is YYYY-MM-DD. */
export function periodRange(id, today) {
  const [y, m] = today.split("-").map(Number);
  if (id === "month") return { date_from: iso(y, m, 1), date_to: today };
  if (id === "last-month") {
    const py = m === 1 ? y - 1 : y;
    const pm = m === 1 ? 12 : m - 1;
    return { date_from: iso(py, pm, 1), date_to: iso(py, pm, lastDay(py, pm)) };
  }
  if (id === "year") return { date_from: iso(y, 1, 1), date_to: today };
  return { date_from: "", date_to: "" };
}
