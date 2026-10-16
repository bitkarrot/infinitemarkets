/* admin_app.js — Infinitemarkets admin shell mixin.

   The host creates window.app (Vue 3 global) BEFORE this script runs and
   mounts it AFTER, so extension modules register mixins/components here.
   One nav section: Orders / Catalog / Publications / Settings.

   Auth: the browser carries the host cookie_access_token automatically
   (same-origin). Mutations send the double-submit CSRF token (gm_csrf
   cookie -> X-CSRF-Token header) and a per-request Idempotency-Key —
   §5.1/§14. */
(function () {
  "use strict";

  var API = "/infinitemarkets/api/v1";

  function readCookie(name) {
    var m = document.cookie.match(
      new RegExp("(?:^|; )" + name + "=([^;]*)")
    );
    return m ? decodeURIComponent(m[1]) : "";
  }

  function idemKey() {
    var buf = new Uint8Array(32);
    crypto.getRandomValues(buf);
    return btoa(String.fromCharCode.apply(null, buf))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }

  /* problem body -> friendly copy (RFC 9457 urn:infinitemarkets:*) */
  var ERROR_COPY = {
    "insufficient-stock":
      "Not enough stock available — reduce quantity or choose another item.",
    "order-expired":
      "Invoice expired. If you already paid, do not pay again;" +
      " contact the merchant. Wait for status verification before" +
      " starting a new checkout.",
    "rate-limited": "Too many requests — wait a minute and try again.",
    "invalid-shipping-destination":
      "This item cannot be shipped to the selected destination.",
    "media-quota": "Local media storage is full — remove unused uploads, or save the image to a Blossom server instead.",
    "media-backend": "No Blossom media server is configured — add one under Settings → Merchant, or save this image to LNbits instead.",
    "media-origin": "Profile images need a public https storefront address — set a public base URL before uploading to LNbits, or use Blossom.",
    "media-remote": "The Blossom media server could not store the file — nothing was stored locally; retry the upload or save to LNbits instead."
  };

  window.app.mixin({
    data: function () {
      return {
        gm: {
          view: "orders",
          loaded: false,
          blocked: false,
          warnings: [],
          dismissableWarning: null,
          dismissingWarning: false,
          merchant: null,
          loadError: null,
          creating: false,
          wallets: [],
          createForm: { display_name: "", wallet_id: "" },
          newTokenLink: "",
          settingsTab: "merchant",
          unreadCount: 0
        }
      };
    },
    watch: {
      /* Section errors/notices also pop a dismissible toast at the top —
         inline banners are easy to miss below long content. */
      "gmCatalog.error": function (v) { this.gmToast(v, "negative"); },
      "gmCatalog.notice": function (v) { this.gmToast(v, "positive"); },
      "gmMigration.error": function (v) { this.gmToast(v, "negative"); },
      "gmMessages.error": function (v) { this.gmToast(v, "negative"); },
      "gmNotify.error": function (v) { this.gmToast(v, "negative"); },
      "gmNotify.notice": function (v) { this.gmToast(v, "positive"); },
      "gmOrders.error": function (v) { this.gmToast(v, "negative"); },
      "gmOrders.notice": function (v) { this.gmToast(v, "positive"); },
      "gmPubs.error": function (v) { this.gmToast(v, "negative"); },
      "gmSettings.error": function (v) { this.gmToast(v, "negative"); },
      "gmSettings.notice": function (v) { this.gmToast(v, "positive"); }
    },
    methods: {
      gmToast: function (message, type) {
        if (!message || !this.$q || !this.$q.notify) return;
        this.$q.notify({
          type: type,
          message: String(message),
          position: "top",
          timeout: 8000,
          actions: [{ icon: "close", color: "white", dense: true, round: true }]
        });
      },
      /* Admin JSON fetch — cookie auth is implicit same-origin; mutations
         carry Origin (browser-supplied), X-CSRF-Token, Idempotency-Key. */
      gmApi: async function (method, path, body) {
        var headers = {};
        if (body !== undefined) headers["Content-Type"] = "application/json";
        if (method !== "GET" && method !== "HEAD") {
          headers["X-CSRF-Token"] = readCookie("gm_csrf");
          headers["Idempotency-Key"] = idemKey();
        }
        var resp = await fetch(API + path, {
          method: method,
          headers: headers,
          credentials: "same-origin",
          body: body !== undefined ? JSON.stringify(body) : undefined
        });
        var data = await resp.json().catch(function () {
          return {};
        });
        if (!resp.ok) {
          var err = new Error(
            (data && (data.detail || data.title)) || "Request failed"
          );
          err.status = resp.status;
          err.problem = data || {};
          throw err;
        }
        return data;
      },
      gmProblemCopy: function (problem) {
        var code = "";
        if (problem && typeof problem.type === "string") {
          code = problem.type.replace("urn:infinitemarkets:", "");
        }
        return (
          ERROR_COPY[code] ||
          (problem && (problem.detail || problem.title)) ||
          "The request could not be completed."
        );
      },
      gmSats: function (n) {
        if (n === null || n === undefined) return "—";
        return Number(n).toLocaleString("en-US") + " sats";
      },
      gmTime: function (ts) {
        if (!ts) return "—";
        return new Date(ts * 1000).toLocaleString();
      },
      gmTrunc: function (s, head, tail) {
        s = String(s || "");
        head = head || 8;
        tail = tail || 6;
        if (s.length <= head + tail + 3) return s;
        return s.slice(0, head) + "…" + s.slice(-tail);
      },
      gmCopy: function (text) {
        if (navigator.clipboard) navigator.clipboard.writeText(text);
      },
      gmOrigin: function () {
        return window.location.origin;
      },
      gmBrandName: function () {
        var t = (this.gmSettings || {}).theme || {};
        return ((t.brand || {}).name || "").trim()
          || (this.gm.merchant || {}).display_name || "";
      },
      gmSerpText: function (s) {
        s = String(s || "").trim().replace(/\s+/g, " ");
        if (s.length <= 160) return s;
        return s.slice(0, 157).replace(/\s+\S*$/, "") + "...";
      },
      gmSerpPrice: function (major, currency, decimals) {
        if (currency == null) return "";
        var n = Number(major || 0);
        if (Number.isNaN(n)) n = 0;
        var d = Number(decimals);
        if (Number.isNaN(d) || decimals == null) d = 0;
        var s = n.toFixed(d).replace(/\.?0+$/, "");
        return s + " " + String(currency).toUpperCase();
      },
      gmLoad: async function () {
        var self = this;
        self.gm.loadError = null;
        try {
          var m = await self.gmApi("GET", "/merchants/current");
          self.gm.merchant = m;
          self.gm.blocked = !!m.blocked;
          self.gm.warnings = m.warnings || [];
          self.gm.dismissableWarning = m.dismissable_warning || null;
        } catch (e) {
          if (e.status === 404) {
            self.gm.merchant = null; /* first-run: show setup card */
          } else {
            self.gm.loadError = self.gmProblemCopy(e.problem);
          }
        }
        /* Host wallet list — needed for first-run setup AND the B4
           wallet selector. */
        try {
          var w = await fetch("/api/v1/wallets", {
            credentials: "same-origin"
          });
          if (w.ok) self.gm.wallets = await w.json();
        } catch (e2) {
          self.gm.wallets = [];
        }
        self.gm.loaded = true;
      },
      gmCreateMerchant: async function () {
        var self = this;
        self.gm.creating = true;
        try {
          var m = await self.gmApi("POST", "/merchants", {
            wallet_id: self.gm.createForm.wallet_id,
            display_name: self.gm.createForm.display_name || undefined
          });
          self.gm.merchant = m;
          /* Create returns the basic projection; reload for warnings. */
          await self.gmLoad();
        } catch (e) {
          self.gm.loadError = self.gmProblemCopy(e.problem);
        }
        self.gm.creating = false;
      },
      gmDismissWarning: async function (w) {
        var self = this;
        self.gm.dismissingWarning = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gm.merchant.id + "/warnings/dismiss",
            { id: "keys-autogenerated" }
          );
          self.gm.warnings = self.gm.warnings.filter(
            function (x) { return x !== w; }
          );
          self.gm.dismissableWarning = null;
        } catch (e) {
          self.gmToast(self.gmProblemCopy(e.problem), "negative");
        }
        self.gm.dismissingWarning = false;
      },
      gmNav: function (view) {
        this.gm.view = view;
        /* Per-surface loaders — each module registers its own method;
           only the active surface's data is fetched. */
        if (view === "orders" && this.gmLoadOrders) this.gmLoadOrders();
        if (view === "catalog" && this.gmLoadCatalog) this.gmLoadCatalog();
        if (view === "migration" && this.gmLoadImports) this.gmLoadImports();
        if (view === "publications" && this.gmLoadPublications) {
          this.gmLoadPublications();
        }
        if (view === "messages" && this.gmLoadMessages) {
          this.gmLoadMessages();
        }
        if (view === "settings") {
          if (this.gmLoadSettings) this.gmLoadSettings();
          if (this.gmLoadNotifications) this.gmLoadNotifications();
        }
      },
      gmMerchantId: function () {
        return this.gm.merchant ? this.gm.merchant.id : "";
      }
    },
    mounted: function () {
      /* Global-mixin hooks fire per component, children BEFORE parents,
         and other Vue roots on the page (e.g. standalone widgets) also
         pass $root === this — their gm is NOT the state rendering this
         page. Bootstrap must always target the component instance that
         owns #vue (the root rendering #gm-admin-root). */
      if (window._gmBooted) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmBooted = true;
      root.proxy.gmLoad();
    }
  });
})();
