import { useEffect, useRef, useState } from "react";

export function ChapterHead({ n, id, title, children }) {
  return (
    <header className="sc-chapter-head">
      <p className="sc-chapter-n"><span>{n}</span> / 06</p>
      <h2 id={id} tabIndex={-1}>{title}</h2>
      {children && <p className="sc-chapter-lede">{children}</p>}
    </header>
  );
}

// Once-only reveal when a block enters the viewport. Without IntersectionObserver, or with reduced motion,
// everything is shown at once: motion never hides content.
export function useInView(reduced, margin = "0px 0px -15% 0px") {
  const ref = useRef(null);
  const [seen, setSeen] = useState(() => reduced || typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (seen || !ref.current) return undefined;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } }, { rootMargin: margin });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [seen, margin]);
  useEffect(() => { if (reduced) setSeen(true); }, [reduced]);
  return [ref, seen];
}

export const Tag = ({ kind, children }) => <span className={`sc-tag tag-${kind}`}>{children}</span>;
