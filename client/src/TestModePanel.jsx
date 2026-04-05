import { useState } from "react";
import { postTest } from "./api.js";

export default function TestModePanel({ enabled }) {
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!enabled) return null;

  async function run(path, label) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await postTest(path, {});
      setMsg({ ok: true, text: `${label}: ${JSON.stringify(r)}` });
    } catch (e) {
      setMsg({ ok: false, text: `${label} failed: ${e.message}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel test-mode-panel">
      <h2>Test mode</h2>
      <p className="muted small">
        Safe simulations (no real GitHub / orchestrator). Requires{" "}
        <code>TEST_MODE=true</code> on the server.
      </p>
      <div className="action-row">
        <button
          type="button"
          disabled={busy}
          onClick={() => run("/api/test/simulate-ticket", "Ticket")}
        >
          Simulate ticket (mock alerts JSON)
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => run("/api/test/simulate-codex", "Codex")}
        >
          Simulate Codex payload
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => run("/api/test/simulate-deploy", "Deploy")}
        >
          Simulate deploy (no GH)
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setMsg(null);
            try {
              const r = await postTest("/api/test/run-flow", { deploy: false });
              setMsg({ ok: true, text: `Flow: ${JSON.stringify(r)}` });
            } catch (e) {
              setMsg({ ok: false, text: e.message });
            } finally {
              setBusy(false);
            }
          }}
        >
          Run mini flow
        </button>
      </div>
      {msg && (
        <div className={`banner ${msg.ok ? "banner-success" : "banner-error"}`}>
          {msg.text}
        </div>
      )}
    </section>
  );
}
