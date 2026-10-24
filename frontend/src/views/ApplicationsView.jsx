import { useEffect, useState } from "react";
import ApplicationList from "../components/ApplicationList.jsx";
import CaseDetail from "../components/CaseDetail.jsx";
import NewApplication from "../components/NewApplication.jsx";
import { ErrorBox, Loading, NotAvailable, useApi } from "../components/ui.jsx";

export default function ApplicationsView({ who, me }) {
  const { data: apps, error, loading, reload } = useApi(who, "/applications");
  const [selected, setSelected] = useState(null);
  const [version, setVersion] = useState(0);

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
    <div className="grid two">
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
        {apps && <ApplicationList apps={apps} selected={selected} onSelect={setSelected} />}
      </div>
      <div>
        {selected ? (
          <CaseDetail key={`${selected}-${version}`} who={who} me={me} id={selected} onChanged={changed} />
        ) : (
          <p className="muted">Select an application to see its route, deadlines and audit timeline.</p>
        )}
      </div>
    </div>
  );
}
