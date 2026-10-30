// Pure helpers behind the rent invoice ledger (RentLedger.jsx): what to say about
// each row, and the per-client history + totals. No React, so it is unit-tested
// in ledgerModel.test.js. `fmt` is passed in so tests don't need the app theme.

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/**
 * What a ledger row says about its payment.
 * tone: "paid" | "late" | "due" | "overdue" | "scheduled" | "muted"
 */
export function describeRow(row, fmt, today = new Date().toISOString().slice(0, 10)) {
  if (row.kind === "scheduled") {
    const detail = !row.send_on
      ? "Auto-send is off — raise this invoice yourself"
      : row.send_on < today
        ? "Goes to the client with the next daily run"
        : `Invoice goes to the client on ${fmt(row.send_on)}`;
    return { label: "Scheduled", tone: "scheduled", detail, due: `Due ${fmt(row.due_date)}` };
  }
  if (row.status === "Paid") {
    const late = row.days_late || 0;
    return {
      label: `Paid ${fmt(row.paid_on)}`,
      tone: late ? "late" : "paid",
      detail: late ? `${plural(late, "day")} after the due date` : "on time",
      due: `Due ${fmt(row.due_date)}`,
    };
  }
  if (row.status === "Cancelled" || row.status === "Refunded") {
    return { label: row.status, tone: "muted", detail: "", due: `Due ${fmt(row.due_date)}` };
  }
  // sent, not paid yet
  if (row.status === "Overdue" || (row.days_overdue || 0) > 0) {
    return { label: "Overdue", tone: "overdue", detail: `${plural(row.days_overdue || 0, "day")} past the due date`, due: `Due ${fmt(row.due_date)}` };
  }
  const left = row.due_in_days || 0;
  return {
    label: left === 0 ? "Due today" : `Due in ${plural(left, "day")}`,
    tone: "due",
    detail: "Invoice sent — awaiting payment",
    due: `Due ${fmt(row.due_date)}`,
  };
}

/** Group ledger rows by client with each client's totals. Clients with money overdue come first. */
export function groupByClient(rows) {
  const clients = new Map();
  for (const row of rows) {
    let c = clients.get(row.party);
    if (!c) {
      c = { party: row.party, name: row.client_name, phone: row.phone, agreements: new Set(), rows: [],
        totals: { invoiced: 0, paid: 0, outstanding: 0, overdueAmount: 0, overdueCount: 0, latePayments: 0, invoices: 0, scheduled: 0 } };
      clients.set(row.party, c);
    }
    c.rows.push(row);
    if (row.agreement_code) c.agreements.add(row.agreement_code);
    const t = c.totals;
    if (row.kind === "scheduled") { t.scheduled += 1; continue; }
    if (row.status === "Cancelled") continue;
    t.invoices += 1;
    if (row.status === "Refunded") continue;
    t.invoiced += row.total;
    if (row.status === "Paid") {
      t.paid += row.total;
      if ((row.days_late || 0) > 0) t.latePayments += 1;
    } else {
      t.outstanding += row.total;
      if (row.status === "Overdue" || (row.days_overdue || 0) > 0) { t.overdueAmount += row.total; t.overdueCount += 1; }
    }
  }
  const byPeriod = (a, b) => String(b.period_start || "").localeCompare(String(a.period_start || ""));
  const list = [...clients.values()].map((c) => ({
    ...c,
    agreements: [...c.agreements].sort(),
    // upcoming first, then the history newest period first
    rows: [...c.rows.filter((r) => r.kind === "scheduled").sort(byPeriod).reverse(), ...c.rows.filter((r) => r.kind !== "scheduled").sort(byPeriod)],
  }));
  return list.sort((a, b) => b.totals.overdueAmount - a.totals.overdueAmount || a.name.localeCompare(b.name));
}

/** Totals across every client shown. */
export function grandTotals(groups) {
  return groups.reduce((sum, g) => ({
    invoiced: sum.invoiced + g.totals.invoiced, paid: sum.paid + g.totals.paid, outstanding: sum.outstanding + g.totals.outstanding,
    overdueAmount: sum.overdueAmount + g.totals.overdueAmount, overdueCount: sum.overdueCount + g.totals.overdueCount, invoices: sum.invoices + g.totals.invoices,
  }), { invoiced: 0, paid: 0, outstanding: 0, overdueAmount: 0, overdueCount: 0, invoices: 0 });
}
