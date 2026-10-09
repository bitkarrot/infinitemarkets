/* admin_notifications.js — B5 notification settings (NOTF-01).

   ≤5 validated merchant addresses, per-event toggles, "Send test"
   (≤5/hour, bucket-enforced server-side), and an honest queue view —
   sent / pending / suppressed (reason) / failed after N attempts.
   Customer email is per-order opt-in, transactional only; the status
   link is a bearer token — disclosed. */
(function () {
  "use strict";

  var EVENTS = [
    { key: "order_received", label: "Order received" },
    { key: "confirmed", label: "Payment confirmed" },
    { key: "processing", label: "Processing" },
    { key: "shipped", label: "Shipped" },
    { key: "delivered", label: "Delivered" },
    { key: "cancelled", label: "Cancelled" },
    { key: "expired", label: "Expired" },
    { key: "on_hold", label: "On hold" },
    { key: "refund_requested", label: "Refund requested" }
  ];

  window.app.mixin({
    data: function () {
      return {
        gmNotify: {
          loading: false,
          error: null,
          emails: [],
          events: {},
          queue: [],
          preview: {
            show: false, loading: false, subject: "", body: ""
          },
          clearConfirm: { show: false },
          clearing: false,
          newEmail: "",
          saving: false,
          testing: null,
          notice: null,
          eventDefs: EVENTS
        }
      };
    },
    methods: {
      gmLoadNotifications: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        self.gmNotify.loading = true;
        self.gmNotify.error = null;
        try {
          var d = await self.gmApi(
            "GET", "/merchants/" + mid + "/notifications"
          );
          self.gmNotify.emails = d.notify_emails || [];
          self.gmNotify.events = d.notify_events || {};
          self.gmNotify.queue = d.queue || [];
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
        self.gmNotify.loading = false;
      },
      gmEventOn: function (key) {
        /* Default set is order_received / confirmed / on_hold (§8.8). */
        var ev = this.gmNotify.events[key];
        if (ev === undefined) {
          return ["order_received", "confirmed", "on_hold"].indexOf(
            key
          ) >= 0;
        }
        return !!ev;
      },
      gmToggleEvent: async function (key, on) {
        var self = this;
        var mid = self.gmMerchantId();
        var ev = {};
        ev[key] = on;
        try {
          var d = await self.gmApi(
            "PATCH",
            "/merchants/" + mid + "/notifications",
            { notify_events: ev }
          );
          self.gmNotify.events = d.notify_events || {};
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
      },
      gmAddEmail: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        var email = self.gmNotify.newEmail.trim();
        if (!email) return;
        if (self.gmNotify.emails.length >= 5) {
          self.gmNotify.error =
            "At most five notification addresses are allowed.";
          return;
        }
        var emails = self.gmNotify.emails.concat([email]);
        self.gmNotify.saving = true;
        self.gmNotify.error = null;
        try {
          var d = await self.gmApi(
            "PATCH",
            "/merchants/" + mid + "/notifications",
            { notify_emails: emails }
          );
          self.gmNotify.emails = d.notify_emails || emails;
          self.gmNotify.newEmail = "";
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
        self.gmNotify.saving = false;
      },
      gmRemoveEmail: async function (email) {
        var self = this;
        var mid = self.gmMerchantId();
        var emails = self.gmNotify.emails.filter(function (e) {
          return e !== email;
        });
        try {
          var d = await self.gmApi(
            "PATCH",
            "/merchants/" + mid + "/notifications",
            { notify_emails: emails }
          );
          self.gmNotify.emails = d.notify_emails || emails;
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
      },
      gmSendTest: async function (email) {
        var self = this;
        var mid = self.gmMerchantId();
        self.gmNotify.testing = email;
        self.gmNotify.notice = null;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + mid + "/notifications/test",
            { recipient: email }
          );
          self.gmNotify.notice = "Test email queued for " + email + ".";
          await self.gmLoadNotifications();
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
        self.gmNotify.testing = null;
      },
      gmViewEmail: async function (row) {
        var self = this;
        var mid = self.gmMerchantId();
        var preview = self.gmNotify.preview;
        preview.show = true;
        preview.loading = true;
        preview.subject = "";
        preview.body = "";
        try {
          var d = await self.gmApi(
            "GET",
            "/merchants/" + mid + "/notifications/email-queue/" + row.id
          );
          preview.subject = d.subject || "";
          preview.body = d.body || "";
        } catch (e) {
          preview.show = false;
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
        preview.loading = false;
      },
      gmQueueHistoryCount: function () {
        return this.gmNotify.queue.filter(function (row) {
          return ["sent", "suppressed", "failed"].indexOf(row.state) >= 0;
        }).length;
      },
      gmClearEmailQueue: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        self.gmNotify.clearing = true;
        try {
          var d = await self.gmApi(
            "DELETE",
            "/merchants/" + mid + "/notifications/email-queue"
          );
          self.gmNotify.notice =
            "Cleared " + (d.deleted || 0) + " email history " +
            ((d.deleted || 0) === 1 ? "entry." : "entries.");
          await self.gmLoadNotifications();
        } catch (e) {
          self.gmNotify.error = self.gmProblemCopy(e.problem);
        }
        self.gmNotify.clearing = false;
      },
      gmQueueLabel: function (row) {
        if (row.state === "sent") return "Sent";
        if (row.state === "pending" || row.state === "claimed") {
          return "Pending";
        }
        if (row.state === "suppressed") {
          return "Suppressed — " + (row.last_error || "disabled");
        }
        if (row.state === "failed") {
          return "Failed after " + row.attempts + " attempts";
        }
        return row.state;
      }
    },
    mounted: function () {
      if (window._gmNotifyWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmNotifyWired = true;
      var self = root.proxy;
      self.$watch("gm.merchant", function (m) {
        if (m && self.gm.view === "settings") self.gmLoadNotifications();
      });
    }
  });
})();
