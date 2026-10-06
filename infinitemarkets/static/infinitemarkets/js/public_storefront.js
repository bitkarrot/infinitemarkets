/* public_storefront.js — shared helpers for standalone public docs.
   Vanilla JS only: CSP is script-src 'self', no third-party scripts.
   Everything lives under window.GM; page modules are public_checkout.js
   (product card) and public_order.js (status page). */
(function () {
  "use strict";

  var GM = (window.GM = window.GM || {});
  var wideBrowse = window.matchMedia("(min-width: 900px)");
  document.querySelectorAll(".browse-disclosure").forEach(function (panel) {
    function syncBrowse() { panel.open = wideBrowse.matches; }
    syncBrowse();
    wideBrowse.addEventListener("change", syncBrowse);
  });
  document.querySelectorAll(".browse-price-track").forEach(function (track) {
    var lower = track.querySelector('[name="min_price"]');
    var upper = track.querySelector('[name="max_price"]');
    var minOutput = track.nextElementSibling.querySelector('[data-price-readout="min"]');
    var maxOutput = track.nextElementSibling.querySelector('[data-price-readout="max"]');
    function updatePrice(changed) {
      if (Number(lower.value) > Number(upper.value)) {
        if (changed === lower) upper.value = lower.value;
        else lower.value = upper.value;
      }
      var width = Number(lower.max) - Number(lower.min);
      var start = width ? (Number(lower.value) - Number(lower.min)) / width * 100 : 0;
      var end = width ? (Number(upper.value) - Number(lower.min)) / width * 100 : 100;
      track.style.setProperty("--price-start", start + "%");
      track.style.setProperty("--price-end", end + "%");
      lower.style.zIndex = changed === lower ? "2" : "1";
      upper.style.zIndex = changed === upper ? "2" : "1";
      minOutput.textContent = lower.value + " " + track.dataset.currency;
      maxOutput.textContent = upper.value + " " + track.dataset.currency;
    }
    lower.addEventListener("input", function () { updatePrice(lower); });
    upper.addEventListener("input", function () { updatePrice(upper); });
    updatePrice(lower);
    track.closest("form").addEventListener("submit", function () {
      if (Number(lower.value) === Number(lower.min)) lower.disabled = true;
      if (Number(upper.value) === Number(upper.max)) upper.disabled = true;
    });
  });
  document.querySelectorAll('.browse-filter-form select[name="currency"]').forEach(function (currency) {
    currency.addEventListener("change", function () {
      currency.closest("form").querySelectorAll('.browse-price-track input').forEach(function (input) {
        input.disabled = true;
      });
      currency.closest("form").requestSubmit();
    });
  });

  /* Light/dark scheme toggle — shopper preference, never a merchant
     theme field. No stored choice means the browser's
     prefers-color-scheme wins via the emitted media rule; an explicit
     toggle sets data-scheme (which outranks it) and persists. */
  (function () {
    var KEY = "gm-scheme";
    var root = document.querySelector(".gm-public");
    var btn = document.getElementById("gm-scheme-toggle");
    if (!root || !btn) return;
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    function stored() {
      try {
        var v = localStorage.getItem(KEY);
        return v === "dark" || v === "light" ? v : null;
      } catch (e) { return null; }
    }
    function effective() {
      return root.getAttribute("data-scheme") ||
        (media.matches ? "dark" : "light");
    }
    function render() {
      var dark = effective() === "dark";
      btn.setAttribute("aria-pressed", dark ? "true" : "false");
      btn.setAttribute("aria-label",
        dark ? "Switch to light mode" : "Switch to dark mode");
      var moon = btn.querySelector(".scheme-moon");
      var sun = btn.querySelector(".scheme-sun");
      if (moon) moon.hidden = dark;
      if (sun) sun.hidden = !dark;
    }
    btn.addEventListener("click", function () {
      var next = effective() === "dark" ? "light" : "dark";
      root.setAttribute("data-scheme", next);
      try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
      render();
    });
    media.addEventListener("change", function () {
      if (!root.getAttribute("data-scheme")) render();
    });
    var saved = stored();
    if (saved) root.setAttribute("data-scheme", saved);
    render();
  })();

  /* Embeddable listing — inside an iframe the page broadcasts its
     content height as {type: 'gm-embed-height', height} so a static
     host page can auto-size the frame. '*' is safe: the payload is a
     public page's pixel height only. */
  (function () {
    var embed = document.querySelector(".gm-public[data-embed]");
    if (!embed || window.parent === window) return;
    var post = function () {
      window.parent.postMessage(
        {type: "gm-embed-height",
         height: document.documentElement.scrollHeight},
        "*"
      );
    };
    if (window.ResizeObserver) {
      new ResizeObserver(post).observe(document.body);
    }
    window.addEventListener("load", post);
    post();
  })();

  /* --- DOM helpers (never innerHTML with API values — XSS boundary) ---- */

  GM.h = function (tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "text") el.textContent = attrs[k];
        else if (k === "class") el.className = attrs[k];
        else if (k === "hidden" && attrs[k]) el.hidden = true;
        else if (k.slice(0, 5) === "data-" || k === "role" ||
                 k === "aria-live" || k === "aria-label" || k === "type" ||
                 k === "href" || k === "readonly" || k === "id" ||
                 k === "colspan" || k === "for" || k === "src" ||
                 k === "alt" || k === "referrerpolicy" || k === "loading" ||
                 k === "value" || k === "maxlength" || k === "placeholder" ||
                 k === "autocomplete" || k === "rows" || k === "novalidate" ||
                 k === "aria-expanded" || k === "aria-haspopup" ||
                 k === "aria-current") {
          el.setAttribute(k, attrs[k]);
        }
      });
    }
    (children || []).forEach(function (c) {
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return el;
  };

  GM.clear = function (el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
  };

  /* --- formatters ------------------------------------------------------- */

  GM.sats = function (n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("en-US") + " sats";
  };

  /* Middle-truncate a long reference (order ref, npub) for display. */
  GM.trunc = function (s, head, tail) {
    s = String(s || "");
    head = head || 8;
    tail = tail || 6;
    if (s.length <= head + tail + 3) return s;
    return s.slice(0, head) + "…" + s.slice(-tail);
  };

  /* --- fetch wrapper ----------------------------------------------------- */

  GM.api = function (url, opts) {
    opts = opts || {};
    return fetch(url, {
      method: opts.method || "GET",
      headers: opts.headers || {},
      body: opts.body,
      credentials: "same-origin"
    }).then(function (resp) {
      return resp
        .json()
        .catch(function () {
          return {};
        })
        .then(function (body) {
          return { status: resp.status, body: body };
        });
    });
  };

  /* --- §5.4 token contract -------------------------------------------------
     The bearer token arrives ONLY as a URL fragment. Read it once, strip
     it via history.replaceState, keep it in memory, send it as
     X-Order-Token — never in path/query/links (§5.4/§11.4). */

  var _token = null;
  if (location.hash.length > 1) {
    _token = location.hash.slice(1);
    /* Keep the (public, non-secret) ?shop= context; drop only the
       fragment that carries the bearer token. */
    history.replaceState(null, "", location.pathname + location.search);
  }
  GM.orderToken = function () {
    return _token;
  };
  /* The checkout module hands over a freshly issued token (from the 201
     response) — still memory-only, never written to storage or URLs. */
  GM.setOrderToken = function (t) {
    _token = t;
  };
  GM.statusUrl = function () {
    /* The shareable status link carries the token in its fragment — the
       fragment is never sent to the server by any browser. The shop
       pubkey (public identity) restores the shop's header and nav. */
    var root = document.querySelector(".gm-public[data-shop]");
    var shop = root ? root.getAttribute("data-shop") : "";
    var base = location.origin + "/infinitemarkets/order" +
      (/^[0-9a-f]{64}$/.test(shop || "") ? "?shop=" + shop : "");
    return _token ? base + "#" + _token : base;
  };

  GM.SHIPPING_LABELS = {
    not_required: "No shipping needed",
    pending: "Preparing to ship",
    processing: "Being prepared",
    shipped: "Shipped",
    delivered: "Delivered",
    exception: "Delivery problem — the seller will be in touch"
  };

  /* Merchant digital-delivery content, rendered as text with http(s)
     links made clickable — never innerHTML (merchant-authored text). */
  var URL_RE = /(https?:\/\/[^\s<>"']+)/g;
  function linkified(text) {
    var frag = document.createDocumentFragment();
    String(text).split(URL_RE).forEach(function (part, i) {
      if (i % 2 === 1) {
        var a = GM.h("a", { href: part, text: part });
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
        frag.appendChild(a);
      } else if (part) {
        frag.appendChild(document.createTextNode(part));
      }
    });
    return frag;
  }
  GM.renderDelivery = function (el, list) {
    if (!el) return;
    GM.clear(el);
    list = list || [];
    el.hidden = !list.length;
    if (!list.length) return;
    el.appendChild(GM.h("h2", { class: "delivery-title", text: "Your digital items" }));
    list.forEach(function (entry) {
      var item = GM.h("div", { class: "delivery-item", "data-gm": "delivery-item" });
      item.appendChild(GM.h("strong", { text: entry.title || "Digital item" }));
      var body = GM.h("p", { class: "delivery-text" });
      body.appendChild(linkified(entry.content || ""));
      item.appendChild(body);
      var only = String(entry.content || "").trim();
      if (/^https?:\/\/\S+$/.test(only)) {
        var dl = GM.h("a", { class: "btn-primary", href: only, text: "Download" });
        dl.setAttribute("target", "_blank");
        dl.setAttribute("rel", "noopener noreferrer");
        item.appendChild(dl);
      }
      el.appendChild(item);
    });
    el.appendChild(GM.h("p", {
      class: "delivery-note",
      text: "Keep your order link — you can come back here any time to access this again."
    }));
  };

  /* --- buyer-facing labels + RFC 9457 -> friendly copy (copywriting
         contract — verbatim strings) ------------------------------------- */

  GM.STATE_LABELS = {
    received: "Order received",
    invoice_pending: "Creating invoice",
    awaiting_payment: "Waiting for payment",
    confirmed: "Payment confirmed",
    processing: "Preparing your order",
    completed: "Complete",
    cancelled: "This order is no longer active",
    rejected: "This order is no longer active",
    expired: "This order is no longer active"
  };

  GM.ERROR_COPY = {
    "insufficient-stock":
      "Not enough stock available — reduce quantity or choose another item.",
    "order-expired":
      "Invoice expired. If you already paid, do not pay again;" +
      " contact the merchant. Wait for status verification before" +
      " starting a new checkout.",
    "rate-limited": "Too many requests — wait a minute and try again.",
    "invalid-shipping-destination":
      "This item cannot be shipped to the selected destination.",
    "quote-changed": "The total changed — review the updated price before paying."
  };

  GM.problemCopy = function (body) {
    /* body is an RFC 9457 problem document (urn:infinitemarkets:<code>). */
    var code = "";
    if (body && typeof body.type === "string") {
      code = body.type.replace("urn:infinitemarkets:", "");
    }
    return (
      GM.ERROR_COPY[code] ||
      (body && (body.detail || body.title)) ||
      "Checkout could not be started."
    );
  };

  /* Terminal order states — polling stops here (§5.4). */
  GM.TERMINAL = {
    confirmed: false, // confirmed still allows forward progress display
    processing: false,
    completed: true,
    cancelled: true,
    rejected: true,
    expired: true
  };
  GM.isTerminal = function (state) {
    return GM.TERMINAL[state] === true;
  };

  /* ISO 3166-1 alpha-2 country list for the checkout country select. */
  GM.COUNTRIES = [
    ["US", "United States"], ["CA", "Canada"], ["MX", "Mexico"],
    ["BR", "Brazil"], ["AR", "Argentina"], ["CL", "Chile"], ["CO", "Colombia"],
    ["GB", "United Kingdom"], ["IE", "Ireland"], ["FR", "France"],
    ["DE", "Germany"], ["NL", "Netherlands"], ["BE", "Belgium"],
    ["ES", "Spain"], ["PT", "Portugal"], ["IT", "Italy"], ["AT", "Austria"],
    ["CH", "Switzerland"], ["SE", "Sweden"], ["NO", "Norway"],
    ["DK", "Denmark"], ["FI", "Finland"], ["PL", "Poland"], ["CZ", "Czechia"],
    ["GR", "Greece"], ["HU", "Hungary"], ["RO", "Romania"],
    ["UA", "Ukraine"], ["TR", "Türkiye"], ["IL", "Israel"],
    ["AU", "Australia"], ["NZ", "New Zealand"], ["JP", "Japan"],
    ["KR", "South Korea"], ["SG", "Singapore"], ["HK", "Hong Kong"],
    ["TW", "Taiwan"], ["IN", "India"], ["TH", "Thailand"], ["VN", "Vietnam"],
    ["PH", "Philippines"], ["ID", "Indonesia"], ["MY", "Malaysia"],
    ["ZA", "South Africa"], ["NG", "Nigeria"], ["KE", "Kenya"],
    ["EG", "Egypt"], ["MA", "Morocco"], ["AE", "United Arab Emirates"],
    ["SA", "Saudi Arabia"], ["IS", "Iceland"], ["LU", "Luxembourg"],
    ["EE", "Estonia"], ["LV", "Latvia"], ["LT", "Lithuania"],
    ["SK", "Slovakia"], ["SI", "Slovenia"], ["HR", "Croatia"],
    ["BG", "Bulgaria"], ["PE", "Peru"], ["UY", "Uruguay"], ["CR", "Costa Rica"],
    ["PA", "Panama"], ["DO", "Dominican Republic"], ["EC", "Ecuador"]
  ];

  /* Gallery thumbs swap the main product image (sketch 001 editorial
     gallery). Delegated listener — no inline handlers, CSP-safe. */
  document.addEventListener("click", function (ev) {
    var thumb =
      ev.target && ev.target.closest
        ? ev.target.closest(".thumb[data-gallery-src]")
        : null;
    if (!thumb) return;
    var main = document.getElementById("gm-gallery-main");
    if (main) main.src = thumb.getAttribute("data-gallery-src");
    document.querySelectorAll(".thumb").forEach(function (el) {
      el.classList.toggle("active", el === thumb);
      el.setAttribute("aria-pressed", el === thumb ? "true" : "false");
    });
  });

  /* Render a Lightning invoice QR into el using the host-vendored
     vue-qrcode build (same-origin vendor script — no third-party code).
     Vue.render mounts a standalone vnode; no app instance needed. */
  GM.renderQr = function (el, value) {
    if (!window.Vue || !window.QrcodeVue || !el) return;
    var comp = window.QrcodeVue.default || window.QrcodeVue;
    window.Vue.render(
      window.Vue.h(comp, {
        value: value,
        size: 216,
        level: "M",
        renderAs: "svg",
        margin: 2
      }),
      el
    );
  };
})();
