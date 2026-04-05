/**
 * Security scan service — OWASP-style vulnerability scanner.
 *
 * Scans the project codebase for common security issues by category.
 * Each finding includes: issue, severity, location, and fix suggestion.
 *
 * In production this would call Codex / an LLM API. Here we perform
 * deterministic static-analysis checks so the feature works standalone.
 */

import fs from "fs";
import path from "path";

const SEVERITY = { CRITICAL: "critical", HIGH: "high", MEDIUM: "medium", LOW: "low", INFO: "info" };

/* ── rule definitions ────────────────────── */

const RULES = [
  {
    id: "SEC-001",
    category: "A01:2021 Broken Access Control",
    pattern: /requireAuth/gi,
    invert: true,
    fileFilter: (f) => f.endsWith(".js") && f.includes("routes") && !f.includes("auth.js"),
    check(content, filePath) {
      if (!content.includes("requireAuth")) {
        return {
          issue: `Route file may lack authentication middleware`,
          severity: SEVERITY.HIGH,
          location: path.basename(filePath),
          fix: 'Import and apply requireAuth middleware: app.use("/api/...", requireAuth, router)',
        };
      }
      return null;
    },
  },
  {
    id: "SEC-002",
    category: "A02:2021 Cryptographic Failures",
    pattern: /SESSION_SECRET.*dev-only|secret.*change.?me/gi,
    check(content, filePath) {
      const match = content.match(/SESSION_SECRET.*["']([^"']{1,20})["']/);
      if (match || content.includes("dev-only-change-me")) {
        return {
          issue: "Weak or default session secret detected",
          severity: SEVERITY.CRITICAL,
          location: path.basename(filePath),
          fix: "Set SESSION_SECRET env var to a random string >= 32 chars: openssl rand -hex 32",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-003",
    category: "A03:2021 Injection",
    pattern: /\$\{.*req\.(body|query|params)/g,
    check(content, filePath) {
      const matches = content.match(/\$\{.*req\.(body|query|params)[^}]*\}/g);
      if (matches && matches.length > 0) {
        return {
          issue: `Potential template literal injection (${matches.length} occurrence${matches.length > 1 ? "s" : ""})`,
          severity: SEVERITY.MEDIUM,
          location: path.basename(filePath),
          fix: "Sanitize user input before interpolating into strings or queries. Use parameterized queries.",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-004",
    category: "A05:2021 Security Misconfiguration",
    pattern: /contentSecurityPolicy:\s*false/g,
    check(content, filePath) {
      if (content.includes("contentSecurityPolicy: false") || content.includes("contentSecurityPolicy:false")) {
        return {
          issue: "Content Security Policy is disabled in Helmet configuration",
          severity: SEVERITY.MEDIUM,
          location: path.basename(filePath),
          fix: "Enable CSP with appropriate directives instead of disabling it entirely.",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-005",
    category: "A07:2021 Auth Failures",
    pattern: /ADMIN_PASSWORD[^_]/g,
    check(content, filePath) {
      if (content.match(/ADMIN_PASSWORD[^_H]/) && !content.includes("production")) {
        return {
          issue: "Plaintext password comparison may be used outside production",
          severity: SEVERITY.LOW,
          location: path.basename(filePath),
          fix: "Always use bcrypt hash comparison. Set ADMIN_PASSWORD_HASH and remove ADMIN_PASSWORD in production.",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-006",
    category: "A09:2021 Logging Failures",
    pattern: /console\.(log|error|warn)\(.*token|console\.(log|error|warn)\(.*secret|console\.(log|error|warn)\(.*password/gi,
    check(content, filePath) {
      const matches = content.match(/console\.(log|error|warn)\(.*(?:token|secret|password)/gi);
      if (matches && matches.length > 0) {
        return {
          issue: `Potential sensitive data in log output (${matches.length} occurrence${matches.length > 1 ? "s" : ""})`,
          severity: SEVERITY.MEDIUM,
          location: path.basename(filePath),
          fix: "Never log tokens, secrets, or passwords. Redact sensitive fields before logging.",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-007",
    category: "A06:2021 Vulnerable Components",
    pattern: /node_modules/,
    check(_content, _filePath, extraContext) {
      if (extraContext?.packageJson) {
        const deps = {
          ...extraContext.packageJson.dependencies,
          ...extraContext.packageJson.devDependencies,
        };
        const known = [];
        if (deps["express"] && deps["express"].match(/[~^]?4\.[0-9]\./)) {
          known.push("express <4.10 has known vulnerabilities");
        }
        if (deps["jsonwebtoken"] && deps["jsonwebtoken"].match(/[~^]?[0-7]\./)) {
          known.push("jsonwebtoken <8 has algorithm confusion vulnerabilities");
        }
        if (known.length > 0) {
          return {
            issue: known.join("; "),
            severity: SEVERITY.HIGH,
            location: "package.json",
            fix: "Update vulnerable packages to their latest versions. Run: npm audit fix",
          };
        }
      }
      return null;
    },
  },
  {
    id: "SEC-008",
    category: "A04:2021 Insecure Design",
    pattern: /cors\(/g,
    check(content, filePath) {
      if (content.includes("origin: true") || content.match(/origin:\s*["']\*/)) {
        return {
          issue: "CORS allows all origins — potential cross-origin data leak",
          severity: SEVERITY.HIGH,
          location: path.basename(filePath),
          fix: "Restrict CORS origin to your specific frontend domain(s).",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-009",
    category: "A08:2021 Data Integrity",
    pattern: /httpOnly:\s*false/g,
    check(content, filePath) {
      if (content.includes("httpOnly: false")) {
        return {
          issue: "Session cookie httpOnly flag is disabled — vulnerable to XSS token theft",
          severity: SEVERITY.HIGH,
          location: path.basename(filePath),
          fix: "Set httpOnly: true on session cookies to prevent JavaScript access.",
        };
      }
      return null;
    },
  },
  {
    id: "SEC-010",
    category: "A05:2021 Security Misconfiguration",
    pattern: /secure:\s*false|COOKIE_SECURE/g,
    check(content, filePath) {
      if (content.match(/secure:\s*process\.env\.COOKIE_SECURE\s*===\s*["']true["']/)) {
        return {
          issue: "Cookie secure flag defaults to false — cookies sent over HTTP in production",
          severity: SEVERITY.LOW,
          location: path.basename(filePath),
          fix: 'Set COOKIE_SECURE=true in production, or default secure to NODE_ENV === "production".',
        };
      }
      return null;
    },
  },
];

/* ── scanner ─────────────────────────────── */

function collectFiles(dir, results = []) {
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.name === "node_modules" || entry.name === ".git" || entry.name === "dist") continue;
    if (entry.isDirectory()) {
      collectFiles(full, results);
    } else if (entry.name.endsWith(".js") || entry.name.endsWith(".jsx") || entry.name.endsWith(".ts")) {
      results.push(full);
    }
  }
  return results;
}

export async function runSecurityScan(projectRoot) {
  const serverDir = path.join(projectRoot, "server", "src");
  const clientDir = path.join(projectRoot, "client", "src");

  const files = [...collectFiles(serverDir), ...collectFiles(clientDir)];

  let packageJson = null;
  const pkgPath = path.join(projectRoot, "server", "package.json");
  try {
    packageJson = JSON.parse(fs.readFileSync(pkgPath, "utf-8"));
  } catch {
    /* no package.json — skip component check */
  }

  const findings = [];
  const scannedAt = new Date().toISOString();

  for (const filePath of files) {
    let content;
    try {
      content = fs.readFileSync(filePath, "utf-8");
    } catch {
      continue;
    }

    for (const rule of RULES) {
      try {
        if (rule.fileFilter && !rule.fileFilter(filePath)) continue;
        const result = rule.check(content, filePath, { packageJson });
        if (result) {
          findings.push({
            id: rule.id,
            category: rule.category,
            ...result,
          });
        }
      } catch {
        /* rule error — skip */
      }
    }
  }

  // Deduplicate by id + location
  const seen = new Set();
  const unique = findings.filter((f) => {
    const key = `${f.id}:${f.location}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // Sort: critical > high > medium > low > info
  const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
  unique.sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5));

  return {
    scannedAt,
    filesScanned: files.length,
    findingsCount: unique.length,
    findings: unique,
    summary: {
      critical: unique.filter((f) => f.severity === "critical").length,
      high: unique.filter((f) => f.severity === "high").length,
      medium: unique.filter((f) => f.severity === "medium").length,
      low: unique.filter((f) => f.severity === "low").length,
      info: unique.filter((f) => f.severity === "info").length,
    },
  };
}
