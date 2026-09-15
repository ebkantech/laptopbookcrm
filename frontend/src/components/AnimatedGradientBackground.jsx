/**
 * Pure CSS + React animated background: three soft, blurred color
 * blobs drifting slowly behind the app content. Kept light and
 * low-opacity so it reads as ambient motion, not a distraction, and
 * respects prefers-reduced-motion by freezing in place.
 *
 * Usage: render once, at the top of the app shell, as a fixed-position
 * layer behind everything else (z-index handled internally).
 */
export default function AnimatedGradientBackground() {
  return (
    <div aria-hidden="true" className="cb-gradient-bg">
      <span className="cb-blob cb-blob-1" />
      <span className="cb-blob cb-blob-2" />
      <span className="cb-blob cb-blob-3" />
    </div>
  );
}
