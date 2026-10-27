import { useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../motion.js";
import ApplicationList from "../components/ApplicationList.jsx";
import CaseDetail from "../components/CaseDetail.jsx";
import NewApplication from "../components/NewApplication.jsx";
import { Empty, ErrorBox, Loading, useApi } from "../components/ui.jsx";

// A regional officer's list comes from the region-scoped case list (GET /cases?region=), which states the
// officer's own region as the server requires; /applications is not region-filtered and refuses them.
const caseRow = (c) => ({
  id: c.case_id, category: c.route_id, status: c.status, current_stage: c.stage, academic_year: "",
  // entering the first stage is the submission; a draft has no stage history and no filing date
  created_at: c.stage_history?.[0]?.entered_at ?? "", submitted_at: c.stage_history?.[0]?.entered_at ?? null,
});
function useCaseList(who, me) {
  const regional = me.role === "RO_OFFICER";
  const apps = useApi(who, regional ? null : "/applications");
  const cases = useApi(who, regional ? `/cases?region=${encodeURIComponent(me.region ?? "")}&limit=100` : null);
  if (!regional) return apps;
  return { ...cases, data: cases.data ? cases.data.items.map(caseRow) : null };
}

// List on the left, the open case as an inspector on the right (stacked below on narrow screens).
export default function ApplicationsView({ who, me, focusCase, onNavigate }) {
  const { data: apps, error, loading, reload } = useCaseList(who, me);
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

  return (
    <div className="split cases-layout">
      <div className="split-list">
        {me.role === "INSTITUTION" && <NewApplication who={who} institution={me.institution_id} onChanged={changed} />}
        {loading && !apps && <div className="card"><Loading what="Loading applications" /></div>}
        <ErrorBox error={error} onRetry={reload} />
        {apps && <ApplicationList apps={apps} selected={selected} onSelect={choose} />}
      </div>
      <div className="split-detail" ref={detailRef}>
        {selected ? (
          <CaseDetail key={`${selected}-${version}`} who={who} me={me} id={selected} onChanged={() => reload()} onLoaded={caseLoaded}
            onNavigate={onNavigate} />
        ) : (
          <div className="card placeholder-case">
            <Empty>Select an application to see its route, deadlines and audit timeline.</Empty>
          </div>
        )}
      </div>
    </div>
  );
}
