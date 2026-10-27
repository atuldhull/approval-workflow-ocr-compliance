import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../motion.js";
import ApplicationList from "../components/ApplicationList.jsx";
import CaseDetail from "../components/CaseDetail.jsx";
import NewApplication from "../components/NewApplication.jsx";
import { Empty, ErrorBox, Loading, NotAvailable, useApi } from "../components/ui.jsx";

// List on the left, the open case as an inspector on the right (stacked below on narrow screens).
export default function ApplicationsView({ who, me, focusCase }) {
  const { data: apps, error, loading, reload } = useApi(who, "/applications");
  const [selected, setSelected] = useState(focusCase ?? null);
  const [version, setVersion] = useState(0);
  const detailRef = useRef(null);

  // When the list and the case are stacked (narrow screens), the case opens below the list: bring it into view.
  const pendingScroll = useRef(false);
  // The open case is part of the address, so a refresh or a shared link reopens it.
  const linkCase = (id) => {
    const target = "#applications?case=" + encodeURIComponent(id);
    if (window.location.hash.startsWith("#applications") && window.location.hash !== target) history.pushState(null, "", target);
  };
  const choose = (id) => {
    setSelected(id);
    linkCase(id);
    pendingScroll.current = window.innerWidth <= 1180;
  };
  useEffect(() => { setSelected(focusCase ?? null); }, [focusCase]);
  // Scroll once the case has loaded: before that the page is too short to bring it to the top.
  const caseLoaded = () => {
    if (!pendingScroll.current) return;
    pendingScroll.current = false;
    requestAnimationFrame(() => detailRef.current?.scrollIntoView?.({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" }));
  };

  useEffect(() => {
    const onClock = () => setVersion((v) => v + 1);
    window.addEventListener("awoc:clock-changed", onClock);
    return () => window.removeEventListener("awoc:clock-changed", onClock);
  }, []);

  const changed = (id) => {
    if (id) {
      setSelected(id);
      linkCase(id);
    }
    setVersion((v) => v + 1);
    reload();
  };

  // Regional officers need a region-filtered list from the workflow module; until then the server refuses it.
  const regionalPending = error?.status === 403 && me.role === "RO_OFFICER";

  return (
    <div className="split cases-layout">
      <div className="split-list">
        {me.role === "INSTITUTION" && <NewApplication who={who} institution={me.institution_id} onChanged={changed} />}
        {loading && !apps && <div className="card"><Loading what="Loading applications" /></div>}
        {regionalPending ? (
          <NotAvailable dependsOn="Person 1: region-filtered case list (GET /applications for regional officers)">
            The case list for regional officers is refused by the server until it can be filtered to your region.
            Open the dashboard for your region's figures.
          </NotAvailable>
        ) : (
          <ErrorBox error={error} onRetry={reload} />
        )}
        {apps && <ApplicationList apps={apps} selected={selected} onSelect={choose} />}
      </div>
      <div className="split-detail" ref={detailRef}>
        {selected ? (
          <CaseDetail key={`${selected}-${version}`} who={who} me={me} id={selected} onChanged={changed} onLoaded={caseLoaded} />
        ) : (
          <div className="card placeholder-case">
            <Empty>Select an application to see its route, deadlines and audit timeline.</Empty>
          </div>
        )}
      </div>
    </div>
  );
}
