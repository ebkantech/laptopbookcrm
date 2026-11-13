import { C, F } from "../lib/theme";

/**
 * Shared page header -- the page title and subtitle on the left, the
 * page's own buttons (e.g. "New rental agreement", "Export Excel") on the
 * right. Notifications, the user menu and settings live in the app header
 * (components/shell/AppHeader.jsx), so they're the same on every page.
 */
export default function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="v2x-pagehead flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0 flex-1 basis-64">
        <h1 className="text-[24px] leading-[1.1] sm:text-[30px]" style={{ fontFamily: F.editorial, fontWeight: 600, color: C.ink, letterSpacing: "-0.015em" }}>{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm" style={{ fontFamily: F.body, color: C.inkSoft }}>{subtitle}</p>}
      </div>
      {actions && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
