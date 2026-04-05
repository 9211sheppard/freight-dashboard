import "dotenv/config";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import express from "express";
import cors from "cors";
import helmet from "helmet";
import session from "express-session";
import sessionFileStore from "session-file-store";
import rateLimit from "express-rate-limit";
import { validateEnvironment, logValidationResult, exitIfFatalInProduction } from "./config/envValidation.js";
import { alertsRouter } from "./routes/alerts.js";
import { githubRouter } from "./routes/github.js";
import { codexRouter } from "./routes/codex.js";
import { actionsRouter } from "./routes/actions.js";
import { authRouter } from "./routes/auth.js";
import { configRouter } from "./routes/config.js";
import { testModeRouter } from "./routes/testMode.js";
import { securityRouter } from "./routes/security.js";
import { requireAuth } from "./middleware/requireAuth.js";
import { requireWebhookSecret } from "./middleware/webhookAuth.js";
import { insertCodexPayload } from "./repositories/codexRepository.js";
import { initDatabase } from "./db/connection.js";

const FileStore = sessionFileStore(session);
const app = express();
const PORT = Number(process.env.PORT) || 5050;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientDistLocal = path.resolve(__dirname, "..", "..", "client", "dist");
const clientDistDeploy = path.resolve(__dirname, "..", "..", "client_dist");
const clientDistPath = fs.existsSync(clientDistDeploy) ? clientDistDeploy : clientDistLocal;

const envResult = validateEnvironment();
logValidationResult(envResult);
exitIfFatalInProduction(envResult);

app.set("trust proxy", process.env.TRUST_PROXY === "1" ? 1 : false);

app.use(
  helmet({
    contentSecurityPolicy: false,
  })
);

app.use(
  cors({
    origin: process.env.CORS_ORIGIN || "http://localhost:5173",
    credentials: true,
  })
);

app.use(express.json({ limit: "2mb" }));

const sessionDir =
  process.env.SESSION_FILE_STORE_PATH ||
  path.join(process.env.DATA_DIR || path.join(process.cwd(), "data"), "sessions");
fs.mkdirSync(sessionDir, { recursive: true });

app.use(
  session({
    name: "saasops.sid",
    secret: process.env.SESSION_SECRET || "dev-only-change-me",
    resave: false,
    saveUninitialized: false,
    store: new FileStore({
      path: sessionDir,
      ttl: 60 * 60 * 24 * 7,
      retries: 1,
    }),
    cookie: {
      httpOnly: true,
      secure: process.env.COOKIE_SECURE === "true",
      sameSite: "lax",
      maxAge: 7 * 24 * 60 * 60 * 1000,
    },
  })
);

const webhookLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: Number(process.env.WEBHOOK_RATE_LIMIT_MAX) || 120,
  standardHeaders: true,
  legacyHeaders: false,
});

const apiLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: Number(process.env.API_RATE_LIMIT_MAX) || 200,
  standardHeaders: true,
  legacyHeaders: false,
});

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, service: "saas-ops-api" });
});

app.use("/api/auth", authRouter);

async function handleCodexWebhook(req, res, next) {
  try {
    const record = await insertCodexPayload(req.body || {});
    res.status(201).json({
      ok: true,
      id: record.id,
      receivedAt: record.receivedAt,
    });
  } catch (e) {
    next(e);
  }
}

app.post("/webhooks/codex", webhookLimiter, requireWebhookSecret, handleCodexWebhook);
app.post("/api/codex/webhook", webhookLimiter, requireWebhookSecret, handleCodexWebhook);

app.use("/api", apiLimiter);

app.use("/api/config", configRouter);
app.use("/api/test", testModeRouter);

app.use("/api/alerts", requireAuth, alertsRouter);
app.use("/api/github", requireAuth, githubRouter);
app.use("/api/codex", requireAuth, codexRouter);
app.use("/api/actions", requireAuth, actionsRouter);
app.use("/api/security", requireAuth, securityRouter);

if (process.env.NODE_ENV === "production") {
  app.use(express.static(clientDistPath));
  app.get("/", (_req, res) => {
    res.sendFile(path.join(clientDistPath, "index.html"));
  });
  app.get("/*", (req, res, next) => {
    if (req.path.startsWith("/api") || req.path.startsWith("/webhooks")) return next();
    res.sendFile(path.join(clientDistPath, "index.html"));
  });
}

app.use((err, _req, res, _next) => {
  console.error(err);
  const status = err.status || 500;
  res.status(status).json({
    error: err.message || "Internal error",
    detail: process.env.NODE_ENV === "development" ? String(err) : undefined,
  });
});

initDatabase()
  .then(() => {
    app.listen(PORT, () => {
      console.log(`SaaS Ops API listening on http://localhost:${PORT}`);
    });
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
