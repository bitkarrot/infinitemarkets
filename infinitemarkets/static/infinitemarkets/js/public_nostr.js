/* public_nostr.js — NIP-07 buyer sign-in, account menu, orders + profile.

   Flow: "Sign in with Nostr" (rendered only when the shop's inbox is
   active, D-06) -> GET /nostr/challenge -> window.nostr.signEvent
   (kind 22242, challenge in content + tag) -> POST /nostr/verify ->
   HttpOnly session cookie. Signed-in state collapses to a header
   account chip (avatar + name from the buyer's kind-0) with a menu:
   My orders (/infinitemarkets/orders), Profile (/infinitemarkets/profile),
   Sign out. The session token never touches JS — the cookie is HttpOnly.
   All DOM builds go through GM.h (no innerHTML with API values). */
(function () {
  "use strict";

  var GM = window.GM || {};
  var API = "/infinitemarkets/api/v1/public";
  var KIND_SIGNIN = 22242;

  var account = document.getElementById("gm-nostr-account");
  var btn = document.getElementById("gm-nostr-signin");
  var menu = document.getElementById("gm-nostr-menu");
  if (!account || !btn || !menu) return;

  var ordersBody = document.getElementById("gm-orders-body");
  var profileBody = document.getElementById("gm-profile-body");

  var state = {
    signedIn: false,
    npub: "",
    pubkey: "",
    profile: null,
    orders: [],
    busy: false,
    menuOpen: false,
    notice: ""
  };

  /*: Kind-0 fields the profile editor manages. */
  var PROFILE_FIELDS = [
    { key: "name", label: "Username", max: 100 },
    { key: "display_name", label: "Display name", max: 100 },
    { key: "picture", label: "Avatar URL", max: 500, hint: "https:// image address" },
    { key: "about", label: "About", max: 2000, area: true },
    { key: "nip05", label: "Nostr address (NIP-05)", max: 200, hint: "you@example.com" },
    { key: "lud16", label: "Lightning address (LUD-16)", max: 200 },
    { key: "website", label: "Website", max: 500 },
    { key: "banner", label: "Banner image URL", max: 500 }
  ];

  function shopQuery() {
    var root = document.querySelector(".gm-public[data-shop]");
    var shop = root ? root.getAttribute("data-shop") : "";
    return /^[0-9a-f]{64}$/.test(shop || "") ? "?shop=" + shop : "";
  }

  function pageUrl(path) {
    return "/infinitemarkets" + path + shopQuery();
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

  function note(text, cls) {
    return GM.h("p", { class: "nostr-note " + (cls || ""), text: text });
  }

  function npubShort(npub) {
    return GM.trunc(npub || "", 12, 6);
  }

  function displayName() {
    var p = state.profile || {};
    return p.display_name || p.name || npubShort(state.npub);
  }

  function avatarEl(size) {
    /* Avatar: the buyer's kind-0 picture when it is an https:// URL —
       otherwise a letter chip. Never innerHTML; onerror falls back. */
    var url = (state.profile && state.profile.picture) || "";
    if (/^https:\/\//i.test(url)) {
      var img = GM.h("img", {
        class: "nostr-avatar" + (size ? " nostr-avatar-" + size : ""),
        src: url,
        alt: "",
        referrerpolicy: "no-referrer",
        loading: "lazy"
      });
      img.addEventListener("error", function () {
        img.replaceWith(avatarFallback(size));
      });
      return img;
    }
    return avatarFallback(size);
  }

  function avatarFallback(size) {
    var initial = (displayName() || "N").trim().charAt(0).toUpperCase();
    return GM.h("span", {
      class: "nostr-avatar nostr-avatar-fallback" +
        (size ? " nostr-avatar-" + size : ""),
      "aria-hidden": "true",
      text: initial
    });
  }

  /* --- account chip + menu ---------------------------------------------- */

  function renderChip() {
    GM.clear(btn);
    btn.classList.toggle("nostr-chip", state.signedIn);
    if (state.signedIn) {
      btn.appendChild(avatarEl("sm"));
      btn.appendChild(
        GM.h("span", { class: "nostr-chip-name", text: displayName() })
      );
      btn.appendChild(
        GM.h("span", { class: "nostr-chip-caret", "aria-hidden": "true", text: "▾" })
      );
    } else {
      btn.textContent = "Sign in with Nostr";
    }
    btn.setAttribute("aria-expanded", state.menuOpen ? "true" : "false");
  }

  function menuItem(el) {
    el.setAttribute("role", "menuitem");
    return el;
  }

  function renderMenu() {
    GM.clear(menu);
    if (state.signedIn) {
      menu.appendChild(
        GM.h("div", { class: "nostr-menu-head" }, [
          avatarEl("lg"),
          GM.h("div", { class: "nostr-menu-id" }, [
            GM.h("strong", { text: displayName() }),
            GM.h("span", { class: "nostr-menu-npub", text: npubShort(state.npub) })
          ])
        ])
      );
      menu.appendChild(
        menuItem(GM.h("a", {
          class: "nostr-menu-item",
          href: pageUrl("/orders"),
          text: "My orders"
        }))
      );
      menu.appendChild(
        menuItem(GM.h("a", {
          class: "nostr-menu-item",
          href: pageUrl("/profile"),
          text: "Profile"
        }))
      );
      var out = menuItem(GM.h("button", {
        type: "button",
        class: "nostr-menu-item nostr-menu-signout",
        id: "gm-nostr-signout",
        text: "Sign out"
      }));
      out.addEventListener("click", doSignOut);
      menu.appendChild(out);
    } else {
      menu.appendChild(
        GM.h("div", { class: "nostr-menu-head" }, [
          GM.h("p", {
            class: "nostr-lead",
            text: "Sign in with your Nostr key to see your orders from this shop."
          }),
          note(
            "You need a Nostr signing extension (NIP-07) in this browser —" +
              " for example Alby or nos2x. Nothing is shared with the shop" +
              " beyond a signature that proves your key."
          )
        ])
      );
      var signin = menuItem(GM.h("button", {
        type: "button",
        class: "btn-primary nostr-menu-signin",
        id: "gm-nostr-menu-signin",
        text: state.busy ? "Waiting for signer…" : "Sign in with Nostr"
      }));
      signin.addEventListener("click", doSignIn);
      menu.appendChild(signin);
      if (state.notice) {
        menu.appendChild(note(state.notice));
      }
    }
  }

  function setMenu(open) {
    state.menuOpen = open;
    menu.hidden = !open;
    if (open) renderMenu();
    renderChip();
  }

  document.addEventListener("click", function (e) {
    if (state.menuOpen && !account.contains(e.target)) setMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && state.menuOpen) setMenu(false);
  });

  /* --- orders page -------------------------------------------------------- */

  function orderRow(order) {
    var label = GM.STATE_LABELS[order.state] || order.state || "";
    var row = GM.h("li", { class: "nostr-order", "data-gm": "nostr-order" });
    var head = GM.h("div", { class: "nostr-order-head" }, [
      GM.h("strong", { text: order.first_item || "Order" }),
      GM.h("span", { class: "status-pill", text: label })
    ]);
    row.appendChild(head);
    var meta = [];
    if (order.total_sat !== null && order.total_sat !== undefined) {
      meta.push(GM.sats(order.total_sat));
    }
    if (order.created_at) {
      meta.push(new Date(order.created_at * 1000).toLocaleDateString());
    }
    if (meta.length) {
      row.appendChild(
        GM.h("p", { class: "nostr-order-meta", text: meta.join(" · ") })
      );
    }
    if (order.digital_delivery && order.digital_delivery.length) {
      var delivery = GM.h("div", { class: "nostr-delivery" });
      GM.renderDelivery(delivery, order.digital_delivery);
      row.appendChild(delivery);
    }
    var links = GM.h("div", { class: "nostr-order-links" });
    if (order.status_url) {
      var link = GM.h("a", {
        href: order.status_url,
        text: "View order details",
        class: "nostr-order-link"
      });
      links.appendChild(link);
    }
    if (links.childNodes.length) row.appendChild(links);
    return row;
  }

  function signInPrompt(text) {
    var box = GM.h("div", { class: "nostr-box", "data-gm": "nostr-signed-out" }, [
      GM.h("p", { class: "nostr-lead", text: text }),
      note(
        "Use the “Sign in with Nostr” button in the top bar — a NIP-07" +
          " extension (Alby, nos2x) signs a proof; nothing else is shared."
      )
    ]);
    var go = GM.h("button", {
      type: "button",
      class: "btn-primary",
      text: "Sign in with Nostr"
    });
    go.addEventListener("click", function () {
      setMenu(true);
      doSignIn();
    });
    box.appendChild(go);
    return box;
  }

  function renderOrdersPage() {
    if (!ordersBody) return;
    GM.clear(ordersBody);
    if (!state.signedIn) {
      ordersBody.appendChild(
        signInPrompt("Sign in with your Nostr key to see your orders.")
      );
      return;
    }
    var box = GM.h("div", { class: "nostr-box", "data-gm": "nostr-signed-in" });
    if (!state.orders.length) {
      box.appendChild(note("No orders yet — your orders will appear here."));
    } else {
      var list = GM.h("ul", { class: "nostr-orders" });
      state.orders.forEach(function (o) {
        list.appendChild(orderRow(o));
      });
      box.appendChild(list);
    }
    /* Claim: paste a private order link to bind it to this key (D-05). */
    var claimBox = GM.h("div", { class: "nostr-claim" }, [
      GM.h("label", {
        for: "gm-claim-input",
        class: "nostr-claim-label",
        text: "Have a private order link? Paste it to link the order to this key."
      }),
      GM.h("input", {
        type: "text",
        id: "gm-claim-input",
        class: "nostr-claim-input",
        "data-gm": "claim-input",
        "aria-label": "Private order link"
      }),
      GM.h("button", {
        type: "button",
        class: "btn-secondary",
        id: "gm-claim-btn",
        text: "Link this order to my Nostr key"
      }),
      GM.h("p", { class: "nostr-claim-msg", id: "gm-claim-msg" })
    ]);
    box.appendChild(claimBox);
    ordersBody.appendChild(box);

    var claimBtn = document.getElementById("gm-claim-btn");
    if (claimBtn) claimBtn.addEventListener("click", doClaim);
  }

  /* --- profile page ------------------------------------------------------- */

  function renderProfilePage() {
    if (!profileBody) return;
    GM.clear(profileBody);
    if (!state.signedIn) {
      profileBody.appendChild(
        signInPrompt("Sign in with your Nostr key to edit your profile.")
      );
      return;
    }
    var p = state.profile || {};
    var form = GM.h("form", {
      class: "nostr-box nostr-form",
      id: "gm-profile-form",
      novalidate: "novalidate"
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      doSaveProfile();
    });
    form.appendChild(
      GM.h("div", { class: "nostr-form-head" }, [
        avatarEl("lg"),
        GM.h("p", {
          class: "nostr-note",
          text: "Editing as " + npubShort(state.npub) +
            " — saved to your Nostr profile (kind-0), signed by your key" +
            " and published to this shop's relays."
        })
      ])
    );
    PROFILE_FIELDS.forEach(function (f) {
      var field = GM.h("div", { class: "field" });
      field.appendChild(
        GM.h("label", {
          for: "gm-profile-" + f.key,
          text: f.label +
            (f.key === "name" || f.key === "display_name" ? "" : " (optional)")
        })
      );
      if (f.area) {
        field.appendChild(GM.h("textarea", {
          id: "gm-profile-" + f.key,
          rows: "4",
          maxlength: String(f.max),
          text: p[f.key] || ""
        }));
      } else {
        field.appendChild(GM.h("input", {
          type: f.key === "picture" || f.key === "banner" || f.key === "website"
            ? "url" : "text",
          id: "gm-profile-" + f.key,
          maxlength: String(f.max),
          value: p[f.key] || "",
          placeholder: f.hint || "",
          autocomplete: "off"
        }));
      }
      form.appendChild(field);
    });
    var actions = GM.h("div", { class: "nostr-form-actions" }, [
      GM.h("button", {
        type: "submit",
        class: "btn-primary",
        id: "gm-profile-save",
        text: state.busy ? "Saving…" : "Save profile"
      }),
      GM.h("p", {
        class: "nostr-claim-msg",
        id: "gm-profile-msg",
        "aria-live": "polite"
      })
    ]);
    form.appendChild(actions);
    profileBody.appendChild(form);
  }

  function doSaveProfile() {
    var msg = document.getElementById("gm-profile-msg");
    if (state.busy || !msg) return;
    if (!window.nostr || typeof window.nostr.signEvent !== "function") {
      msg.textContent =
        "No Nostr signer found — a NIP-07 extension is required to save.";
      return;
    }
    /* Merge onto the fetched kind-0 content so keys outside the editor
       (e.g. fields another client set) survive the update. */
    var content = Object.assign({}, state.profile || {});
    PROFILE_FIELDS.forEach(function (f) {
      var el = document.getElementById("gm-profile-" + f.key);
      var v = el ? el.value.trim() : "";
      if (v) content[f.key] = v;
      else delete content[f.key];
    });
    state.busy = true;
    msg.textContent = "Waiting for your signer…";
    window.nostr
      .signEvent({
        kind: 0,
        created_at: Math.floor(Date.now() / 1000),
        content: JSON.stringify(content),
        tags: []
      })
      .then(function (signed) {
        return api("/nostr/profile", {
          method: "POST",
          body: JSON.stringify({ event: JSON.stringify(signed) })
        });
      })
      .then(function (res) {
        if (!res) return;
        if (res.status === 200 && res.body && res.body.published) {
          state.profile = content;
          renderChip();
          msg.textContent =
            "Profile published — it may take a moment to reach other apps.";
          return;
        }
        if (res.status === 200 && res.body && res.body.failed) {
          msg.textContent =
            "Saved signature was valid but no relay accepted the event —" +
            " try again shortly.";
          return;
        }
        msg.textContent = "Profile could not be saved. Try again.";
      })
      .catch(function () {
        msg.textContent = "Signing was cancelled or failed — nothing saved.";
      })
      .finally(function () {
        state.busy = false;
        var save = document.getElementById("gm-profile-save");
        if (save) save.textContent = "Save profile";
      });
  }

  /* --- flows -------------------------------------------------------------- */

  function loadOrders() {
    return api("/nostr/orders").then(function (res) {
      if (res.status === 200) {
        state.orders = (res.body && res.body.orders) || [];
      } else {
        state.orders = [];
      }
      renderOrdersPage();
    });
  }

  function loadIdentity() {
    return api("/nostr/profile").then(function (res) {
      if (res.status === 200 && res.body) {
        state.signedIn = true;
        state.pubkey = res.body.pubkey || "";
        state.npub = res.body.npub || "";
        state.profile = res.body.profile || null;
      } else {
        state.signedIn = false;
        state.pubkey = "";
        state.npub = "";
        state.profile = null;
      }
      renderChip();
      if (state.menuOpen) renderMenu();
      renderOrdersPage();
      renderProfilePage();
      return state.signedIn;
    });
  }

  function doSignIn() {
    if (state.busy) return;
    /* Extension-absent is a friendly state, never a crash. */
    if (!window.nostr || typeof window.nostr.signEvent !== "function") {
      state.notice =
        "No Nostr signer found. Install a NIP-07 extension" +
        " (for example Alby or nos2x), then try again.";
      if (!state.menuOpen) setMenu(true);
      else renderMenu();
      return;
    }
    state.busy = true;
    state.notice = "";
    setMenu(true);
    api("/nostr/challenge" + shopQuery())
      .then(function (res) {
        if (res.status !== 200 || !res.body.challenge) {
          throw new Error("challenge failed");
        }
        var challenge = res.body.challenge;
        return window.nostr
          .signEvent({
            kind: KIND_SIGNIN,
            created_at: Math.floor(Date.now() / 1000),
            content: challenge,
            tags: [["challenge", challenge]]
          })
          .then(function (signed) {
            return api("/nostr/verify" + shopQuery(), {
              method: "POST",
              body: JSON.stringify({ event: JSON.stringify(signed) })
            });
          });
      })
      .then(function (res) {
        if (!res) return;
        if (res.status === 200) {
          state.notice = "";
          return loadIdentity().then(function () {
            loadOrders();
          });
        }
        if (res.status !== undefined) {
          state.notice =
            "Sign-in could not be verified. Try again — your signer may" +
            " have declined or the request expired.";
          renderMenu();
        }
      })
      .catch(function () {
        state.notice =
          "Sign-in was cancelled or failed. Try again when you're ready.";
        renderMenu();
      })
      .finally(function () {
        state.busy = false;
      });
  }

  function doSignOut() {
    api("/nostr/logout", { method: "POST" }).finally(function () {
      state.signedIn = false;
      state.npub = "";
      state.pubkey = "";
      state.profile = null;
      state.orders = [];
      setMenu(false);
      renderOrdersPage();
      renderProfilePage();
    });
  }

  function extractToken(raw) {
    /* Accept a bare token or a full private link — the fragment after
       '#' carries the bearer token (§5.4 contract). */
    raw = String(raw || "").trim();
    var hashIdx = raw.indexOf("#");
    if (hashIdx >= 0) raw = raw.slice(hashIdx + 1);
    return raw;
  }

  function doClaim() {
    var input = document.getElementById("gm-claim-input");
    var msg = document.getElementById("gm-claim-msg");
    if (!input || !msg) return;
    var token = extractToken(input.value);
    if (!token) {
      msg.textContent = "Paste your private order link first.";
      return;
    }
    msg.textContent = "";
    api("/nostr/claim", {
      method: "POST",
      body: JSON.stringify({ token: token })
    }).then(function (res) {
      if (res.status === 200) {
        return loadOrders().then(function () {
          /* loadOrders() re-renders the page — write the confirmation
             into the FRESH claim-msg element, not the discarded one. */
          var fresh = document.getElementById("gm-claim-msg");
          if (fresh) {
            fresh.textContent =
              "Order linked — it now appears in your history.";
          }
        });
      }
      msg.textContent =
        "That link could not be linked. Check the link and try again.";
    });
  }

  /* --- wiring ------------------------------------------------------------- */

  btn.addEventListener("click", function () {
    if (state.signedIn) {
      setMenu(!state.menuOpen);
      return;
    }
    setMenu(true);
    doSignIn();
  });

  /* Signed-in detection probes the session once per page view — a 401 is
     the normal signed-out signal (no cookie is readable from JS). The
     profile probe also returns kind-0 name/avatar for the chip. */
  loadIdentity().then(function (signedIn) {
    if (signedIn && ordersBody) loadOrders();
    else if (ordersBody) renderOrdersPage();
  });
})();
