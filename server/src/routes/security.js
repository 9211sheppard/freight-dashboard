import { Router } from "express";
import path from "path";
import { fileURLToPath } from "url";
import { runSecurityScan } from "../services/securityScan.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..", "..", "..");

export const securityRouter = Router();

let lastScanResult = null;

securityRouter.post("/scan", async (_req, res, next) => {
  try {
    const result = await runSecurityScan(PROJECT_ROOT);
    lastScanResult = result;
    res.json({ ok: true, ...result });
  } catch (e) {
    next(e);
  }
});

securityRouter.get("/results", (_req, res) => {
  if (!lastScanResult) {
    return res.json({ ok: true, scannedAt: null, findings: [], message: "No scan has been run yet." });
  }
  res.json({ ok: true, ...lastScanResult });
});
