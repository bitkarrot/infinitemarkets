/* public_nostr.js — buyer sign-in (Nostr NIP-07 or email magic link),
   account menu, orders + profile.

   Flow: the sign-in modal offers BOTH methods (D-13) — "Sign in with
   Nostr" (GET /nostr/challenge -> window.nostr.signEvent kind 22242 ->
   POST /nostr/verify) and "Email me a sign-in link" (POST
   /nostr/email/request -> the mailed fragment link lands on
   /auth/email). Both end at the same HttpOnly session cookie. The
   chip renders whenever EITHER method can work (the server-side
   nostr_signin ctx flag); per-method availability arrives via the
   /nostr/challenge capability flags — an unavailable method renders
   an honest hint, never a dead control. Signed-in state collapses to
   a header account chip (avatar + name from the buyer's kind-0, else
   the verified email) with a menu: My orders, Profile, Sign out. The
   session token never touches JS — the cookie is HttpOnly.
   All DOM builds go through GM.h (no innerHTML with API values). */
(function () {
  "use strict";

  var GM = window.GM || {};
  var API = "/infinitemarkets/api/v1/public";
  var KIND_SIGNIN = 22242;

  var account = document.getElementById("gm-nostr-account");
  var btn = document.getElementById("gm-nostr-signin");
  var menu = document.getElementById("gm-nostr-menu");
  var backdrop = document.getElementById("gm-nostr-backdrop");
  var modal = document.getElementById("gm-nostr-modal");
  if (!account || !btn || !menu || !backdrop || !modal) return;

  var ordersBody = document.getElementById("gm-orders-body");
  var profileBody = document.getElementById("gm-profile-body");

  var state = {
    signedIn: false,
    npub: "",
    pubkey: "",
    email: "",
    profile: null,
    orders: [],
    busy: false,
    menuOpen: false,
    modalOpen: false,
    notice: "",
    nsecSignin: false,
    flagFetched: false,
    nsecOpen: false,
    /* Per-method availability from the /nostr/challenge capability
       flags — optimistic-true until the first probe so the Nostr path
       is never regressed when the flags are absent. */
    nostrAvailable: true,
    emailAvailable: true,
    emailSent: false,
    emailNotice: ""
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

  /* Uniform no-oracle copy for the email request — ONE literal for
     every outcome (known/unknown/capped addresses are
     indistinguishable). Request-level failures append a retry tail. */
  var EMAIL_SENT_COPY =
    "Check your email — if that address can sign in here," +
    " a link is on its way.";

  function note(text, cls) {
    return GM.h("p", { class: "nostr-note " + (cls || ""), text: text });
  }

  function npubShort(npub) {
    return GM.trunc(npub || "", 12, 6);
  }

  function truncMiddle(s, max) {
    s = String(s || "");
    if (s.length <= max) return s;
    var head = Math.ceil((max - 1) / 2);
    var tail = max - 1 - head;
    return s.slice(0, head) + "…" + s.slice(s.length - tail);
  }

  function displayName() {
    var p = state.profile || {};
    return (
      p.display_name || p.name || npubShort(state.npub) ||
      truncMiddle(state.email, 28)
    );
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
      btn.textContent = "Sign in";
    }
    btn.setAttribute("aria-expanded", state.menuOpen ? "true" : "false");
  }

  function menuItem(el) {
    el.setAttribute("role", "menuitem");
    return el;
  }

  function renderMenu() {
    /* The dropdown is signed-in only — signed-out opens the modal. */
    GM.clear(menu);
    menu.appendChild(
      GM.h("div", { class: "nostr-menu-head" }, [
        avatarEl("lg"),
        GM.h("div", { class: "nostr-menu-id" }, [
          GM.h("strong", { text: displayName() }),
          GM.h("span", {
            class: "nostr-menu-npub",
            text: state.npub
              ? npubShort(state.npub)
              : truncMiddle(state.email, 40)
          })
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
  }

  /* --- sign-in modal ------------------------------------------------------ */

  function renderModal() {
    /* Re-renders (capability-flag probe, busy flips) rebuild the DOM —
       keep what the buyer already typed instead of wiping it. */
    var keepEmail = "";
    var keepNsec = "";
    var curEmail = document.getElementById("gm-email-input");
    var curNsec = document.getElementById("gm-nsec-input");
    if (curEmail && modal.contains(curEmail)) keepEmail = curEmail.value;
    if (curNsec && modal.contains(curNsec)) keepNsec = curNsec.value;
    GM.clear(modal);
    var close = GM.h("button", {
      type: "button",
      class: "nostr-modal-close",
      "aria-label": "Close",
      text: "×"
    });
    close.addEventListener("click", closeModal);
    modal.appendChild(close);
    modal.appendChild(
      GM.h("h2", { id: "gm-nostr-modal-title", text: "Sign in" })
    );
    /* Method 1 — Nostr (NIP-07). The method always renders; when the
       shop's inbox is off the challenge flag renders an honest hint
       (show-with-hint, never a dead control). */
    var nostrMethod = GM.h("div", { class: "nostr-method" });
    nostrMethod.appendChild(
      note(
        "A browser signer (NIP-07) proves your key — no password," +
          " nothing shared with the shop."
      )
    );
    var signin = GM.h("button", {
      type: "button",
      class: "btn-primary",
      id: "gm-nostr-modal-signin",
      text: state.busy ? "Waiting for signer…" : "Sign in with Nostr"
    });
    signin.addEventListener("click", doSignIn);
    nostrMethod.appendChild(signin);
    if (!state.nostrAvailable) {
      nostrMethod.appendChild(
        note(
          "Nostr sign-in isn't available on this shop —" +
            " use email below.",
          "nostr-method-hint"
        )
      );
    }
    /* Dev/e2e path — rendered only when the deployment enables
       INFINITEMARKETS_NSEC_SIGNIN (challenge response flag). */
    if (state.nsecSignin) {
      var nsecRow = GM.h("div", { class: "nostr-nsec" });
      if (state.nsecOpen) {
        var input = GM.h("input", {
          type: "password",
          id: "gm-nsec-input",
          class: "nostr-claim-input",
          placeholder: "nsec1…",
          autocomplete: "off",
          "aria-label": "Secret key (nsec)"
        });
        var go = GM.h("button", {
          type: "button",
          class: "btn-secondary",
          id: "gm-nsec-btn",
          text: "Sign in with key"
        });
        go.addEventListener("click", doNsecSignin);
        if (keepNsec) input.value = keepNsec;
        nsecRow.appendChild(input);
        nsecRow.appendChild(go);
      } else {
        var toggle = GM.h("button", {
          type: "button",
          class: "nostr-nsec-toggle",
          id: "gm-nsec-toggle",
          text: "Use a key instead"
        });
        toggle.addEventListener("click", function () {
          state.nsecOpen = true;
          renderModal();
          var el = document.getElementById("gm-nsec-input");
          if (el) el.focus();
        });
        nsecRow.appendChild(toggle);
      }
      nostrMethod.appendChild(nsecRow);
    }
    modal.appendChild(nostrMethod);

    /* Method 2 — email magic link (D-13). Always rendered; the input
       + button disable with an honest hint when the host can't send
       (the emailed link lands on /auth/email and verifies there). */
    modal.appendChild(
      GM.h("div", { class: "nostr-method-divider" }, [
        GM.h("span", { text: "or" })
      ])
    );
    var emailMethod = GM.h("div", {
      class: "nostr-method",
      "data-gm": "email-method"
    });
    if (state.emailSent) {
      emailMethod.appendChild(
        note(state.emailNotice || EMAIL_SENT_COPY)
      );
    } else {
      emailMethod.appendChild(
        GM.h("label", {
          for: "gm-email-input",
          class: "nostr-claim-label",
          text: "Sign in with email"
        })
      );
      var emailInput = GM.h("input", {
        type: "email",
        id: "gm-email-input",
        "data-gm": "email-input",
        class: "nostr-claim-input",
        autocomplete: "email",
        maxlength: "254",
        placeholder: "you@example.com"
      });
      var emailBtn = GM.h("button", {
        type: "button",
        class: "btn-primary",
        id: "gm-email-btn",
        text: state.busy ? "Sending…" : "Email me a sign-in link"
      });
      emailBtn.addEventListener("click", doEmailRequest);
      if (keepEmail) emailInput.value = keepEmail;
      if (!state.emailAvailable) {
        emailInput.disabled = true;
        emailBtn.disabled = true;
      }
      emailMethod.appendChild(emailInput);
      emailMethod.appendChild(emailBtn);
      if (!state.emailAvailable) {
        emailMethod.appendChild(
          note(
            "Email sign-in isn't configured on this host —" +
              " use Nostr above or contact the shop.",
            "nostr-method-hint"
          )
        );
      }
    }
    modal.appendChild(emailMethod);
    if (state.notice) {
      modal.appendChild(note(state.notice, "nostr-modal-notice"));
    }
  }

  function openModal() {
    state.modalOpen = true;
    backdrop.hidden = false;
    renderModal();
    modal.focus();
    if (!state.flagFetched) {
      state.flagFetched = true;
      /* Learn which methods this deployment can serve (challenge
         response capability flags) — re-render the open modal when
         they arrive. Flags absent -> the optimistic-true defaults
         keep the Nostr path exactly as before. */
      api("/nostr/challenge" + shopQuery()).then(function (res) {
        if (res.status === 200 && res.body) {
          state.nsecSignin = !!res.body.nsec_signin;
          if (res.body.email_signin !== undefined) {
            state.emailAvailable = !!res.body.email_signin;
          }
          if (res.body.nostr_signin !== undefined) {
            state.nostrAvailable = !!res.body.nostr_signin;
          }
          if (state.modalOpen && !state.signedIn && !state.nsecOpen) {
            renderModal();
          }
        }
      });
    }
  }

  function closeModal() {
    state.modalOpen = false;
    backdrop.hidden = true;
    state.notice = "";
    state.emailSent = false;
    state.emailNotice = "";
  }

  function setMenu(open) {
    state.menuOpen = open;
    menu.hidden = !open;
    if (open) renderMenu();
    /* NOT renderChip() — re-rendering the chip here would detach the
       clicked avatar mid-event, making the outside-click handler treat
       it as a click outside and immediately re-close the menu. */
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  document.addEventListener("click", function (e) {
    if (!state.menuOpen) return;
    /* composedPath captures the DOM path AT DISPATCH TIME — in-menu
       controls that re-render (and detach) their own target mid-event
       are still recognised as inside clicks. */
    var inside = e.composedPath
      ? e.composedPath().indexOf(account) >= 0
      : account.contains(e.target);
    if (!inside) setMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (state.modalOpen) closeModal();
    else if (state.menuOpen) setMenu(false);
  });
  backdrop.addEventListener("click", function (e) {
    if (e.target === backdrop) closeModal();
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
        "Use the “Sign in” button in the top bar — a Nostr signer or" +
          " a sign-in email gets you in; no password."
      )
    ]);
    var go = GM.h("button", {
      type: "button",
      class: "btn-primary",
      text: "Sign in"
    });
    go.addEventListener("click", openModal);
    box.appendChild(go);
    return box;
  }

  function renderOrdersPage() {
    if (!ordersBody) return;
    GM.clear(ordersBody);
    if (!state.signedIn) {
      ordersBody.appendChild(
        signInPrompt("Sign in to see your orders.")
      );
      return;
    }
    var box = GM.h("div", { class: "nostr-box", "data-gm": "nostr-signed-in" });
    /* D-09 — the email-auth landing stashed bound_orders; acknowledge
       the merge once (honest UX, not silent magic), then clear. */
    var bound = 0;
    try {
      bound =
        parseInt(sessionStorage.getItem("gm_bound_orders") || "0", 10) ||
        0;
      if (bound > 0) sessionStorage.removeItem("gm_bound_orders");
    } catch (e) {
      bound = 0;
    }
    if (bound > 0) {
      box.appendChild(
        note(
          "We found " + bound + " past order" + (bound === 1 ? "" : "s") +
            " linked to your account.",
          "nostr-bound-note"
        )
      );
    }
    if (!state.orders.length) {
      box.appendChild(note("No orders yet — your orders will appear here."));
    } else {
      var list = GM.h("ul", { class: "nostr-orders" });
      state.orders.forEach(function (o) {
        list.appendChild(orderRow(o));
      });
      box.appendChild(list);
    }
    /* Claim: paste a private order link to bind it to this account
       (D-05) — method-neutral: email accounts claim too. */
    var claimBox = GM.h("div", { class: "nostr-claim" }, [
      GM.h("label", {
        for: "gm-claim-input",
        class: "nostr-claim-label",
        text: "Have a private order link? Paste it to link the order to your account."
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
        text: "Link this order to my account"
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
        signInPrompt("Sign in to edit your profile.")
      );
      return;
    }
    var p = state.profile || {};

    /* Account card (D-12) — the sign-in methods this account holds,
       each marked linked. Order prefs are display-only: per-order
       email opt-in is unchanged (deferred scope — no new preference
       storage, and unlink has no UI affordance or API yet). */
    var accountCard = GM.h("div", {
      class: "nostr-box nostr-account-card",
      "data-gm": "account-card"
    });
    accountCard.appendChild(
      GM.h("p", { class: "nostr-lead", text: "Sign-in methods" })
    );
    var methods = GM.h("ul", { class: "nostr-methods" });
    if (state.email) {
      methods.appendChild(
        GM.h("li", { class: "nostr-method-row" }, [
          GM.h("span", {
            text: "Email · " + truncMiddle(state.email, 40)
          }),
          GM.h("span", {
            class: "status-pill nostr-state-pill", text: "linked"
          })
        ])
      );
    }
    if (state.npub) {
      methods.appendChild(
        GM.h("li", { class: "nostr-method-row" }, [
          GM.h("span", { text: "Nostr key · " + npubShort(state.npub) }),
          GM.h("span", {
            class: "status-pill nostr-state-pill", text: "linked"
          })
        ])
      );
    }
    accountCard.appendChild(methods);
    accountCard.appendChild(
      note("Order emails still follow the per-order opt-in — unchanged.")
    );
    profileBody.appendChild(accountCard);

    /* Link a Nostr key (email-only accounts — D-10): the same
       challenge -> signEvent -> verify round-trip as sign-in, bound
       to this account; on success the identity reloads and the kind-0
       editor unlocks. */
    if (state.email && !state.npub) {
      var linkBox = GM.h("div", {
        class: "nostr-box nostr-account-card",
        "data-gm": "link-nostr-card"
      });
      linkBox.appendChild(
        GM.h("p", { class: "nostr-lead", text: "Link a Nostr key" })
      );
      linkBox.appendChild(
        note(
          "Prove your key to link it to this account —" +
            " orders and history merge."
        )
      );
      var linkBtn = GM.h("button", {
        type: "button",
        class: "btn-primary",
        id: "gm-link-nostr-btn",
        text: state.busy ? "Waiting for signer…" : "Link a Nostr key"
      });
      linkBtn.addEventListener("click", doLinkNostr);
      linkBox.appendChild(linkBtn);
      linkBox.appendChild(
        GM.h("p", {
          class: "nostr-claim-msg",
          id: "gm-link-nostr-msg",
          "aria-live": "polite"
        })
      );
      profileBody.appendChild(linkBox);
    }

    /* Link an email (nostr accounts — D-10): mails a purpose='link'
       token; the click verifies through the same /auth/email landing
       (prove, don't sign-in — no new cookie). */
    if (state.npub && !state.email) {
      var emailBox = GM.h("div", {
        class: "nostr-box nostr-account-card",
        "data-gm": "link-email-card"
      });
      emailBox.appendChild(
        GM.h("p", { class: "nostr-lead", text: "Link an email" })
      );
      emailBox.appendChild(
        note(
          "Verify an email address to also sign in by link —" +
            " your Nostr key stays your key."
        )
      );
      emailBox.appendChild(
        GM.h("label", {
          for: "gm-link-email-input",
          class: "nostr-claim-label",
          text: "Email address"
        })
      );
      emailBox.appendChild(
        GM.h("input", {
          type: "email",
          id: "gm-link-email-input",
          "data-gm": "link-email-input",
          class: "nostr-claim-input",
          autocomplete: "email",
          maxlength: "254",
          placeholder: "you@example.com"
        })
      );
      var linkEmailBtn = GM.h("button", {
        type: "button",
        class: "btn-primary",
        id: "gm-link-email-btn",
        text: state.busy ? "Sending…" : "Email me a verification link"
      });
      linkEmailBtn.addEventListener("click", doLinkEmail);
      emailBox.appendChild(linkEmailBtn);
      emailBox.appendChild(
        GM.h("p", {
          class: "nostr-claim-msg",
          id: "gm-link-email-msg",
          "aria-live": "polite"
        })
      );
      profileBody.appendChild(emailBox);
    }

    /* Kind-0 gating (D-12): the editor needs a real key to sign and
       author — email-only accounts get a locked state naming the fix,
       never a dead form. */
    if (!state.npub) {
      var locked = GM.h("div", {
        class: "nostr-box nostr-account-card",
        "data-gm": "profile-locked"
      });
      locked.appendChild(
        GM.h("p", { class: "nostr-lead", text: "Public profile" })
      );
      locked.appendChild(
        note(
          "Profile editing needs a linked Nostr key — link one above" +
            " to publish a kind-0 profile."
        )
      );
      profileBody.appendChild(locked);
      return;
    }
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
    var keyReq =
      typeof window.nostr.getPublicKey === "function"
        ? window.nostr.getPublicKey()
        : Promise.resolve(null);
    signerTimeout(keyReq)
      .then(function (pk) {
        return signerTimeout(
          window.nostr.signEvent({
            kind: 0,
            created_at: Math.floor(Date.now() / 1000),
            content: JSON.stringify(content),
            tags: [],
            pubkey: pk || undefined
          })
        );
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
      .catch(function (err) {
        msg.textContent =
          err && err.message === "signer-timeout"
            ? "Your signer didn't respond — check the extension's" +
              " popup, then try again."
            : "Signing was cancelled or failed — nothing saved.";
      })
      .finally(function () {
        state.busy = false;
        var save = document.getElementById("gm-profile-save");
        if (save) save.textContent = "Save profile";
      });
  }

  function setProfileMsg(id, text) {
    /* Re-resolve the node — a re-render may have replaced it while a
       flow was in flight. */
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function doLinkNostr() {
    var msg = document.getElementById("gm-link-nostr-msg");
    if (state.busy || !msg) return;
    /* Extension-absent is a friendly state, never a crash. */
    if (!window.nostr || typeof window.nostr.signEvent !== "function") {
      msg.textContent =
        "No Nostr signer found. Install a NIP-07 extension" +
        " (for example Alby or nos2x), then try again.";
      return;
    }
    state.busy = true;
    msg.textContent = "Waiting for your signer…";
    api("/nostr/link/challenge" + shopQuery())
      .then(function (res) {
        if (res.status !== 200 || !res.body.challenge) {
          throw new Error("challenge failed");
        }
        var challenge = res.body.challenge;
        var keyReq =
          typeof window.nostr.getPublicKey === "function"
            ? window.nostr.getPublicKey()
            : Promise.resolve(null);
        return signerTimeout(keyReq)
          .then(function (pk) {
            return signerTimeout(
              window.nostr.signEvent({
                kind: KIND_SIGNIN,
                created_at: Math.floor(Date.now() / 1000),
                content: challenge,
                tags: [["challenge", challenge]],
                pubkey: pk || undefined
              })
            );
          })
          .then(function (signed) {
            return api("/nostr/link/verify" + shopQuery(), {
              method: "POST",
              body: JSON.stringify({ event: JSON.stringify(signed) })
            });
          });
      })
      .then(function (res) {
        if (!res) return;
        if (res.status === 200 && res.body) {
          /* Linked (or union-merged) — reload the identity so the
             npub row + editor render from server truth, then leave
             the honest confirmation at the top of the page. */
          var merged = !!res.body.merged;
          return loadIdentity().then(function () {
            if (profileBody) {
              profileBody.insertBefore(
                note(
                  merged
                    ? "Nostr key linked — accounts merged."
                    : "Nostr key linked — your orders are merged."
                ),
                profileBody.firstChild
              );
            }
          });
        }
        if (res.status === 409) {
          setProfileMsg(
            "gm-link-nostr-msg",
            "That key is already linked to a different account —" +
              " sign in with it there instead."
          );
          return;
        }
        setProfileMsg(
          "gm-link-nostr-msg",
          "The link could not be verified. Try again — your signer" +
            " may have declined or the request expired."
        );
      })
      .catch(function (err) {
        setProfileMsg(
          "gm-link-nostr-msg",
          err && err.message === "signer-timeout"
            ? "Your signer didn't respond — check the extension's" +
              " popup, then try again."
            : "Signing was cancelled or failed — nothing linked."
        );
      })
      .finally(function () {
        state.busy = false;
        var b = document.getElementById("gm-link-nostr-btn");
        if (b) b.textContent = "Link a Nostr key";
      });
  }

  function doLinkEmail() {
    var input = document.getElementById("gm-link-email-input");
    var msg = document.getElementById("gm-link-email-msg");
    if (!input || !msg || state.busy) return;
    var email = input.value.trim();
    if (!email || email.indexOf("@") < 0) {
      msg.textContent = "Enter your email address.";
      return;
    }
    state.busy = true;
    msg.textContent = "";
    api("/nostr/link/email" + shopQuery(), {
      method: "POST",
      body: JSON.stringify({ email: email })
    })
      .then(function (res) {
        /* Same no-oracle posture as the sign-in request; a 409 is
           the early honest refusal (the account already holds a
           verified email), never an oracle. */
        if (res && res.status === 409) {
          msg.textContent =
            "This account already has a verified email —" +
            " sign-in links already go there.";
          return;
        }
        msg.textContent =
          "Check your email — a link to verify it is on its way." +
          (res && res.status === 200 ? "" : " Try again shortly.");
        if (res && res.status === 200) input.value = "";
      })
      .catch(function () {
        msg.textContent =
          "Check your email — a link to verify it is on its way." +
          " Try again shortly.";
      })
      .finally(function () {
        state.busy = false;
      });
  }

  /* --- flows -------------------------------------------------------------- */

  function loadOrders() {
    return api("/nostr/orders").then(function (res) {
      if (res.status === 200) {
        state.orders = (res.body && res.body.orders) || [];
      } else {
        /* A 401 mid-page means the session is gone — drop to the
           signed-out prompt rather than a silently empty list. */
        state.orders = [];
        if (res.status === 401) {
          state.signedIn = false;
          renderChip();
        }
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
        state.email = res.body.email || "";
        state.profile = res.body.profile || null;
      } else {
        state.signedIn = false;
        state.pubkey = "";
        state.npub = "";
        state.email = "";
        state.profile = null;
      }
      renderChip();
      if (state.menuOpen) renderMenu();
      /* Orders page renders via loadOrders() (signed-in) or the boot
         fallback (signed-out) — rendering here AND from loadOrders
         would detach a claim input the user already filled. */
      renderProfilePage();
      return state.signedIn;
    });
  }

  /* Some signers never settle on dismissal or suppress their prompt —
     a hung call must not wedge the modal in "Waiting for signer…". */
  function signerTimeout(promise) {
    return Promise.race([
      Promise.resolve(promise),
      new Promise(function (_, reject) {
        setTimeout(function () {
          reject(new Error("signer-timeout"));
        }, 90000);
      })
    ]);
  }

  function doSignIn() {
    if (state.busy) return;
    /* Extension-absent is a friendly state, never a crash. */
    if (!window.nostr || typeof window.nostr.signEvent !== "function") {
      state.notice =
        "No Nostr signer found. Install a NIP-07 extension" +
        " (for example Alby or nos2x), then try again.";
      if (!state.modalOpen) openModal();
      else renderModal();
      return;
    }
    state.busy = true;
    state.notice = "";
    if (!state.modalOpen) openModal();
    else renderModal();
    api("/nostr/challenge" + shopQuery())
      .then(function (res) {
        if (res.status !== 200 || !res.body.challenge) {
          throw new Error("challenge failed");
        }
        var challenge = res.body.challenge;
        /* getPublicKey FIRST — extensions use it as the site-authorization
           handshake; signEvent called cold can queue silently with no
           prompt (the "waiting for signer" hang). */
        var keyReq =
          typeof window.nostr.getPublicKey === "function"
            ? window.nostr.getPublicKey()
            : Promise.resolve(null);
        return signerTimeout(keyReq)
          .then(function (pk) {
            return signerTimeout(
              window.nostr.signEvent({
                kind: KIND_SIGNIN,
                created_at: Math.floor(Date.now() / 1000),
                content: challenge,
                tags: [["challenge", challenge]],
                pubkey: pk || undefined
              })
            );
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
          closeModal();
          return loadIdentity().then(function () {
            loadOrders();
          });
        }
        if (res.status !== undefined) {
          state.notice =
            "Sign-in could not be verified. Try again — your signer may" +
            " have declined or the request expired.";
          renderModal();
        }
      })
      .catch(function (err) {
        state.notice =
          err && err.message === "signer-timeout"
            ? "Your signer didn't respond — check the extension's" +
              " popup or approval list, then try again."
            : "Sign-in was cancelled or failed. Try again when you're ready.";
        if (state.modalOpen) renderModal();
      })
      .finally(function () {
        state.busy = false;
      });
  }

  function doNsecSignin() {
    var input = document.getElementById("gm-nsec-input");
    if (!input || state.busy) return;
    var nsec = input.value.trim();
    if (!nsec) {
      state.notice = "Paste your nsec first.";
      renderModal();
      return;
    }
    state.busy = true;
    state.notice = "";
    api("/nostr/verify" + shopQuery(), {
      method: "POST",
      body: JSON.stringify({ nsec: nsec })
    })
      .then(function (res) {
        if (!res) return;
        if (res.status === 200) {
          state.nsecOpen = false;
          closeModal();
          return loadIdentity().then(function () {
            loadOrders();
          });
        }
        state.notice = "That key could not sign you in — check it and try again.";
        renderModal();
      })
      .catch(function () {
        state.notice = "Sign-in failed. Try again when you're ready.";
        if (state.modalOpen) renderModal();
      })
      .finally(function () {
        state.busy = false;
        input.value = "";
      });
  }

  function doEmailRequest() {
    if (state.busy || !state.emailAvailable || state.emailSent) return;
    var input = document.getElementById("gm-email-input");
    if (!input) return;
    var email = input.value.trim();
    if (!email || email.indexOf("@") < 0) {
      state.notice = "Enter your email address.";
      renderModal();
      return;
    }
    state.busy = true;
    state.notice = "";
    renderModal();
    api("/nostr/email/request" + shopQuery(), {
      method: "POST",
      body: JSON.stringify({ email: email })
    })
      .then(function (res) {
        /* Uniform no-oracle copy for EVERY outcome — the modal never
           distinguishes known/unknown/capped addresses (the single
           EMAIL_SENT_COPY literal). Request-level failures (Origin,
           rate-limit) only append a retry tail. */
        state.emailSent = true;
        state.emailNotice = EMAIL_SENT_COPY +
          (res && res.status === 200 ? "" : " Try again shortly.");
      })
      .catch(function () {
        state.emailSent = true;
        state.emailNotice = EMAIL_SENT_COPY + " Try again shortly.";
      })
      .finally(function () {
        state.busy = false;
        if (state.modalOpen) renderModal();
      });
  }

  function doSignOut() {
    api("/nostr/logout", { method: "POST" }).finally(function () {
      state.signedIn = false;
      state.npub = "";
      state.pubkey = "";
      state.email = "";
      state.profile = null;
      state.orders = [];
      setMenu(false);
      renderChip();
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
    /* The chip ONLY opens the method picker — firing the Nostr flow
       on click would land an email-only shop on a 'No Nostr signer'
       error against its working email method. */
    openModal();
  });

  /* Signed-in detection probes the session once per page view — a 401 is
     the normal signed-out signal (no cookie is readable from JS). The
     profile probe also returns kind-0 name/avatar for the chip. */
  loadIdentity().then(function (signedIn) {
    if (!ordersBody) return;
    if (signedIn) loadOrders();
    else renderOrdersPage();
  });
})();
