/* admin_publications.js — B2 publication health (PUB-02).

   Per-relay connection + ACK evidence labeled "delivery evidence" —
   relay delivery is NEVER presented as payment settlement. Outbox rows
   carry state pills, attempts, per-relay outcomes, supersession markers;
   partial publications name the missing relays; failed rows retry. */
(function () {
  "use strict";

  var KIND_LABELS = {
    0: "Profile",
    5: "Deletion",
    30402: "Product",
    30405: "Collection",
    30406: "Shipping",
    31989: "Handler",
    31990: "Handler info",
    order_msg: "Order message",
    products: "Product",
    collections: "Collection",
    shipping_options: "Shipping",
    categories: "Category",
    merchant: "Merchant"
  };

  var STATE_PILLS = {
    pending: "Pending",
    claimed: "Claimed",
    publishing: "Publishing",
    partially_published: "Partially published",
    published: "Published",
    failed: "Failed",
    superseded: "Superseded"
  };

  var RELAY_CHECK_LOCAL_STATES = [
    {label: "Active", value: "active"},
    {label: "Inactive", value: "inactive"},
    {label: "Draft", value: "draft"},
    {label: "Deleted", value: "deleted"}
  ];
  var RELAY_CHECK_RESULTS = [
    {label: "Published", value: "observed"},
    {label: "Partial", value: "partial"},
    {label: "Missing", value: "missing"},
    {label: "Divergent", value: "divergent"},
    {label: "Stale copy", value: "stale"},
    {label: "Deleted copy served", value: "stale-deleted"},
    {label: "Draft copy served", value: "draft-copy-served"},
    {label: "Inactive copy served", value: "inactive-copy-served"},
    {label: "Not observed", value: "not-observed"}
  ];

  function fmtTime(ts) {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString();
  }

  window.app.mixin({
    data: function () {
      return {
        gmPubs: {
          loading: false,
          error: null,
          tab: "delivery",
          relays: [],
          defaults: { relays: [], blossom_servers: [] },
          blossomServers: [],
          intents: [],
          retrying: null,
          detail: null,
          exceptionOrders: [],
          check: {
            busy: false,
            checked_at: null,
            relays: [],
            items: [],
            unmatched: [],
            summary: null,
            showAll: false,
            localStates: [],
            results: [],
            reissuing: false
          },
          prune: {show: false, days: 90, busy: false, result: null},
          pruneDayOptions: [7, 14, 30, 60, 90, 180, 365]
        },
        /* q-table columns for the relay-health surface (q-markup-table
           can't be used — in-DOM template foster-parenting breaks it). */
        gmRelayColumns: [
          { name: "relay_url", label: "Relay", field: "relay_url",
            align: "left" },
          { name: "direction", label: "Direction", field: "direction",
            align: "left" },
          { name: "connection", label: "Connection", align: "left",
            field: function (r) {
              return r.enabled ? "enabled" : "disabled";
            } },
          { name: "ack", label: "Last positive ACK", align: "left",
            field: function (r) {
              return r.accepted
                ? r.accepted + " accepted · " + fmtTime(r.last_attempt_at)
                : "—";
            } },
          { name: "failures", label: "Rejected / timed out", align: "left",
            field: function (r) {
              return r.rejected || r.timeout
                ? r.rejected + " rejected · " + r.timeout + " timed out"
                : "—";
            } }
        ],
        gmRelayCheckLocalStateOptions: RELAY_CHECK_LOCAL_STATES,
        gmRelayCheckResultOptions: RELAY_CHECK_RESULTS,
        gmRelayCheckColumns: [
          { name: "kind", label: "Kind", field: "kind", align: "left",
            sortable: true },
          { name: "item", label: "Catalog item", align: "left",
            sortable: true,
            field: function (row) {
              return row.title || row.d_tag || "";
            } },
          { name: "local", label: "Local state", align: "left",
            sortable: true,
            field: function (row) {
              var detail = row.local.visibility ||
                (row.local.member_count != null
                  ? row.local.member_count + " members" : "");
              return row.local.state + ":" + detail;
            } },
          { name: "relays", label: "Relay copies", align: "left",
            sortable: true,
            field: function (row) {
              return row.observed_on.length;
            } },
          { name: "latest", label: "Latest observed", align: "left",
            sortable: true,
            field: function (row) {
              return row.latest_event ? row.latest_event.created_at : 0;
            } },
          { name: "result", label: "Result", field: "status",
            align: "left", sortable: true }
        ]
      };
    },
    methods: {
      gmPubKindLabel: function (row) {
        if (!row) return "—";
        var key = row.event_kind != null ? row.event_kind : row.aggregate_type;
        return KIND_LABELS[key] || "Kind " + key;
      },
      gmSelectPub: function (row) {
        this.gmPubs.detail = row;
      },
      gmPubDetailFields: function (row) {
        var fields = [
          { label: "Intent ID", value: row.id, code: true },
          { label: "Aggregate",
            value: row.aggregate_type + ":" + row.aggregate_id, code: true },
          { label: "Revision", value: String(row.aggregate_revision) },
          { label: "Event kind",
            value: row.event_kind != null ? String(row.event_kind) : "—" },
          { label: "Event address",
            value: row.event_address || "—", code: true },
          { label: "Attempts", value: String(row.attempts) },
          { label: "Queued", value: fmtTime(row.created_at) },
          { label: "Last update", value: fmtTime(row.updated_at) },
          { label: "Next attempt", value: fmtTime(row.next_attempt_at) },
          { label: "Claimed", value: row.claimed_at
              ? fmtTime(row.claimed_at) +
                (row.claimed_until ? " – " + fmtTime(row.claimed_until) : "") +
                (row.claimed_by ? " by " + row.claimed_by : "")
              : "—" },
          { label: "Depends on", value: (row.depends_on || []).length
              ? row.depends_on.map(function (d) {
                  return d.slice(0, 8) + "…" + d.slice(-4);
                }).join(", ")
              : "—" }
        ];
        if (row.last_error) {
          fields.push({ label: "Last error", value: row.last_error });
        }
        return fields;
      },
      gmPubStateLabel: function (s) {
        return STATE_PILLS[s] || s;
      },
      /* Relays named in a partial publication — configured public
         targets minus the ones that returned a positive ACK. */
      gmMissingRelays: function (intent) {
        var pubs = intent.relay_publications || [];
        var accepted = {};
        pubs.forEach(function (p) {
          if (p.result === "accepted") accepted[p.relay_url] = true;
        });
        var targets = (this.gmPubs.relays || [])
          .filter(function (r) {
            return r.enabled &&
              (r.direction === "public" || r.direction === "both");
          })
          .map(function (r) {
            return r.relay_url;
          });
        var missing = targets.filter(function (r) {
          return !accepted[r];
        });
        if (missing.length) return missing;
        /* Fallback: publication rows that did not land an ACK. */
        return pubs
          .filter(function (p) { return p.result !== "accepted"; })
          .map(function (p) { return p.relay_url; });
      },
      gmRunRelayCheck: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        self.gmPubs.check.busy = true;
        self.gmPubs.error = null;
        try {
          var res = await self.gmApi(
            "POST",
            "/merchants/" + mid + "/catalog/relay-check",
            {}
          );
          self.gmPubs.check.checked_at = res.checked_at;
          self.gmPubs.check.relays = res.relays || [];
          self.gmPubs.check.items = res.items || [];
          self.gmPubs.check.unmatched = res.unmatched || [];
          self.gmPubs.check.summary = res.summary || null;
        } catch (e) {
          self.gmPubs.error = self.gmProblemCopy(e.problem);
        }
        self.gmPubs.check.busy = false;
      },
      gmRelayCheckRows: function () {
        var check = this.gmPubs.check;
        var rows = check.items || [];
        if (!check.showAll) {
          rows = rows.filter(function (r) {
            return r.expected || r.observed_on.length ||
              r.tombstoned_on.length || r.status !== "not-observed";
          });
        }
        if (check.localStates.length) {
          rows = rows.filter(function (r) {
            return check.localStates.indexOf(r.local.state) !== -1;
          });
        }
        if (check.results.length) {
          rows = rows.filter(function (r) {
            return check.results.indexOf(r.status) !== -1;
          });
        }
        return rows;
      },
      gmRelayCheckSetLocalStates: function (value) {
        this.gmPubs.check.localStates = Array.isArray(value) ? value : [];
      },
      gmRelayCheckSetResults: function (value) {
        this.gmPubs.check.results = Array.isArray(value) ? value : [];
      },
      gmRelayCheckClearFilters: function () {
        this.gmPubs.check.localStates = [];
        this.gmPubs.check.results = [];
      },
      gmRelayCheckStaleAddresses: function () {
        return (this.gmPubs.check.items || [])
          .filter(function (r) {
            return r.status === "stale-deleted";
          })
          .map(function (r) { return r.address; });
      },
      gmReissueTombstones: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        var addresses = self.gmRelayCheckStaleAddresses();
        if (!addresses.length || self.gmPubs.check.reissuing) return;
        self.gmPubs.check.reissuing = true;
        self.gmPubs.error = null;
        try {
          var res = await self.gmApi(
            "POST",
            "/merchants/" + mid + "/catalog/tombstones/reissue",
            {addresses: addresses}
          );
          self.gmToast(
            res.queued + " deletion request" +
              (res.queued === 1 ? "" : "s") +
              " queued — relays may still ignore kind-5 removals",
            "positive"
          );
          await self.gmLoadPublications();
        } catch (e) {
          self.gmPubs.error = self.gmProblemCopy(e.problem);
        }
        self.gmPubs.check.reissuing = false;
      },
      gmRelayCheckKind: function (row) {
        var labels = {
          30017: "Stall",
          30018: "NIP-15 product",
          30402: "Product",
          30405: "Collection",
          30406: "Shipping"
        };
        return labels[row.kind] || "Kind " + row.kind;
      },
      gmRelayCheckLabel: function (row) {
        var labels = {
          observed: "Published",
          partial: "Partial",
          missing: "Missing",
          divergent: "Divergent",
          stale: "Stale copy",
          "stale-deleted": "Deleted copy served",
          "draft-copy-served": "Draft copy served",
          "inactive-copy-served": "Inactive copy served",
          "not-observed": "Not observed"
        };
        return labels[row.status] || row.status;
      },
      gmRelayCheckColor: function (row) {
        if ([
          "missing", "stale-deleted", "draft-copy-served",
          "inactive-copy-served"
        ].includes(row.status)) {
          return "negative";
        }
        if (["partial", "divergent", "stale"].includes(row.status)) {
          return "warning";
        }
        if (row.status === "observed") return "positive";
        return "grey";
      },
      gmRelayCheckFinding: function (code) {
        var labels = {
          "deleted-copy-served": "relay still serves a deleted catalog item",
          "tombstone-not-observed": "deletion event not observed",
          "tombstone-did-not-remove-copy": "relay kept a deleted copy",
          "draft-copy-served": "relay serves a draft",
          "inactive-copy-served": "relay serves an item that is not currently publishable",
          "missing-on-checked-relays": "not returned by any healthy relay",
          "missing-on-some-relays": "missing on some relays",
          "relay-divergence": "relays disagree about the latest event",
          "revision-history-observed": "relay returned multiple revisions",
          "same-title-local-records": "same title exists on multiple local records",
          "older-than-local-latest": "relay copy is older than local evidence",
          "stock-tag-missing": "no stock tag — some public marketplaces omit this product"
        };
        return labels[code] || code;
      },
      gmRelayCheckRelay: function (url) {
        return String(url || "").replace(/^wss?:\/\//, "");
      },
      gmRelayCheckErrors: function () {
        return (this.gmPubs.check.relays || []).filter(function (r) {
          return r.state !== "ok";
        });
      },
      gmLoadPublications: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        if (!mid) return;
        self.gmPubs.loading = true;
        self.gmPubs.error = null;
        try {
          var res = await Promise.all([
            self.gmApi("GET", "/merchants/" + mid + "/relay-health"),
            self.gmApi("GET", "/merchants/" + mid + "/outbox"),
            self.gmApi(
              "GET",
              "/merchants/" + mid + "/orders?state=needs_attention"
            )
          ]);
          self.gmPubs.relays = (res[0].relays || []).map(function (r) {
            r.rkey = r.relay_url + ":" + r.direction;
            return r;
          });
          self.gmPubs.defaults = res[0].defaults || { relays: [] };
          self.gmPubs.blossomServers = res[0].blossom_servers || [];
          self.gmPubs.intents = res[1].intents || [];
          self.gmPubs.exceptionOrders = res[2] || [];
        } catch (e) {
          self.gmPubs.error = self.gmProblemCopy(e.problem);
        }
        self.gmPubs.loading = false;
      },
      gmRetryIntent: async function (intent) {
        var self = this;
        var mid = self.gmMerchantId();
        self.gmPubs.retrying = intent.id;
        try {
          await self.gmApi(
            "POST",
            "/merchants/" + mid + "/outbox/" + intent.id + "/retry",
            {}
          );
          await self.gmLoadPublications();
        } catch (e) {
          self.gmPubs.error = self.gmProblemCopy(e.problem);
        }
        self.gmPubs.retrying = null;
      },
      gmPruneOutbox: async function () {
        var self = this;
        var mid = self.gmMerchantId();
        self.gmPubs.prune.busy = true;
        self.gmPubs.prune.result = null;
        try {
          var res = await self.gmApi(
            "POST",
            "/merchants/" + mid + "/outbox/prune",
            {older_than_days: self.gmPubs.prune.days}
          );
          self.gmPubs.prune.result = res;
          await self.gmLoadPublications();
        } catch (e) {
          self.gmPubs.error = self.gmProblemCopy(e.problem);
          self.gmPubs.prune.show = false;
        }
        self.gmPubs.prune.busy = false;
      },
      gmPubCellLabel: function (p) {
        if (!p) return "—";
        if (p.result === "accepted") return "ACKed";
        if (p.result === "rejected") return "Rejected";
        return "Failed";
      }
    },
    mounted: function () {
      if (window._gmPubsWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmPubsWired = true;
      var self = root.proxy;
      self.$watch("gm.merchant", function (m) {
        if (m && self.gm.view === "publications") {
          self.gmLoadPublications();
        }
      });
    }
  });
})();
