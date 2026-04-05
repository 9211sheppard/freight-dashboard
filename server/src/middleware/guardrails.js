/**
 * Express middleware that enforces production guardrails on action routes.
 *
 * Checks (in order):
 *  1. Kill-switch  — blocks ALL destructive actions instantly
 *  2. Allowlist    — rejects unknown actions or environments
 *  3. Rate limit   — sliding-window per-action RPS cap
 *  4. Deploy block — prevents deploy when unresolved Sev0/Sev1 alerts exist
 */
import {
  isKillSwitchActive,
  isActionAllowed,
  isEnvironmentAllowed,
  checkRateLimit,
  shouldBlockDeploy,
} from "../config/guardrails.js";
import { listSubscriptionAlerts } from "../services/azureAlerts.js";

export function enforceGuardrails(actionName) {
  return async (req, res, next) => {
    // 1. Kill-switch
    if (isKillSwitchActive()) {
      res.status(503).json({
        error: "Kill-switch is active — all destructive actions are disabled.",
        guardrail: "kill-switch",
      });
      return;
    }

    // 2. Action allowlist
    if (!isActionAllowed(actionName)) {
      res.status(403).json({
        error: `Action "${actionName}" is not in the allowlist.`,
        guardrail: "allowlist",
      });
      return;
    }

    // 3. Environment allowlist
    const env = req.body?.environment;
    if (env && !isEnvironmentAllowed(env)) {
      res.status(403).json({
        error: `Environment "${env}" is not in the allowlist.`,
        guardrail: "allowlist",
      });
      return;
    }

    // 4. Rate limit
    const rl = checkRateLimit(actionName);
    res.setHeader("X-RateLimit-Limit", rl.limit);
    res.setHeader("X-RateLimit-Remaining", rl.remaining);
    if (!rl.allowed) {
      res.setHeader("Retry-After", Math.ceil(rl.retryAfterMs / 1000));
      res.status(429).json({
        error: `Rate limit exceeded for "${actionName}". Try again in ${Math.ceil(rl.retryAfterMs / 1000)}s.`,
        guardrail: "rate-limit",
        retryAfterMs: rl.retryAfterMs,
      });
      return;
    }

    // 5. Deploy-block-on-critical (only for deploy)
    if (actionName === "deploy-azure") {
      try {
        const alertResult = await listSubscriptionAlerts();
        if (alertResult.configured && alertResult.items?.length > 0) {
          const block = shouldBlockDeploy(alertResult.items);
          if (block.blocked) {
            res.status(409).json({
              error: block.reason,
              guardrail: "deploy-block-critical",
              alerts: block.alerts.map((a) => ({
                id: a.id,
                name: a.name,
                severity: a.severity,
              })),
            });
            return;
          }
        }
      } catch {
        /* alerts unavailable — allow deploy, don't block on infra failure */
      }
    }

    next();
  };
}
