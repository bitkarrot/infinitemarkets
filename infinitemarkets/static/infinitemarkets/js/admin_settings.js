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
    },
    "lightnin-dark": {
      "--color-bg": "#242833", "--color-surface": "#2f3442",
      "--color-surface-alt": "#384051", "--color-border": "#454c5e",
      "--color-text": "#d0d2d7", "--color-text-muted": "#a9afbb",
      "--color-primary": "#fce477", "--color-on-primary": "#121212",
      "--color-primary-hover": "#fdf0a6", "--color-accent": "#fce477",
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
    "high-contrast": "High Contrast",
    "lightnin-dark": "Lightnin' Dark"
  };
  /* Which scheme each preset owns — mirrors themes.py PRESET_SCHEME;
     the opposite scheme is derived (and tinted via theme.counterpart). */
  var PRESET_SCHEME = {
    "warm-market": "light",
    "clean-minimal": "light",
    "high-contrast": "dark",
    "lightnin-dark": "dark"
  };
  /* Counterpart surface ramps — mirror themes.py _DARK_SURFACES /
     _LIGHT_SURFACES and the mix-derivation for a merchant-chosen
     counterpart background. */
  var DARK_SURFACES = {
    "--color-bg": "#1b1510", "--color-surface": "#241c15",
    "--color-surface-alt": "#2e241b",
    "--color-border": "rgba(245, 239, 230, 0.12)",
    "--color-text": "#f5efe6", "--color-text-muted": "#b8a996",
    "--color-focus": "#8ab5ff",
    "--shadow-sm": "0 1px 2px rgba(0, 0, 0, 0.45)",
    "--shadow-md": "0 8px 24px rgba(0, 0, 0, 0.45)",
    "--shadow-lg": "0 18px 52px rgba(0, 0, 0, 0.55)"
  };
  var LIGHT_SURFACES = {
    "--color-bg": "#f5f6f8", "--color-surface": "#ffffff",
    "--color-surface-alt": "#e8ebef",
    "--color-border": "rgba(23, 27, 34, 0.12)",
    "--color-text": "#171b22", "--color-text-muted": "#4d5665",
    "--color-focus": "#165dff"
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
  /* Point-and-click fine-tune controls — friendly names over the same
     allowlisted tokens the server validates (colors #rrggbb, radius
     0-24px, spacing 0-99px). */
  var TUNE_COLORS = [
    { token: "--color-bg", label: "Page background",
      help: "Behind everything on your storefront." },
    { token: "--color-surface", label: "Cards & panels",
      help: "Header, footer, product cards and checkout boxes." },
    { token: "--color-surface-alt", label: "Soft highlights",
      help: "Hover states, chips, and the hero tint." },
    { token: "--color-border", label: "Lines & borders",
      help: "Dividers and card outlines." },
    { token: "--color-text", label: "Text color",
      help: "Headings, prices and body text." },
    { token: "--color-text-muted", label: "Secondary text",
      help: "Captions, descriptions and helper text." },
    { token: "--color-primary", label: "Buttons & links",
      help: "Buy/Pay buttons, selected filters, active links." },
    { token: "--color-on-primary", label: "Text on buttons",
      help: "The label color inside buttons." },
    { token: "--color-primary-hover", label: "Button hover",
      help: "Button color while the pointer is over it." },
    { token: "--color-accent", label: "Lightning accent",
      help: "Tints the lightning-bolt icons and the pulsing “waiting " +
            "for payment” dot. Does not change buttons or links." }
  ];
  var TUNE_RADIUS = [
    { token: "--radius-sm", label: "Small corners", max: 24, def: 6,
      help: "Chips, badges and small boxes." },
    { token: "--radius-md", label: "Medium corners", max: 24, def: 10,
      help: "Buttons, inputs and cards." },
    { token: "--radius-lg", label: "Large corners", max: 24, def: 16,
      help: "Big panels, hero and galleries." }
  ];
  var TUNE_SPACE = [
    { token: "--space-sm", label: "Tight gaps", max: 24, def: 8,
      help: "Space between small related items." },
    { token: "--space-md", label: "Normal gaps", max: 40, def: 16,
      help: "Padding inside cards and between rows." },
    { token: "--space-lg", label: "Roomy gaps", max: 64, def: 32,
      help: "Space between page sections." },
    { token: "--space-16", label: "Section breathing room", max: 96, def: 64,
      help: "Extra space above the footer and on message pages." }
  ];
  var TUNE_LABELS = {};
  TUNE_COLORS.forEach(function (c) { TUNE_LABELS[c.token] = c.label; });
  TUNE_LABELS["--color-focus"] = "Keyboard focus ring";

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
  function mixHex(a, b, t) {
    var ca = String(a).replace("#", "");
    var cb = String(b).replace("#", "");
    var out = "#";
    [0, 2, 4].forEach(function (i) {
      var va = parseInt(ca.slice(i, i + 2), 16);
      var vb = parseInt(cb.slice(i, i + 2), 16);
      out += ("0" + Math.round(va + (vb - va) * t).toString(16)).slice(-2);
    });
    return out;
  }
  function lightenTo(color, bg, target) {
    var mixed = color, t = 0;
    while (contrast(mixed, bg) < target && t < 0.85) {
      t += 0.05;
      mixed = mixHex(color, "#ffffff", t);
    }
    return mixed;
  }
  function darkenTo(color, bg, target) {
    var mixed = color, t = 0;
    while (contrast(mixed, bg) < target && t < 0.85) {
      t += 0.05;
      mixed = mixHex(color, "#000000", t);
    }
    return mixed;
  }
  function darkSurfaces(bg) {
    var out = Object.assign({}, DARK_SURFACES);
    if (!bg) return out;
    out["--color-bg"] = bg;
    out["--color-surface"] = mixHex(bg, "#ffffff", 0.07);
    out["--color-surface-alt"] = mixHex(bg, "#ffffff", 0.13);
    return out;
  }
  function lightSurfaces(bg) {
    var out = Object.assign({}, LIGHT_SURFACES);
    if (!bg) return out;
    out["--color-bg"] = bg;
    out["--color-surface"] = mixHex(bg, "#ffffff", 0.55);
    out["--color-surface-alt"] = mixHex(bg, "#000000", 0.05);
    return out;
  }
  /* Mirror of themes.py counterpart_scheme_tokens: for a light preset
     the dark scheme is derived (surfaces + lightened brand colors on
     the lightest gated surface); for a dark preset the light scheme is
     derived symmetrically. */
  function counterpartTokens(baseTokens, theme) {
    var dark = PRESET_SCHEME[theme.preset] !== "dark";
    var cpBg = (theme.counterpart || {})["--color-bg"];
    var surfaces = dark ? darkSurfaces(cpBg) : lightSurfaces(cpBg);
    var out = Object.assign({}, baseTokens, surfaces);
    var bg = out["--color-bg"];
    var on = dark ? out["--color-surface"] : bg;
    out["--color-primary"] = (dark ? lightenTo : darkenTo)(
      baseTokens["--color-primary"], on, 4.5);
    out["--color-primary-hover"] = (dark ? lightenTo : darkenTo)(
      baseTokens["--color-primary-hover"], on, 4.5);
    var accent = baseTokens["--color-accent"];
    out["--color-accent"] = contrast(accent, bg) >= 3.0
      ? accent
      : (dark ? lightenTo : darkenTo)(accent, bg, 3.0);
    out["--color-on-primary"] = bg;
    out["color-scheme"] = dark ? "dark" : "light";
    return out;
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
          walletId: null,
          walletBlocked: false,
          displayName: "",
          profileJson: {},
          profileAvatar: "",
          profileBanner: "",
          profileBio: "",
          profileNip05: "",
          profileLud16: "",
          identitySaving: false,
          nsecInput: "",
          nsecNote: NSEC_NOTE,
          nsecReveal: "",
          nsecRevealing: false,
          importing: false,
          relays: [],
          blossom: [],
          newRelay: "",
          newRelayDirection: "public",
          newBlossom: "",
          directions: DIRECTIONS,
          publishing: false,
          inbox: { state: "off", busy: false },
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
          tuneColors: TUNE_COLORS,
          tuneRadius: TUNE_RADIUS,
          tuneSpace: TUNE_SPACE,
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
            brand: {}, advanced: {}, advanced_opt_in: false,
            counterpart: {},
            hero: {
              slogan: "", subtitle: "", image_url: "",
              primary: {label: "", url: ""},
              secondary: {label: "", url: ""}
            },
            footer: {tagline: "", note: "", logo_url: ""},
            storefront: {grid: "standard", hero_hidden: false},
            share: {card_image: "brand_logo"}
          },
          previewScheme: "base",
          saving: false,
          themeError: null,
          themeNotice: null
        }
      };
    },
    computed: {
      /* Fully resolved base-scheme token set — same merge order as
         services/themes.py resolve_tokens. */
      gmBaseTokens: function () {
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
      /* The opposite scheme's derived tokens — what shoppers get when
         they flip the storefront's light/dark toggle. */
      gmCounterpartTokens: function () {
        return counterpartTokens(this.gmBaseTokens, this.gmSettings.theme);
      },
      gmPreviewTokens: function () {
        return this.gmSettings.previewScheme === "counterpart"
          ? this.gmCounterpartTokens
          : this.gmBaseTokens;
      },
      gmSchemeOptions: function () {
        var base = PRESET_SCHEME[this.gmSettings.theme.preset] === "dark"
          ? "Dark" : "Light";
        var other = base === "Dark" ? "Light" : "Dark";
        return [
          { label: base, value: "base" },
          { label: other, value: "counterpart" }
        ];
      },
      gmCounterpartLabel: function () {
        return PRESET_SCHEME[this.gmSettings.theme.preset] === "dark"
          ? "Light-mode background"
          : "Dark-mode background";
      },
      gmCounterpartHelp: function () {
        var scheme =
          PRESET_SCHEME[this.gmSettings.theme.preset] === "dark"
            ? "light" : "dark";
        return "Page background when a shopper switches to " + scheme +
          " mode — the other colors are derived automatically.";
      },
      gmCounterpartIsCustom: function () {
        var cp = this.gmSettings.theme.counterpart || {};
        return !!cp["--color-bg"];
      },
      gmPreviewStyle: function () {
        var tokens = this.gmPreviewTokens;
        var parts = [];
        Object.keys(tokens).forEach(function (k) {
          parts.push(k + ":" + tokens[k]);
        });
        return parts.join(";");
      },
      /* WCAG meters — computed live on every edit, before save. The
         meter list shows the scheme being previewed; the save gate
         checks both schemes. */
      gmContrastPairs: function () {
        return this.gmPairsFor(this.gmPreviewTokens);
      },
      gmContrastOk: function () {
        var self = this;
        return [this.gmBaseTokens, this.gmCounterpartTokens].every(
          function (tokens) {
            return self.gmPairsFor(tokens).every(function (p) {
              return p.ok;
            });
          }
        );
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
            self.gmApi("GET", "/merchants/" + mid + "/storefront-mode"),
            self.gmApi("GET", "/merchants/" + mid + "/inbox-state")
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
          self.gmSettings.inbox.state =
            (res[2] && res[2].inbox_state) || "off";
          self.gmPollInbox();
          self.gmSettings.wallets = self.gm.wallets || [];
          var m = self.gm.merchant;
          self.gmSettings.walletId = m.wallet_id || null;
          self.gmSettings.displayName = m.display_name || "";
          var profile = {};
          try {
            profile = JSON.parse(m.profile_json || "{}");
          } catch (e2) {
            profile = {};
          }
          self.gmSettings.profileJson = profile;
          self.gmSettings.profileAvatar = profile.picture || "";
          self.gmSettings.profileBanner = profile.banner || "";
          self.gmSettings.profileBio = profile.about || "";
          self.gmSettings.profileNip05 = profile.nip05 || "";
          self.gmSettings.profileLud16 = profile.lud16 || "";
          self.gmSettings.specRevision = m.spec_revision || "";
          var t = m.theme || {};
          var h = t.hero || {};
          self.gmSettings.theme = {
            preset: t.preset || "warm-market",
            layout: t.layout || "editorial",
            brand: Object.assign({}, t.brand || {}),
            advanced: Object.assign({}, t.advanced || {}),
            advanced_opt_in: !!t.advanced_opt_in,
            counterpart: Object.assign({}, t.counterpart || {}),
            hero: {
              slogan: h.slogan || "",
              subtitle: h.subtitle || "",
              image_url: h.image_url || "",
              primary: {
                label: (h.primary || {}).label || "",
                url: (h.primary || {}).url || ""
              },
              secondary: {
                label: (h.secondary || {}).label || "",
                url: (h.secondary || {}).url || ""
              }
            },
            footer: {
              tagline: (t.footer || {}).tagline || "",
              note: (t.footer || {}).note || "",
              logo_url: (t.footer || {}).logo_url || ""
            },
            storefront: {
              grid: (t.storefront || {}).grid || "standard",
              hero_hidden: !!(t.storefront || {}).hero_hidden
            },
            share: {
              card_image: (t.share || {}).card_image || "brand_logo",
              custom_image_url: (t.share || {}).custom_image_url || ""
            }
          };
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.loading = false;
      },
      gmSaveIdentity: async function () {
        var self = this;
        var avatar = (self.gmSettings.profileAvatar || "").trim();
        var banner = (self.gmSettings.profileBanner || "").trim();
        var bio = (self.gmSettings.profileBio || "").trim();
        var nip05 = (self.gmSettings.profileNip05 || "").trim();
        var lud16 = (self.gmSettings.profileLud16 || "").trim();
        var addressPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (avatar && !/^https:\/\//.test(avatar)) {
          self.gmSettings.error =
            "Use an https:// image address for the avatar.";
          return;
        }
        if (banner && !/^https:\/\//.test(banner)) {
          self.gmSettings.error =
            "Use an https:// image address for the header image.";
          return;
        }
        if (nip05 && !addressPattern.test(nip05)) {
          self.gmSettings.error =
            "Use a name@domain address for the Nostr address.";
          return;
        }
        if (lud16 && !addressPattern.test(lud16)) {
          self.gmSettings.error =
            "Use a name@domain address for the Lightning address.";
          return;
        }
        if (bio.length > 2000) {
          self.gmSettings.error = "Keep the bio to 2000 characters or fewer.";
          return;
        }
        var profile = Object.assign({}, self.gmSettings.profileJson || {});
        var fields = {
          picture: avatar, banner: banner, about: bio,
          nip05: nip05, lud16: lud16
        };
        Object.keys(fields).forEach(function (key) {
          if (fields[key]) profile[key] = fields[key];
          else delete profile[key];
        });
        self.gmSettings.identitySaving = true;
        try {
          var m = await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(),
            {
              display_name: self.gmSettings.displayName,
              profile_json: profile
            }
          );
          self.gm.merchant.display_name = m.display_name;
          self.gm.merchant.profile_json = m.profile_json;
          self.gmSettings.profileJson = profile;
          self.gmSettings.notice = "Identity saved.";
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.identitySaving = false;
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
          self.gmSettings.nsecReveal = "";
          self.gmSettings.notice = "Key imported.";
          await self.gmLoad();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
          self.gmSettings.nsecInput = "";
        }
        self.gmSettings.importing = false;
      },
      gmTogglePrivateKey: async function () {
        var self = this;
        if (self.gmSettings.nsecReveal) {
          self.gmSettings.nsecReveal = "";
          return;
        }
        self.gmSettings.nsecRevealing = true;
        try {
          var res = await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() + "/keys/export"
          );
          self.gmSettings.nsecReveal = res.nsec || "";
        } catch (e) {
          self.gmSettings.nsecReveal = "";
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.nsecRevealing = false;
      },
      gmChangeWallet: async function (walletId) {
        var self = this;
        var prev = self.gmSettings.walletId;
        self.gmSettings.walletId = walletId;
        try {
          await self.gmApi(
            "PATCH", "/merchants/" + self.gmMerchantId(),
            { wallet_id: walletId }
          );
          self.gmSettings.notice = "Wallet updated.";
          self.gmSettings.walletBlocked = false;
          self.gm.merchant.wallet_id = walletId;
        } catch (e) {
          /* 409 wallet-mismatch — open invoice_pending/awaiting_payment
             orders exist; the disabled-reason surfaces verbatim. */
          self.gmSettings.walletId = prev;
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
      gmEnableInbox: async function () {
        var self = this;
        self.gmSettings.inbox.busy = true;
        try {
          var res = await self.gmApi(
            "POST", "/merchants/" + self.gmMerchantId() + "/inbox/enable"
          );
          self.gmSettings.inbox.state = res.inbox_state || "pending";
          self.gmSettings.notice =
            "Inbox enabling — pending until a relay accepts the kind-10050.";
          /* Showcase/Nostr-only cards unblock once the inbox is active —
             re-read the mode gate now and poll until activation lands. */
          await self.gmRefreshModeGate();
          self.gmPollInbox();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.inbox.busy = false;
      },
      gmDisableInbox: async function () {
        var self = this;
        self.gmSettings.inbox.busy = true;
        try {
          var res = await self.gmApi(
            "POST", "/merchants/" + self.gmMerchantId() + "/inbox/disable"
          );
          self.gmSettings.inbox.state = res.inbox_state || "deactivating";
          await self.gmRefreshModeGate();
          self.gmPollInbox();
        } catch (e) {
          self.gmSettings.error = self.gmProblemCopy(e.problem);
        }
        self.gmSettings.inbox.busy = false;
      },
      gmRefreshModeGate: async function () {
        var modeRes = await this.gmApi(
          "GET", "/merchants/" + this.gmMerchantId() + "/storefront-mode"
        );
        this.gmSettings.mode.blocked = modeRes.blocked || {};
        this.gmSettings.mode.blockedReason = modeRes.blocked_reason || "";
      },
      /* Inbox activation/deactivation completes in the outbox worker —
         poll /inbox-state while it is in flight and re-read the mode gate
         when it settles. Stops on a terminal state or leaving Settings. */
      gmPollInbox: function () {
        var self = this;
        clearTimeout(self.gmInboxPollTimer);
        var state = self.gmSettings.inbox.state;
        if (state !== "pending" && state !== "deactivating") return;
        self.gmInboxPollTimer = setTimeout(async function () {
          var mid = self.gmMerchantId();
          if (self.gm.view !== "settings" || !mid) return;
          try {
            var res = await self.gmApi(
              "GET", "/merchants/" + mid + "/inbox-state"
            );
            var next = res.inbox_state || "off";
            if (next !== self.gmSettings.inbox.state) {
              self.gmSettings.inbox.state = next;
              await self.gmRefreshModeGate();
            }
          } catch (e) {
            /* transient — retry on the next tick */
          }
          self.gmPollInbox();
        }, 3000);
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
      /* Blocked cards name the live inbox state instead of the static
         server reason — "pending" means a relay still hasn't accepted
         the kind-10050, "error" means it tried and failed. */
      gmBlockedModeReason: function () {
        var s = this.gmSettings.inbox.state;
        if (s === "pending")
          return (
            "your Nostr inbox is enabling — waiting for a relay to " +
            "accept the kind-10050. It flips to active on its own."
          );
        if (s === "error")
          return (
            "your Nostr inbox failed to activate — check relay " +
            "auth/evidence in Messages, then retry Enable above."
          );
        if (s === "deactivating")
          return "your Nostr inbox is switching off — try again shortly.";
        return (
          (this.gmSettings.mode.blockedReason ||
            "requires an active Nostr inbox (kind-10050 published)") +
          " Enable it in the Nostr inbox card above."
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
      gmPairsFor: function (tokens) {
        return GATED_PAIRS.map(function (pair) {
          var fg = tokens[pair[0]];
          var bg = tokens[pair[1]];
          var ratio = contrast(fg, bg);
          return {
            pair: (TUNE_LABELS[pair[0]] || pair[0]) + " on " +
              (TUNE_LABELS[pair[1]] || pair[1]),
            ratio: ratio,
            ok: ratio >= 4.5
          };
        });
      },
      gmSetPreset: function (preset) {
        var t = this.gmSettings.theme;
        /* A counterpart tint is scheme-specific — switching direction
           (light<->dark preset) drops it rather than fail the gate on
           the wrong scheme. */
        if (PRESET_SCHEME[preset] !== PRESET_SCHEME[t.preset]) {
          t.counterpart = {};
        }
        t.preset = preset;
      },
      gmCounterpartSet: function (value) {
        this.gmSettings.theme.counterpart = { "--color-bg": value };
      },
      gmCounterpartReset: function () {
        this.gmSettings.theme.counterpart = {};
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
      /* Fine-tune helpers — the first edit opts in automatically; no
         technical toggle. Resetting the last override opts back out. */
      gmTuneValue: function (item) {
        var v = this.gmPreviewTokens[item.token];
        if (item.def === undefined) return v;
        var n = parseInt(v, 10);
        return isNaN(n) ? item.def : n;
      },
      /* The accent is stored in the brand block (existing stores keep
         their saved value); every other token is an advanced override. */
      gmTuneIsCustom: function (token) {
        var t = this.gmSettings.theme;
        if (token === "--color-accent") return !!(t.brand || {}).accent;
        var adv = t.advanced || {};
        return Object.prototype.hasOwnProperty.call(adv, token);
      },
      gmTuneSet: function (token, value, px) {
        var t = this.gmSettings.theme;
        if (token === "--color-accent") {
          if (!t.brand) t.brand = {};
          t.brand.accent = value;
          if (t.advanced) delete t.advanced["--color-accent"];
          return;
        }
        if (!t.advanced) t.advanced = {};
        t.advanced[token] = px ? Math.round(Number(value)) + "px" : value;
        t.advanced_opt_in = true;
      },
      gmTuneReset: function (token) {
        var t = this.gmSettings.theme;
        if (token === "--color-accent") {
          if (t.brand) delete t.brand.accent;
          return;
        }
        if (t.advanced) delete t.advanced[token];
        if (!t.advanced || !Object.keys(t.advanced).length) {
          t.advanced_opt_in = false;
        }
      },
      gmTuneCustomCount: function () {
        var t = this.gmSettings.theme;
        return Object.keys(t.advanced || {}).length +
          ((t.brand || {}).accent ? 1 : 0) +
          (((t.counterpart || {})["--color-bg"]) ? 1 : 0);
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
          t.counterpart = {};
          if (t.brand) delete t.brand.accent;
        }
      },
      gmSaveTheme: async function () {
        var self = this;
        if (!self.gmContrastOk) {
          var opts = self.gmSchemeOptions;
          var failing = null;
          var failingScheme = "";
          [self.gmBaseTokens, self.gmCounterpartTokens].forEach(
            function (tokens, i) {
              var bad = self.gmPairsFor(tokens).filter(function (p) {
                return !p.ok;
              })[0];
              if (bad && !failing) {
                failing = bad;
                failingScheme = opts[i].label + ": ";
              }
            });
          self.gmSettings.themeError =
            "Contrast gate failed: " + failingScheme + failing.pair +
            " = " + failing.ratio.toFixed(2) + ":1 (needs ≥4.5:1)";
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
          hero: t.hero || {},
          footer: t.footer || {},
          storefront: t.storefront || {},
          share: t.share || {card_image: "brand_logo", custom_image_url: ""},
          counterpart: t.counterpart || {},
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
      },
      /* Hero background upload (gm-media-picker @files-chosen). D-26:
         appearance fields store result.path for local uploads (the
         same-origin /library/ path always passes theme validation even
         when public_base_url is an IP literal) and result.url for
         Blossom results, which carry no path. One failed file never
         discards its siblings (MEDIA-12). */
      gmMediaHeroUpload: async function (payload) {
        var self = this;
        var files = (payload && payload.files) || [];
        if (!files.length) return;
        self.gmSettings.themeError = null;
        self.gmMedia.retryFile = null;
        self.gmMedia.retryLocal = false;
        self.gmMedia.uploading = true;
        try {
          for (var i = 0; i < files.length; i++) {
            var file = files[i];
            try {
              var res = await self.gmMediaUpload(
                file, "appearance", payload.backend,
                function (frac) { self.gmMedia.progress = frac; }
              );
              var result = (res.results || [])[0] || {};
              if (result.state === "stored") {
                self.gmSettings.theme.hero.image_url =
                  result.backend === "local"
                    ? (result.path || "")
                    : (result.url || "");
                self.gmSettings.themeNotice =
                  "Image uploaded — save appearance to keep it.";
              } else {
                self.gmSettings.themeError =
                  "The image could not be stored (" +
                  (result.reason || "unknown reason") +
                  ") — try a different file.";
              }
            } catch (e) {
              self.gmSettings.themeError = self.gmProblemCopy(e.problem);
              /* MEDIA-03: a Blossom failure keeps the file for an
                 explicit retry to LNbits — never a silent failover. */
              if (payload.backend === "blossom") {
                self.gmMedia.retryFile = file;
                self.gmMedia.retryLocal = true;
              }
            }
          }
        } finally {
          self.gmMedia.uploading = false;
          self.gmMedia.progress = 0;
        }
      },
      /* MEDIA-03 — explicit retry to LNbits after a Blossom failure:
         re-uploads the kept File with backend local; never a silent
         failover. */
      gmMediaRetryLocal: function () {
        var file = this.gmMedia.retryFile;
        if (!file) return;
        this.gmMedia.retryFile = null;
        this.gmMedia.retryLocal = false;
        this.gmMediaHeroUpload({files: [file], backend: "local"});
      },
      /* Single-image clear — a tiny dotted-path setter under
         gmSettings.theme. Clearing mutates only that one theme key, so
         unrelated appearance/profile fields are untouched (MEDIA-10);
         reused by the other single-image fields. */
      gmMediaClearField: function (path) {
        var parts = String(path || "").split(".");
        var target = this.gmSettings.theme;
        for (var i = 0; i < parts.length - 1; i++) {
          target = target ? target[parts[i]] : null;
          if (!target || typeof target !== "object") return;
        }
        if (target && parts.length) {
          target[parts[parts.length - 1]] = "";
        }
      },
      /* Embed shop — copy/paste snippets for the WebPages extension or
         any static page. The component script renders real DOM (no
         iframe); checkout always happens on the hosted shop pages. */
      gmEmbedSnippets: function () {
        var self = this;
        var pubkey = (self.gm.merchant || {}).pubkey || "<merchant-pubkey>";
        var origin = self.gmOrigin();
        var scriptUrl = origin +
          "/infinitemarkets/static/infinitemarkets/js/gm-embed.js";
        var frameUrl = origin +
          "/infinitemarkets/public/embed/merchants/" + pubkey;
        return [
          {
            id: "component-link",
            title: "Product grid — cards open the shop",
            desc: "Renders product cards inside your page (no iframe). " +
                  "Clicking a card opens the hosted product page in a new tab.",
            code:
              '<div data-gm-shop="' + pubkey + '" ' +
              'data-gm-title="Our products"></div>\n' +
              '<script src="' + scriptUrl + '" defer></' + 'script>'
          },
          {
            id: "component-modal",
            title: "Product grid — details in a popup",
            desc: "Cards open a product dialog on your page; only the Buy " +
                  "button leaves for the hosted checkout page.",
            code:
              '<div data-gm-shop="' + pubkey + '" ' +
              'data-gm-title="Our products" data-gm-mode="modal"></div>\n' +
              '<script src="' + scriptUrl + '" defer></' + 'script>'
          },
          {
            id: "iframe",
            title: "Full browse — iframe",
            desc: "Filters, sorting and pagination inside an auto-sizing " +
                  "frame; products and order tracking open new tabs.",
            code:
              '<iframe id="im-shop" src="' + frameUrl + '" ' +
              'style="width:100%;border:0" loading="lazy"></iframe>\n' +
              "<script>\n" +
              "  addEventListener('message', function (e) {\n" +
              "    if (e.data && e.data.type === 'gm-embed-height')\n" +
              "      document.getElementById('im-shop')" +
              ".style.height = e.data.height + 'px';\n" +
              "  });\n" +
              "</" + "script>"
          }
        ];
      },
      gmCopyEmbed: async function (s) {
        var self = this;
        try {
          await navigator.clipboard.writeText(s.code);
          self.gmSettings.notice =
            s.title + " — snippet copied to clipboard.";
        } catch (e) {
          self.gmSettings.notice =
            "Clipboard blocked — select the snippet text and copy it.";
        }
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
