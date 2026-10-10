/* admin_catalog.js — B3 catalog management (UI-SPEC §B3).

   Dense lists for products / collections / shipping with draft badges,
   visibility pills, soft-delete dialogs (tombstone disclosure verbatim),
   and a read-only unsigned-event dry-run viewer. Every mutating control
   carries a text label — no icon-only mutators. */
(function () {
  "use strict";

  var PRODUCT_TYPES = ["simple", "variable", "variation"];
  var FORMATS = ["digital", "physical"];
  var VISIBILITIES = ["on-sale", "hidden", "pre-order"];
  var SERVICES = ["standard", "express", "overnight", "pickup"];
  var DURATION_UNITS = ["H", "D", "W"];
  var COUNTRY_CODES = (
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ " +
    "BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ " +
    "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ " +
    "DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR " +
    "GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY " +
    "HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP " +
    "KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY " +
    "MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ " +
    "NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY " +
    "QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ " +
    "TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ " +
    "UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
  ).split(" ");
  var EU_COUNTRIES = (
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE"
  ).split(" ");
  var countryNames = typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames([navigator.language || "en"], { type: "region" })
    : null;
  var COUNTRY_OPTIONS = COUNTRY_CODES.map(function (code) {
    return {
      label: (countryNames ? countryNames.of(code) : code) + " (" + code + ")",
      value: code
    };
  }).sort(function (a, b) { return a.label.localeCompare(b.label); });
  var COUNTRY_LABELS = Object.fromEntries(COUNTRY_OPTIONS.map(function (item) {
    return [item.value, item.label];
  }));
  var PRODUCT_COLUMNS = [
    { name: "actions", label: "Actions", field: "id", align: "left", style: "width: 124px", headerStyle: "width: 124px" },
    { name: "title", label: "Title", field: "title", align: "left", sortable: true },
    { name: "type", label: "Type", field: "_typeSort", align: "left", sortable: true, style: "width: 140px", headerStyle: "width: 140px" },
    { name: "price", label: "Price", field: "_priceSort", align: "left", sortable: true, style: "width: 104px", headerStyle: "width: 104px" },
    { name: "stock", label: "Stock", field: "_stockSort", align: "left", sortable: true, style: "width: 88px", headerStyle: "width: 88px" },
    { name: "visibility", label: "Visibility", field: "visibility", align: "left", sortable: true, style: "width: 104px", headerStyle: "width: 104px" },
    { name: "state", label: "State", field: "nip99_status", align: "left", sortable: true, style: "width: 90px", headerStyle: "width: 90px" },
    { name: "delete", label: "Delete", field: "id", align: "left", style: "width: 68px", headerStyle: "width: 68px" }
  ];
  var CATEGORY_COLUMNS = [
    { name: "name", label: "Name", field: "name", align: "left", sortable: true, style: "width: 240px", headerStyle: "width: 240px" },
    { name: "products", label: "Products", field: "_products", align: "left", style: "width: 100px", headerStyle: "width: 100px" },
    { name: "description", label: "Description", field: "description", align: "left", style: "width: 280px", headerStyle: "width: 280px" },
    { name: "actions", label: "Actions", field: "id", align: "left", style: "width: 120px", headerStyle: "width: 120px" }
  ];
  var COLLECTION_COLUMNS = [
    { name: "title", label: "Title", field: "title", align: "left", sortable: true, style: "width: 280px", headerStyle: "width: 280px" },
    { name: "id", label: "ID", field: "d_tag", align: "left", style: "width: 220px", headerStyle: "width: 220px" },
    { name: "actions", label: "Actions", field: "id", align: "left", style: "width: 120px", headerStyle: "width: 120px" }
  ];
  var SHIPPING_COLUMNS = [
    { name: "title", label: "Title", field: "title", align: "left", sortable: true, style: "width: 180px", headerStyle: "width: 180px" },
    { name: "service", label: "Service", field: "service", align: "left", style: "width: 110px", headerStyle: "width: 110px" },
    { name: "price", label: "Price", field: "base_price_minor", align: "left", style: "width: 120px", headerStyle: "width: 120px" },
    { name: "countries", label: "Countries", field: "countries", align: "left", style: "width: 180px", headerStyle: "width: 180px" },
    { name: "active", label: "Active", field: "active", align: "left", style: "width: 80px", headerStyle: "width: 80px" },
    { name: "actions", label: "Actions", field: "id", align: "left", style: "width: 150px", headerStyle: "width: 150px" }
  ];
  /* Common codes offered as dropdown options — the backend accepts any
     ^[A-Z0-9]{3,8}$ code, so the editor also keeps free-text entry. */
  var CURRENCIES = [
    "SAT", "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF",
    "BRL", "MXN", "INR", "KRW", "PLN", "SEK", "NOK", "DKK",
    "NZD", "SGD", "HKD", "ZAR", "BTC"
  ];
  /* Mirrors fx.default_currency_decimals for the dropdown codes —
     anything unlisted defaults to 2 like the backend. */
  var CURRENCY_DECIMALS = {
    SAT: 0, BTC: 8, JPY: 0, KRW: 0
  };
  var gmDecimals = function (code) {
    var d = CURRENCY_DECIMALS[String(code || "").toUpperCase()];
    return d === undefined ? 2 : d;
  };
  var BULK_ACTIONS = [
    { label: "Increase prices by percentage", value: "price-markup" },
    { label: "Move to collection", value: "move-collection" },
    { label: "Set visibility", value: "visibility" },
    { label: "Move to draft", value: "draft" },
    { label: "Remove draft status", value: "publish" }
  ];

  var DELETE_DISCLOSURE =
    "This is a soft delete. A deletion tombstone is published, but" +
    " removal from every relay and client cannot be guaranteed.";
  var IMAGE_DISCLOSURE = "Remote image hosts can learn viewer IP and time";

  window.app.mixin({
    data: function () {
      return {
        gmCatalog: {
          loading: false,
          error: null,
          tab: "products",
          categories: [],
          products: [],
          collections: [],
          shipping: [],
          countryOptions: COUNTRY_OPTIONS,
          productColumns: PRODUCT_COLUMNS,
          categoryColumns: CATEGORY_COLUMNS,
          collectionColumns: COLLECTION_COLUMNS,
          shippingColumns: SHIPPING_COLUMNS,
          selectedProducts: [],
          bulkActions: BULK_ACTIONS,
          bulkEditor: {
            show: false, saving: false, error: null, action: null,
            markup: 10, collectionId: null, visibility: "on-sale"
          },
          bulkDeleteDialog: { show: false, busy: false, error: null },
          notice: null,
          services: SERVICES,
          productTypes: PRODUCT_TYPES,
          formats: FORMATS,
          visibilities: VISIBILITIES,
          currencies: CURRENCIES,
          durationUnits: DURATION_UNITS,
          imageDisclosure: IMAGE_DISCLOSURE,
          deleteDisclosure: DELETE_DISCLOSURE,
          editor: {
            show: false, saving: false, error: null, isNew: true,
            form: {}
          },
          categoryEditor: {
            show: false, saving: false, error: null, isNew: true,
            form: {}
          },
          collectionEditor: {
            show: false, saving: false, error: null, isNew: true,
            form: {}
          },
          shippingEditor: {
            show: false, saving: false, error: null, isNew: true,
            form: {}
          },
          deleteDialog: {
            show: false, kind: "", id: "", title: "", refs: null,
            busy: false
          },
          expandedProducts: [],
          dryRun: { show: false, json: "", loading: false }
        }
      };
    },
    computed: {
      gmShippingEuSelected: function () {
        var selected = this.gmCatalog.shippingEditor.form.countries || [];
        return EU_COUNTRIES.every(function (code) { return selected.includes(code); });
      },
      gmShippingChoices: function () {
        return this.gmCatalog.shipping.map(function (option) {
          return Object.assign({}, option, {
            title: option.title + (option.active ? "" : " (inactive)"),
            disable: !option.active
          });
        });
      },
      gmCatalogRows: function () {
        var counts = {};
        this.gmCatalog.products.forEach(function (p) {
          counts[p.category_id] = (counts[p.category_id] || 0) + 1;
        });
        return this.gmCatalog.categories.map(function (c) {
          return Object.assign({}, c, { _products: counts[c.id] || 0 });
        });
      },
      gmProductRows: function () {
        /* Variations are rows of their parent product, not standalone
           entries — nest them under the parent so a sized product reads
           as one listing with options. */
        var children = {};
        var parents = [];
        var byId = {};
        this.gmCatalog.products.forEach(function (p) {
          byId[p.id] = p;
          if (p.product_type === "variation" && p.parent_product_id) {
            (children[p.parent_product_id] =
              children[p.parent_product_id] || []).push(p);
          }
        });
        this.gmCatalog.products.forEach(function (p) {
          if (p.product_type !== "variation" ||
              !p.parent_product_id ||
              !byId[p.parent_product_id] ||
              byId[p.parent_product_id].product_type !== "variable") {
            parents.push(p);
          }
        });

        function decorate(p, opts) {
          var unlimited = p.stock_on_hand === null || p.stock_on_hand === undefined;
          var stockValue = unlimited
            ? Number.MAX_SAFE_INTEGER
            : (p.stock_on_hand || 0) - (p.stock_reserved || 0);
          var stock = unlimited ? "Unlimited" : String(stockValue);
          var price = "—";
          var priceSort = Number.MAX_SAFE_INTEGER;
          if (p.amount_minor !== null && p.amount_minor !== undefined) {
            var dec = p.currency_decimals || 0;
            priceSort = p.amount_minor;
            price = dec > 0
              ? (p.amount_minor / Math.pow(10, dec)).toFixed(dec) +
                " " + (p.currency || "SAT")
              : p.amount_minor + " " + (p.currency || "SAT");
          }
          return Object.assign({}, p, opts || {}, {
            _stock: stock,
            _stockSort: stockValue,
            _price: price,
            _priceSort: priceSort,
            _typeSort: (p.product_type || "") + "/" + (p.format || "")
          });
        }

        var self = this;
        var rows = [];
        parents.forEach(function (p) {
          var kids = children[p.id] || [];
          var prow = decorate(p, { _variantCount: kids.length });
          if (kids.length) {
            /* A variable parent's own stock row is meaningless — sellable
               units live on the options. Show the live aggregate. */
            var sum = 0;
            var anyUnlimited = false;
            kids.forEach(function (v) {
              if (v.stock_on_hand === null || v.stock_on_hand === undefined) {
                anyUnlimited = true;
              } else {
                sum += (v.stock_on_hand || 0) - (v.stock_reserved || 0);
              }
            });
            prow._stock = anyUnlimited ? "Unlimited" : sum + " total";
            prow._stockSort = anyUnlimited ? Number.MAX_SAFE_INTEGER : sum;
          }
          rows.push(prow);
          if (self.gmCatalog.expandedProducts.includes(p.id)) {
            kids.forEach(function (v) {
              rows.push(decorate(v, {
                _variantOf: (byId[p.id].title || "") ||
                  byId[p.id].d_tag,
                _isVariant: true
              }));
            });
          }
        });
        return rows;
      }
    },
    methods: {
      gmDecimals: gmDecimals,
      gmPrice: function (minor, currency, decimals) {
        if (minor === null || minor === undefined) return "—";
        var dec = decimals || 0;
        return dec > 0
          ? (minor / Math.pow(10, dec)).toFixed(dec) +
              " " + (currency || "SAT")
          : minor + " " + (currency || "SAT");
      },
      gmOnCurrency: function (val) {
        /* Keep decimals in step with the picked currency — the editor
           works in major units and stores minor units on save. */
        var f = this.gmCatalog.editor.form;
        f.currency = val;
        f.currency_decimals = gmDecimals(val);
      },
      gmOnShippingCurrency: function (val) {
        var f = this.gmCatalog.shippingEditor.form;
        f.currency = val;
        f.currency_decimals = gmDecimals(val);
      },
      gmLoadCatalog: async function () {
        var self = this;
        self.gmCatalog.loading = true;
        self.gmCatalog.error = null;
        try {
          var res = await Promise.all([
            self.gmApi("GET", "/categories"),
            self.gmApi("GET", "/products"),
            self.gmApi("GET", "/collections"),
            self.gmApi("GET", "/shipping")
          ]);
          self.gmCatalog.categories = res[0];
          self.gmCatalog.products = res[1];
          self.gmCatalog.collections = res[2];
          self.gmCatalog.shipping = res[3];
          self.gmCatalog.selectedProducts = [];
        } catch (e) {
          self.gmCatalog.error = self.gmProblemCopy(e.problem);
        }
        self.gmCatalog.loading = false;
      },

      /* --- products ---------------------------------------------------- */
      gmNewProduct: function () {
        this.gmCatalog.tab = "products";
        this.gmCatalog.bulkEditor.show = false;
        this.gmCatalog.editor = {
          show: true, saving: false, error: null, isNew: true,
          form: {
            category_id: this.gmCatalog.categories.length
              ? this.gmCatalog.categories[0].id
              : "",
            title: "", summary: "", description_md: "",
            product_type: "simple", format: "digital",
            price_major: 0, currency: "SAT", currency_decimals: 0,
            visibility: "on-sale", draft: false,
            stock_on_hand: null,
            parent_product_id: "",
            collection_ids: [], shipping_option_ids: [],
            shipping_option_extras: {}, images_text: "", delivery_content: ""
          }
        };
      },
      gmEditProduct: async function (row) {
        var self = this;
        self.gmCatalog.tab = "products";
        self.gmCatalog.bulkEditor.show = false;
        var d = await self.gmApi("GET", "/products/" + row.id);
        self.gmCatalog.editor = {
          show: true, saving: false, error: null, isNew: false,
          form: {
            id: d.id,
            category_id: d.category_id,
            title: d.title || "", summary: d.summary || "",
            description_md: d.description_md || "",
            product_type: d.product_type || "simple",
            format: d.format || "digital",
            price_major: (d.amount_minor || 0) /
              Math.pow(10, d.currency_decimals || 0),
            currency: d.currency || "SAT",
            currency_decimals:
              d.currency_decimals === null ||
              d.currency_decimals === undefined
                ? gmDecimals(d.currency || "SAT")
                : d.currency_decimals,
            visibility: d.visibility || "on-sale",
            draft: !!d.draft,
            stock_on_hand: d.stock_on_hand,
            parent_product_id: d.parent_product_id || "",
            collection_ids: d.collection_ids || [],
            shipping_option_ids: (d.shipping_options || []).map(function (option) {
              return option.shipping_option_id;
            }),
            shipping_option_extras: (d.shipping_options || []).reduce(function (extras, option) {
              extras[option.shipping_option_id] = option.extra_cost_minor;
              return extras;
            }, {}),
            images_text: (d.images || [])
              .map(function (i) { return i.url; })
              .join("\n"),
            delivery_content: d.delivery_content || ""
          }
        };
      },
      gmSaveProduct: async function () {
        var self = this;
        var ed = self.gmCatalog.editor;
        ed.saving = true;
        ed.error = null;
        var f = ed.form;
        var body = {
          category_id: f.category_id,
          title: f.title,
          summary: f.summary || undefined,
          description_md: f.description_md || undefined,
          product_type: f.product_type,
          format: f.format,
          amount_minor: Math.round(
            (Number(f.price_major) || 0) *
            Math.pow(10, f.currency_decimals === null ||
              f.currency_decimals === undefined
              ? gmDecimals(f.currency) : f.currency_decimals)
          ),
          currency: f.currency || "SAT",
          currency_decimals: f.currency_decimals === null ||
            f.currency_decimals === undefined
            ? gmDecimals(f.currency) : f.currency_decimals,
          visibility: f.visibility,
          draft: !!f.draft,
          stock_on_hand:
            f.stock_on_hand === null || f.stock_on_hand === "" ||
              f.stock_on_hand === undefined
              ? null
              : Number(f.stock_on_hand),
          collection_ids: f.collection_ids || [],
          shipping_option_ids: f.format === "physical"
            ? (f.shipping_option_ids || []).map(function (id) {
                var extra = f.shipping_option_extras[id];
                return extra == null ? id : { id: id, extra_cost_minor: extra };
              })
            : []
        };
        if (f.format === "digital") {
          body.delivery_content = (f.delivery_content || "").trim();
        }
        if (f.product_type === "variation" && f.parent_product_id) {
          body.parent_product_id = f.parent_product_id;
        }
        var images = (f.images_text || "")
          .split("\n")
          .map(function (s) { return s.trim(); })
          .filter(function (s) { return s.length; })
          .map(function (u) { return { url: u }; });
        if (images.length) body.images = images;
        try {
          if (ed.isNew) {
            await self.gmApi("POST", "/products", body);
          } else {
            await self.gmApi("PATCH", "/products/" + f.id, body);
          }
          ed.show = false;
          self.gmCatalog.notice = ed.isNew ? "Product created." : "Product saved.";
          await self.gmLoadCatalog();
        } catch (e) {
          ed.error = self.gmProblemCopy(e.problem);
        }
        ed.saving = false;
      },
      gmToggleVariants: function (id) {
        var list = this.gmCatalog.expandedProducts;
        var i = list.indexOf(id);
        if (i >= 0) list.splice(i, 1);
        else list.push(id);
      },
      gmDryRun: async function (row) {
        /* GET /products/{id}/events — rendered unsigned JSON viewer. */
        var self = this;
        self.gmCatalog.dryRun = { show: true, json: "", loading: true };
        try {
          var events = await self.gmApi(
            "GET", "/products/" + row.id + "/events"
          );
          self.gmCatalog.dryRun.json = JSON.stringify(events, null, 2);
        } catch (e) {
          self.gmCatalog.dryRun.json = self.gmProblemCopy(e.problem);
        }
        self.gmCatalog.dryRun.loading = false;
      },
      gmOpenBulkEditor: function () {
        if (!this.gmCatalog.selectedProducts.length) return;
        this.gmCatalog.editor.show = false;
        this.gmCatalog.bulkEditor = {
          show: true, saving: false, error: null, action: null,
          markup: 10, collectionId: null, visibility: "on-sale"
        };
      },
      gmApplyBulk: async function () {
        var self = this;
        var ed = self.gmCatalog.bulkEditor;
        var selected = self.gmCatalog.selectedProducts;
        ed.error = null;
        if (!selected.length) {
          ed.error = "Select at least one product.";
          return;
        }
        if (!ed.action) {
          ed.error = "Choose a bulk action.";
          return;
        }
        var body = {
          product_ids: selected.map(function (row) { return row.id; }),
          action: ed.action
        };
        if (ed.action === "price-markup") {
          var markup = Number(ed.markup);
          if (!Number.isFinite(markup) || markup <= 0 || markup > 10000) {
            ed.error = "Markup must be greater than 0% and at most 10,000%.";
            return;
          }
          body.value = markup;
        } else if (ed.action === "move-collection") {
          if (selected.some(function (row) { return !!row.draft; })) {
            ed.error = "Draft products cannot be moved to a collection. Remove draft status first.";
            return;
          }
          if (!ed.collectionId) {
            ed.error = "Choose a destination collection.";
            return;
          }
          body.value = ed.collectionId;
        } else if (ed.action === "visibility") {
          body.value = ed.visibility;
        }
        ed.saving = true;
        try {
          await self.gmApi("POST", "/products/bulk", body);
          self.gmCatalog.notice = selected.length + " products updated.";
          ed.show = false;
          await self.gmLoadCatalog();
        } catch (e) {
          ed.error = self.gmProblemCopy(e.problem);
        }
        ed.saving = false;
      },
      gmAskBulkDelete: function () {
        if (!this.gmCatalog.selectedProducts.length) return;
        this.gmCatalog.bulkDeleteDialog = {
          show: true, busy: false, error: null
        };
      },
      gmBulkDeleteConfirm: async function () {
        var self = this;
        var dialog = self.gmCatalog.bulkDeleteDialog;
        var ids = self.gmCatalog.selectedProducts.map(function (row) {
          return row.id;
        });
        dialog.busy = true;
        dialog.error = null;
        try {
          await self.gmApi("POST", "/products/bulk", {
            product_ids: ids,
            action: "delete"
          });
          dialog.show = false;
          self.gmCatalog.notice = ids.length + " products deleted.";
          await self.gmLoadCatalog();
        } catch (e) {
          dialog.error = self.gmProblemCopy(e.problem);
        }
        dialog.busy = false;
      },

      /* --- collections ---------------------------------------------------- */
      gmNewCollection: function () {
        this.gmCatalog.tab = "collections";
        this.gmCatalog.collectionEditor = {
          show: true, saving: false, error: null, isNew: true,
          form: { title: "", description: "", image: "", location: "" }
        };
      },
      gmEditCollection: function (row) {
        this.gmCatalog.tab = "collections";
        this.gmCatalog.collectionEditor = {
          show: true, saving: false, error: null, isNew: false,
          form: {
            id: row.id, title: row.title || "",
            description: row.description || "", image: row.image || "",
            location: row.location || ""
          }
        };
      },
      gmSaveCollection: async function () {
        var self = this;
        var ed = self.gmCatalog.collectionEditor;
        ed.saving = true;
        ed.error = null;
        var f = ed.form;
        var body = {
          title: f.title,
          description: f.description || undefined,
          image: f.image || undefined,
          location: f.location || undefined
        };
        try {
          if (ed.isNew) {
            await self.gmApi("POST", "/collections", body);
          } else {
            await self.gmApi("PATCH", "/collections/" + f.id, body);
          }
          ed.show = false;
          self.gmCatalog.notice = ed.isNew ? "Collection created." : "Collection saved.";
          await self.gmLoadCatalog();
        } catch (e) {
          ed.error = self.gmProblemCopy(e.problem);
        }
        ed.saving = false;
      },

      /* --- categories ------------------------------------------------------ */
      gmNewCategory: function () {
        this.gmCatalog.tab = "categories";
        this.gmCatalog.categoryEditor = {
          show: true, saving: false, error: null, isNew: true,
          form: { name: "", description: "" }
        };
      },
      gmEditCategory: function (row) {
        this.gmCatalog.tab = "categories";
        this.gmCatalog.categoryEditor = {
          show: true, saving: false, error: null, isNew: false,
          form: {
            id: row.id, name: row.name || "",
            description: row.description || ""
          }
        };
      },
      gmSaveCategory: async function () {
        var self = this;
        var ed = self.gmCatalog.categoryEditor;
        ed.saving = true;
        ed.error = null;
        var f = ed.form;
        var body = {
          name: f.name,
          description: f.description || undefined
        };
        try {
          if (ed.isNew) {
            await self.gmApi("POST", "/categories", body);
          } else {
            await self.gmApi("PATCH", "/categories/" + f.id, body);
          }
          ed.show = false;
          self.gmCatalog.notice = ed.isNew ? "Category created." : "Category saved.";
          await self.gmLoadCatalog();
        } catch (e) {
          ed.error = self.gmProblemCopy(e.problem);
        }
        ed.saving = false;
      },

      /* --- shipping -------------------------------------------------------- */
      gmCountryLabel: function (code) {
        return COUNTRY_LABELS[code] || code + " (unsupported)";
      },
      gmFilterShippingCountries: function (term, update) {
        var query = (term || "").trim().toLowerCase();
        var self = this;
        update(function () {
          self.gmCatalog.countryOptions = query
            ? COUNTRY_OPTIONS.filter(function (item) {
                return item.label.toLowerCase().includes(query);
              })
            : COUNTRY_OPTIONS;
        });
      },
      gmToggleShippingEu: function (checked) {
        var f = this.gmCatalog.shippingEditor.form;
        this.gmCatalog.shippingEditor.error = null;
        f.countries = checked
          ? Array.from(new Set((f.countries || []).concat(EU_COUNTRIES)))
          : (f.countries || []).filter(function (code) {
              return !EU_COUNTRIES.includes(code);
            });
      },
      gmRemoveShippingCountry: function (code) {
        var f = this.gmCatalog.shippingEditor.form;
        f.countries = f.countries.filter(function (item) { return item !== code; });
      },
      gmNewShipping: function () {
        this.gmCatalog.tab = "shipping";
        this.gmCatalog.countryOptions = COUNTRY_OPTIONS;
        this.gmCatalog.shippingEditor = {
          show: true, saving: false, error: null, isNew: true,
          form: {
            title: "", service: "standard", base_price_major: 0,
            currency: "SAT", currency_decimals: 0,
            countries: [], regions_text: "",
            duration_min: null, duration_max: null, duration_unit: "D",
            location: "", active: true
          }
        };
      },
      gmEditShipping: function (row) {
        this.gmCatalog.tab = "shipping";
        this.gmCatalog.countryOptions = COUNTRY_OPTIONS;
        this.gmCatalog.shippingEditor = {
          show: true, saving: false, error: null, isNew: false,
          form: {
            id: row.id, title: row.title || "",
            service: row.service || "standard",
            base_price_major: (row.base_price_minor || 0) /
              Math.pow(10, row.currency_decimals || 0),
            currency: row.currency || "SAT",
            currency_decimals:
              row.currency_decimals === null ||
              row.currency_decimals === undefined
                ? gmDecimals(row.currency || "SAT")
                : row.currency_decimals,
            countries: Array.from(new Set((row.countries || []).flatMap(function (code) {
              return code === "EU" ? EU_COUNTRIES : [code];
            }))),
            regions_text: (row.regions || []).join(", "),
            duration_min: row.duration_min, duration_max: row.duration_max,
            duration_unit: row.duration_unit || "D",
            location: row.location || "", active: row.active !== false
          }
        };
      },
      gmSaveShipping: async function () {
        var self = this;
        var ed = self.gmCatalog.shippingEditor;
        ed.saving = true;
        ed.error = null;
        var f = ed.form;
        var splitList = function (s) {
          return (s || "")
            .split(",")
            .map(function (x) { return x.trim().toUpperCase(); })
            .filter(function (x) { return x.length; });
        };
        if (!f.countries.length || f.countries.some(function (code) {
          return !COUNTRY_LABELS[code];
        })) {
          ed.error = "Select at least one valid destination country.";
          ed.saving = false;
          return;
        }
        var body = {
          title: f.title,
          service: f.service,
          base_price_minor: Math.round(
            (Number(f.base_price_major) || 0) *
            Math.pow(10, f.currency_decimals === null ||
              f.currency_decimals === undefined
              ? gmDecimals(f.currency) : f.currency_decimals)
          ),
          currency: f.currency || "SAT",
          currency_decimals: f.currency_decimals === null ||
            f.currency_decimals === undefined
            ? gmDecimals(f.currency) : f.currency_decimals,
          countries: Array.from(new Set(f.countries)),
          regions: splitList(f.regions_text),
          duration_min:
            f.duration_min === null || f.duration_min === ""
              ? null
              : Number(f.duration_min),
          duration_max:
            f.duration_max === null || f.duration_max === ""
              ? null
              : Number(f.duration_max),
          duration_unit: f.duration_unit,
          location: f.location || undefined,
          active: !!f.active
        };
        try {
          if (ed.isNew) {
            await self.gmApi("POST", "/shipping", body);
          } else {
            await self.gmApi("PATCH", "/shipping/" + f.id, body);
          }
          ed.show = false;
          self.gmCatalog.notice = ed.isNew ? "Shipping option created." : "Shipping option saved.";
          await self.gmLoadCatalog();
        } catch (e) {
          ed.error = self.gmProblemCopy(e.problem);
        }
        ed.saving = false;
      },

      /* --- soft delete (tombstone disclosure + strip choice) -------------- */
      gmAskDelete: function (kind, row) {
        this.gmCatalog.deleteDialog = {
          show: true, kind: kind, id: row.id,
          title: row.title || row.name || row.d_tag, refs: null, busy: false
        };
      },
      gmDeleteConfirm: async function (strip) {
        var self = this;
        var dlg = self.gmCatalog.deleteDialog;
        dlg.busy = true;
        var path =
          "/" +
          (dlg.kind === "collection"
            ? "collections"
            : dlg.kind === "shipping"
              ? "shipping"
              : dlg.kind === "category"
                ? "categories"
                : "products") +
          "/" +
          dlg.id +
          (strip ? "?strip=true" : "");
        try {
          await self.gmApi("DELETE", path);
          dlg.show = false;
          await self.gmLoadCatalog();
        } catch (e) {
          /* 409 detail carries the reference report — offer the explicit
             strip-and-republish choice (spec §6.7). */
          if (e.status === 409) {
            dlg.refs = e.problem.detail || e.problem.title;
          } else {
            dlg.refs = self.gmProblemCopy(e.problem);
          }
        }
        dlg.busy = false;
      }
    },
    mounted: function () {
      if (window._gmCatalogWired) return;
      var vueEl = document.getElementById("vue");
      var root = vueEl && vueEl._vnode && vueEl._vnode.component;
      if (!root || !root.isMounted) return;
      if (!document.getElementById("gm-admin-root")) return;
      window._gmCatalogWired = true;
      var self = root.proxy;
      self.$watch("gm.merchant", function (m) {
        if (m && self.gm.view === "catalog") self.gmLoadCatalog();
      });
    }
  });
})();
