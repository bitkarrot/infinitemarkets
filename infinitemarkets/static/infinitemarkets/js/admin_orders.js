/* admin_orders.js — B1 order workspace (sketch 002-A Linear Split).

   390px searchable/filterable list + persistent detail pane. Legal
   actions only — derived from the §7.1/§7.2 tables; illegal transitions
   are never offered (hidden or disabled with a reason). */
(function () {
  "use strict";

  var STATE_FILTERS = [
    { value: "", label: "All" },
    { value: "awaiting_payment", label: "Awaiting payment" },
    { value: "confirmed", label: "Confirmed" },
    { value: "processing", label: "Processing" },
    { value: "completed", label: "Completed" },
    { value: "needs_attention", label: "Needs attention" },
    { value: "expired", label: "Expired" },
    { value: "cancelled", label: "Cancelled" }
  ];

  var STATE_LABELS = {
    received: "Received",
    invoice_pending: "Invoice pending",
    awaiting_payment: "Awaiting payment",
    confirmed: "Confirmed",
    processing: "Processing",
    completed: "Completed",
    rejected: "Rejected",
    expired: "Expired",
    cancelled: "Cancelled"
  };

  /* Semantic state styling — colour is always paired with a label and an
     icon, never the only signal (WCAG 1.4.1). Quasar palette names so the
     badges follow the host light/dark theme. */
  var STATE_STYLES = {
    received: { color: "blue-grey-6", text: "white", icon: "inbox" },
    invoice_pending: { color: "blue-grey-6", text: "white", icon: "hourglass_top" },
    awaiting_payment: { color: "amber-7", text: "black", icon: "schedule" },
    confirmed: { color: "teal-6", text: "white", icon: "paid" },
    processing: { color: "blue-6", text: "white", icon: "local_shipping" },
    completed: { color: "green-7", text: "white", icon: "check_circle" },
    expired: { color: "grey-7", text: "white", icon: "timer_off" },
    cancelled: { color: "red-6", text: "white", icon: "cancel" },
    rejected: { color: "red-6", text: "white", icon: "block" }
  };
  var CLOSED_STATES = ["completed", "cancelled", "expired", "rejected"];

  var SHIPPING_LABELS = {
    not_required: "No shipping needed",
    pending: "Not started",
    processing: "Preparing",
    shipped: "Shipped",
    delivered: "Delivered",
    exception: "Delivery problem"
  };
  var PAYMENT_LABELS = {
    creating: "Creating invoice",
    creation_unknown: "Being verified",
    pending: "Awaiting payment",
    settled: "Paid",
    paid: "Paid",
    failed: "Failed",
    expired: "Expired"
  };

  var CHANNEL_LABELS = { web: "Web", gamma: "Gamma", nip15: "NIP-15" };

  window.app.mixin({
    data: function () {
      return {
        gmOrders: {
          loading: false,
          error: null,
          list: [],
          q: "",
          stateFilter: "",
          archiveView: "active",
          selectedIds: [],
          selectedId: null,
          detail: null,
          events: [],
          thread: { messages: [] },
          threadReply: "",
          threadSending: false,
          detailLoading: false,
          detailError: null,
          mobileDetail: false,
          stateFilters: STATE_FILTERS,
          actionError: null,
          bulkError: null,
          bulkBusy: false,
          notice: null,
          archiveDialog: { show: false, busy: false, error: null },
          cancelDialog: { show: false, reason: "", busy: false },
          shipDialog: {
            show: false, target: "", tracking: "", carrier: "", eta: "",
            busy: false
          },
          refundDialog: { show: false, reference: "", busy: false },
          reissue: { show: false, link: "" }
        }
      };
    },
    computed: {
      gmOrdersSummary: function () {
        if (this.gmOrders.archiveView === "archived") {
          return this.gmOrders.list.length + " archived orders";
        }
        var active = this.gmOrders.list.filter(function (o) {
          return ["completed", "rejected", "cancelled", "expired"].indexOf(
            o.state
          ) === -1;
        }).length;
        var attention = this.gmOrders.list.filter(function (o) {
          return o.payment_exception || o.oversold;
        }).length;
        return active + " active orders · " + attention + " need attention";
      },
      gmSelectableOrders: function () {
        var self = this;
        return self.gmOrders.list.filter(function (order) {
          return self.gmOrderCanSelect(order);
        });
      },
      gmAllSelectableOrdersSelected: function () {
        var selected = this.gmOrders.selectedIds;
        return this.gmSelectableOrders.length > 0 &&
          this.gmSelectableOrders.every(function (order) {
            return selected.indexOf(order.id) >= 0;
          });
      },
      gmOrderActions: function () {
        /* §7.1/§7.2 legal-action map — only legal controls render; the
           terminal state renders a disabled control with the reason. */
        var d = this.gmOrders.detail;
        if (!d) return [];
        var out = [];
        if (d.archived_at) return out;
        if (d.payment_exception) {
          if (["expired", "cancelled"].indexOf(d.state) !== -1 &&
              d.payment && d.payment.status === "settled") {
            out.push({ key: "accept", label: "Accept paid order", kind: "exception" });
          }
          if (["confirmed", "processing"].indexOf(d.state) !== -1) {
            out.push({ key: "cancel", label: "Cancel with reason", kind: "danger" });
          }
          out.push(
            { key: "refund", label: "Request refund", kind: "exception" },
            {
              key: "confirm-refund",
              label: "Confirm refund sent",
              kind: "exception"
            }
          );
          return out;
        }
        switch (d.state) {
          case "confirmed":
            out.push({
              key: "status:processing",
              label: "Start processing",
              kind: "primary"
            });
            out.push({
              key: "cancel",
              label: "Cancel with reason",
              kind: "danger"
            });
            break;
          case "processing":
            /* §7.2 shipping transitions: pending→processing,
               processing/exception→shipped, shipped→delivered. */
            if (d.shipping_state === "pending") {
              out.push({
                key: "ship:processing",
                label: "Start fulfillment",
                kind: "secondary"
              });
            } else if (d.shipping_state === "processing" ||
                       d.shipping_state === "exception") {
              out.push({
                key: "ship:shipped",
                label: "Mark shipped",
                kind: "primary"
              });
            } else if (d.shipping_state === "shipped") {
              out.push({
                key: "ship:delivered",
                label: "Mark delivered",
                kind: "primary"
              });
            }
            out.push({
              key: "status:completed",
              label: "Mark complete",
              kind: "secondary"
            });
            out.push({
              key: "cancel",
              label: "Cancel with reason",
              kind: "danger"
            });
            break;
          case "awaiting_payment":
          case "invoice_pending":
          case "received":
            out.push({ key: "cancel", label: "Cancel", kind: "danger" });
            break;
        }
        if (d.fulfillment_authorized !== true || !d.payment ||
            d.payment.status !== "settled") {
          out = out.filter(function (action) {
            return action.key.indexOf("status:") !== 0 && action.key.indexOf("ship:") !== 0;
          });
        }
        if (d.protocol === "web") {
          out.push({
            key: "reissue",
            label: "Reissue status link",
            kind: "secondary"
          });
        }
        return out;
      },
      /* Closed orders explain themselves in plain language instead of a
         disabled "no action" control. */
      gmOrderClosedNote: function () {
        var d = this.gmOrders.detail;
        if (d && ["confirmed", "processing", "completed"].indexOf(d.state) !== -1 &&
            (d.fulfillment_authorized !== true || !d.payment ||
             d.payment.status !== "settled" || d.payment_exception)) {
          return "Fulfillment requires review. Verify payment and complete inventory accounting before continuing.";
        }
        if (!d || d.payment_exception || CLOSED_STATES.indexOf(d.state) < 0) {
          return "";
        }
        var why = {
          completed: "This order is complete.",
          cancelled: "This order was cancelled.",
          expired: "This order expired before it was paid.",
          rejected: "This order was rejected."
        }[d.state];
        return why + " Its status can no longer change.";
      }
    },
    methods: {
      gmOrderCanSelect: function (order) {
        if (!order) return false;
        if (this.gmOrders.archiveView === "archived") {
          return !!order.archived_at;
        }
        return !!order.archive_eligible;
      },
      gmToggleOrderSelection: function (orderId, selected) {
        var ids = this.gmOrders.selectedIds.slice();
        var index = ids.indexOf(orderId);
        if (selected && index < 0) ids.push(orderId);
        if (!selected && index >= 0) ids.splice(index, 1);
        this.gmOrders.selectedIds = ids;
      },
      gmToggleAllOrders: function (selected) {
        this.gmOrders.selectedIds = selected
          ? this.gmSelectableOrders.map(function (order) { return order.id; })
          : [];
      },
      gmSwitchOrderView: function () {
        this.gmOrders.selectedIds = [];
        this.gmOrders.selectedId = null;
        this.gmOrders.detail = null;
        this.gmOrders.events = [];
        this.gmOrders.mobileDetail = false;
        this.gmOrders.bulkError = null;
        this.gmLoadOrders();
      },
      gmAskArchiveOrders: function () {
        if (!this.gmOrders.selectedIds.length) return;
        this.gmOrders.archiveDialog = {
          show: true, busy: false, error: null
        };
      },
      gmRunOrderBulk: async function (action) {
        var self = this;
        var ids = self.gmOrders.selectedIds.slice();
        if (!ids.length) return;
        var mid = self.gmMerchantId();
        self.gmOrders.bulkBusy = true;
        self.gmOrders.bulkError = null;
        self.gmOrders.archiveDialog.error = null;
        if (action === "archive") self.gmOrders.archiveDialog.busy = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + mid + "/orders/bulk",
            { order_ids: ids, action: action }
          );
          self.gmOrders.notice = ids.length + " " +
            (ids.length === 1 ? "order" : "orders") + " " +
            (action === "archive" ? "archived." : "restored.");
          self.gmOrders.archiveDialog.show = false;
          self.gmOrders.selectedIds = [];
          if (ids.indexOf(self.gmOrders.selectedId) >= 0) {
            self.gmOrders.selectedId = null;
            self.gmOrders.detail = null;
            self.gmOrders.events = [];
            self.gmOrders.mobileDetail = false;
          }
          await self.gmLoadOrders();
        } catch (e) {
          var message = self.gmProblemCopy(e.problem);
          self.gmOrders.bulkError = message;
          self.gmOrders.archiveDialog.error = message;
        }
        self.gmOrders.bulkBusy = false;
        self.gmOrders.archiveDialog.busy = false;
      },
      gmArchiveConfirm: function () {
        return this.gmRunOrderBulk("archive");
      },
      gmRestoreOrders: function () {
        return this.gmRunOrderBulk("restore");
      },
      gmOrderStateLabel: function (s) {
        return STATE_LABELS[s] || s;
      },
      gmStateStyle: function (o) {
        if (!o) return STATE_STYLES.received;
        if (o.payment_exception) {
          return { color: "negative", text: "white", icon: "error", label: "Needs attention" };
        }
        if (o.oversold) {
          return { color: "deep-orange-7", text: "white", icon: "warning", label: "Oversold" };
        }
        var s = STATE_STYLES[o.state] || { color: "grey-6", text: "white", icon: "help" };
        return { color: s.color, text: s.text, icon: s.icon, label: STATE_LABELS[o.state] || o.state };
      },
      gmStatusLabel: function (s) {
        return STATE_LABELS[s] || SHIPPING_LABELS[s] || s || "—";
      },
      gmShippingLabel: function (s) {
        return SHIPPING_LABELS[s] || s || "—";
      },
      gmPaymentLabel: function (s) {
        return PAYMENT_LABELS[s] || s || "—";
      },
      gmEventColor: function (e) {
        var s = STATE_STYLES[e.to_state];
        return s ? s.color : "primary";
      },
      gmActorLabel: function (a) {
        return { system: "Automatic", buyer: "Buyer", merchant: "You" }[a] || a;
      },
      gmChannelLabel: function (p) {
        return CHANNEL_LABELS[p] || p;
      },
      gmLoadOrders: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        self.gmOrders.loading = true;
        self.gmOrders.error = null;
        try {
          var params = [];
          if (self.gmOrders.stateFilter) {
            params.push("state=" + self.gmOrders.stateFilter);
          }
          if (self.gmOrders.q) {
            params.push("q=" + encodeURIComponent(self.gmOrders.q));
          }
          if (self.gmOrders.archiveView === "archived") {
            params.push("archived=true");
          }
          var qs = params.length ? "?" + params.join("&") : "";
          var rows = await self.gmApi(
            "GET", "/merchants/" + mid + "/orders" + qs
          );
          self.gmOrders.list = rows;
          self.gmOrders.selectedIds = self.gmOrders.selectedIds.filter(
            function (id) {
              return rows.some(function (order) {
                return order.id === id && self.gmOrderCanSelect(order);
              });
            }
          );
        } catch (e) {
          self.gmOrders.error = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.loading = false;
      },
      gmSelectOrder: async function (id) {
        var self = this;
        self.gmOrders.selectedId = id;
        self.gmOrders.mobileDetail = true;
        self.gmOrders.detailLoading = true;
        self.gmOrders.detailError = null;
        self.gmOrders.actionError = null;
        var mid = self.gmMerchantId();
        try {
          var pair = await Promise.all([
            self.gmApi("GET", "/merchants/" + mid + "/orders/" + id),
            self.gmApi("GET", "/merchants/" + mid + "/orders/" + id + "/events")
          ]);
          self.gmOrders.detail = pair[0];
          /* Order-bound NIP-17 thread (D-12) — best-effort, never
             blocks the detail render. */
          try {
            var thread = await self.gmApi(
              "GET",
              "/merchants/" + mid + "/orders/" + id + "/messages"
            );
            self.gmOrders.thread = thread;
          } catch (e2) {
            self.gmOrders.thread = { messages: [] };
          }
          /* Several transitions share one second; break ties by lifecycle
             order so the history reads top-to-bottom. */
          var rank = ["received", "invoice_pending", "awaiting_payment",
            "confirmed", "processing", "shipped", "delivered", "completed"];
          self.gmOrders.events = pair[1].slice().sort(function (a, b) {
            var ra = rank.indexOf(a.to_state), rb = rank.indexOf(b.to_state);
            return (a.created_at - b.created_at) ||
              ((ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb));
          });
        } catch (e) {
          self.gmOrders.detailError = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.detailLoading = false;
      },
      gmOrderBack: function () {
        /* ≤560px: detail → list navigation ("← Back to orders"). */
        this.gmOrders.mobileDetail = false;
      },
      gmSendOrderReply: async function () {
        /* Reply threads onto order:<id> (D-13) — the merchant never
           types a recipient, the conversation resolves the buyer. */
        var self = this;
        var content = (self.gmOrders.threadReply || "").trim();
        var cid = "order:" + self.gmOrders.selectedId;
        if (!content || !self.gmOrders.selectedId) return;
        self.gmOrders.threadSending = true;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + self.gmMerchantId() +
              "/messages/conversations/" + encodeURIComponent(cid) +
              "/reply",
            { content: content }
          );
          self.gmOrders.threadReply = "";
          var thread = await self.gmApi(
            "GET",
            "/merchants/" + self.gmMerchantId() + "/orders/" +
              self.gmOrders.selectedId + "/messages"
          );
          self.gmOrders.thread = thread;
        } catch (e) {
          self.gmOrders.actionError = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.threadSending = false;
      },
      gmDoAction: async function (action) {
        var self = this;
        var mid = self.gmMerchantId();
        var id = self.gmOrders.selectedId;
        self.gmOrders.actionError = null;
        try {
          if (action.key === "cancel") {
            self.gmOrders.cancelDialog = {
              show: true, reason: "", busy: false
            };
            return;
          }
          if (action.key.indexOf("ship:") === 0) {
            self.gmOrders.shipDialog = {
              show: true,
              target: action.key.split(":")[1],
              tracking: "", carrier: "", eta: "", busy: false
            };
            return;
          }
          if (action.key === "refund") {
            self.gmOrders.refundDialog = {
              show: false, reference: "", busy: true
            };
            await self.gmResolve("refund", null);
            return;
          }
          if (action.key === "confirm-refund") {
            self.gmOrders.refundDialog = {
              show: true, reference: "", busy: false
            };
            return;
          }
          if (action.key === "accept") {
            await self.gmResolve("accept", null);
            return;
          }
          if (action.key === "reissue") {
            var res = await self.gmApi(
              "POST",
              "/merchants/" + mid + "/orders/" + id +
                "/public-token/reissue",
              {}
            );
            self.gmOrders.reissue = {
              show: true,
              /* The new link is shown ONCE — old token revoked already. */
              link: "/infinitemarkets/order#" + res.public_token
            };
            return;
          }
          if (action.key.indexOf("status:") === 0) {
            await self.gmApi(
              "POST",
              "/merchants/" + mid + "/orders/" + id + "/status",
              { to_state: action.key.split(":")[1] }
            );
            await self.gmSelectOrder(id);
            await self.gmLoadOrders();
          }
        } catch (e) {
          self.gmOrders.actionError = self.gmProblemCopy(e.problem);
        }
      },
      gmResolve: async function (action, refundRef) {
        var self = this;
        var mid = self.gmMerchantId();
        var id = self.gmOrders.selectedId;
        var body = { action: action };
        if (refundRef) body.refund_reference = refundRef;
        await self.gmApi(
          "POST",
          "/merchants/" + mid + "/orders/" + id + "/resolve-exception",
          body
        );
        await self.gmSelectOrder(id);
        await self.gmLoadOrders();
      },
      gmCancelConfirm: async function () {
        var self = this;
        if (!self.gmOrders.cancelDialog.reason.trim()) return;
        self.gmOrders.cancelDialog.busy = true;
        var mid = self.gmMerchantId();
        var id = self.gmOrders.selectedId;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + mid + "/orders/" + id + "/cancel",
            { reason: self.gmOrders.cancelDialog.reason.trim() }
          );
          self.gmOrders.cancelDialog.show = false;
          await self.gmSelectOrder(id);
          await self.gmLoadOrders();
        } catch (e) {
          self.gmOrders.actionError = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.cancelDialog.busy = false;
      },
      gmShipConfirm: async function () {
        var self = this;
        self.gmOrders.shipDialog.busy = true;
        var mid = self.gmMerchantId();
        var id = self.gmOrders.selectedId;
        var d = self.gmOrders.shipDialog;
        var body = { shipping_state: d.target };
        if (d.tracking.trim()) body.tracking = d.tracking.trim();
        if (d.carrier.trim()) body.carrier = d.carrier.trim();
        if (d.eta.trim()) body.eta = d.eta.trim();
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + mid + "/orders/" + id + "/shipping",
            body
          );
          self.gmOrders.shipDialog.show = false;
          await self.gmSelectOrder(id);
          await self.gmLoadOrders();
        } catch (e) {
          self.gmOrders.actionError = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.shipDialog.busy = false;
      },
      gmRefundConfirm: async function () {
        var self = this;
        self.gmOrders.refundDialog.busy = true;
        try {
          await self.gmResolve(
            "confirm-refund",
            self.gmOrders.refundDialog.reference.trim() || null
          );
          self.gmOrders.refundDialog.show = false;
        } catch (e) {
          self.gmOrders.actionError = self.gmProblemCopy(e.problem);
        }
        self.gmOrders.refundDialog.busy = false;
      }
    },
    mounted: function () {
      /* Wire once, on the app root — mixin hooks run per component and
         a leaf's gm is a different object than the root's (the one the
         template renders). */
      if (window._gmOrdersWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmOrdersWired = true;
      var self = root.proxy;
      self.$watch("gm.merchant", function (m) {
        if (m && self.gm.view === "orders") self.gmLoadOrders();
      });
      self.$watch("gm.view", function (v) {
        if (v === "orders" && self.gm.merchant) self.gmLoadOrders();
      });
    }
  });
})();
