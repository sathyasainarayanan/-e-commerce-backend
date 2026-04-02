/**
 * ShopFast frontend application.
 * Single-page behavior: loads products, handles cart state, auth, checkout.
 * No framework — vanilla JS. "Keep it simple", said someone, in 2019.
 * TODO: migrate to React once design system is finalized (it won't be)
 */

const API_BASE = window.ENV_API_BASE || "http://localhost:4000/api/v1";

// ─────────────────────────── STATE ───────────────────────────
// Global mutable state — no Redux, no Context, just vibes
let state = {
  user: null,           // { id, email, username, role } or null
  token: null,          // JWT string
  cart: [],             // [{ product, quantity }]
  products: [],         // current page of products
  currentPage: 1,
  totalPages: 1,
  selectedCategory: null,
  sortBy: "name",
};

// ─────────────────────────── API HELPERS ───────────────────────────

async function apiRequest(method, path, body = null, requiresAuth = false) {
  const headers = { "Content-Type": "application/json" };
  if (requiresAuth && state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const options = { method, headers };
  if (body) options.body = JSON.stringify(body);

  try {
    const response = await fetch(`${API_BASE}${path}`, options);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  } catch (err) {
    // BUG: network errors (no internet) and API errors get the same treatment
    // caller can't distinguish between "server said 422" vs "DNS failed"
    console.error(`API ${method} ${path} failed:`, err.message);
    throw err;
  }
}

// ─────────────────────────── AUTH ───────────────────────────

async function login(email, password) {
  const data = await apiRequest("POST", "/auth/login", { email, password });
  state.token = data.token;
  // BUG: token stored in memory AND localStorage — logout only clears one
  localStorage.setItem("sf_token", data.token);
  state.user = decodeTokenPayload(data.token);
  updateAuthUI();
  showToast("Signed in successfully!", "success");
}

async function register(email, username, password) {
  const data = await apiRequest("POST", "/auth/register", { email, username, password });
  showToast("Account created! Please sign in.", "success");
  return data;
}

function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("sf_token");
  updateAuthUI();
  showToast("Signed out.", "info");
}

function decodeTokenPayload(token) {
  try {
    // BUG: no expiry check — expired tokens are still "decoded" successfully
    const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

function restoreSession() {
  const saved = localStorage.getItem("sf_token");
  if (saved) {
    state.token = saved;
    state.user = decodeTokenPayload(saved);
    updateAuthUI();
  }
}

// ─────────────────────────── PRODUCTS ───────────────────────────

async function loadProducts(page = 1) {
  const grid = document.getElementById("product-grid");
  grid.innerHTML = '<div class="loading-spinner"></div>';

  try {
    let url = `/products?page=${page}&page_size=12&sort_by=${state.sortBy}`;
    if (state.selectedCategory) url += `&category=${encodeURIComponent(state.selectedCategory)}`;

    const data = await apiRequest("GET", url);
    state.products = data.products || data;  // handle both response shapes
    state.currentPage = data.page || page;
    state.totalPages = data.total_pages || 1;

    renderProducts(state.products);
    renderPagination();
  } catch (err) {
    grid.innerHTML = '<p class="error-msg">Failed to load products. Please try again.</p>';
  }
}

function renderProducts(products) {
  const grid = document.getElementById("product-grid");

  if (!products.length) {
    grid.innerHTML = '<p class="empty-msg">No products found.</p>';
    return;
  }

  grid.innerHTML = products.map(p => `
    <div class="product-card" data-id="${p.id}">
      <div class="product-image">
        <img src="${p.images && p.images[0] ? p.images[0] : '/placeholder.png'}"
             alt="${escapeHtml(p.name)}" loading="lazy" />
        ${p.discount_percent > 0 ? `<span class="badge badge-sale">${p.discount_percent}% OFF</span>` : ""}
      </div>
      <div class="product-info">
        <h3 class="product-name">${escapeHtml(p.name)}</h3>
        <p class="product-category">${escapeHtml(p.category || "")}</p>
        <div class="product-pricing">
          <span class="price-effective">$${(p.effective_price / 100).toFixed(2)}</span>
          ${p.discount_percent > 0
            ? `<span class="price-original">$${(p.price_cents / 100).toFixed(2)}</span>`
            : ""}
        </div>
        <div class="product-stock ${p.stock > 0 ? "in-stock" : "out-of-stock"}">
          ${p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}
        </div>
      </div>
      <button class="btn btn-primary btn-add-cart"
              onclick="addToCart(${p.id})"
              ${p.stock <= 0 ? "disabled" : ""}>
        Add to Cart
      </button>
    </div>
  `).join("");
}

// ─────────────────────────── CART ───────────────────────────

function addToCart(productId) {
  // BUG: if state.products is empty (e.g. after page reload), find returns undefined
  // and accessing .id on undefined throws — cart silently breaks
  const product = state.products.find(p => p.id === productId);
  const existing = state.cart.find(i => i.product.id === productId);

  if (existing) {
    existing.quantity += 1;
  } else {
    state.cart.push({ product, quantity: 1 });
  }

  updateCartUI();
  showToast(`${product.name} added to cart`, "success");
}

function removeFromCart(productId) {
  state.cart = state.cart.filter(i => i.product.id !== productId);
  updateCartUI();
}

function updateCartUI() {
  const count = state.cart.reduce((sum, i) => sum + i.quantity, 0);
  document.getElementById("cart-count").textContent = count;

  const itemsEl = document.getElementById("cart-items");
  if (!state.cart.length) {
    itemsEl.innerHTML = '<p class="empty-cart">Your cart is empty.</p>';
    document.getElementById("cart-total").textContent = "$0.00";
    return;
  }

  itemsEl.innerHTML = state.cart.map(i => `
    <div class="cart-item">
      <span class="cart-item-name">${escapeHtml(i.product.name)}</span>
      <span class="cart-item-qty">× ${i.quantity}</span>
      <span class="cart-item-price">$${((i.product.effective_price * i.quantity) / 100).toFixed(2)}</span>
      <button onclick="removeFromCart(${i.product.id})" class="btn-remove">✕</button>
    </div>
  `).join("");

  const total = state.cart.reduce((sum, i) => sum + i.product.effective_price * i.quantity, 0);
  document.getElementById("cart-total").textContent = `$${(total / 100).toFixed(2)}`;
}

// ─────────────────────────── CHECKOUT ───────────────────────────

async function placeOrder() {
  const address = {
    street: document.getElementById("ship-street").value,
    city: document.getElementById("ship-city").value,
    zip: document.getElementById("ship-zip").value,
    country: document.getElementById("ship-country").value,
  };

  const paymentMethod = document.querySelector('input[name="payment"]:checked').value;
  const items = state.cart.map(i => ({ product_id: i.product.id, quantity: i.quantity }));

  try {
    const result = await apiRequest("POST", "/orders", { items, shipping_address: address, payment_method: paymentMethod }, true);
    state.cart = [];
    updateCartUI();
    document.getElementById("checkout-modal").hidden = true;
    showToast(`Order #${result.order_id} placed! 🎉`, "success");
  } catch (err) {
    document.getElementById("checkout-error").hidden = false;
    document.getElementById("checkout-error").textContent = err.message;
  }
}

// ─────────────────────────── UI HELPERS ───────────────────────────

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  // BUG: if many toasts fire rapidly, container overflows — no max-toast limit
  setTimeout(() => toast.remove(), 3500);
}

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function updateAuthUI() {
  const btn = document.getElementById("auth-btn");
  btn.textContent = state.user ? "Sign Out" : "Sign In";
}

function renderPagination() {
  const el = document.getElementById("pagination");
  if (state.totalPages <= 1) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <button onclick="loadProducts(${state.currentPage - 1})" ${state.currentPage <= 1 ? "disabled" : ""}>← Prev</button>
    <span>Page ${state.currentPage} of ${state.totalPages}</span>
    <button onclick="loadProducts(${state.currentPage + 1})" ${state.currentPage >= state.totalPages ? "disabled" : ""}>Next →</button>
  `;
}

// ─────────────────────────── INIT ───────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  restoreSession();
  loadProducts();

  document.getElementById("sort-select").addEventListener("change", e => {
    state.sortBy = e.target.value;
    loadProducts(1);
  });

  document.getElementById("auth-btn").addEventListener("click", () => {
    if (state.user) logout();
    else document.getElementById("auth-modal").hidden = false;
  });

  document.getElementById("cart-btn").addEventListener("click", () => {
    document.getElementById("cart-drawer").classList.add("open");
    document.getElementById("cart-overlay").classList.add("visible");
  });

  document.getElementById("close-cart").addEventListener("click", () => {
    document.getElementById("cart-drawer").classList.remove("open");
    document.getElementById("cart-overlay").classList.remove("visible");
  });

  document.getElementById("checkout-btn").addEventListener("click", () => {
    if (!state.token) { showToast("Please sign in to checkout", "error"); return; }
    document.getElementById("checkout-modal").hidden = false;
  });

  document.getElementById("confirm-order-btn").addEventListener("click", placeOrder);
  document.getElementById("cancel-checkout").addEventListener("click", () => {
    document.getElementById("checkout-modal").hidden = true;
  });

  document.getElementById("login-btn").addEventListener("click", async () => {
    try {
      await login(
        document.getElementById("login-email").value,
        document.getElementById("login-password").value
      );
      document.getElementById("auth-modal").hidden = true;
    } catch (err) {
      document.getElementById("auth-error").hidden = false;
      document.getElementById("auth-error").textContent = err.message;
    }
  });
});
