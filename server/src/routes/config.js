import { Router } from "express";
import { requireAuth } from "../middleware/requireAuth.js";
import { validateEnvironment } from "../config/envValidation.js";
import { isTestModeEnabled } from "../config/testMode.js";
import { getGuardrailStatus, setKillSwitch, isKillSwitchActive } from "../config/guardrails.js";

export const configRouter = Router();

configRouter.get("/", requireAuth, (_req, res) => {
  const v = validateEnvironment();
  const hasHttpApprove = !!process.env.ORCHESTRATOR_APPROVE_URL?.trim();
  const hasScriptApprove =
    !!process.env.ORCHESTRATOR_APPROVE_SCRIPT?.trim() &&
    !!process.env.ORCHESTRATOR_ACTIVE_DIR?.trim();

  let orchestratorMode = "missing";
  if (hasHttpApprove) orchestratorMode = "http";
  else if (hasScriptApprove) orchestratorMode = "script";

  const githubVars = {
    GITHUB_TOKEN: !!process.env.GITHUB_TOKEN?.trim(),
    GITHUB_OWNER: !!process.env.GITHUB_OWNER?.trim(),
    GITHUB_REPO: !!process.env.GITHUB_REPO?.trim(),
  };

  const orchestratorVars = hasHttpApprove
    ? {
        ORCHESTRATOR_APPROVE_URL: true,
        ORCHESTRATOR_API_SECRET: !!process.env.ORCHESTRATOR_API_SECRET?.trim(),
      }
    : hasScriptApprove
      ? {
          ORCHESTRATOR_APPROVE_SCRIPT: true,
          ORCHESTRATOR_ACTIVE_DIR: true,
        }
      : {
          ORCHESTRATOR_APPROVE_URL: false,
          ORCHESTRATOR_API_SECRET: false,
        };

  const azureAlertVars = {
    AZURE_SUBSCRIPTION_ID: !!process.env.AZURE_SUBSCRIPTION_ID?.trim(),
    AZURE_TENANT_ID: !!process.env.AZURE_TENANT_ID?.trim(),
    AZURE_CLIENT_ID: !!process.env.AZURE_CLIENT_ID?.trim(),
    AZURE_CLIENT_SECRET: !!process.env.AZURE_CLIENT_SECRET?.trim(),
  };
  const azureHasAuth =
    (azureAlertVars.AZURE_TENANT_ID && azureAlertVars.AZURE_CLIENT_ID && azureAlertVars.AZURE_CLIENT_SECRET);

  res.json({
    environment: process.env.NODE_ENV || "development",
    testMode: isTestModeEnabled(),
    integrations: {
      github: {
        ready: githubVars.GITHUB_TOKEN && githubVars.GITHUB_OWNER && githubVars.GITHUB_REPO,
        vars: githubVars,
        hint: "Set GITHUB_TOKEN (PAT with repo + actions:write), GITHUB_OWNER (org/user), GITHUB_REPO (repo name).",
      },
      orchestrator: {
        ready: orchestratorMode !== "missing",
        mode: orchestratorMode,
        vars: orchestratorVars,
        hint: orchestratorMode === "missing"
          ? "Set ORCHESTRATOR_APPROVE_URL + ORCHESTRATOR_API_SECRET (HTTP mode) or ORCHESTRATOR_APPROVE_SCRIPT + ORCHESTRATOR_ACTIVE_DIR (script mode)."
          : orchestratorMode === "http" && !orchestratorVars.ORCHESTRATOR_API_SECRET
            ? "ORCHESTRATOR_API_SECRET is recommended for HTTP approve unless your endpoint is network-isolated."
            : null,
      },
      azureAlerts: {
        ready: azureAlertVars.AZURE_SUBSCRIPTION_ID && azureHasAuth,
        subscriptionSet: azureAlertVars.AZURE_SUBSCRIPTION_ID,
        authSet: azureHasAuth,
        vars: azureAlertVars,
        hint: !azureAlertVars.AZURE_SUBSCRIPTION_ID
          ? "Set AZURE_SUBSCRIPTION_ID to enable Azure Monitor alerts."
          : !azureHasAuth
            ? "Set AZURE_TENANT_ID + AZURE_CLIENT_ID + AZURE_CLIENT_SECRET for service-principal auth (or use az login / managed identity)."
            : null,
      },
      database:
        process.env.DATABASE_URL?.startsWith("postgres") ||
        process.env.DATABASE_URL?.startsWith("postgresql")
          ? "postgres"
          : "sqlite",
    },
    envWarnings: v.warnings.map((w) => ({
      name: w.name,
      message: w.message,
    })),
    envFatalCount: v.fatal.length,
    guardrails: getGuardrailStatus(),
  });
});

configRouter.get("/guardrails", requireAuth, (_req, res) => {
  res.json({ ok: true, ...getGuardrailStatus() });
});

configRouter.put("/guardrails/kill-switch", requireAuth, (req, res) => {
  const active = !!req.body?.active;
  const result = setKillSwitch(active);
  console.warn(`[guardrails] Kill-switch ${result ? "ACTIVATED" : "deactivated"} by ${req.session?.user?.name || "unknown"}`);
  res.json({ ok: true, killSwitch: result });
});
