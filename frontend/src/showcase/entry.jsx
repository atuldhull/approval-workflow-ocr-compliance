import { Suspense, lazy, useEffect, useState } from "react";
import "./link.css";

// The showcase lives at #showcase (and #showcase/<chapter>, #showcase/tour/<step>). The workspace keeps every
// other fragment, so its deep links (#inbox, #applications?case=…) and history are unchanged. This file is the
// only showcase code in the main bundle; the experience itself is a lazy chunk and needs no backend.

const Showcase = lazy(() => import("./Showcase.jsx"));

export const SHOWCASE_HASH = "#showcase";

export function isShowcaseHash(hash = typeof window === "undefined" ? "" : window.location.hash) {
  return hash === SHOWCASE_HASH || hash.startsWith(`${SHOWCASE_HASH}/`) || hash.startsWith(`${SHOWCASE_HASH}?`);
}

// Leave the showcase for the workspace. An empty fragment lets the workspace pick the role's default screen.
export function enterWorkspace(fragment = "") {
  history.pushState(null, "", `${window.location.pathname}${window.location.search}${fragment ? `#${fragment}` : ""}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function ShowcaseLink({ className = "showcase-link" }) {
  return (
    <a className={className} href={SHOWCASE_HASH}>
      How it works <span aria-hidden="true">↗</span>
    </a>
  );
}

export function ShowcaseGate({ children }) {
  const [showing, setShowing] = useState(() => isShowcaseHash());
  useEffect(() => {
    const sync = () => setShowing(isShowcaseHash());
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);
  const [left, setLeft] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle("in-showcase", showing);
    if (showing) setLeft(true);
    else if (left) {
      // Back in the workspace: put focus where the workspace's own navigation would.
      // The workspace mounts after its config request, so wait briefly for its content region.
      let tries = 0;
      const t = setInterval(() => {
        const content = document.getElementById("content");
        if (content) content.focus({ preventScroll: true });
        if (content || ++tries > 30) clearInterval(t);
      }, 100);
      return () => clearInterval(t);
    }
    return undefined;
  }, [showing, left]);
  if (!showing) return children;
  return (
    <Suspense fallback={<div className="showcase-loading" role="status">Opening the showcase…</div>}>
      <Showcase />
    </Suspense>
  );
}
