import { useEffect, useMemo, useState } from "react";
import { DEMO_USERS, SESSION_EXPIRED, api, publicApi } from "./api.js";
import { clearSession, completeSignIn, hasSession, signIn, signOut } from "./auth/oidc.js";
import { Sidebar, TopBar } from "./components/Layout.jsx";
import { ErrorBox, Loading } from "./components/ui.jsx";
import { navFor } from "./nav.js";
import ApplicationsView from "./views/ApplicationsView.jsx";
import AuditView from "./views/AuditView.jsx";
import DashboardView from "./views/DashboardView.jsx";
import DeliveryView from "./views/DeliveryView.jsx";
import InboxView from "./views/InboxView.jsx";
import OcrReviewView from "./views/OcrReviewView.jsx";
import { ComplianceView, EvcView } from "./views/PreviewViews.jsx";
import ScorecardView from "./views/ScorecardView.jsx";

const VIEWS = {
  dashboard: DashboardView,
  applications: ApplicationsView,
  inbox: InboxView,
  ocr: OcrReviewView,
  evc: EvcView,
  compliance: ComplianceView,
  audit: AuditView,
  delivery: DeliveryView,
  scorecard: ScorecardView,
};

const remembered = {
  get: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* convenience only */
    }
  },
};

export function Workspace({ who, me, config, identityControl }) {
  const items = useMemo(() => navFor(me.role), [me.role]);
  const [view, setView] = useState(items[0]?.key);
  useEffect(() => {
    if (!items.some((i) => i.key === view)) setView(items[0]?.key);
  }, [items, view]);
  const View = VIEWS[view];
  const title = items.find((i) => i.key === view)?.label;

  return (
    <div className="shell">
      <a className="skip-link" href="#content">Skip to content</a>
      <Sidebar items={items} current={view} onNavigate={setView} />
      <div className="main">
        <TopBar me={me} who={who} config={config} identityControl={identityControl} />
        <main className="content" id="content" tabIndex={-1}>
          <h1>{title}</h1>
          {View && <View key={`${view}-${me.user_id}`} who={who} me={me} />}
        </main>
      </div>
    </div>
  );
}

function DemoApp({ config }) {
  const [key, setKey] = useState(() => remembered.get("awoc.demo-user") || DEMO_USERS[0].key);
  const who = DEMO_USERS.find((u) => u.key === key) ?? DEMO_USERS[0];
  const [me, setMe] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setMe(null);
    api(who, "/auth/me").then(setMe).catch(setError);
  }, [who]);

  const switcher = (
    <label className="inline">
      Acting as
      <select
        value={key}
        onChange={(e) => {
          setKey(e.target.value);
          remembered.set("awoc.demo-user", e.target.value);
        }}
      >
        {DEMO_USERS.map((u) => (
          <option key={u.key} value={u.key}>
            {u.label}
          </option>
        ))}
      </select>
    </label>
  );
  if (error) return <ErrorBox error={error} />;
  if (!me) return <Loading what="Signing in" />;
  return <Workspace who={who} me={me} config={config} identityControl={switcher} />;
}

export function SignIn({ config, message }) {
  return (
    <div className="sign-in">
      <div className="card">
        <h1>Approval Workflow</h1>
        <p className="muted">Compliance monitoring and alerts</p>
        {message && <div className="alert error" role="alert">{message}</div>}
        <button onClick={() => signIn(config)}>Sign in</button>
        <p className="muted small">You will be sent to the identity provider and returned here.</p>
      </div>
    </div>
  );
}

function OidcApp({ config }) {
  const who = useMemo(() => ({ mode: "oidc", config }), [config]);
  const [state, setState] = useState({ phase: "loading" });

  useEffect(() => {
    (async () => {
      try {
        await completeSignIn(config);
        if (!hasSession()) return setState({ phase: "signed-out" });
        setState({ phase: "ready", me: await api(who, "/auth/me") });
      } catch (e) {
        if (e.status === 401) clearSession();
        setState({ phase: "signed-out", message: e.message });
      }
    })();
  }, [config, who]);

  useEffect(() => {
    const expired = () => setState({ phase: "signed-out", message: "Your session has ended. Please sign in again." });
    window.addEventListener(SESSION_EXPIRED, expired);
    return () => window.removeEventListener(SESSION_EXPIRED, expired);
  }, []);

  if (state.phase === "loading") return <Loading what="Signing in" />;
  if (state.phase === "signed-out") return <SignIn config={config} message={state.message} />;
  const logout = (
    <button className="secondary small" onClick={() => signOut(config)}>
      Sign out
    </button>
  );
  return <Workspace who={who} me={state.me} config={config} identityControl={logout} />;
}

export default function App() {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    publicApi("/auth/config").then(setConfig).catch(setError);
  }, []);
  if (error) return <ErrorBox error={new Error("The server cannot be reached. Try again shortly.")} />;
  if (!config) return <Loading />;
  return config.mode === "oidc" ? <OidcApp config={config} /> : <DemoApp config={config} />;
}
