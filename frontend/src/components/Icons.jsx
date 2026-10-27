// Line icons, 16px, 1.5px stroke, currentColor. Decorative unless given a title.
const P = {
  overview: "M3 13.5V8l5-4.5L13 8v5.5H9.5v-3h-3v3H3z",
  dashboard: "M2.5 13.5h11M4 11V7m4 4V4m4 7V8.5",
  applications: "M3 3.5h10M3 8h10M3 12.5h6",
  inbox: "M2.5 9.5 4 3.5h8l1.5 6M2.5 9.5V13h11V9.5H10a2 2 0 0 1-4 0H2.5z",
  ocr: "M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12M6 8h4M6 10.5h3",
  documents: "M5.5 4.5V2.5h5L13 5v7h-2M3 4.5h5.5L11 7v6.5H3zM8.5 4.5V7H11",
  alerts: "M4 11V7.5a4 4 0 0 1 8 0V11l1.2 1.5H2.8zM6.8 14h2.4",
  evc: "M3 4h10v9.5H3zM3 7h10M6 2.5V5m4-2.5V5M6 10h2",
  compliance: "M8 2.5 13 4.5v3.5c0 3-2.2 5-5 5.5-2.8-.5-5-2.5-5-5.5V4.5zM5.8 8l1.6 1.6L10.5 6.5",
  audit: "M6.5 9.5 9.5 6.5M7 4.5l1.3-1.3a2.5 2.5 0 0 1 3.5 3.5L10.5 8M9 11.5l-1.3 1.3a2.5 2.5 0 0 1-3.5-3.5L5.5 8",
  delivery: "M2.5 8 13.5 3l-3 10.5-2.5-4.5zM8 9l5.5-6",
  scorecard: "M3 13a5 5 0 0 1 10 0M8 13l2.5-4M8 3.5V5M3.5 8.5l1.2.6M12.5 8.5l-1.2.6",
  collapse: "M10 4 6 8l4 4",
  expand: "M6 4l4 4-4 4",
  menu: "M2.5 4.5h11M2.5 8h11M2.5 11.5h11",
  close: "M4 4l8 8M12 4l-8 8",
  lock: "M4.5 7.5h7v6h-7zM6 7.5V5.5a2 2 0 0 1 4 0v2",
  refresh: "M13 8a5 5 0 1 1-1.5-3.5M13 3v2.5h-2.5",
  copy: "M5.5 5.5h7v7h-7zM3.5 10.5v-7h7",
  download: "M8 2.5v7.5M5 7l3 3 3-3M3 13h10",
  turnLeft: "M5 6 3 8l2 2M3 8h7a3 3 0 0 1 3 3",
  turnRight: "M11 6l2 2-2 2M13 8H6a3 3 0 0 0-3 3",
  pause: "M5.5 3.5v9M10.5 3.5v9",
  play: "M5 3.5v9l7.5-4.5z",
  zoom: "M7 11.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM10.3 10.3 13.5 13.5M7 5v4M5 7h4",
};

export function Icon({ name, title, size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round" role={title ? "img" : undefined}
      aria-hidden={title ? undefined : "true"} aria-label={title} focusable="false">
      <path d={P[name] ?? P.dashboard} />
    </svg>
  );
}

// The product mark: three stages of an approval route, the last one reached.
export function Mark({ size = 30 }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="9" fill="var(--raised)" />
      <path d="M8 22 C 12 22, 12 10, 16 10 S 20 22, 24 22" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="8" cy="22" r="2.6" fill="var(--muted)" />
      <circle cx="16" cy="10" r="2.6" fill="var(--muted)" />
      <circle cx="24" cy="22" r="3.4" fill="var(--accent)" />
    </svg>
  );
}

// The route glyph used by empty states.
export function RouteGlyph() {
  return (
    <svg className="route-glyph" width="120" height="44" viewBox="0 0 120 44" aria-hidden="true" focusable="false">
      <path d="M8 34 C 30 34, 30 10, 60 10 S 90 34, 112 34" fill="none" stroke="var(--control)" strokeWidth="1.5" strokeDasharray="3 5" />
      <circle cx="8" cy="34" r="4" fill="var(--raised)" stroke="var(--control)" />
      <circle cx="60" cy="10" r="4" fill="var(--raised)" stroke="var(--control)" />
      <circle cx="112" cy="34" r="4" fill="var(--raised)" stroke="var(--control)" />
    </svg>
  );
}
