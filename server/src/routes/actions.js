import { Router } from "express";
import { approvePipelineJob } from "../services/orchestratorApprove.js";
import {
  triggerDeployWorkflow,
  triggerRollbackWorkflow,
} from "../services/githubWorkflows.js";
import {
  insertActionEvent,
  fetchActionEvents,
} from "../repositories/actionEventsRepository.js";
import {
  validateApproveBody,
  validateDeployBody,
  validateRollbackBody,
} from "../middleware/actionValidation.js";
import { enforceGuardrails } from "../middleware/guardrails.js";

export const actionsRouter = Router();

async function recordActionEvent({ req, action, ok, httpStatus, detail }) {
  try {
    await insertActionEvent({
      action,
      ok,
      httpStatus,
      userName: req.session?.user?.name || null,
      detail,
    });
  } catch {
    /* best-effort */
  }
}

actionsRouter.get("/events", async (req, res, next) => {
  try {
    const limit = Math.min(Number(req.query.limit) || 25, 200);
    const items = await fetchActionEvents(limit);
    res.json({ ok: true, items });
  } catch (e) {
    next(e);
  }
});

actionsRouter.post(
  "/approve-fix",
  validateApproveBody,
  enforceGuardrails("approve-fix"),
  async (req, res, next) => {
    try {
      const jobId = req.body?.jobId ?? req.body?.job_id;
      const result = await approvePipelineJob(jobId);
      await recordActionEvent({
        req,
        action: "approve-fix",
        ok: true,
        httpStatus: result.status || 200,
        detail: {
          request: { jobId, notes: req.body?.notes },
          result,
          evidence: req.body?.evidence || null,
          severity: req.body?.severity || null,
          fix: req.body?.fix || null,
          retest: req.body?.retest || null,
        },
      });
      res.json({
        ok: true,
        action: "approve-fix",
        ...result,
      });
    } catch (e) {
      await recordActionEvent({
        req,
        action: "approve-fix",
        ok: false,
        httpStatus: e.status || 500,
        detail: { request: { jobId: req.body?.jobId ?? req.body?.job_id }, error: e.message },
      });
      next(e);
    }
  }
);

actionsRouter.post(
  "/deploy-azure",
  validateDeployBody,
  enforceGuardrails("deploy-azure"),
  async (req, res, next) => {
    try {
      const { environment, imageTag, webAppName } = req.body || {};
      const result = await triggerDeployWorkflow({
        imageTag,
        environment,
        webAppName,
      });
      await recordActionEvent({
        req,
        action: "deploy-azure",
        ok: true,
        httpStatus: result.httpStatus || 204,
        detail: {
          request: { environment, imageTag, webAppName },
          result,
          evidence: req.body?.evidence || null,
          severity: req.body?.severity || null,
          fix: req.body?.fix || null,
          retest: req.body?.retest || null,
        },
      });
      res.json({
        ok: true,
        action: "deploy-azure",
        ...result,
      });
    } catch (e) {
      await recordActionEvent({
        req,
        action: "deploy-azure",
        ok: false,
        httpStatus: e.status || 500,
        detail: { request: req.body || {}, error: e.message },
      });
      next(e);
    }
  }
);

actionsRouter.post(
  "/rollback",
  validateRollbackBody,
  enforceGuardrails("rollback"),
  async (req, res, next) => {
    try {
      const { environment, targetImageTag, reason } = req.body || {};
      const result = await triggerRollbackWorkflow({
        environment,
        targetImageTag,
        reason,
      });
      await recordActionEvent({
        req,
        action: "rollback",
        ok: true,
        httpStatus: result.httpStatus || 204,
        detail: {
          request: { environment, targetImageTag, reason },
          result,
          evidence: req.body?.evidence || null,
          severity: req.body?.severity || null,
          fix: req.body?.fix || null,
          retest: req.body?.retest || null,
        },
      });
      res.json({
        ok: true,
        action: "rollback",
        ...result,
      });
    } catch (e) {
      await recordActionEvent({
        req,
        action: "rollback",
        ok: false,
        httpStatus: e.status || 500,
        detail: { request: req.body || {}, error: e.message },
      });
      next(e);
    }
  }
);
