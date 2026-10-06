/* Infinite Markets embeddable shop — a real component, not an iframe.
 *
 * Host pages (the WebPages extension or any static site) drop in:
 *
 *   <div data-gm-shop="64-hex-pubkey"></div>
 *   <script src="https://HOST/infinitemarkets/static/infinitemarkets/js/gm-embed.js"
 *           defer></script>
 *
 * The script derives the shop origin from its own src, fetches the
 * public products API, and renders cards into the container — cards
 * open the hosted product/checkout pages in a new tab. API data is
 * rendered via textContent/createElement only (never innerHTML), so a
 * hostile product title can't inject markup into the host page.
 *
 * Optional container attributes:
 *   data-gm-collection="<d_tag>"  only products in that collection
 *   data-gm-category="<slug>"     only products in that category
 *   data-gm-limit="8"             cap the number of cards
 *   data-gm-title="Shop"          heading text ('' or 'false' hides it)
 *   data-gm-scheme="dark|light"   palette override (default: follows
 *                                 prefers-color-scheme)
 *   data-gm-mode="link|modal"     'link' (default): cards open the
 *                                 hosted product page in a new tab.
 *                                 'modal': cards open a product detail
 *                                 dialog inside the host page; its Buy
 *                                 button opens hosted checkout.
 *   data-gm-target="_self"        link-mode navigation target
 *                                 (default '_blank')
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script || !script.src) return;
  var origin = new URL(script.src).origin;
  var extBase = origin + "/infinitemarkets";

  var CSS = [
    ".gmx-shop{font-family:ui-sans-serif,system-ui,sans-serif;--gmx-bg:#fff;--gmx-fg:#241f1a;--gmx-muted:#6f665c;--gmx-line:#e8e0d5;--gmx-accent:#b35c2e;--gmx-card:#fff;color:var(--gmx-fg)}",
    ".gmx-shop[data-gm-scheme='dark'],.gmx-shop.gmx-auto-dark{--gmx-bg:#1e1a16;--gmx-fg:#f2ece4;--gmx-muted:#a89c8e;--gmx-line:rgba(255,255,255,.14);--gmx-card:#2a241f}",
    ".gmx-shop .gmx-title{margin:0 0 14px;font-size:22px;font-weight:800;letter-spacing:-.01em}",
    ".gmx-shop .gmx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:18px}",
    ".gmx-shop .gmx-card{display:block;border:1px solid var(--gmx-line);border-radius:14px;overflow:hidden;background:var(--gmx-card);color:inherit;text-decoration:none;transition:box-shadow .15s ease,transform .15s ease}",
    ".gmx-shop .gmx-card:hover{box-shadow:0 6px 24px rgba(0,0,0,.10);transform:translateY(-1px)}",
    ".gmx-shop .gmx-card:focus-visible{outline:2px solid var(--gmx-accent);outline-offset:2px}",
    ".gmx-shop .gmx-art{aspect-ratio:4/3;background:var(--gmx-line);display:flex;align-items:center;justify-content:center;color:var(--gmx-muted);font-size:12px}",
    ".gmx-shop .gmx-art img{width:100%;height:100%;object-fit:cover;display:block}",
    ".gmx-shop .gmx-body{padding:10px 12px 12px}",
    ".gmx-shop .gmx-name{margin:0;font-size:15px;font-weight:650;line-height:1.3}",
    ".gmx-shop .gmx-meta{margin:4px 0 0;font-size:12.5px;color:var(--gmx-muted)}",
    ".gmx-shop .gmx-chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;background:var(--gmx-line);color:var(--gmx-fg)}",
    ".gmx-shop .gmx-chip.gmx-sold{background:transparent;border:1px solid var(--gmx-line);color:var(--gmx-muted)}",
    ".gmx-shop .gmx-price{margin:6px 0 0;font-size:15px;font-weight:750}",
    ".gmx-shop .gmx-state{color:var(--gmx-muted);font-size:14px;padding:18px 0}",
    ".gmx-shop .gmx-more{margin-top:16px;font-size:13px}",
    ".gmx-shop .gmx-more a{color:var(--gmx-accent)}",
    /* Product detail modal (data-gm-mode='modal') — the overlay mounts
       INSIDE the container so it inherits the shop's palette vars. */
    ".gmx-shop .gmx-overlay{position:fixed;inset:0;background:rgba(15,12,9,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:18px}",
    ".gmx-shop .gmx-dialog{background:var(--gmx-bg);color:var(--gmx-fg);border-radius:16px;max-width:520px;width:100%;max-height:85vh;overflow:auto;position:relative;box-shadow:0 20px 60px rgba(0,0,0,.35)}",
    ".gmx-shop .gmx-dialog .gmx-close{position:absolute;top:10px;right:10px;width:34px;height:34px;border-radius:50%;border:0;background:rgba(0,0,0,.4);color:#fff;font-size:18px;line-height:1;cursor:pointer;z-index:2}",
    ".gmx-shop .gmx-dialog .gmx-close:hover{background:rgba(0,0,0,.6)}",
    ".gmx-shop .gmx-dialog .gmx-dialog-art{aspect-ratio:16/10;background:var(--gmx-line);display:flex;align-items:center;justify-content:center;color:var(--gmx-muted);font-size:12px}",
    ".gmx-shop .gmx-dialog .gmx-dialog-art img{width:100%;height:100%;object-fit:cover;display:block}",
    ".gmx-shop .gmx-dialog .gmx-dialog-body{padding:16px 18px 20px}",
    ".gmx-shop .gmx-dialog .gmx-name{margin:0;font-size:19px;font-weight:750}",
    ".gmx-shop .gmx-dialog .gmx-meta{margin:6px 0 0;font-size:12.5px;color:var(--gmx-muted)}",
    ".gmx-shop .gmx-dialog .gmx-price{margin:8px 0 0;font-size:17px;font-weight:750}",
    ".gmx-shop .gmx-dialog .gmx-desc{margin:12px 0 0;font-size:14px;line-height:1.55;white-space:pre-wrap;max-height:200px;overflow:auto}",
    ".gmx-shop .gmx-dialog .gmx-buy{display:inline-block;margin-top:16px;padding:11px 22px;border-radius:999px;background:var(--gmx-accent);color:#fff;font-size:14px;font-weight:700;text-decoration:none;text-align:center}",
    ".gmx-shop .gmx-dialog .gmx-buy:hover{filter:brightness(1.08)}",
    ".gmx-shop .gmx-card{cursor:pointer}",
  ].join("\n");

  function injectStyle() {
    if (document.getElementById("gm-embed-css")) return;
    var style = document.createElement("style");
    style.id = "gm-embed-css";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function priceLabel(product) {
    var price = product.price || {};
    if (price.amount_minor == null) return "";
    var currency = (price.currency || "SAT").toUpperCase();
    if (currency === "SAT" || currency === "SATS") {
      return Number(price.amount_minor).toLocaleString() + " sats";
    }
    var decimals = price.decimals == null ? 2 : Number(price.decimals);
    var major = Number(price.amount_minor) / Math.pow(10, decimals);
    return (
      major.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }) + " " + currency
    );
  }

  /* Cheap de-markdown for the modal — plain text shown via textContent,
     so no markup ever reaches the host DOM. */
  function plainText(md) {
    return String(md || "")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/\*(.+?)\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^\s*[-*]\s+/gm, "• ")
      .trim();
  }

  function openProductModal(container, pubkey, product) {
    var overlay = el("div", "gmx-overlay");
    var dialog = el("div", "gmx-dialog");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", product.title || "Product");

    function close() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) {
      if (e.key === "Escape") close();
    }

    var closeBtn = el("button", "gmx-close", "✕");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Close product details");
    closeBtn.addEventListener("click", close);
    dialog.appendChild(closeBtn);

    var art = el("div", "gmx-dialog-art");
    var artHasImage = false;
    if (product.image) {
      var img = document.createElement("img");
      img.src = product.image;
      img.alt = "";
      img.referrerPolicy = "no-referrer";
      art.appendChild(img);
      artHasImage = true;
    } else {
      art.appendChild(el("span", null, "No image"));
    }
    dialog.appendChild(art);

    var body = el("div", "gmx-dialog-body");
    body.appendChild(el("h3", "gmx-name", product.title || "Untitled"));
    var meta = el("p", "gmx-meta");
    if (product.availability === "sold") {
      meta.appendChild(el("span", "gmx-chip gmx-sold", "Sold out"));
    } else if (product.availability === "preorder") {
      meta.appendChild(el("span", "gmx-chip", "Pre-order"));
    } else {
      meta.appendChild(document.createTextNode("In stock"));
    }
    if (product.format === "digital") {
      meta.appendChild(document.createTextNode(" "));
      meta.appendChild(el("span", "gmx-chip", "Digital"));
    }
    body.appendChild(meta);
    var price = priceLabel(product);
    if (price) body.appendChild(el("p", "gmx-price", price));

    var desc = el("p", "gmx-desc", "Loading details…");
    body.appendChild(desc);

    var buy = el("a", "gmx-buy", "Buy — opens the shop");
    buy.href = origin + product.url;
    buy.target = "_blank";
    buy.rel = "noopener";
    body.appendChild(buy);
    dialog.appendChild(body);

    overlay.appendChild(dialog);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });
    document.addEventListener("keydown", onKey);
    container.appendChild(overlay);
    closeBtn.focus();

    /* Fill in the full description asynchronously — the listing payload
       stays light, detail comes from the product endpoint on demand. */
    fetch(
      extBase + "/api/v1/public/products/" + pubkey + "/" + product.d_tag,
      {credentials: "omit"}
    )
      .then(function (r) {
        if (!r.ok) throw new Error("unavailable");
        return r.json();
      })
      .then(function (d) {
        var text = plainText(d.description_md || d.summary || "");
        desc.textContent = text || "No description provided.";
        var imgs = (d.images || []).filter(function (i) {
          return i.url;
        });
        if (imgs.length && !artHasImage) {
          art.textContent = "";
          var first = document.createElement("img");
          first.src = imgs[0].url;
          first.alt = "";
          first.referrerPolicy = "no-referrer";
          art.appendChild(first);
        }
      })
      .catch(function () {
        desc.textContent = "";
      });
  }

  function card(container, pubkey, product, opts) {
    var link = el("a", "gmx-card");
    link.href = origin + product.url;
    if (opts.mode === "modal") {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        openProductModal(container, pubkey, product);
      });
    } else {
      link.target = opts.target;
      link.rel = "noopener";
    }

    var art = el("div", "gmx-art");
    if (product.image) {
      var img = document.createElement("img");
      img.src = product.image;
      img.alt = "";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      art.appendChild(img);
    } else {
      art.appendChild(el("span", null, "No image"));
    }
    link.appendChild(art);

    var body = el("div", "gmx-body");
    body.appendChild(el("h3", "gmx-name", product.title || "Untitled"));

    var meta = el("p", "gmx-meta");
    if (product.availability === "sold") {
      meta.appendChild(el("span", "gmx-chip gmx-sold", "Sold out"));
    } else if (product.availability === "preorder") {
      meta.appendChild(el("span", "gmx-chip", "Pre-order"));
    } else {
      meta.appendChild(document.createTextNode("In stock"));
    }
    if (product.format === "digital") {
      meta.appendChild(document.createTextNode(" "));
      meta.appendChild(el("span", "gmx-chip", "Digital"));
    }
    body.appendChild(meta);

    var price = priceLabel(product);
    if (price) body.appendChild(el("p", "gmx-price", price));
    link.appendChild(body);
    return link;
  }

  function state(container, text) {
    container.appendChild(el("p", "gmx-state", text));
  }

  function mount(container) {
    var pubkey = container.getAttribute("data-gm-shop") || "";
    if (!/^[0-9a-f]{64}$/i.test(pubkey)) {
      container.textContent =
        "Infinite Markets embed: set data-gm-shop to a 64-char hex pubkey.";
      return;
    }
    injectStyle();
    container.classList.add("gmx-shop");
    container.textContent = "";
    var scheme = container.getAttribute("data-gm-scheme") || "";
    if (scheme === "dark" || scheme === "light") {
      container.setAttribute("data-gm-scheme", scheme);
    } else if (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      container.classList.add("gmx-auto-dark");
    }

    var params = new URLSearchParams();
    var collection = container.getAttribute("data-gm-collection");
    var category = container.getAttribute("data-gm-category");
    if (collection) params.set("collection", collection);
    if (category) params.set("category", category);
    var url =
      extBase +
      "/api/v1/public/merchants/" +
      pubkey +
      "/products" +
      (params.toString() ? "?" + params : "");

    state(container, "Loading products…");
    fetch(url, {credentials: "omit"})
      .then(function (r) {
        if (!r.ok) throw new Error("shop unavailable (" + r.status + ")");
        return r.json();
      })
      .then(function (data) {
        container.textContent = "";
        var title = container.getAttribute("data-gm-title");
        if (title) container.appendChild(el("h2", "gmx-title", title));

        var products = (data && data.products) || [];
        var limit = parseInt(container.getAttribute("data-gm-limit"), 10);
        if (limit > 0) products = products.slice(0, limit);

        if (!products.length) {
          state(container, "No products on sale yet.");
          return;
        }
        var opts = {
          mode: container.getAttribute("data-gm-mode") === "modal"
            ? "modal"
            : "link",
          target: container.getAttribute("data-gm-target") === "_self"
            ? "_self"
            : "_blank",
        };
        var grid = el("div", "gmx-grid");
        products.forEach(function (p) {
          grid.appendChild(card(container, pubkey, p, opts));
        });
        container.appendChild(grid);

        if (limit > 0 && (data.products || []).length > limit) {
          var more = el("p", "gmx-more");
          var link = el(
            "a",
            null,
            "See all products in the full shop →"
          );
          link.href = extBase + "/public/merchants/" + pubkey;
          link.target = "_blank";
          link.rel = "noopener";
          more.appendChild(link);
          container.appendChild(more);
        }
      })
      .catch(function (err) {
        container.textContent = "";
        state(container, "Couldn't load this shop (" + err.message + ").");
      });
  }

  function boot() {
    var containers = document.querySelectorAll("[data-gm-shop]");
    for (var i = 0; i < containers.length; i++) mount(containers[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
