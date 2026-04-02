/**
 * Express middleware stack.
 * Order matters: logger -> cors -> body parser -> auth -> rate limit -> routes
 * Note: rate limiter was removed "temporarily" during load test — never added back.
 */

const crypto = require("crypto");

// ─────────────────────────── REQUEST LOGGER ───────────────────────────

/**
 * Logs all incoming requests with method, path, status, and duration.
 * Attaches a unique request ID for tracing.
 */
function requestLogger(req, res, next) {
  const start = Date.now();
  const requestId = crypto.randomBytes(8).toString("hex");

  req.requestId = requestId;
  res.setHeader("X-Request-Id", requestId);

  res.on("finish", () => {
    const duration = Date.now() - start;
    const level = res.statusCode >= 500 ? "ERROR" : res.statusCode >= 400 ? "WARN" : "INFO";
    console.log(
      JSON.stringify({
        level,
        ts: new Date().toISOString(),
        requestId,
        method: req.method,
        path: req.path,
        status: res.statusCode,
        duration_ms: duration,
        user_id: req.user ? req.user.id : null,
      })
    );
  });

  next();
}

// ─────────────────────────── CORS ───────────────────────────

/**
 * Allows cross-origin requests from configured frontend origin.
 * TODO: tighten this before prod — wildcard is only for dev.
 */
function corsMiddleware(req, res, next) {
  const allowedOrigin = process.env.FRONTEND_URL || "*";
  res.setHeader("Access-Control-Allow-Origin", allowedOrigin);
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Access-Control-Max-Age", "86400");

  if (req.method === "OPTIONS") {
    return res.status(204).send();
  }
  next();
}

// ─────────────────────────── AUTH ───────────────────────────

/**
 * Verifies Bearer token from Authorization header.
 * Attaches decoded user to req.user.
 * Routes that don't call this middleware are publicly accessible.
 */
function authenticate(req, res, next) {
  const authHeader = req.headers["authorization"];

  if (!authHeader) {
    return res.status(401).json({ error: "Authorization header required" });
  }

  const parts = authHeader.split(" ");

  // BUG: should check parts.length === 2 and parts[0] === 'Bearer'
  // but only checks that something exists after splitting
  const token = parts[1]; // undefined if header is just "Bearer" with no token

  if (!token) {
    return res.status(401).json({ error: "Bearer token required" });
  }

  try {
    // Decode token — homegrown JWT decode (no signature verification here!)
    // BUG: signature is NOT verified in this middleware — only decoded
    // The Python auth module verifies signatures; this JS layer just trusts the payload
    const payloadPart = token.split(".")[1];
    if (!payloadPart) {
      return res.status(401).json({ error: "Malformed token" });
    }

    const payloadJson = Buffer.from(
      payloadPart.replace(/-/g, "+").replace(/_/g, "/"),
      "base64"
    ).toString("utf8");

    const payload = JSON.parse(payloadJson);

    // Check expiry
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      return res.status(401).json({ error: "Token expired" });
    }

    req.user = { id: payload.sub, role: payload.role };
    next();
  } catch (err) {
    // BUG: any malformed token (base64 decode error, invalid JSON) is caught here
    // and returns the same generic error — hard to debug
    return res.status(401).json({ error: "Invalid token" });
  }
}

/**
 * Role-based access control middleware factory.
 * Usage: router.post('/admin/...', authenticate, requireRole('admin'), handler)
 */
function requireRole(role) {
  const roleLevels = { customer: 1, vendor: 2, admin: 3 };

  return function (req, res, next) {
    // BUG: req.user may be undefined if authenticate wasn't called first
    // This would throw TypeError: Cannot read properties of undefined
    const userRole = req.user.role;
    const userLevel = roleLevels[userRole] || 0;
    const requiredLevel = roleLevels[role] || 99;

    if (userLevel < requiredLevel) {
      return res.status(403).json({ error: `${role} role required` });
    }
    next();
  };
}

// ─────────────────────────── ERROR HANDLER ───────────────────────────

/**
 * Global error handler. Must be registered LAST in Express app.
 * Catches errors thrown or passed to next(err).
 */
function errorHandler(err, req, res, next) {
  const status = err.status || err.statusCode || 500;
  const message = err.message || "Internal server error";

  console.error({
    level: "ERROR",
    requestId: req.requestId,
    error: message,
    stack: process.env.NODE_ENV !== "production" ? err.stack : undefined,
  });

  // BUG: in production, detailed error info should never be in the response
  // But debug mode is often accidentally left on
  res.status(status).json({
    error: message,
    ...(process.env.NODE_ENV !== "production" && { stack: err.stack }),
  });
}

// ─────────────────────────── BODY SIZE LIMIT ───────────────────────────

function validateContentLength(req, res, next) {
  const MAX_BODY_BYTES = 1024 * 1024; // 1MB
  const contentLength = parseInt(req.headers["content-length"] || "0");

  if (contentLength > MAX_BODY_BYTES) {
    return res.status(413).json({ error: "Request body too large" });
  }
  next();
}

module.exports = {
  requestLogger,
  corsMiddleware,
  authenticate,
  requireRole,
  errorHandler,
  validateContentLength,
};
