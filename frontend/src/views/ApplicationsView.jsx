import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../motion.js";
import ApplicationList from "../components/ApplicationList.jsx";
import CaseDetail from "../components/CaseDetail.jsx";
import NewApplication from "../components/NewApplication.jsx";
import { Empty, ErrorBox, Loading, NotAvailable, useApi } from "../components/ui.jsx";

export default function ApplicationsView({ who, me, focusCase }) {
  const { data: apps, error, loading, reload } = useApi(who, "/applications");
  const [selected, setSelected] = useState(focusCase ?? null);
  const [version, setVersion] = useState(0);
  const detailRef = useRef(null);

  // When the list and the case are stacked (narrow screens), the case opens below the list: bring it into view.
  const pendingScroll = useRef(false);
  const choose = (id) => {
    setSelected(id);
    pendingScroll.current = window.innerWidth <= 1100;
  };
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
    if (id) setSelected(id);
    setVersion((v) => v + 1);
    reload();
  };

  // Regional officers need a region-filtered list from the workflow module; until then the server refuses it.
  const regionalPending = error?.status === 403 && me.role === "RO_OFFICER";

  return (
    <div className="grid two cases-layout">
      <div>
        {me.role === "INSTITUTION" && <NewApplication who={who} institution={me.institution_id} onChanged={changed} />}
        {loading && !apps && <Loading what="Loading applications" />}
        {regionalPending ? (
          <NotAvailable dependsOn="Person 1: region-filtered case list (GET /applications for regional officers)">
            The case list for regional officers is refused by the server until it can be filtered to your region.
            Open the dashboard for your region's figures.
          </NotAvailable>
        ) : (
          <ErrorBox error={error} />
        )}
        {apps && <ApplicationList apps={apps} selected={selected} onSelect={choose} />}
      </div>
      <div ref={detailRef}>
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
