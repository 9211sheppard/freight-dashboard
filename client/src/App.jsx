import { useCallback, useEffect, useState } from "react";
import {
  fetchAlerts,
  fetchPulls,
  fetchCodexLatest,
  fetchActionEvents,
  postAction,
  fetchMe,
  fetchConfig,
  logout,
  toggleKillSwitch,
} from "./api.js";
import Login from "./Login.jsx";
import TestModePanel from "./TestModePanel.jsx";
import "./App.css";

function PanelSkeleton() {
  return (
    <div className="skeleton-block" aria-hidden="true">
      <div className="skeleton-line" />
      <div className="skeleton-line short" />
      <div className="skeleton-line" />
    </div>
  );
}

function useRefreshable(loadFn) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const d = await loadFn();
      setData(d);
    } catch (e) {
      setErr(e.message || String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [loadFn]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, err, loading, refresh };
}

export default function App() {
  const [user, setUser] = useState(undefined);

  useEffect(() => {
    fetchMe()
      .then((d) => setUser(d.user))
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return (
      <div className="app loading-screen">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <Login
        onLoggedIn={() =>
          fetchMe()
            .then((d) => setUser(d.user))
            .catch(() => setUser(null))
        }
      />
    );
  }

  return <Dashboard user={user} onLogout={() => setUser(null)} />;
}

function Dashboard({ user, onLogout }) {
  const alerts = useRefreshable(fetchAlerts);
  const pulls = useRefreshable(fetchPulls);
  const codex = useRefreshable(fetchCodexLatest);
  const events = useRefreshable(fetchActionEvents);

  const [cfg, setCfg] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);
  const [actionOk, setActionOk] = useState(true);
  const [busy, setBusy] = useState(null);
  const [killSwitch, setKillSwitch] = useState(false);
  const [ksLoading, setKsLoading] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then((c) => {
        setCfg(c);
        setKillSwitch(!!c?.guardrails?.killSwitch);
      })
      .catch(() => setCfg(null));
  }, []);

  async function handleKillSwitch(active) {
    setKsLoading(true);
    try {
      const r = await toggleKillSwitch(active);
      setKillSwitch(r.killSwitch);
    } catch (e) {
      setActionMsg(`Kill-switch toggle failed: ${e.message}`);
      setActionOk(false);
    } finally {
      setKsLoading(false);
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } catch {
      /* ignore */
    }
    onLogout();
  }

  async function runAction(name, path, body) {
    setBusy(name);
    setActionMsg(null);
    try {
      const r = await postAction(path, body);
      const detail =
        r.message ||
        r.method ||
        r.workflow ||
        JSON.stringify(r);
      setActionMsg(`${name}: ${detail}`);
      setActionOk(true);
      if (path.includes("codex") || name.includes("Codex")) {
        /* noop */
      }
      if (name.includes("Deploy") || name.includes("Rollback")) {
        codex.refresh();
      }
      events.refresh();
    } catch (e) {
      setActionMsg(`${name} failed: ${e.message}`);
      setActionOk(false);
    } finally {
      setBusy(null);
    }
  }

  const envLabel = cfg?.environment || "development";

  return (
    <div className="app">
      <header className="header">
        <div className="header-row">
          <div>
            <h1>SaaS Ops</h1>
            <p className="subtitle">
              Alerts &middot; Pull Requests &middot; Codex &middot; Deploy
              <span className={`badge ${envLabel === "production" ? "status-failure" : "status-pending"}`} style={{ marginLeft: "0.5rem", fontSize: "0.6875rem" }}>
                {envLabel}
              </span>
            </p>
          </div>
          <div className="header-user">
            <span className="muted small">{user.name}</span>
            <button type="button" onClick={handleLogout}>
              Sign out
            </button>
          </div>
        </div>
        {cfg && <IntegrationStatus integrations={cfg.integrations} />}
        {cfg?.envWarnings?.length > 0 && (
          <div className="banner banner-warn">
            <strong>Config warnings</strong>
            <ul className="warn-list">
              {cfg.envWarnings.map((w) => (
                <li key={w.name}>
                  <code>{w.name}</code> {w.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="toolbar">
          <button type="button" onClick={() => alerts.refresh()} disabled={alerts.loading}>
            Refresh alerts
          </button>
          <button type="button" onClick={() => pulls.refresh()} disabled={pulls.loading}>
            Refresh PRs
          </button>
          <button type="button" onClick={() => codex.refresh()} disabled={codex.loading}>
            Refresh Codex
          </button>
        </div>
      </header>

      {actionMsg && (
        <div
          className={`banner ${actionOk ? "banner-success" : "banner-error"}`}
          role="status"
        >
          {actionMsg}
        </div>
      )}

      <section className="panel">
        <h2>Azure alerts</h2>
        {alerts.loading && <PanelSkeleton />}
        {alerts.err && <p className="error">{alerts.err}</p>}
        {!alerts.loading && alerts.data && !alerts.data.configured && (
          <p className="muted">{alerts.data.message}</p>
        )}
        {alerts.data?.items?.length === 0 && alerts.data?.configured && (
          <p className="muted">No open alerts.</p>
        )}
        {alerts.data?.items?.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name / rule</th>
                  <th>Severity</th>
                  <th>State</th>
                  <th>Fired</th>
                  <th>Resource</th>
                </tr>
              </thead>
              <tbody>
                {alerts.data.items.map((a) => (
                  <tr key={a.id}>
                    <td>{a.name || a.id}</td>
                    <td>{a.severity ?? "—"}</td>
                    <td>{a.state ?? a.monitorCondition ?? "—"}</td>
                    <td className="nowrap">{a.firedTime ?? "—"}</td>
                    <td className="truncate" title={a.targetResource}>
                      {a.targetResource ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>GitHub pull requests</h2>
        {pulls.loading && <PanelSkeleton />}
        {pulls.err && <p className="error">{pulls.err}</p>}
        {!pulls.loading && pulls.data && !pulls.data.configured && (
          <p className="muted">{pulls.data.message}</p>
        )}
        {pulls.data?.items?.length === 0 && pulls.data?.configured && (
          <p className="muted">No open PRs.</p>
        )}
        {pulls.data?.items?.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>PR</th>
                  <th>Title</th>
                  <th>Branch</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {pulls.data.items.map((p) => (
                  <tr key={p.number}>
                    <td>
                      <a
                        href={p.html_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        #{p.number}
                      </a>
                    </td>
                    <td>{p.title}</td>
                    <td className="nowrap">
                      {p.head} → {p.base}
                    </td>
                    <td>
                      <span className={`badge status-${p.checkStatus}`}>
                        {p.checkStatus}
                        {p.checkConclusion
                          ? ` (${p.checkConclusion})`
                          : ""}
                      </span>
                    </td>
                    <td className="nowrap muted">{p.updated_at?.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Codex output</h2>
        {codex.loading && <PanelSkeleton />}
        {codex.err && <p className="error">{codex.err}</p>}
        {!codex.data?.entry && !codex.loading && (
          <p className="muted">
            No Codex payloads yet. POST JSON to <code>/webhooks/codex</code> with{" "}
            <code>Authorization: Bearer &lt;WEBHOOK_SECRET&gt;</code>.
          </p>
        )}
        {codex.data?.entry && <CodexCard entry={codex.data.entry} />}
      </section>

      <GuardrailsPanel
        guardrails={cfg?.guardrails}
        killSwitch={killSwitch}
        ksLoading={ksLoading}
        onToggleKillSwitch={handleKillSwitch}
      />

      <section className="panel actions-panel">
        <h2>Actions</h2>
        <p className="muted small">
          Approve: orchestrator HTTP or script. Deploy / rollback: GitHub{" "}
          <code>workflow_dispatch</code> (see server logs for payload).
        </p>
        {killSwitch && (
          <div className="banner banner-error" style={{ marginBottom: "0.75rem" }}>
            Kill-switch is active — all destructive actions are blocked.
          </div>
        )}
        <div className="action-row">
          <button
            type="button"
            className="primary"
            disabled={!!busy || killSwitch || !codex.data?.entry?.payload?.jobId || !cfg?.integrations?.orchestrator?.ready}
            title={killSwitch ? "Kill-switch active" : !cfg?.integrations?.orchestrator?.ready ? "Orchestrator not configured" : undefined}
            onClick={() =>
              runAction("Approve fix", "/api/actions/approve-fix", {
                jobId: codex.data?.entry?.payload?.jobId,
                notes: "Approved from dashboard",
              })
            }
          >
            Approve fix
          </button>
          <button
            type="button"
            className="primary"
            disabled={!!busy || killSwitch || !cfg?.integrations?.github?.ready}
            title={killSwitch ? "Kill-switch active" : !cfg?.integrations?.github?.ready ? "GitHub not configured" : undefined}
            onClick={() =>
              runAction("Deploy", "/api/actions/deploy-azure", {
                environment: "production",
                imageTag: codex.data?.entry?.payload?.imageTag || "",
              })
            }
          >
            Deploy to Azure
          </button>
          <button
            type="button"
            className="danger"
            disabled={!!busy || killSwitch || !cfg?.integrations?.github?.ready}
            title={killSwitch ? "Kill-switch active" : !cfg?.integrations?.github?.ready ? "GitHub not configured" : undefined}
            onClick={() =>
              runAction("Rollback", "/api/actions/rollback", {
                environment: "production",
                targetImageTag:
                  codex.data?.entry?.payload?.previousImageTag || "",
                reason: "Manual rollback from dashboard",
              })
            }
          >
            Rollback
          </button>
        </div>
      </section>

      <section className="panel">
        <h2>Action history</h2>
        {events.loading && <PanelSkeleton />}
        {events.err && <p className="error">{events.err}</p>}
        {events.data?.items?.length === 0 && !events.loading && (
          <p className="muted">No recent actions.</p>
        )}
        {events.data?.items?.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>User</th>
                  <th>Result</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {events.data.items.map((ev) => (
                  <tr key={ev.id}>
                    <td className="nowrap muted">{ev.createdAt?.slice(0, 16)}</td>
                    <td className="nowrap">{ev.action}</td>
                    <td className="nowrap muted">{ev.userName || "—"}</td>
                    <td>
                      <span className={`badge ${ev.ok ? "status-success" : "status-failure"}`}>
                        {ev.ok ? "ok" : "failed"}
                      </span>
                    </td>
                    <td className="nowrap muted">{ev.httpStatus ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <TestModePanel enabled={cfg?.testMode === true} />
    </div>
  );
}

function GuardrailsPanel({ guardrails, killSwitch, ksLoading, onToggleKillSwitch }) {
  if (!guardrails) return null;
  return (
    <section className="panel guardrails-panel">
      <h2>Guardrails</h2>
      <div className="guardrail-grid">
        <div className={`guardrail-card ${killSwitch ? "guardrail-danger" : "guardrail-ok"}`}>
          <div className="guardrail-card-title">Kill-switch</div>
          <p className="small muted">
            {killSwitch
              ? "All destructive actions are BLOCKED."
              : "Actions are enabled."}
          </p>
          <button
            type="button"
            className={killSwitch ? "primary" : "danger"}
            disabled={ksLoading}
            onClick={() => onToggleKillSwitch(!killSwitch)}
          >
            {ksLoading
              ? "..."
              : killSwitch
                ? "Deactivate kill-switch"
                : "Activate kill-switch"}
          </button>
        </div>

        <div className="guardrail-card">
          <div className="guardrail-card-title">Allowlist</div>
          <p className="small muted">
            <strong>Actions:</strong> {guardrails.allowedActions?.join(", ") || "—"}
          </p>
          <p className="small muted">
            <strong>Environments:</strong> {guardrails.allowedEnvironments?.join(", ") || "—"}
          </p>
        </div>

        <div className="guardrail-card">
          <div className="guardrail-card-title">Rate limit</div>
          <p className="small muted">
            Max <strong>{guardrails.maxRpsPerAction}</strong> req/s per action
            ({guardrails.windowSeconds}s window)
          </p>
        </div>

        <div className="guardrail-card">
          <div className="guardrail-card-title">Deploy block on critical</div>
          <p className="small muted">
            {guardrails.blockDeployOnCritical ? (
              <span className="var-ok">Enabled — deploy blocked when Sev0/Sev1 alerts are open</span>
            ) : (
              <span className="var-missing">Disabled</span>
            )}
          </p>
        </div>
      </div>
    </section>
  );
}

function IntegrationStatus({ integrations }) {
  if (!integrations) return null;
  const { github, orchestrator, azureAlerts } = integrations;

  const allReady = github?.ready && orchestrator?.ready && azureAlerts?.ready;
  if (allReady) {
    return (
      <div className="integration-bar integration-ok">
        All integrations connected
      </div>
    );
  }

  function VarCheck({ name, ok }) {
    return (
      <span className={`var-check ${ok ? "var-ok" : "var-missing"}`}>
        <span className="var-dot">{ok ? "\u2713" : "\u2717"}</span>
        <code>{name}</code>
      </span>
    );
  }

  return (
    <div className="integration-bar integration-warn">
      <strong>Integration setup</strong>
      <div className="integration-cards">
        {github && !github.ready && (
          <div className="int-card">
            <div className="int-card-title">GitHub</div>
            <div className="var-list">
              {Object.entries(github.vars || {}).map(([k, v]) => (
                <VarCheck key={k} name={k} ok={v} />
              ))}
            </div>
            {github.hint && <p className="int-hint">{github.hint}</p>}
          </div>
        )}
        {github?.ready && (
          <div className="int-card int-card-ok">
            <div className="int-card-title">GitHub <span className="var-dot var-ok">{"\u2713"}</span></div>
          </div>
        )}

        {orchestrator && !orchestrator.ready && (
          <div className="int-card">
            <div className="int-card-title">Orchestrator (Approve Fix)</div>
            <div className="var-list">
              {Object.entries(orchestrator.vars || {}).map(([k, v]) => (
                <VarCheck key={k} name={k} ok={v} />
              ))}
            </div>
            {orchestrator.hint && <p className="int-hint">{orchestrator.hint}</p>}
          </div>
        )}
        {orchestrator?.ready && (
          <div className="int-card int-card-ok">
            <div className="int-card-title">
              Orchestrator ({orchestrator.mode}) <span className="var-dot var-ok">{"\u2713"}</span>
            </div>
            {orchestrator.hint && <p className="int-hint">{orchestrator.hint}</p>}
          </div>
        )}

        {azureAlerts && !azureAlerts.ready && (
          <div className="int-card">
            <div className="int-card-title">Azure Alerts</div>
            <div className="var-list">
              {Object.entries(azureAlerts.vars || {}).map(([k, v]) => (
                <VarCheck key={k} name={k} ok={v} />
              ))}
            </div>
            {azureAlerts.hint && <p className="int-hint">{azureAlerts.hint}</p>}
          </div>
        )}
        {azureAlerts?.ready && (
          <div className="int-card int-card-ok">
            <div className="int-card-title">Azure Alerts <span className="var-dot var-ok">{"\u2713"}</span></div>
          </div>
        )}
      </div>
    </div>
  );
}

function CodexCard({ entry }) {
  const p = entry.payload || {};
  const ticketStatus =
    p.ticketStatus ||
    p.ticket_status ||
    p.alertState ||
    p.status ||
    null;
  const summary = p.fixSummary || p.summary || p.message || "(no summary)";
  const files = p.filesChanged || p.files || [];
  const tests = p.tests || p.testResults;

  return (
    <div className="codex-card">
      <div className="codex-meta">
        <span>Received {entry.receivedAt}</span>
        {p.jobId && <span className="muted">Job: {p.jobId}</span>}
      </div>
      {ticketStatus && (
        <>
          <h3>Ticket / workflow status</h3>
          <p className="ticket-status">
            <span className="badge badge-ticket">{String(ticketStatus)}</span>
          </p>
        </>
      )}
      <h3>Fix summary</h3>
      <pre className="block">
        {typeof summary === "string"
          ? summary
          : JSON.stringify(summary, null, 2)}
      </pre>
      <h3>Files changed</h3>
      {Array.isArray(files) && files.length > 0 ? (
        <ul className="file-list">
          {files.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">—</p>
      )}
      <h3>Test results</h3>
      {tests ? (
        <pre className="block small">{JSON.stringify(tests, null, 2)}</pre>
      ) : (
        <p className="muted">—</p>
      )}
      <details className="raw">
        <summary>Raw payload</summary>
        <pre className="block small">{JSON.stringify(p, null, 2)}</pre>
      </details>
    </div>
  );
}
