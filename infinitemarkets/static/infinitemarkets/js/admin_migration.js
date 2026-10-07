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
          sourceKind: "shopify",
          sourceInstance: "",
          mappingText: "",
          presetName: "",
          selectedPreset: null,
          presets: [],
          currency: "",
          selections: {},
          selectionDirty: false,
          imports: [],
          audit: null,
          cutover: null,
          preview: null,
          result: null,
          error: null,
          busy: false
        }
      };
    },
    methods: {
      gmLoadImports: async function () {
        try {
          this.gmMigration.imports = await this.gmApi("GET", "/migration/imports");
          this.gmMigration.presets = await this.gmApi("GET", "/migration/csv-presets");
        } catch (error) {
          this.gmMigration.error = this.gmProblemCopy(error.problem);
        }
      },
      gmLoadImportAudit: async function (id) {
        try {
          this.gmMigration.cutover = null;
          this.gmMigration.audit = await this.gmApi("GET", "/migration/imports/" + id);
        } catch (error) {
          this.gmMigration.error = this.gmProblemCopy(error.problem);
        }
      },
      gmStageCutover: async function (id) {
        try {
          this.gmMigration.cutover = await this.gmApi(
            "POST", "/migration/imports/" + id + "/cutover", {}
          );
          await this.gmLoadCutover(this.gmMigration.cutover.id);
        } catch (error) {
          this.gmMigration.error = this.gmProblemCopy(error.problem);
        }
      },
      gmLoadCutover: async function (id) {
        try {
          this.gmMigration.cutover = await this.gmApi(
            "GET", "/migration/cutovers/" + id
          );
        } catch (error) {
          this.gmMigration.error = this.gmProblemCopy(error.problem);
        }
      },
      gmCutoverAction: async function (action) {
        var epoch = this.gmMigration.cutover;
        try {
          await this.gmApi("POST", "/migration/cutovers/" + epoch.id + "/" + action, {});
          await this.gmLoadCutover(epoch.id);
        } catch (error) {
          this.gmMigration.error = this.gmProblemCopy(error.problem);
        }
      },
      gmChooseCsvPreset: function (id) {
        var preset = this.gmMigration.presets.find(function (item) {
          return item.id === id;
        });
        this.gmMigration.mappingText = preset ? JSON.stringify(preset.mapping) : "";
        this.gmMigration.selectionDirty = true;
      },
      gmSaveCsvPreset: async function () {
        var state = this.gmMigration;
        try {
          var mapping = JSON.parse(state.mappingText);
          await this.gmApi("POST", "/migration/csv-presets", {
            name: state.presetName, mapping: mapping
          });
          state.presets = await this.gmApi("GET", "/migration/csv-presets");
          state.error = null;
        } catch (error) {
          state.error = error.problem ? this.gmProblemCopy(error.problem) :
            "Enter a valid column mapping as JSON before saving.";
        }
      },
      gmMigrationKindChanged: function () {
        this.gmMigration.file = null;
        this.gmMigration.preview = null;
        this.gmMigration.selections = {};
        this.gmMigration.selectionDirty = false;
      },
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
          if (state.sourceKind === "shopify" && state.mappingText.trim()) {
            form.append("mapping", JSON.stringify(JSON.parse(state.mappingText)));
          }
          if (operation === "execute") {
            form.append("source_hash", state.preview.source_hash);
          }
          var route = state.sourceKind === "shopify" ? "shopify" :
            "legacy/" + state.sourceKind;
          var response = await fetch(
            "/infinitemarkets/api/v1/migration/" + route + "/" + operation,
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
          if (operation !== "execute") {
            state.preview = result;
            state.selectionDirty = false;
            state.result = null;
          } else {
            state.result = result;
            state.preview = null;
            this.gmLoadImports();
            this.gmLoadImportAudit(result.import_id);
            if (this.gmLoadCatalog) this.gmLoadCatalog();
          }
        } catch (error) {
          state.error = error.message || "Import failed";
        } finally {
          state.busy = false;
        }
      },
      gmExecuteShopify: function () {
        this.gmShopifyUpload("execute");
      }
    }
  });
})();
