// Pure helpers for the staff performance view (no app imports, so node --test can load it).

export function formatHours(hours) {
  if (hours === null || hours === undefined || Number.isNaN(Number(hours))) return "—";
  const h = Number(hours);
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h % 1 === 0 ? h : h.toFixed(1)} h`;
  const days = Math.floor(h / 24);
  const rest = Math.round(h - days * 24);
  return rest ? `${days}d ${rest}h` : `${days}d`;
}

export function delayLabel(job) {
  if (!job.delayed) return job.ready_at ? "On time" : "On track";
  return `${formatHours(job.delay_hours)} late`;
}

export function onTimeRate(period) {
  if (!period || !period.done) return null;
  return Math.round((period.on_time / period.done) * 100);
}

// Staff needing attention first: most overdue open jobs, then most delayed finished jobs.
export function attentionOrder(staff) {
  return [...staff].sort((a, b) => (b.overdue - a.overdue) || (b.period.delayed - a.period.delayed) || a.name.localeCompare(b.name));
}

export function hasProblems(row) {
  return row.overdue > 0 || row.period.delayed > 0;
}

export function revisionDiff(previous, proposed) {
  const diff = Number(proposed) - Number(previous);
  return { diff, direction: diff > 0 ? "up" : diff < 0 ? "down" : "same" };
}
