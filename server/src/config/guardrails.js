/**
 * Production-safe guardrails: allowlist, max RPS, kill-switch,
 * deploy-block-on-critical.
 *
 * Runtime state lives in memory (kill-switch toggle).
 * Static config comes from env vars with sensible defaults.
 */

/* ── runtime state ──────────────────────────────────────── */
let killSwitchActive = process.env.GUARDRAIL_KILL_SWITCH === "true";

export function isKillSwitchActive() {
  return killSwitchActive;
}
export function setKillSwitch(on) {
  killSwitchActive = !!on;
  return killSwitchActive;
}

/* ── allowlist ──────────────────────────────────────────── */
function csvSet(envKey, fallback) {
  const raw = process.env[envKey]?.trim();
  if (!raw) return new Set(fallback);
  return new Set(raw.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean));
}

const ALLOWED_ACTIONS = csvSet("GUARDRAIL_ALLOWED_ACTIONS", [
  "approve-fix",
  "deploy-azure",
  "rollback",
]);

const ALLOWED_ENVIRONMENTS = csvSet("GUARDRAIL_ALLOWED_ENVS", [
  "production",
  "staging",
  "development",
]);

export function isActionAllowed(action) {
  return ALLOWED_ACTIONS.has(String(action).toLowerCase());
}

export function isEnvironmentAllowed(env) {
  if (!env) return true;
  return ALLOWED_ENVIRONMENTS.has(String(env).toLowerCase());
}

/* ── max RPS (sliding-window token bucket per action) ──── */
const DEFAULT_MAX_RPS = Number(process.env.GUARDRAIL_MAX_RPS) || 2;
const WINDOW_MS = 60_000;

const buckets = new Map();

export function checkRateLimit(action) {
  const key = String(action).toLowerCase();
  const now = Date.now();
  if (!buckets.has(key)) buckets.set(key, []);
  const timestamps = buckets.get(key).filter((t) => now - t < WINDOW_MS);
  buckets.set(key, timestamps);

  const maxPerWindow = DEFAULT_MAX_RPS * (WINDOW_MS / 1000);
  if (timestamps.length >= maxPerWindow) {
    return {
      allowed: false,
      retryAfterMs: WINDOW_MS - (now - timestamps[0]),
      limit: maxPerWindow,
      remaining: 0,
    };
  }
  timestamps.push(now);
  return {
    allowed: true,
    retryAfterMs: 0,
    limit: maxPerWindow,
    remaining: maxPerWindow - timestamps.length,
  };
}

/* ── deploy-block-on-critical ──────────────────────────── */
const BLOCK_DEPLOY_ON_CRITICAL =
  (process.env.GUARDRAIL_BLOCK_DEPLOY_ON_CRITICAL ?? "true") !== "false";

export function shouldBlockDeploy(alerts) {
  if (!BLOCK_DEPLOY_ON_CRITICAL) return { blocked: false, reason: null };
  if (!Array.isArray(alerts) || alerts.length === 0) return { blocked: false, reason: null };

  const critical = alerts.filter(
    (a) =>
      (a.severity === "Sev0" || a.severity === "Sev1") &&
      a.state !== "Closed" &&
      a.monitorCondition !== "Resolved"
  );

  if (critical.length > 0) {
    return {
      blocked: true,
      reason: `${critical.length} unresolved critical alert(s): ${critical
        .map((a) => a.name || a.id)
        .join(", ")}`,
      alerts: critical,
    };
  }
  return { blocked: false, reason: null };
}

/* ── full status snapshot (for /api/config and UI) ─────── */
export function getGuardrailStatus() {
  return {
    killSwitch: killSwitchActive,
    allowedActions: [...ALLOWED_ACTIONS],
    allowedEnvironments: [...ALLOWED_ENVIRONMENTS],
    maxRpsPerAction: DEFAULT_MAX_RPS,
    windowSeconds: WINDOW_MS / 1000,
    blockDeployOnCritical: BLOCK_DEPLOY_ON_CRITICAL,
  };
}
