/* admin_settings.js — B4 merchant settings + B6 appearance (UI-SPEC).

   B4: identity card, masked nsec import ("Sent once over TLS and never
   displayed or logged."), wallet selector (blocked while open invoices
   exist), relay topology config, publish/deactivation flows, topology +
   audit-posture banners.

   B6: Tiered Controls — presets / Brand Basics / guarded Advanced
   Tokens, layout-preset selector, live PUBLIC-only preview, client-side
   WCAG contrast meters (the server gate remains authoritative), reset
   to preset. Public theme tokens never reach admin chrome. */
(function () {
  "use strict";

  var LAYOUTS = [
    { value: "editorial", label: "Editorial" },
    { value: "guided", label: "Guided" },
    { value: "compact", label: "Compact" },
    { value: "gallery", label: "Gallery" }
  ];
  /* Verbatim contract copy — kept on one line each so the strings are
     greppable (UI-SPEC asserts them literally). */
  var LAYOUT_NOTE =
    "Mobile always uses the compact layout — responsive safety overrides this preference.";
  var BOUNDARY_NOTE =
    "Appearance applies to your public storefront only. It never changes the admin area, checkout fields, totals, validation, or payment states.";
  var NSEC_NOTE = "Sent once over TLS and never displayed or logged.";
  var REFUND_NOTE =
    "Records your attestation that a refund was paid from the wallet" +
    " UI. infinitemarkets cannot verify outgoing payments.";

  /* Preset palettes mirror services/themes.py PRESET_TOKENS — the client
     preview/contrast math must match the server-side gate. */
  var PRESET_TOKENS = {
    "warm-market": {
      "--color-bg": "#f7f1e8", "--color-surface": "#fffaf3",
      "--color-surface-alt": "#f1e4d3", "--color-border": "#dfcfbb",
      "--color-text": "#2b241f", "--color-text-muted": "#75685c",
      "--color-primary": "#a34f2a", "--color-on-primary": "#ffffff",
      "--color-primary-hover": "#843d20", "--color-accent": "#d69a3a",
      "--color-focus": "#225bdb"
    },
    "clean-minimal": {
      "--color-bg": "#f4f7f7", "--color-surface": "#ffffff",
      "--color-surface-alt": "#e9efef", "--color-border": "#d7e0e0",
      "--color-text": "#172223", "--color-text-muted": "#647274",
      "--color-primary": "#266760", "--color-on-primary": "#ffffff",
      "--color-primary-hover": "#1c514c", "--color-accent": "#d69a3a",
      "--color-focus": "#165dff"
    },
    "high-contrast": {
      "--color-bg": "#0b0f14", "--color-surface": "#141a21",
      "--color-surface-alt": "#1d2630", "--color-border": "#415064",
      "--color-text": "#f7fafc", "--color-text-muted": "#bac5d1",
      "--color-primary": "#ffb000", "--color-on-primary": "#111111",
      "--color-primary-hover": "#ffd166", "--color-accent": "#63d2ff",
      "--color-focus": "#ffffff"
    }
  };
  var CORNER_RADIUS = {
    sharp: { "--radius-sm": "0px", "--radius-md": "0px", "--radius-lg": "0px" },
    rounded: {
      "--radius-sm": "4px", "--radius-md": "8px", "--radius-lg": "16px"
    },
    soft: {
      "--radius-sm": "8px", "--radius-md": "16px", "--radius-lg": "24px"
    }
  };
  var FONT_VALUE = {
    system: 'ui-rounded, "Avenir Next", system-ui, sans-serif',
    serif: 'Georgia, "Times New Roman", serif',
    mono: 'ui-monospace, "SF Mono", Menlo, monospace'
  };
  var PRESET_NAMES = {
    "warm-market": "Warm Market",
    "clean-minimal": "Clean Minimal",
    "high-contrast": "High Contrast"
  };
  var GATED_PAIRS = [
    ["--color-text", "--color-bg"],
    ["--color-text", "--color-surface"],
    ["--color-text", "--color-surface-alt"],
    ["--color-text-muted", "--color-bg"],
    ["--color-text-muted", "--color-surface"],
    ["--color-primary", "--color-on-primary"],
    ["--color-primary-hover", "--color-on-primary"],
    ["--color-primary", "--color-bg"],
    ["--color-primary", "--color-surface"],
    ["--color-focus", "--color-bg"],
    ["--color-focus", "--color-surface"]
  ];
  var ADVANCED_TOKENS = [
    "--color-bg", "--color-surface", "--color-surface-alt",
    "--color-border", "--color-text", "--color-text-muted",
    "--color-primary", "--color-on-primary", "--color-primary-hover",
    "--color-accent",
    "--radius-sm", "--radius-md", "--radius-lg",
    "--space-sm", "--space-md", "--space-lg", "--space-16"
  ];
  var DIRECTIONS = [
    { value: "public", label: "Public (outbox)" },
    { value: "inbox", label: "Inbox" },
    { value: "both", label: "Both" }
  ];

  function luminance(hex) {
    var c = String(hex || "").replace("#", "");
    if (c.length !== 6) return 0;
    var ch = [0, 2, 4].map(function (i) {
      var v = parseInt(c.slice(i, i + 2), 16) / 255;
      return v <= 0.04045
        ? v / 12.92
        : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  }
  function contrast(fg, bg) {
    var l1 = luminance(fg);
    var l2 = luminance(bg);
    var hi = Math.max(l1, l2);
    var lo = Math.min(l1, l2);
    return (hi + 0.05) / (lo + 0.05);
  }

  window.app.mixin({
    data: function () {
      return {
        gmSettings: {
          loading: false,
          error: null,
          notice: null,
          /* B4 */
          wallets: [],
          walletBlocked: false,
          displayName: "",
          nsecInput: "",
          nsecNote: NSEC_NOTE,
          importing: false,
          relays: [],
          blossom: [],
          newRelay: "",
          newRelayDirection: "public",
          newBlossom: "",
          directions: DIRECTIONS,
          publishing: false,
          deactivate: {
            show: false, step: 1, blockers: [], busy: false,
            retireKeys: false
          },
          specRevision: "",
          /* Storefront mode (03-03, D-07..D-11) */
          mode: {
            current: "full",
            modes: ["full", "showcase", "browse_only", "nostr_only"],
            blocked: {},
            blockedReason: "",
            pending: null,
            pendingImpact: [],
            confirmShow: false,
            applying: false
          },
          /* B6 */
          layouts: LAYOUTS,
          layoutNote: LAYOUT_NOTE,
          boundaryNote: BOUNDARY_NOTE,
          presetNames: PRESET_NAMES,
          advancedTokens: ADVANCED_TOKENS,
          fontStacks: [
            { value: "system", label: "System" },
            { value: "serif", label: "Serif" },
            { value: "mono", label: "Mono" }
          ],
          cornerOptions: [
            { value: "sharp", label: "Sharp" },
            { value: "rounded", label: "Rounded" },
            { value: "soft", label: "Soft" }
          ],
          theme: {
            preset: "warm-market", layout: "editorial",
            brand: {}, advanced: {}, advanced_opt_in: false
          },
          saving: false,
          themeError: null,
          themeNotice: null
        }
      };
    },
    computed: {
      /* Fully resolved token set for the live preview — same merge order
         as services/themes.py resolve_tokens. */
      gmPreviewTokens: function () {
        var t = this.gmSettings.theme;
        var tokens = Object.assign(
          {}, PRESET_TOKENS[t.preset] || PRESET_TOKENS["warm-market"]
        );
        var brand = t.brand || {};
        if (brand.accent) tokens["--color-accent"] = brand.accent;
        if (brand.corners) {
          Object.assign(tokens, CORNER_RADIUS[brand.corners] || {});
        }
        if (brand.font) tokens["--font-body"] = FONT_VALUE[brand.font];
        if (t.advanced_opt_in && t.advanced) {
          Object.assign(tokens, t.advanced);
        }
        return tokens;
      },
      gmPreviewStyle: function () {
        var tokens = this.gmPreviewTokens;
        var parts = [];
        Object.keys(tokens).forEach(function (k) {
          parts.push(k + ":" + tokens[k]);
        });
        return parts.join(";");
      },
      /* WCAG meters — computed live on every edit, before save. */
      gmContrastPairs: function () {
        var tokens = this.gmPreviewTokens;
        return GATED_PAIRS.map(function (pair) {
          var fg = tokens[pair[0]];
          var bg = tokens[pair[1]];
          var ratio = contrast(fg, bg);
          return {
            pair: pair[0] + " on " + pair[1],
            ratio: ratio,
            ok: ratio >= 4.5
          };
        });
      },
      gmContrastOk: function () {
        return this.gmContrastPairs.every(function (p) {
          return p.ok;
        });
      }
    },
    methods: {
      gmLoadSettings: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        self.gmSettings.loading = true;
        self.gmSettings.error = null;
        try {
          var res = await Promise.all([
            self.gmApi("GET", "/merchants/" + mid + "/relay-health"),
            self.gmApi("GET", "/merchants/" + mid + "/storefront-mode")
          ]);
          self.gmSettings.relays = res[0].relays || [];
          self.gmSettings.blossom = res[0].blossom_servers || [];
          var modeRes = res[1] || {};
          self.gmSettings.mode.current = modeRes.mode || "full";
          self.gmSettings.mode.modes =
            modeRes.modes || self.gmSettings.mode.modes;
          self.gmSettings.mode.blocked = modeRes.blocked || {};
          self.gmSettings.mode.blockedReason =
            modeRes.blocked_reason || "";
          self.gmSettings.wallets = self.gm.wallets || [];
          var m = self.gm.merchant;
          self.gmSettings.displayName = m.display_name || "";
          self.gmSettings.specRevision = m.spec_revision || "";
          var t = m.theme || {};
          self.gmSettings.theme = {
            preset: t.preset || "warm-market",
            layout: t.layout || "editorial",
            brand: Object.assign({}, t.brand || {}),
            advanced: Object.assign({}, t.advanced || {}),
            advanced_opt_in: !!t.advanced_opt_in
          };
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.loading = false;
      },
      gmSaveDisplayName: async function () {
        var self = this;
        try {
          var m = await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(),
            { display_name: self.gmSettings.displayName }
          );
          self.gm.merchant.display_name = m.display_name;
          self.gmSettings.notice = "Display name saved.";
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
      },
      gmImportKey: async function () {
        /* nsec enters a masked input, posts once over TLS, and is cleared
           immediately — never echoed, logged, or rendered. */
        var self = this;
        var nsec = self.gmSettings.nsecInput;
        if (!nsec) return;
        self.gmSettings.importing = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() + "/keys/import",
            { nsec: nsec }
          );
          self.gmSettings.nsecInput = "";
          self.gmSettings.notice = "Key imported.";
          await self.gmLoad();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
          self.gmSettings.nsecInput = "";
        }
        self.gmSettings.importing = false;
      },
      gmChangeWallet: async function (walletId) {
        var self = this;
        try {
          await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(),
            { wallet_id: walletId }
          );
          self.gmSettings.notice = "Wallet updated.";
          self.gmSettings.walletBlocked = false;
        } catch (e) {
          /* 409 wallet-mismatch — open invoice_pending/awaiting_payment
             orders exist; the disabled-reason surfaces verbatim. */
          self.gmSettings.walletBlocked = true;
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
      },
      gmAddRelay: function () {
        var url = (this.gmSettings.newRelay || "").trim();
        if (!url) return;
        this.gmSettings.relays.push({
          relay_url: url,
          direction: this.gmSettings.newRelayDirection,
          enabled: true
        });
        this.gmSettings.newRelay = "";
      },
      gmRemoveRelay: function (idx) {
        this.gmSettings.relays.splice(idx, 1);
      },
      gmSaveRelays: async function () {
        var self = this;
        var body = {
          relay_configs: self.gmSettings.relays.map(function (r) {
            return {
              relay_url: r.relay_url,
              direction: r.direction,
              enabled: !!r.enabled
            };
          }),
          blossom_servers: self.gmSettings.blossom
        };
        try {
          await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(), body
          );
          self.gmSettings.notice = "Relay configuration saved.";
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
      },
      gmAddBlossom: function () {
        var url = (this.gmSettings.newBlossom || "").trim();
        if (!url) return;
        this.gmSettings.blossom.push(url);
        this.gmSettings.newBlossom = "";
      },
      gmRemoveBlossom: function (idx) {
        this.gmSettings.blossom.splice(idx, 1);
      },
      gmPublishEverything: async function () {
        var self = this;
        self.gmSettings.publishing = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() + "/publish",
            {}
          );
          self.gmSettings.notice =
            "Publish queued — check Publications for delivery evidence.";
          await self.gmLoad();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.publishing = false;
      },
      gmBeginDeactivate: async function () {
        /* Two-step: the first call lists blocking nonterminal orders and
           exceptions; the second confirms. */
        var self = this;
        var mid = self.gmMerchantId();
        self.gmSettings.deactivate.busy = true;
        try {
          var res = await self.gmApi("DELETE", "/merchants/" + mid);
          self.gmSettings.deactivate.show = false;
          self.gmSettings.notice = "Deactivation started — tombstones queued.";
          await self.gmLoad();
        } catch (e) {
          if (e.status === 409) {
            var blockers = [];
            try {
              blockers = JSON.parse(e.problem.detail || "[]");
            } catch (e2) {
              blockers = [
                { type: "unknown", count: 0, label: e.problem.title }
              ];
            }
            self.gmSettings.deactivate = {
              show: true, step: 1, blockers: blockers, busy: false,
              retireKeys: false
            };
          } else {
            self.gmSettings.error = self.gmProblemCopy(e.problem);
          }
        }
        self.gmSettings.deactivate.busy = false;
      },

      /* --- Relay auth pills (D-26..D-28) ----------------------------------- */

      gmAuthLabel: function (state) {
        return (
          {
            none: "no-auth",
            authenticated: "authenticated",
            "auth-required": "auth-required",
            "auth-failed": "auth-failed",
            "payment-required": "payment-required"
          }[state] || "no-auth"
        );
      },
      gmAuthColor: function (state) {
        return (
          {
            authenticated: "positive",
            "auth-required": "warning",
            "auth-failed": "negative",
            "payment-required": "warning"
          }[state] || "grey"
        );
      },
      gmRetryRelayAuth: async function (relay) {
        /* "Paid externally — retry" — the paid_invoice blob itself is
           never rendered; retry re-runs auth against every blocked
           aggregate. */
        var self = this;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/relay-auth/retry/" + encodeURIComponent(relay.relay_url),
            {}
          );
          self.gmSettings.notice =
            "Auth retry queued for " + relay.relay_url + ".";
          await self.gmLoadSettings();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
      },

      /* --- Storefront mode (D-07..D-11) ------------------------------------ */

      gmModeLabel: function (m) {
        return (
          {
            full: "Full",
            showcase: "Showcase",
            browse_only: "Browse-only",
            nostr_only: "Nostr-only"
          }[m] || m
        );
      },
      gmModeBlurb: function (m) {
        return (
          {
            full: "Browse + web checkout — the normal store.",
            showcase:
              "Products remain visible; buy controls become 'Order via Nostr' guidance.",
            browse_only:
              "No new purchases; products stop publishing changes to Nostr.",
            nostr_only:
              "Storefront shows a Nostr-only notice; ordering happens over Nostr DMs."
          }[m] || ""
        );
      },
      gmSelectMode: async function (mode) {
        /* Step 1 of the two-step apply — fetch the impact preview. */
        var self = this;
        if (self.gmSettings.mode.blocked[mode]) return;
        if (mode === self.gmSettings.mode.current) return;
        try {
          var res = await self.gmApi(
            "PUT",
            "/merchants/" + self.gmMerchantId() + "/storefront-mode",
            { mode: mode, confirm: false }
          );
          self.gmSettings.mode.pending = mode;
          self.gmSettings.mode.pendingImpact = res.impact || [];
          self.gmSettings.mode.confirmShow = true;
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
      },
      gmApplyMode: async function () {
        /* Step 2 — confirm the impact list and apply. */
        var self = this;
        var mode = self.gmSettings.mode.pending;
        if (!mode) return;
        self.gmSettings.mode.applying = true;
        try {
          await self.gmApi(
            "PUT",
            "/merchants/" + self.gmMerchantId() + "/storefront-mode",
            { mode: mode, confirm: true }
          );
          self.gmSettings.mode.current = mode;
          self.gmSettings.mode.confirmShow = false;
          self.gmSettings.mode.pending = null;
          self.gmSettings.mode.pendingImpact = [];
          self.gmSettings.notice =
            "Storefront mode is now " + self.gmModeLabel(mode) + ".";
        } catch (e) {
          self.gmSettings.mode.confirmShow = false;
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.mode.applying = false;
      },

      /* --- B6 appearance -------------------------------------------------- */
      gmSetPreset: function (preset) {
        this.gmSettings.theme.preset = preset;
      },
      gmSetLayout: function (layout) {
        this.gmSettings.theme.layout = layout;
      },
      gmSwatches: function (preset) {
        var t = PRESET_TOKENS[preset] || {};
        return [
          t["--color-bg"], t["--color-surface"], t["--color-primary"],
          t["--color-accent"]
        ];
      },
      gmResetTier: function (tier) {
        var t = this.gmSettings.theme;
        if (tier === "preset") {
          t.preset = "warm-market";
          t.layout = "editorial";
        } else if (tier === "brand") {
          t.brand = {};
        } else if (tier === "advanced") {
          t.advanced = {};
          t.advanced_opt_in = false;
        }
      },
      gmSaveTheme: async function () {
        var self = this;
        if (!self.gmContrastOk) {
          var failing = self.gmContrastPairs.filter(function (p) {
            return !p.ok;
          })[0];
          self.gmSettings.themeError =
            "Contrast gate failed: " + failing.pair + " = " +
            failing.ratio.toFixed(2) + ":1 (needs ≥4.5:1)";
          return;
        }
        self.gmSettings.saving = true;
        self.gmSettings.themeError = null;
        self.gmSettings.themeNotice = null;
        var t = self.gmSettings.theme;
        /* validate_theme() replaces the whole object from DEFAULT_THEME —
           always send brand (empty clears it); advanced only while opted
           in (the server rejects advanced tokens without the flag). */
        var theme = {
          preset: t.preset,
          layout: t.layout,
          brand: t.brand || {},
          advanced_opt_in: !!t.advanced_opt_in
        };
        if (t.advanced_opt_in) {
          theme.advanced = t.advanced || {};
        }
        try {
          var m = await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(),
            { theme: theme }
          );
          self.gm.merchant.theme = m.theme;
          self.gmSettings.themeNotice = "Appearance saved.";
        } catch (e) {
          self.gmSettings.themeError = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.saving = false;
      }
    },
    mounted: function () {
      if (window._gmSettingsWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmSettingsWired = true;
      var self = root.proxy;
      self.$watch("gm.merchant", function (m) {
        if (m && self.gm.view === "settings") {
          self.gmLoadSettings();
          if (self.gmLoadNotifications) self.gmLoadNotifications();
        }
      });
    }
  });
})();
