/* public_checkout.js — A2 adaptive checkout (sketch 001-D Adaptive Blend).

   The checkout card is embedded in the A1 product document (there is no
   standalone checkout route in §5.4). Layout presets are merchant-chosen
   (editorial | guided | compact | gallery via data-layout); ≤560px forces compact.
   The field set, summary, validation, payment states, and security copy
   are invariant across presets and themes. */
(function () {
  "use strict";

  var GM = window.GM;
  var form = document.getElementById("gm-checkout");
  var card = document.getElementById("gm-checkout-card");
  if (!form || !card || !GM) return;

  var STATUS_API = "/infinitemarkets/api/v1/public/order-status";

  /* --- layout ------------------------------------------------------------
     Merchant preset drives desktop presentation; ≤560px always compacts
     (responsive safety overrides the preference — never a squeezed
     desktop layout on mobile). */
  var mqNarrow = window.matchMedia
    ? window.matchMedia("(max-width: 560px)")
    : { matches: false };
  function effectiveLayout() {
    var preset = card.getAttribute("data-layout") || "editorial";
    /* "gallery" is a visual language (CSS-only) on top of the editorial
       flow — checkout behaviour is identical to editorial. */
    if (preset === "gallery") preset = "editorial";
    return mqNarrow.matches ? "compact" : preset;
  }

  /* --- guided stepper (Product → Delivery → Pay) ------------------------- */
  var step = 1;
  var lastMode = null;

  function syncVisibility() {
    var mode = effectiveLayout();
    card.querySelectorAll(".co-section").forEach(function (sec) {
      var body = sec.querySelector(".co-section-body");
      var n = Number(sec.getAttribute("data-step") || "0");
      if (!body) return;
      if (mode === "guided") {
        /* Sketch 001-B: exactly one step panel at a time — step 3 (Pay)
           shows only the persistent summary + submit. */
        body.hidden = n !== step;
      } else if (mode === "compact") {
        body.hidden = sec.getAttribute("data-open") !== "true";
      } else {
        body.hidden = false;
      }
    });
    var payBack = card.querySelector("[data-pay-back]");
    if (payBack) payBack.hidden = !(mode === "guided" && step === 3);
    /* Guided: the invoice CTA belongs to the Pay step only (sketch
       001-B); the summary itself stays visible at every step. */
    var payRow = card.querySelector(".pay-row");
    if (payRow) payRow.hidden = mode === "guided" && step !== 3;
    var payIntro = card.querySelector("[data-pay-intro]");
    if (payIntro) payIntro.hidden = !(mode === "guided" && step === 3);
    card.querySelectorAll(".progress-step").forEach(function (el) {
      el.classList.toggle(
        "active",
        Number(el.getAttribute("data-step")) === step
      );
      el.classList.toggle(
        "done",
        Number(el.getAttribute("data-step")) < step
      );
    });
  }

  /* Editorial desktop keeps the title/price/checkout column in view while
     the gallery and description scroll — only when the whole column fits
     the viewport, so a tall physical-delivery form never hides its CTA. */
  var layoutEl = card.closest(".product-layout");
  var detailEl = card.closest(".product-detail");
  function syncSticky() {
    if (!layoutEl || !detailEl) return;
    layoutEl.classList.toggle(
      "is-sticky",
      effectiveLayout() === "editorial" && window.innerWidth > 860 &&
        detailEl.offsetHeight < window.innerHeight - 104
    );
  }
  window.addEventListener("resize", syncSticky);
  if (window.ResizeObserver && detailEl) {
    new window.ResizeObserver(syncSticky).observe(detailEl);
  }

  function applyLayout() {
    var mode = effectiveLayout();
    card.setAttribute("data-mode", mode);
    /* The preset recomposes the WHOLE page shell, not just the card —
       guided = focused step flow, compact = narrow express sheet
       (sketch 001-B/C). */
    if (layoutEl) layoutEl.setAttribute("data-mode", mode);
    var progress = card.querySelector(".progress");
    if (progress) progress.hidden = mode !== "guided";
    card.querySelectorAll(".co-section").forEach(function (sec) {
      var head = sec.querySelector(".co-section-head");
      if (head) head.hidden = mode !== "compact";
    });
    if (mode !== lastMode) {
      if (mode === "compact") {
        /* Progressive disclosure (sketch 001-C): the first section open,
           later ones collapsed behind their disclosure heads. */
        var first = true;
        card.querySelectorAll(".co-section").forEach(function (sec) {
          sec.setAttribute("data-open", first ? "true" : "false");
          var head = sec.querySelector(".co-section-head");
          if (head) {
            head.setAttribute(
              "aria-expanded", first ? "true" : "false"
            );
          }
          first = false;
        });
      }
      if (mode === "guided") step = 1;
      lastMode = mode;
    }
    syncVisibility();
    syncSticky();
  }
  if (mqNarrow.addEventListener) {
    mqNarrow.addEventListener("change", applyLayout);
  }

  /* Compact disclosure: section heads toggle their bodies open. */
  card.querySelectorAll(".co-section-head").forEach(function (head) {
    head.addEventListener("click", function () {
      var sec = head.parentElement;
      var open = sec.getAttribute("data-open") === "true";
      sec.setAttribute("data-open", open ? "false" : "true");
      head.setAttribute("aria-expanded", open ? "false" : "true");
      syncVisibility();
    });
  });

  /* --- country select ----------------------------------------------------- */
  var countrySel = form.querySelector("select[name=country]");
  if (countrySel && countrySel.options.length <= 1) {
    GM.COUNTRIES.forEach(function (c) {
      countrySel.appendChild(GM.h("option", { text: c[1] }));
      countrySel.lastChild.value = c[0];
    });
  }

  /* --- inline validation (aria-live, contract copy) ---------------------- */
  function fieldError(name, msg) {
    var err = form.querySelector('[data-error-for="' + name + '"]');
    if (!err) return;
    if (msg) {
      err.textContent = msg;
      err.hidden = false;
    } else {
      err.textContent = "";
      err.hidden = true;
    }
  }

  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  var emailInput = form.querySelector("input[name=email]");
  var emailOptIn = form.querySelector("input[name=email_opt_in]");
  function syncEmailOptIn() {
    if (!emailOptIn) return;
    var email = emailInput ? emailInput.value.trim() : "";
    var enabled = EMAIL_RE.test(email);
    if (!enabled) emailOptIn.checked = false;
    emailOptIn.disabled = !enabled;
    if (!email) fieldError("email", "");
  }
  if (emailInput) emailInput.addEventListener("input", syncEmailOptIn);
  window.addEventListener("pageshow", syncEmailOptIn);
  window.setTimeout(syncEmailOptIn, 0);
  syncEmailOptIn();

  /* --- quantity stepper (sketch 001 −/+ control) ------------------------- */
  var qtyInput = form.querySelector("input[name=quantity]");
  var qtyButtons = form.querySelectorAll("[data-qty-step]");
  function qtyMax() {
    return Math.min(10000, Number(qtyInput && qtyInput.max) || 10000);
  }
  function syncQtyButtons() {
    var q = currentQty();
    qtyButtons.forEach(function (btn) {
      var dir = Number(btn.getAttribute("data-qty-step"));
      btn.disabled = !qtyInput || qtyInput.disabled ||
        (dir < 0 ? q <= 1 : q >= qtyMax());
    });
  }
  qtyButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!qtyInput || qtyInput.disabled) return;
      var next = Math.min(qtyMax(), Math.max(1,
        currentQty() + Number(btn.getAttribute("data-qty-step"))));
      if (next === currentQty()) return;
      qtyInput.value = String(next);
      qtyInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  /* --- order summary (persistent Items/Shipping/Total) ------------------- */
  var summaryEl = card.querySelector(".summary");
  var summaryItems = card.querySelector('[data-sum="items"]');
  var summaryShipping = card.querySelector('[data-sum="shipping"]');
  var summaryTotal = card.querySelector('[data-sum="total"]');
  var summaryQty = card.querySelector("[data-sum-qty]");
  var summaryHint = card.querySelector("[data-sum-hint]");
  var refreshQuote = card.querySelector("[data-refresh-quote]");
  var hintCopy = summaryHint ? summaryHint.textContent : "";
  function setBusy(on) {
    if (summaryEl) summaryEl.setAttribute("aria-busy", on ? "true" : "false");
  }
  /* Quote problems read as a message under the summary, never as the
     Total value itself. */
  function showHint(text, isError) {
    if (!summaryHint) return;
    summaryHint.textContent = text || hintCopy;
    summaryHint.classList.toggle("is-error", !!isError);
    summaryHint.hidden = false;
  }
  function hideHint() {
    if (summaryHint) summaryHint.hidden = true;
  }
  var quote = null;
  var quoteVersion = 0;
  var quoteTimer = null;
  var lastQuotePayload = null;
  var QUOTE_API = "/infinitemarkets/api/v1/public/quote";

  /* Region is optional ISO 3166-2 (spec §8.1): omit it when blank and
     accept the short subdivision code a buyer naturally types ("IL" with
     country US → "US-IL"). */
  var REGION_COPY = "Use the state or region code, e.g. CA.";
  function regionFor(country) {
    var raw = val("region").toUpperCase().replace(/\s+/g, "");
    if (!raw) return null;
    return raw.indexOf("-") < 0 && country ? country + "-" + raw : raw;
  }
  function regionOk(country, region) {
    return !region || (/^[A-Z]{2}-[A-Z0-9]{1,3}$/.test(region) &&
      region.indexOf(country + "-") === 0);
  }
  function currentQty() {
    var q = Number((form.querySelector("input[name=quantity]") || {}).value || "0");
    return Number.isInteger(q) ? q : 0;
  }
  function quotePayload() {
    var chosen = form.querySelector("input[name=variation]:checked");
    if (form.querySelectorAll("input[name=variation]").length && !chosen) return null;
    var qty = currentQty();
    if (qty < 1 || qty > 10000) return null;
    var payload = {
      merchant_pubkey: form.getAttribute("data-merchant"),
      items: [{d_tag: chosen ? chosen.value : form.getAttribute("data-d-tag"), quantity: qty}]
    };
    if (form.getAttribute("data-physical") === "true") {
      var country = countrySel ? countrySel.value : "";
      var shipping = form.querySelector("select[name=shipping_option]");
      var region = regionFor(country);
      var badRegion = !!country && !regionOk(country, region);
      fieldError("region", badRegion ? REGION_COPY : "");
      if (!country || !shipping || !shipping.value || badRegion) return null;
      payload.shipping_option_d = shipping.value;
      payload.address = {country: country};
      if (region) payload.address.region = region;
    }
    return payload;
  }
  /* The header price is server-rendered for the parent product — when a
     variation is picked it must re-render for the chosen option or the
     buyer reads the wrong amount. */
  function syncVariationPrice() {
    var priceEl = document.querySelector(".product-price .amount");
    if (!priceEl) return;
    var chosen = form.querySelector("input[name=variation]:checked");
    if (!chosen) return;
    var minor = Number(chosen.getAttribute("data-price"));
    if (!Number.isSafeInteger(minor)) return;
    priceEl.textContent = GM.price(
      minor,
      chosen.getAttribute("data-currency"),
      chosen.getAttribute("data-decimals")
    );
    priceEl.setAttribute("data-minor", String(minor));
  }
  function updateSummary(ev) {
    if (ev && ["quantity", "variation", "country", "region", "shipping_option"]
        .indexOf(ev.target.name) < 0) return;
    if (ev && ev.target.name === "variation") syncVariationPrice();
    if (pendingPayload) return;
    syncQtyButtons();
    var qty = currentQty();
    if (summaryQty) summaryQty.textContent = qty > 0 ? "× " + qty : "";
    var payload = quotePayload();
    var signature = payload ? JSON.stringify(payload) : null;
    if (ev && signature === lastQuotePayload) return;
    lastQuotePayload = signature;
    var version = ++quoteVersion;
    clearTimeout(quoteTimer);
    quote = null;
    var physical = form.getAttribute("data-physical") === "true";
    if (refreshQuote) refreshQuote.hidden = true;
    if (submitButton) submitButton.disabled = true;
    if (summaryItems) summaryItems.textContent = "—";
    if (summaryShipping) summaryShipping.textContent =
      physical ? "Choose delivery" : "0 sats";
    if (summaryTotal) summaryTotal.textContent = payload ? "Calculating…" : "—";
    if (physical && !payload && qty > 0) showHint(); else hideHint();
    setBusy(!!payload);
    if (!payload) {
      if (submitButton) submitButton.disabled = false;
      return;
    }
    quoteTimer = setTimeout(function () {
      GM.api(QUOTE_API, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      }).then(function (r) {
        if (version !== quoteVersion || pendingPayload) return;
        setBusy(false);
        if (r.status !== 200 || !Number.isSafeInteger(r.body.total_sat)) {
          if (summaryTotal) summaryTotal.textContent = "—";
          showHint(GM.problemCopy(r.body), true);
          if (refreshQuote) refreshQuote.hidden = false;
          return;
        }
        quote = r.body;
        if (summaryItems) summaryItems.textContent = GM.sats(quote.subtotal_sat);
        if (summaryShipping) summaryShipping.textContent = GM.sats(quote.shipping_sat);
        if (summaryTotal) summaryTotal.textContent = GM.sats(quote.total_sat);
        if (submitButton) submitButton.disabled = false;
      }).catch(function () {
        if (version === quoteVersion && summaryTotal) {
          setBusy(false);
          summaryTotal.textContent = "—";
          showHint("Price unavailable — try again shortly.", true);
          if (refreshQuote) refreshQuote.hidden = false;
        }
      });
    }, 120);
  }
  if (refreshQuote) refreshQuote.addEventListener("click", function () { updateSummary(); });
  form.addEventListener("change", updateSummary);
  form.addEventListener("input", updateSummary);

  /* --- invoice state machine ----------------------------------------------
     creating (skeleton, no QR) → awaiting_payment → confirmed |
     expired | creation_unknown | cancelled — never a second invoice
     after uncertainty (§8.2). */
  var panel = document.getElementById("gm-invoice-panel");
  var pollTimer = null;
  var token = null; // in-memory only — never in path/query/links
  var countdownTimer = null;

  function pill(label, kind) {
    return GM.h("span", { class: "pill pill-" + kind, text: label });
  }

  /* Copy with visible feedback that resets, and a select-the-text
     fallback when the Clipboard API is unavailable or refused. */
  function copyButton(label, getText, fallbackEl) {
    var btn = GM.h("button", { type: "button", class: "btn-secondary", text: label });
    var reset = null;
    function fallback() {
      if (fallbackEl && fallbackEl.select) fallbackEl.select();
    }
    btn.addEventListener("click", function () {
      var text = getText();
      if (!text) return;
      if (!navigator.clipboard) return fallback();
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copied";
        clearTimeout(reset);
        reset = setTimeout(function () { btn.textContent = label; }, 2000);
      }, fallback);
    });
    return btn;
  }

  function statusLinkBlock() {
    return GM.h("div", { class: "invoice-actions" }, [
      copyButton("Copy status link", function () { return GM.statusUrl(); }),
      GM.h("p", {
        class: "invoice-help",
        text: "Save this private link to check your order later."
      })
    ]);
  }

  /* Keep the invoice in view when the form collapses (mobile users are
     usually scrolled down to the pay button). */
  function revealPanel() {
    if (!card.getBoundingClientRect || card.getBoundingClientRect().top >= 80) return;
    var reduce = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }

  var shownBolt11 = null;

  function renderCreating() {
    if (!panel) return;
    GM.clear(panel);
    shownBolt11 = null;
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "creating");
    panel.appendChild(
      GM.h("div", { class: "invoice-skeleton", "aria-live": "polite" }, [
        GM.h("div", { class: "skel skel-qr" }),
        GM.h("div", { class: "skel skel-line" }),
        GM.h("div", { class: "skel skel-line short" }),
        GM.h("p", { class: "invoice-note", text: "Creating your invoice…" })
      ])
    );
    revealPanel();
  }

  function renderAwaiting(bolt11, expiresAt, totalSat) {
    if (!panel) return;
    /* Polls re-deliver the same invoice every 5s — don't rebuild the QR,
       reset copy feedback, or drop a text selection mid-copy. */
    if (panel.getAttribute("data-invoice-state") === "awaiting_payment" &&
        shownBolt11 === bolt11) return;
    GM.clear(panel);
    shownBolt11 = bolt11;
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "awaiting_payment");
    var wrap = GM.h("div", { class: "invoice-view" });
    wrap.appendChild(pill("Waiting for payment", "waiting"));
    wrap.appendChild(GM.h("h3", { class: "invoice-title", text: "Scan or open in your wallet" }));
    if (totalSat !== null && totalSat !== undefined) {
      wrap.appendChild(
        GM.h("p", { class: "invoice-amount", text: GM.sats(totalSat) })
      );
    }
    var countdown = GM.h("p", {
      class: "invoice-countdown",
      "aria-live": "polite"
    });
    wrap.appendChild(countdown);
    var qr = GM.h("div", { class: "invoice-qr" });
    wrap.appendChild(qr);
    var ta = GM.h("textarea", {
      class: "bolt11",
      readonly: "",
      "aria-label": "Lightning invoice"
    });
    ta.rows = 2;
    ta.value = bolt11 || "";
    wrap.appendChild(
      GM.h("div", { class: "invoice-actions" }, [
        GM.h("a", {
          class: "btn-primary btn-pay",
          href: "lightning:" + (bolt11 || ""),
          text: "Open in wallet"
        }),
        GM.h("div", { class: "invoice-string" }, [
          ta,
          copyButton("Copy invoice", function () { return bolt11; }, ta)
        ])
      ])
    );
    wrap.appendChild(statusLinkBlock());
    wrap.appendChild(
      GM.h("p", {
        class: "invoice-security",
        text:
          "Invoice is correlated to this order only. Creating it does" +
          " not mark the order paid."
      })
    );
    panel.appendChild(wrap);
    GM.renderQr(qr, "lightning:" + (bolt11 || ""));
    startCountdown(countdown, expiresAt);
    revealPanel();
  }

  function startCountdown(el, expiresAt) {
    if (countdownTimer) clearInterval(countdownTimer);
    function tick() {
      var left = Math.max(0, Number(expiresAt || 0) - Date.now() / 1000);
      var m = Math.floor(left / 60);
      var s = Math.floor(left % 60);
      el.textContent =
        "Expires in " + m + ":" + (s < 10 ? "0" : "") + s;
      if (left <= 0 && countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  var shownConfirmed = null;
  function renderConfirmed(body) {
    if (!panel) return;
    /* Polling continues through processing — don't rebuild an identical
       view (it would reset copy feedback every 5s). */
    var key = body.state + "|" + JSON.stringify(body.digital_delivery || []);
    if (panel.getAttribute("data-invoice-state") === "confirmed" &&
        shownConfirmed === key) return;
    shownConfirmed = key;
    GM.clear(panel);
    shownBolt11 = null;
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "confirmed");
    var wrap = GM.h("div", { class: "invoice-view" });
    wrap.appendChild(
      pill(
        GM.STATE_LABELS[body.state] || "Payment confirmed",
        "success"
      )
    );
    wrap.appendChild(GM.h("h3", { class: "invoice-title", text: "Thank you for your order" }));
    wrap.appendChild(
      GM.h("p", {
        class: "invoice-amount",
        text: GM.sats(body.total_sat)
      })
    );
    if (body.items && body.items.length) {
      var ul = GM.h("ul", { class: "order-items" });
      body.items.forEach(function (i) {
        ul.appendChild(
          GM.h("li", {
            text: i.title + " ×" + i.quantity + " — " +
              GM.sats(i.line_total_sat)
          })
        );
      });
      wrap.appendChild(ul);
    }
    var delivery = GM.h("div", { class: "order-delivery" });
    GM.renderDelivery(delivery, body.digital_delivery);
    wrap.appendChild(delivery);
    wrap.appendChild(statusLinkBlock());
    panel.appendChild(wrap);
  }

  function renderExpired() {
    if (!panel) return;
    GM.clear(panel);
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "expired");
    var wrap = GM.h("div", { class: "invoice-view" });
    wrap.appendChild(pill("This order is no longer active", "muted"));
    wrap.appendChild(
      GM.h("p", {
        class: "invoice-note",
        text:
          "Invoice expired. If you already paid, do not pay again;" +
          " contact the merchant. Wait for status verification before" +
          " starting a new checkout."
      })
    );
    var review = GM.h("button", {
      type: "button",
      class: "btn-secondary",
      text: "Review order again"
    });
    review.addEventListener("click", function () {
      panel.hidden = true;
      form.hidden = false;
      token = null;
    });
    wrap.appendChild(review);
    panel.appendChild(wrap);
  }

  function renderUncertain() {
    /* §8.2: invoice creation outcome unknown — NEVER offer a second
       invoice or a "pay again" affordance. The status poll is the only
       recovery path. */
    if (!panel) return;
    GM.clear(panel);
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "creation_unknown");
    var wrap = GM.h("div", { class: "invoice-view" });
    wrap.appendChild(
      pill("On hold — the merchant is reviewing a payment issue.", "warn")
    );
    wrap.appendChild(
      GM.h("p", {
        class: "invoice-note",
        text:
          "Payment status is being verified with the payment provider." +
          " An invoice may already have been created — do not pay a second" +
          " invoice."
      })
    );
    panel.appendChild(wrap);
  }

  function renderCancelled() {
    if (!panel) return;
    GM.clear(panel);
    panel.hidden = false;
    panel.setAttribute("data-invoice-state", "cancelled");
    var wrap = GM.h("div", { class: "invoice-view" });
    wrap.appendChild(pill("This order is no longer active", "muted"));
    panel.appendChild(wrap);
  }

  /* --- status polling (5s, X-Order-Token, stop at terminal) --------------- */
  function pollStatus() {
    if (!token) return;
    GM.api(STATUS_API, { headers: { "X-Order-Token": token } })
      .then(function (r) {
        if (r.status !== 200) return;
        var body = r.body;
        if (body.payment_exception || body.payment_status === "creation_unknown") {
          renderUncertain();
        } else if (body.state === "awaiting_payment" && body.bolt11) {
          renderAwaiting(body.bolt11, body.expires_at, body.total_sat);
        } else if (
          body.state === "confirmed" ||
          body.state === "processing" ||
          body.state === "completed"
        ) {
          renderConfirmed(body);
        } else if (body.state === "expired") {
          renderExpired();
        } else if (body.state === "cancelled" || body.state === "rejected") {
          renderCancelled();
        }
        if (!GM.isTerminal(body.state)) {
          pollTimer = setTimeout(pollStatus, 5000);
        }
      })
      .catch(function () {
        pollTimer = setTimeout(pollStatus, 5000);
      });
  }

  function beginOrder(publicToken, order) {
    token = publicToken; /* memory only — §5.4 */
    GM.setOrderToken(publicToken);
    form.hidden = true;
    if (order && order.state === "awaiting_payment" && order.bolt11) {
      renderAwaiting(order.bolt11, order.expires_at, order.total_sat);
    } else {
      renderCreating();
    }
    pollTimer = setTimeout(pollStatus, 5000);
  }

  /* --- submit --------------------------------------------------------------
     Idempotency-Key: generated once per checkout session from ≥128
     random bits, [A-Za-z0-9_-]{32,128}, REUSED on every retry — a 409
     replay renders the existing order rather than creating a second. */
  var idempotencyKey = null;
  function checkoutKey() {
    if (!idempotencyKey) {
      var buf = new Uint8Array(32); // 256 bits ≥ 128 required
      crypto.getRandomValues(buf);
      idempotencyKey = btoa(String.fromCharCode.apply(null, buf))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");
    }
    return idempotencyKey;
  }

  var errorEl = form.querySelector(".form-error");
  var varError = document.querySelector(".variation-error");
  var submitButton = form.querySelector("button[type=submit]");
  var pendingPayload = null;
  var retryUncertain = false;
  var lockedFields = null;
  function lockFields(locked) {
    if (locked && !lockedFields) {
      lockedFields = Array.from(form.querySelectorAll("input, select"))
        .map(function (el) { return {el: el, disabled: el.disabled}; });
      lockedFields.forEach(function (field) { field.el.disabled = true; });
    } else if (!locked && lockedFields) {
      lockedFields.forEach(function (field) { field.el.disabled = field.disabled; });
      lockedFields = null;
    }
    syncQtyButtons();
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (errorEl) errorEl.hidden = true;
    if (varError) varError.hidden = true;

    var dTag = form.getAttribute("data-d-tag");
    var chosen = form.querySelector("input[name=variation]:checked");
    if (form.querySelectorAll("input[name=variation]").length) {
      if (!chosen) {
        if (varError) varError.hidden = false;
        return;
      }
      dTag = chosen.value;
    }

    var qty = currentQty();
    if (!(qty >= 1 && qty <= 10000)) {
      fieldError("quantity", "Enter a valid quantity.");
      return;
    }

    var physical = form.getAttribute("data-physical") === "true";
    var payload = {
      merchant_pubkey: form.getAttribute("data-merchant"),
      items: [{ d_tag: dTag, quantity: qty }]
    };
    if (physical) {
      var country = countrySel ? countrySel.value : "";
      if (!country) {
        fieldError("country", "Choose a shipping option for this destination.");
        return;
      }
      var shipSel = form.querySelector("select[name=shipping_option]");
      if (!shipSel || !shipSel.value) {
        fieldError(
          "shipping_option",
          "Choose a shipping option for this destination."
        );
        return;
      }
      payload.shipping_option_d = shipSel.value;
      payload.address = {
        country: country,
        line1: val("line1"),
        city: val("city"),
        postal_code: val("postal_code")
      };
      var region = regionFor(country);
      if (!regionOk(country, region)) {
        fieldError("region", REGION_COPY);
        return;
      }
      if (region) payload.address.region = region;
    }
    var email = val("email");
    var wantsEmail = !!(emailOptIn && emailOptIn.checked);
    if (wantsEmail && !email) {
      /* consent-without-email — contract copy */
      fieldError(
        "email",
        "Enter an email to receive order updates, or turn updates off."
      );
      return;
    }
    if (email && !EMAIL_RE.test(email)) {
      fieldError("email", "Enter a valid email for order updates.");
      return;
    }
    if (email) payload.email = email;
    payload.email_opt_in = wantsEmail;

    if (!pendingPayload) {
      if (!quote) {
        if (errorEl) {
          errorEl.textContent = "Wait for the current total before paying.";
          errorEl.hidden = false;
        }
        return;
      }
      payload.expected_total_sat = quote.total_sat;
      pendingPayload = JSON.stringify(payload);
    }
    lockFields(true);
    if (submitButton) submitButton.disabled = true;
    renderCreating();

    GM.api(form.getAttribute("data-endpoint"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": checkoutKey()
      },
      body: pendingPayload
    })
      .then(function (r) {
        /* 201 and 409 replay both carry {public_token, order} — the
           replay renders the existing order, never a duplicate. */
        if (
          (r.status === 201 || r.status === 200) &&
          r.body.public_token
        ) {
          beginOrder(r.body.public_token, r.body.order);
          return;
        }
        if (r.status === 409 && r.body.public_token) {
          beginOrder(r.body.public_token, r.body.order);
          return;
        }
        if (panel) panel.hidden = true;
        form.hidden = false;
        if (r.status === 422 && !retryUncertain) {
          pendingPayload = null;
          idempotencyKey = null;
          lockFields(false);
          updateSummary();
        } else {
          retryUncertain = true;
        }
        if (errorEl) {
          errorEl.textContent = GM.problemCopy(r.body);
          errorEl.hidden = false;
        }
        if (submitButton && pendingPayload) submitButton.disabled = false;
      })
      .catch(function () {
        retryUncertain = true;
        if (panel) panel.hidden = true;
        form.hidden = false;
        if (errorEl) {
          errorEl.textContent = "Network error — retry this same checkout.";
          errorEl.hidden = false;
        }
        if (submitButton) submitButton.disabled = false;
      });
  });

  function val(name) {
    var el = form.querySelector("[name=" + name + "]");
    return el ? el.value.trim() : "";
  }

  /* Guided step CTAs — "Continue to delivery" precedes "Review payment". */
  card.querySelectorAll("[data-goto-step]").forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      step = Number(btn.getAttribute("data-goto-step"));
      syncVisibility();
    });
  });

  applyLayout();
  updateSummary();
})();
