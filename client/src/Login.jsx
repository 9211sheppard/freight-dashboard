import { useState } from "react";
import { login } from "./api.js";

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      await login(username, password);
      onLoggedIn();
    } catch (e2) {
      setErr(e2.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div style={{ marginBottom: "0.25rem", fontSize: "1.75rem", letterSpacing: "-0.04em" }} aria-hidden="true">
          &#9670;
        </div>
        <h1>SaaS Ops</h1>
        <p className="login-hint">Sign in to your operations dashboard</p>
        <form onSubmit={handleSubmit}>
          <label>
            Username
            <input
              type="text"
              autoComplete="username"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {err && <p className="login-error">{err}</p>}
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? "Signing in\u2026" : "Sign in"}
          </button>
        </form>
        <p className="login-footer-hint">Premium support available for enterprise customers.</p>
      </div>
    </div>
  );
}
