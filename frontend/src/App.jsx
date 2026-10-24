import { useEffect, useMemo, useRef, useState } from "react";
import { DEMO_USERS, SESSION_EXPIRED, api, publicApi } from "./api.js";
import { clearSession, completeSignIn, hasSession, signIn, signOut } from "./auth/oidc.js";
import { Sidebar, TopBar } from "./components/Layout.jsx";
import { ErrorBox, Loading } from "./components/ui.jsx";
import { navFor } from "./nav.js";
import { WORLDS, useMotionRoot, useReveal, useScrollVar } from "./motion.js";
import OverviewView from "./views/OverviewView.jsx";
import ApplicationsView from "./views/ApplicationsView.jsx";
import AuditView from "./views/AuditView.jsx";
import DashboardView from "./views/DashboardView.jsx";
import DeliveryView from "./views/DeliveryView.jsx";
import InboxView from "./views/InboxView.jsx";
import OcrReviewView from "./views/OcrReviewView.jsx";
import { ComplianceView, EvcView } from "./views/PreviewViews.jsx";
import ScorecardView from "./views/ScorecardView.jsx";

const VIEWS = {
  overview: OverviewView,
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

// What each screen says under its title (DESIGN.md: a noun title, one sentence about the data).
const SUBTITLES = {
  overview: "Where each of your applications stands on its approval route, and what is due next.",
  dashboard: "Applications, ageing and deadlines, rebuilt from the audit event log.",
  applications: "File, submit and follow each case along its route.",
  inbox: "Signals sent to you or to the role you hold.",
  ocr: "Read the document first; the machine reading is revealed only after you commit yours.",
  evc: "Expert visit scheduling.",
  compliance: "Undertakings, affidavits and letter conditions.",
  audit: "Three independent layers of evidence that the record has not been altered.",
  delivery: "Every alert message, its attempts and where it is now.",
  scorecard: "What the system can show about its own correctness, and how each line was measured.",
};

export function Workspace({ who, me, config, identityControl }) {
  const items = useMemo(() => navFor(me.role), [me.role]);
  const [view, setView] = useState(items[0]?.key);        // what the navigation shows as current
  const [shown, setShown] = useState(items[0]?.key);      // what the content area shows
  const [phase, setPhase] = useState("in");
  const [focusCase, setFocusCase] = useState(null);
  const [collapsed, setCollapsed] = useState(() => remembered.get("awoc.sidebar") === "rail");
  const contentRef = useRef(null);
  const timer = useRef(null);
  const reduced = useMotionRoot();
  useScrollVar();
  useReveal(contentRef, shown);

  useEffect(() => {
    if (!items.some((i) => i.key === view)) {
      setView(items[0]?.key);
      setShown(items[0]?.key);
    }
  }, [items, view]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const navigate = (key, opts = {}) => {
    if (opts.caseId) setFocusCase(opts.caseId);
    setView(key);
    if (key === shown) return;
    clearTimeout(timer.current);
    const arrive = () => {
      setShown(key);
      setPhase("in");
      window.scrollTo?.({ top: 0 });
      contentRef.current?.focus({ preventScroll: true });
    };
    if (reduced) return arrive();
    setPhase("out");
    timer.current = setTimeout(arrive, 160);
  };

  const toggleCollapse = () => {
    setCollapsed((c) => {
      remembered.set("awoc.sidebar", c ? "full" : "rail");
      return !c;
    });
  };

  const View = VIEWS[shown];
  const title = items.find((i) => i.key === shown)?.label;
  const navTitle = items.find((i) => i.key === view)?.label;
  const world = WORLDS[shown] ?? { motion: "slide", world: "cases" };

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`} data-world={world.world}>
      <a className="skip-link" href="#content">Skip to content</a>
      <Backplate world={world.world} />
      <Sidebar items={items} current={view} onNavigate={navigate} collapsed={collapsed}
        onToggleCollapse={toggleCollapse} title={navTitle} />
      <div className="main">
        <TopBar me={me} who={who} config={config} identityControl={identityControl} title={navTitle} view={view} />
        <main className={`content world-${world.motion} phase-${phase}`} id="content" tabIndex={-1} ref={contentRef}>
          <header className="page-head" key={`head-${shown}`}>
            <h1>{title}</h1>
            {SUBTITLES[shown] && <p className="page-sub">{SUBTITLES[shown]}</p>}
          </header>
          {View && (
            <View key={`${shown}-${me.user_id}`} who={who} me={me} onNavigate={navigate}
              focusCase={shown === "applications" ? focusCase : undefined} />
          )}
        </main>
      </div>
    </div>
  );
}

// The atmosphere behind each world: a faint field, one soft light in the world's hue, and a motif drawn
// from the world's subject. aria-hidden, behind everything, scroll-parallaxed (MOTION.md).
function Backplate({ world }) {
  return (
    <div className="backplate" data-world={world} aria-hidden="true">
      <div className="bp-field" />
      <div className="bp-light" />
      <svg className="bp-motif" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
        <path d="M-40 640 C 220 640, 260 260, 520 260 S 820 560, 1240 300" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <path d="M-40 700 C 260 700, 320 380, 600 380 S 900 640, 1240 420" fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.6" />
        <circle cx="520" cy="260" r="5" fill="currentColor" />
        <circle cx="600" cy="380" r="3.5" fill="currentColor" opacity="0.7" />
        <circle cx="1040" cy="372" r="4" fill="currentColor" opacity="0.8" />
      </svg>
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
