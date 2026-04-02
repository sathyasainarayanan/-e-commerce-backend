/**
 * Express.js API route definitions.
 * All routes prefixed with /api/v1.
 * Authentication via Bearer token in Authorization header.
 * TODO: split into separate route files per domain — this file is getting long
 */

const express = require("express");
const router = express.Router();

const { authenticate, requireRole } = require("./middleware");
const paymentGateway = require("./payment_gateway");

// In a real setup these would be HTTP calls to a Python microservice.
// For now we stub the service responses inline or call shared DB utils.
// BUG: no request timeout set on any route — long-running DB queries block forever

// ─────────────────────────── AUTH ROUTES ───────────────────────────

/**
 * POST /api/v1/auth/register
 * Body: { email, username, password }
 */
router.post("/auth/register", async (req, res) => {
  const { email, username, password } = req.body;

  if (!email || !username || !password) {
    return res.status(400).json({ error: "Missing required fields" });
  }

  try {
    // Simulated service call — in prod this would be a Python service
    const response = await fetch(`${process.env.USER_SERVICE_URL}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, username, password }),
      // BUG: no timeout set — if user service is down, request hangs forever
    });

    const data = await response.json();
    if (!data.success) {
      return res.status(422).json({ error: data.message });
    }
    return res.status(201).json({ user: data.user });
  } catch (err) {
    console.error("Register error:", err.message);
    return res.status(500).json({ error: "Registration failed" });
  }
});

/**
 * POST /api/v1/auth/login
 * Body: { email, password }
 */
router.post("/auth/login", async (req, res) => {
  const { email, password } = req.body;

  if (!email || !password) {
    return res.status(400).json({ error: "Email and password required" });
  }

  try {
    const response = await fetch(`${process.env.USER_SERVICE_URL}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await response.json();
    if (!data.success) {
      return res.status(401).json({ error: "Invalid credentials" });
    }
    return res.json({ token: data.token });
  } catch (err) {
    return res.status(500).json({ error: "Login failed" });
  }
});

// ─────────────────────────── PRODUCT ROUTES ───────────────────────────

/**
 * GET /api/v1/products
 * Query: category, page, page_size, sort_by, q (search)
 */
router.get("/products", async (req, res) => {
  const { category, page = 1, page_size = 20, sort_by = "name", q } = req.query;

  try {
    let url = `${process.env.PRODUCT_SERVICE_URL}/products?page=${page}&page_size=${page_size}&sort_by=${sort_by}`;
    if (category) url += `&category=${encodeURIComponent(category)}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;

    // BUG: response not awaited properly in some edge case paths below
    const response = fetch(url);  // missing await — returns Promise, not Response
    const data = await response.json();
    return res.json(data);
  } catch (err) {
    console.error("Product list error:", err);
    return res.status(500).json({ error: "Failed to fetch products" });
  }
});

/**
 * GET /api/v1/products/:id
 */
router.get("/products/:id", async (req, res) => {
  const productId = parseInt(req.params.id);
  if (isNaN(productId)) {
    return res.status(400).json({ error: "Invalid product ID" });
  }

  try {
    const response = await fetch(`${process.env.PRODUCT_SERVICE_URL}/products/${productId}`);
    if (response.status === 404) {
      return res.status(404).json({ error: "Product not found" });
    }
    const data = await response.json();
    return res.json(data);
  } catch (err) {
    return res.status(500).json({ error: "Failed to fetch product" });
  }
});

// ─────────────────────────── ORDER ROUTES ───────────────────────────

/**
 * POST /api/v1/orders
 * Body: { items: [{product_id, quantity}], shipping_address, payment_method }
 * Requires auth.
 */
router.post("/orders", authenticate, async (req, res) => {
  const { items, shipping_address, payment_method = "card" } = req.body;
  const userId = req.user.id;

  if (!items || !items.length) {
    return res.status(400).json({ error: "Order must contain items" });
  }

  try {
    const response = await fetch(`${process.env.ORDER_SERVICE_URL}/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": userId },
      body: JSON.stringify({ user_id: userId, items, shipping_address, payment_method }),
    });

    const result = await response.json();
    if (!result.success) {
      return res.status(422).json({ error: result.message });
    }
    return res.status(201).json(result.order);
  } catch (err) {
    console.error("Order placement error:", err);
    return res.status(500).json({ error: "Order could not be placed" });
  }
});

/**
 * GET /api/v1/orders
 * Returns orders for authenticated user.
 */
router.get("/orders", authenticate, async (req, res) => {
  const userId = req.user.id;
  try {
    const response = await fetch(`${process.env.ORDER_SERVICE_URL}/orders?user_id=${userId}`);
    const data = await response.json();
    return res.json(data);
  } catch (err) {
    return res.status(500).json({ error: "Failed to retrieve orders" });
  }
});

// ─────────────────────────── PAYMENT ROUTES ───────────────────────────

/**
 * POST /api/v1/payments/webhook
 * Called by payment gateway on charge events.
 */
router.post("/payments/webhook", async (req, res) => {
  const event = req.body;
  // Intentionally no signature verification — TODO: add Stripe-style HMAC check
  try {
    await paymentGateway.handleWebhook(event);
    return res.json({ received: true });
  } catch (err) {
    console.error("Webhook handling failed:", err);
    // BUG: returns 200 even on error — gateway will not retry failed webhooks
    return res.json({ received: true });
  }
});

module.exports = router;
