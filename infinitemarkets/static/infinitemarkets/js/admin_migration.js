(function () {
  "use strict";

  function csrfToken() {
    var match = document.cookie.match(/(?:^|; )gm_csrf=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  window.app.mixin({
    data: function () {
      return {
        gmMigration: {
          file: null,
          sourceInstance: "",
          currency: "",
          selections: {},
          selectionDirty: false,
          preview: null,
          result: null,
          error: null,
          busy: false
        }
      };
    },
    methods: {
      gmMigrationFileChanged: function (event) {
        this.gmMigration.file = event.target.files[0] || null;
        this.gmMigration.preview = null;
        this.gmMigration.result = null;
        this.gmMigration.selections = {};
        this.gmMigration.selectionDirty = false;
      },
      gmToggleImportImage: function (handle, url, selected) {
        var state = this.gmMigration;
        var chosen = (state.selections[handle] || []).slice();
        if (selected && chosen.indexOf(url) === -1) {
          if (chosen.length >= 20) {
            state.error = "Select no more than 20 images per product.";
            return;
          }
          chosen.push(url);
        } else if (!selected) {
          chosen = chosen.filter(function (item) { return item !== url; });
        }
        state.selections[handle] = chosen;
        state.selectionDirty = true;
        state.error = null;
      },
      gmShopifyUpload: async function (operation) {
        var state = this.gmMigration;
        state.busy = true;
        state.error = null;
        try {
          var form = new FormData();
          form.append("file", state.file);
          form.append("currency", state.currency.trim().toUpperCase());
          form.append("source_instance", state.sourceInstance.trim());
          if (Object.keys(state.selections).length) {
            form.append("image_selection", JSON.stringify(state.selections));
          }
          if (operation === "execute") {
            form.append("source_hash", state.preview.source_hash);
          }
          var response = await fetch(
            "/infinitemarkets/api/v1/migration/shopify/" + operation,
            {
              method: "POST",
              credentials: "same-origin",
              headers: { "X-CSRF-Token": csrfToken() },
              body: form
            }
          );
          var result = await response.json();
          if (!response.ok) {
            throw new Error(result.detail || result.title || "Import failed");
          }
          if (operation === "preview") {
            state.preview = result;
            state.selectionDirty = false;
            state.result = null;
          } else {
            state.result = result;
            state.preview = null;
            if (this.gmLoadCatalog) this.gmLoadCatalog();
          }
        } catch (error) {
          state.error = error.message || "Import failed";
        } finally {
          state.busy = false;
        }
      },
      gmPreviewShopify: function () {
        this.gmShopifyUpload("preview");
      },
      gmExecuteShopify: function () {
        this.gmShopifyUpload("execute");
      }
    }
  });
})();
