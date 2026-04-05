const base = "";

async function json(path, options = {}) {
  const res = await fetch(`${base}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    const err = new Error(data.error || "Unauthorized");
    err.status = 401;
    throw err;
  }
  if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
  return data;
}

export function fetchMe() {
  return json("/api/auth/me");
}

export function fetchConfig() {
  return json("/api/config");
}

export function login(username, password) {
  return json("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return json("/api/auth/logout", { method: "POST" });
}

export function fetchAlerts() {
  return json("/api/alerts");
}

export function fetchPulls() {
  return json("/api/github/pulls");
}

export function fetchCodexLatest() {
  return json("/api/codex/latest");
}

export function fetchActionEvents(limit = 25) {
  const lim = Math.min(Number(limit) || 25, 200);
  return json(`/api/actions/events?limit=${encodeURIComponent(String(lim))}`);
}

export function postAction(path, body) {
  return json(path, { method: "POST", body: JSON.stringify(body || {}) });
}

export function postTest(path, body) {
  return json(path, {
    method: "POST",
    body: JSON.stringify(body || {}),
  });
}

export function fetchGuardrails() {
  return json("/api/config/guardrails");
}

export function toggleKillSwitch(active) {
  return json("/api/config/guardrails/kill-switch", {
    method: "PUT",
    body: JSON.stringify({ active }),
  });
}
