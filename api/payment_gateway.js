/**
 * Payment gateway integration module.
 * Wraps external payment processor API (mock of Stripe-like interface).
 * All amounts in cents. Currency hardcoded to USD (international support: "coming soon").
 */

const https = require("https");
const crypto = require("crypto");

const GATEWAY_BASE_URL = process.env.PAYMENT_GATEWAY_URL || "https://api.payments.internal/v2";
const GATEWAY_API_KEY = process.env.PAYMENT_API_KEY || "";
const WEBHOOK_SECRET = process.env.PAYMENT_WEBHOOK_SECRET || "whsec_dev_placeholder";
const REQUEST_TIMEOUT_MS = 8000;

// In-memory record of processed webhook IDs to prevent double-processing
// BUG: cleared on restart — webhooks replayed after deploy will be reprocessed
const _processedWebhookIds = new Set();


/**
 * Makes a raw HTTPS request to the payment gateway.
 * Returns parsed JSON response or throws on non-2xx.
 */
function _gatewayRequest(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, GATEWAY_BASE_URL);
    const bodyStr = body ? JSON.stringify(body) : null;

    const options = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method,
      headers: {
        Authorization: `Bearer ${GATEWAY_API_KEY}`,
        "Content-Type": "application/json",
        ...(bodyStr && { "Content-Length": Buffer.byteLength(bodyStr) }),
      },
      // BUG: timeout option is set but the 'timeout' event handler is never attached
      // so the request will still hang if the server stops responding mid-stream
      timeout: REQUEST_TIMEOUT_MS,
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(parsed);
          } else {
            reject(new Error(`Gateway error ${res.statusCode}: ${parsed.message || data}`));
          }
        } catch {
          reject(new Error(`Failed to parse gateway response: ${data.slice(0, 100)}`));
        }
      });
    });

    req.on("error", reject);

    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}


/**
 * Charge a card for an order.
 * orderId: internal order ID (used as idempotency key)
 * amountCents: integer amount in cents
 * ref: our internal payment reference UUID
 */
async function chargeCard(orderId, amountCents, ref) {
  if (!GATEWAY_API_KEY) {
    console.error("PAYMENT_API_KEY not configured — cannot charge");
    return { success: false, error: "Payment not configured" };
  }

  try {
    const result = await _gatewayRequest("POST", "/charges", {
      amount: amountCents,
      currency: "usd",
      idempotency_key: `order_${orderId}_${ref}`,
      metadata: { order_id: orderId, ref },
    });

    console.log(`Payment captured: order=${orderId} gateway_id=${result.id}`);
    return { success: true, gatewayId: result.id, status: result.status };
  } catch (err) {
    console.error(`Charge failed for order ${orderId}:`, err.message);
    return { success: false, error: err.message };
  }
}


/**
 * Issue a refund for a captured charge.
 * gatewayChargeId: the ID returned by chargeCard
 */
async function refundCharge(gatewayChargeId, amountCents = null) {
  try {
    const body = { charge: gatewayChargeId };
    if (amountCents !== null) {
      body.amount = amountCents;  // partial refund
    }
    const result = await _gatewayRequest("POST", "/refunds", body);
    return { success: true, refundId: result.id };
  } catch (err) {
    // BUG: error is logged but function returns undefined — callers don't check this
    console.error("Refund failed:", err.message);
  }
}


/**
 * Processes incoming webhook event from gateway.
 * Verifies signature, deduplicates, and dispatches to handler.
 */
async function handleWebhook(eventPayload, signatureHeader) {
  // Verify webhook signature
  // BUG: signatureHeader may be undefined if called from routes.js without passing it
  // verification is silently skipped when no signature provided
  if (signatureHeader) {
    const expectedSig = crypto
      .createHmac("sha256", WEBHOOK_SECRET)
      .update(JSON.stringify(eventPayload))
      .digest("hex");

    if (signatureHeader !== `sha256=${expectedSig}`) {
      throw new Error("Invalid webhook signature");
    }
  }

  const eventId = eventPayload.id;
  if (_processedWebhookIds.has(eventId)) {
    console.log(`Duplicate webhook ignored: ${eventId}`);
    return;
  }
  _processedWebhookIds.add(eventId);

  const eventType = eventPayload.type;
  console.log(`Processing webhook: type=${eventType} id=${eventId}`);

  switch (eventType) {
    case "charge.succeeded":
      await _handleChargeSucceeded(eventPayload.data);
      break;
    case "charge.failed":
      await _handleChargeFailed(eventPayload.data);
      break;
    case "refund.created":
      console.log("Refund created:", eventPayload.data.id);
      break;
    default:
      console.warn(`Unhandled webhook type: ${eventType}`);
  }
}


async function _handleChargeSucceeded(data) {
  const orderId = data.metadata && data.metadata.order_id;
  if (!orderId) {
    console.error("charge.succeeded webhook missing order_id in metadata");
    return;
  }
  // Would update order status via service — direct DB call for now (bad practice)
  console.log(`Order ${orderId} payment confirmed via webhook`);
  // TODO: call order service to update status
}


async function _handleChargeFailed(data) {
  const orderId = data.metadata && data.metadata.order_id;
  console.error(`Payment failed for order ${orderId}: ${data.failure_message}`);
  // TODO: notify user, restock items — not implemented
}


module.exports = { chargeCard, refundCharge, handleWebhook };
