/* admin_messages.js — GAM-04 merchant Messages workspace (plan 03-03).

   Linear-style split surface: Customer/Unknown folder list on the left,
   decrypted thread + per-copy delivery evidence on the right. Every row
   ships its own durable state (unread flag, intent state, relay results)
   so the UI never invents delivery claims. */
(function () {
  "use strict";

  window.app.mixin({
    data: function () {
      return {
        gmMessages: {
          loading: false,
          error: null,
          folder: "customer",
          folderOptions: [
            { label: "Customers", value: "customer" },
            { label: "Unknown", value: "unknown" }
          ],
          conversations: [],
          selected: null,
          thread: { messages: [], order_id: null },
          delivery: [],
          replyText: "",
          sending: false,
          health: { inbox_state: "off", outbox_pending: 0, relays: [] },
          compose: {
            show: false, recipient: "", orderId: "",
            content: "", busy: false
          },
          rejected: [],
          showRejected: false,
          muteConfirm: { show: false, row: null, busy: false }
        }
      };
    },
    watch: {
      "gmMessages.folder": function () {
        this.gmLoadConversations();
      }
    },
    methods: {
      gmLoadMessages: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        /* Health + unread badge bind to real APIs; list reloads for the
           active folder. */
        try {
          var res = await Promise.all([
            self.gmApi("GET", "/merchants/" + mid + "/messages/health"),
            self.gmApi(
              "GET", "/merchants/" + mid + "/messages/unread-count"
            )
          ]);
          self.gmMessages.health = res[0] || self.gmMessages.health;
          self.gm.unreadCount = (res[1] && res[1].total) || 0;
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
        await self.gmLoadConversations(true);
      },
      gmLoadConversations: async function (refreshProfiles) {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        self.gmMessages.loading = true;
        self.gmMessages.error = null;
        try {
          var res = await self.gmApi(
            "GET",
            "/merchants/" + mid + "/messages/conversations?folder=" +
              self.gmMessages.folder +
              (refreshProfiles ? "&refresh_profiles=true" : "")
          );
          self.gmMessages.conversations = res.conversations || [];
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
        self.gmMessages.loading = false;
      },
      gmSelectConversation: async function (c) {
        var self = this;
        self.gmMessages.selected = c.conversation_id;
        self.gmMessages.delivery = [];
        try {
          var res = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() +
              "/messages/conversations/" +
              encodeURIComponent(c.conversation_id)
          );
          self.gmMessages.thread = res;
          /* Opening a thread marks it read + refreshes the badge. */
          await self.gmMarkRead();
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
      },
      gmMarkRead: async function () {
        var self = this;
        var cid = self.gmMessages.selected;
        if (!cid) return;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/messages/conversations/" +
              encodeURIComponent(cid) + "/read",
            {}
          );
          self.gmMessages.thread.messages.forEach(function (m) {
            if (m.direction === "in") m.read = true;
          });
          var counts = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() +
              "/messages/unread-count"
          );
          self.gm.unreadCount = counts.total || 0;
          self.gmMessages.conversations.forEach(function (c) {
            if (c.conversation_id === cid) c.unread = 0;
          });
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
      },
      gmLoadDelivery: async function () {
        var self = this;
        var cid = self.gmMessages.selected;
        if (!cid) return;
        try {
          var res = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() +
              "/messages/conversations/" +
              encodeURIComponent(cid) + "/delivery"
          );
          self.gmMessages.delivery = res.messages || [];
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
      },
      gmSelectedCounterparty: function () {
        var self = this;
        var selected = self.gmMessages.thread.counterparty;
        if (selected) return selected;
        var conv = self.gmMessages.conversations.find(function (c) {
          return c.conversation_id === self.gmMessages.selected;
        });
        return conv ? conv.counterparty : null;
      },
      gmProfileName: function (profile) {
        if (!profile) return "Unknown sender";
        if (profile.display_name) return profile.display_name;
        if (profile.nip05) return profile.nip05;
        if (profile.npub) return this.gmTrunc(profile.npub, 10, 4);
        return "Unknown sender";
      },
      gmProfileInitial: function (profile) {
        var name = profile && (
          profile.display_name || profile.username || profile.nip05
        );
        if (name) return name.trim().charAt(0).toUpperCase();
        return profile && profile.npub
          ? profile.npub.slice(4, 6).toUpperCase()
          : "?";
      },
      gmClearAvatar: function (profile) {
        if (profile) profile.avatar_url = null;
      },
      gmRetryMessageIntent: async function (d) {
        var self = this;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/outbox/" + d.intent_id + "/retry",
            {}
          );
          await self.gmLoadDelivery();
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
      },
      gmSendReply: async function () {
        var self = this;
        var cid = self.gmMessages.selected;
        var content = (self.gmMessages.replyText || "").trim();
        if (!cid || !content) return;
        self.gmMessages.sending = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/messages/conversations/" +
              encodeURIComponent(cid) + "/reply",
            { content: content }
          );
          self.gmMessages.replyText = "";
          await self.gmSelectConversation(
            { conversation_id: cid }
          );
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
        self.gmMessages.sending = false;
      },
      gmSendCompose: async function () {
        var self = this;
        var c = self.gmMessages.compose;
        if (!c.recipient || !c.content) return;
        c.busy = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() + "/messages/compose",
            {
              recipient: c.recipient.trim(),
              order_id: (c.orderId || "").trim() || null,
              content: c.content
            }
          );
          self.gmMessages.compose = {
            show: false, recipient: "", orderId: "",
            content: "", busy: false
          };
          await self.gmLoadConversations();
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
          self.gmMessages.compose.busy = false;
        }
      },
      gmOpenRejected: async function () {
        var self = this;
        self.gmMessages.showRejected = true;
        await self.gmLoadRejected();
      },
      gmLoadRejected: async function () {
        var self = this;
        try {
          var res = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() + "/rejected-intake"
          );
          self.gmMessages.rejected = res.entries || [];
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
      },
      gmAskMuteSender: function (row) {
        this.gmMessages.muteConfirm = { show: true, row: row, busy: false };
      },
      gmMuteSender: async function () {
        var self = this;
        var dlg = self.gmMessages.muteConfirm;
        var row = dlg.row;
        if (!row) return;
        dlg.busy = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/rejected-intake/" + row.id + "/mute",
            {}
          );
          row.muted = true;
          dlg.show = false;
          dlg.row = null;
        } catch (e) {
          self.gmMessages.error = self.gmProblemCopy(e.problem);
        }
        dlg.busy = false;
      }
    },
    mounted: function () {
      if (window._gmMessagesWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmMessagesWired = true;
      var self = root.proxy;
      /* The nav badge binds to unread-count on every merchant load. */
      self.$watch("gm.merchant", async function (m) {
        if (!m) return;
        try {
          var res = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() + "/messages/unread-count"
          );
          self.gm.unreadCount = res.total || 0;
        } catch (e) { /* badge is best-effort */ }
      });
      if (self.gm && self.gm.merchant) {
        self.gmApi(
          "GET",
          "/merchants/" + self.gmMerchantId() + "/messages/unread-count"
        ).then(function (res) {
          self.gm.unreadCount = res.total || 0;
        }).catch(function () {});
      }
    }
  });
})();
