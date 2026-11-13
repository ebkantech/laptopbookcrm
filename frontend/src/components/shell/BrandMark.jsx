// The Vantage2x mark: an amber tile with the V and a teal dot (index.css .v2x-mark).
export default function BrandMark({ size = 34 }) {
  return (
    <span className="v2x-mark" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 64 64" width={size * 0.62} height={size * 0.62}><path d="M11 14h11l10 25 10-25h11L38 52H26z" fill="currentColor" /></svg>
      <i />
    </span>
  );
}
