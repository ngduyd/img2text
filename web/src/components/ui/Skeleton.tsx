/**
 * Skeleton loader (DESIGN.md §4): shimmer matching layout dimensions via
 * className. One sanctioned motion loop in tool UI (index.css @keyframes skeleton).
 * Default testid "skeleton" — Task 2 Jobs loading state consumes it.
 */
export default function Skeleton({
  testid = "skeleton",
  className = "h-4 w-full",
}: {
  testid?: string;
  className?: string;
}) {
  return <div data-testid={testid} aria-hidden="true" className={`skeleton ${className}`} />;
}
