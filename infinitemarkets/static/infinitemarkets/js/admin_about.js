/* admin_about.js — About + More tabs: what the extension is, who made it,
   a screenshot tour of the admin panel and the public storefront, and
   links to docs, source and related specs. Static content only — no API
   calls, no merchant data. External links open in a new tab with
   rel="noopener". */
(function () {
  "use strict";

  var IMG = "/infinitemarkets/static/infinitemarkets/img/screenshots/";
  var REPO = "https://github.com/bitkarrot/infinitemarkets";

  var SHOTS = {
    admin: [
      { file: "admin-orders.jpg", title: "Orders",
        caption: "Order workspace: search, filter and move orders through " +
                 "their states with a full audit trail." },
      { file: "admin-categories.jpg", title: "Catalog: products & categories",
        caption: "One primary category per product, plus collections and " +
                 "shipping options, with bulk editing." },
      { file: "admin-publications.jpg", title: "Publications",
        caption: "Relay health and every outbox entry with timestamps and " +
                 "per-relay delivery evidence." },
      { file: "admin-messages.jpg", title: "Messages",
        caption: "Encrypted order conversations as a list and chat thread " +
                 "(demo conversation shown)." },
      { file: "admin-appearance.jpg", title: "Appearance",
        caption: "Preset, layout, brand, hero and footer with a live " +
                 "storefront preview." },
      { file: "admin-embed.jpg", title: "Embed",
        caption: "Copy-ready snippets to embed your shop in any page, " +
                 "including the WebPages extension." }
    ],
    storefront: [
      { file: "store-home.jpg", title: "Storefront",
        caption: "Configurable hero, category and collection browsing, " +
                 "price slider and sorting." },
      { file: "store-product.jpg", title: "Product page",
        caption: "Gallery, description and a Lightning checkout that " +
                 "starts right on the page." },
      { file: "store-gallery.jpg", title: "Gallery layout",
        caption: "Four layouts — Editorial, Guided, Compact and Gallery — " +
                 "over the same data." },
      { file: "store-dark.jpg", title: "Dark mode",
        caption: "Shoppers can switch between light and dark from the " +
                 "store navigation." },
      { file: "store-mobile.jpg", title: "Mobile",
        caption: "Compact, touch-friendly layout on small screens." },
      { file: "store-embed.jpg", title: "Embedded on a page",
        caption: "The shop component rendered inside a static web page, " +
                 "no iframe." }
    ]
  };

  var LINK_GROUPS = [
    {
      title: "Project",
      links: [
        { label: "Source code on GitHub", href: REPO,
          icon: "code", note: "bitkarrot/infinitemarkets — MIT licensed" },
        { label: "Releases & changelog", href: REPO + "/releases",
          icon: "new_releases", note: "Download builds and read release notes" },
        { label: "Report a bug or request a feature",
          href: REPO + "/issues", icon: "bug_report",
          note: "Open an issue on GitHub" },
        { label: "Demo video",
          href: REPO + "/blob/main/docs/assets/infinitemarkets_demo.mp4",
          icon: "smart_display",
          note: "Key import, publishing, a live Lightning purchase" }
      ]
    },
    {
      title: "Documentation",
      links: [
        { label: "README — install & configuration", href: REPO + "#readme",
          icon: "menu_book", note: "Requirements, secrets, tuning, embedding" },
        { label: "Technical specification",
          href: REPO + "/blob/main/docs/technical-specification.md",
          icon: "description", note: "Normative behaviour and API contracts" },
        { label: "Architecture overview",
          href: REPO + "/blob/main/docs/architecture-overview.md",
          icon: "account_tree", note: "How the pieces fit together" }
      ]
    },
    {
      title: "Related",
      links: [
        { label: "LNbits", href: "https://github.com/lnbits/lnbits",
          icon: "bolt", note: "The Lightning wallet platform this extends" },
        { label: "LNbits documentation", href: "https://docs.lnbits.com",
          icon: "library_books", note: "Extensions, funding sources, admin guide" },
        { label: "NIP-99 — classified listings",
          href: "https://github.com/nostr-protocol/nips/blob/master/99.md",
          icon: "sell", note: "How products are published on Nostr" },
        { label: "NIP-17 — private direct messages",
          href: "https://github.com/nostr-protocol/nips/blob/master/17.md",
          icon: "lock", note: "How encrypted order messages travel" }
      ]
    }
  ];

  window.app.mixin({
    data: function () {
      return {
        gmAbout: {
          tab: "about",
          creator: "bitkarrot",
          creatorUrl: "https://github.com/bitkarrot",
          repoUrl: REPO,
          shots: SHOTS,
          linkGroups: LINK_GROUPS,
          preview: { show: false, src: "", title: "", caption: "" }
        }
      };
    },
    computed: {
      /* Read lazily at render time — the mixin data() can resolve before
         the DOM attribute is present. */
      gmAboutVersion: function () {
        var root = document.getElementById("gm-admin-root");
        return (root && root.getAttribute("data-version")) || "";
      }
    },
    methods: {
      gmAboutShot: function (s) {
        return IMG + s.file;
      },
      gmAboutOpen: function (s) {
        this.gmAbout.preview = {
          show: true, src: IMG + s.file, title: s.title, caption: s.caption
        };
      }
    }
  });
})();
