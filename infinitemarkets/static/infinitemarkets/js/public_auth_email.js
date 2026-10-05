/* public_auth_email.js — §5.4 email magic-link landing.

   The sign-in token travels ONLY in the URL fragment. This module NEVER
   reads location.hash: public_storefront.js (deferred before {% block
   scripts %}) already captured the fragment into GM.orderToken() and
   stripped it via history.replaceState. The token is POSTed to
   /nostr/email/verify in the JSON body — never a GET-with-token route,
   never a query param.

   Self-contained on purpose: public_nostr.js is IIFE-private and its
   script tag is nostr_signin-gated (absent when a stale link lands on a
   shop with sign-in chrome off), so local api()/shopQuery() mirrors are
   defined here verbatim from that module. All DOM builds go through
   GM.h — no innerHTML. */
(function () {
  "use strict";

  var GM = window.GM || {};
  var API = "/infinitemarkets/api/v1/public";
  var root = document.getElementById("gm-email-auth-card");
  if (!root || !GM.h || !GM.orderToken) return;

  function shopQuery() {
    var el = document.querySelector(".gm-public[data-shop]");
    var shop = el ? el.getAttribute("data-shop") : "";
    return /^[0-9a-f]{64}$/.test(shop || "") ? "?shop=" + shop : "";
  }

  function api(url, opts) {
    opts = opts || {};
    var headers = opts.headers || {};
    if (opts.method && opts.method !== "GET") {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
      headers["Origin"] = location.origin;
    }
    return GM.api(API + url, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body
    });
  }

  function show(hook, title, detail) {
    GM.clear(root);
    var card = GM.h("div", { "data-gm": hook });
    card.appendChild(GM.h("p", { class: "order-state", text: title }));
    if (detail) {
      card.appendChild(GM.h("p", { class: "nostr-note", text: detail }));
    }
    root.appendChild(card);
    return card;
  }

  function deadLink() {
    show(
      "email-auth-error",
      "This sign-in link is no longer valid.",
      "Request a fresh sign-in link from the shop."
    );
  }

  var token = GM.orderToken();
  if (!token) {
    deadLink();
    return;
  }

  api("/nostr/email/verify" + shopQuery(), {
    method: "POST",
    body: JSON.stringify({ token: token })
  }).then(function (res) {
    var body = res.body || {};
    if (res.status === 200 && body.signed_in) {
      try {
        sessionStorage.setItem(
          "gm_bound_orders", String(body.bound_orders || 0)
        );
      } catch (e) {
        /* sessionStorage unavailable — the orders page still works. */
      }
      var dest = (body.redirect || "/infinitemarkets/orders") + shopQuery();
      location.replace(dest);
      return;
    }
    if (res.status === 200 && body.linked) {
      var card = show(
        "email-auth-linked",
        "Identity linked.",
        "Your email is now attached to this account."
      );
      card.appendChild(
        GM.h("a", {
          class: "btn-primary",
          href: (body.redirect || "/infinitemarkets/profile") + shopQuery(),
          text: "Continue"
        })
      );
      return;
    }
    if (res.status === 409) {
      show(
        "email-auth-conflict",
        "This identity is already attached to a different sign-in.",
        GM.problemCopy ? GM.problemCopy(body) : "Sign in with that identity instead."
      );
      return;
    }
    deadLink();
  }).catch(function () {
    show(
      "email-auth-error",
      "Something went wrong.",
      "Try opening the link again."
    );
  });
})();
