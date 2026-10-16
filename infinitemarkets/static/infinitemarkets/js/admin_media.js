/* admin_media.js — shared image-upload control + transport (MEDIA-02/03/08/12).

   Registers `gm-media-picker`, the one upload control reused at every
   image field site (product gallery, avatar, banner, brand logo, hero
   background, footer logo, custom share image): a dashed drop-zone that
   doubles as the Choose-files button, plus an in-control destination
   selector ("Save to LNbits" / "Save to Blossom · <hostname>") that
   renders only when a Blossom server is configured. Local is the
   default on every mount — the choice is made at the moment of upload,
   one backend per file, and is never persisted.

   The companion mixin carries the shared `gmMedia` slice: a lazy
   Blossom-server list (seeded from a prior settings load when present,
   else fetched from relay-health) and `gmMediaUpload`, an XMLHttpRequest
   multipart helper — fetch() cannot report upload progress, and
   MEDIA-12 requires per-file progress. FormData carries exactly
   `usage`, `backend`, `file`: the server's multipart parser is bounded
   to 4 non-file fields and a third text part 422s invalid-content.
   CSRF uses the same double-submit pattern as admin_migration.js —
   X-CSRF-Token echoing the gm_csrf cookie; no Content-Type (the browser
   sets the multipart boundary); no Idempotency-Key (D-28, matching the
   migration-upload precedent). */
(function () {
  "use strict";

  function csrfToken() {
    var match = document.cookie.match(/(?:^|; )gm_csrf=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  window.app.component("gm-media-picker", {
    props: {
      usage: { type: String, default: "catalog" },
      multiple: { type: Boolean, default: false },
      disabled: { type: Boolean, default: false },
      blossomServers: {
        type: Array,
        default: function () { return []; }
      }
    },
    emits: ["files-chosen", "servers-needed"],
    data: function () {
      /* D-17: the destination resets to local on EVERY mount and is
         never persisted — it is chosen at the moment of upload. */
      return { backend: "local", drag: false };
    },
    computed: {
      blossomHost: function () {
        try {
          return new URL(this.blossomServers[0] || "").hostname;
        } catch (e) {
          return "";
        }
      },
      destinationLabel: function () {
        return this.backend === "blossom" && this.blossomHost
          ? "Blossom · " + this.blossomHost
          : "this LNbits";
      },
      backendOptions: function () {
        return [
          { value: "local", label: "Save to LNbits" },
          {
            value: "blossom",
            label: "Save to Blossom · " + this.blossomHost
          }
        ];
      }
    },
    mounted: function () {
      /* Parents lazy-load the server list — emit so they can fetch on
         first sight of a picker rather than on every nav. */
      this.$emit("servers-needed");
    },
    methods: {
      pick: function () {
        if (this.disabled) return;
        this.$refs.input.click();
      },
      onFiles: function (list) {
        if (this.disabled) return;
        var files = Array.prototype.slice.call(list || []);
        if (files.length) {
          this.$emit("files-chosen", {
            files: files,
            backend: this.backend
          });
        }
        /* Reset so choosing the same file twice still fires change. */
        this.$refs.input.value = "";
      }
    },
    template:
      '<div class="gm-media-picker">' +
      '  <div class="gm-drop" :class="{drag: drag}" role="button"' +
      '       tabindex="0" :aria-disabled="disabled"' +
      '       @click="pick"' +
      '       @keydown.enter.prevent="pick"' +
      '       @keydown.space.prevent="pick"' +
      '       @dragover.prevent="drag = true"' +
      '       @dragleave="drag = false"' +
      '       @drop.prevent="drag = false; onFiles($event.dataTransfer.files)">' +
      '    <input ref="input" type="file" hidden :multiple="multiple"' +
      '           :disabled="disabled"' +
      '           accept="image/png,image/jpeg,image/webp"' +
      '           @change="onFiles($event.target.files)">' +
      '    <div class="gm-drop-label">Drop images here or choose files' +
      '      — saved to {{ destinationLabel }} when you upload.' +
      '      Uploading is not saving; save the form to keep it.</div>' +
      '  </div>' +
      '  <q-select v-if="blossomServers.length" v-model="backend" dense' +
      '            outlined emit-value map-options class="q-mt-xs"' +
      '            :options="backendOptions"' +
      '            label="Upload destination"></q-select>' +
      '</div>'
  });

  window.app.mixin({
    data: function () {
      return {
        gmMedia: {
          servers: [],
          serversLoaded: false,
          uploading: false,
          progress: 0,
          /* MEDIA-03: a Blossom failure keeps the rejected File so the
             merchant can explicitly retry to LNbits — never silently. */
          retryFile: null,
          retryLocal: false
        }
      };
    },
    methods: {
      /* Lazy Blossom-server list — seeded from gmSettings.blossom when a
         settings load already fetched relay-health (same payload), else
         fetched here. Idempotent: safe as every picker's servers-needed
         handler. */
      gmMediaLoadServers: async function () {
        var self = this;
        if (self.gmMedia.serversLoaded || !self.gmMerchantId()) return;
        if (self.gmSettings && self.gmSettings.blossom &&
            self.gmSettings.blossom.length) {
          self.gmMedia.servers = self.gmSettings.blossom;
          self.gmMedia.serversLoaded = true;
          return;
        }
        try {
          var res = await self.gmApi(
            "GET", "/merchants/" + self.gmMerchantId() + "/relay-health"
          );
          self.gmMedia.servers = res.blossom_servers || [];
        } catch (e) {
          self.gmMedia.servers = [];
        }
        self.gmMedia.serversLoaded = true;
      },
      /* One file per request; resolves the response body on 2xx,
         rejects an Error carrying {status, problem} for gmProblemCopy. */
      gmMediaUpload: function (file, usage, backend, onProgress) {
        return new Promise(function (resolve, reject) {
          var form = new FormData();
          form.append("usage", usage);
          form.append("backend", backend);
          form.append("file", file);
          var xhr = new XMLHttpRequest();
          xhr.open("POST", "/infinitemarkets/api/v1/media/upload");
          xhr.withCredentials = true;
          xhr.setRequestHeader("X-CSRF-Token", csrfToken());
          xhr.upload.onprogress = function (e) {
            if (e.lengthComputable && onProgress) {
              onProgress(e.loaded / e.total);
            }
          };
          xhr.onload = function () {
            var body = {};
            try {
              body = JSON.parse(xhr.responseText || "{}");
            } catch (e) { /* keep {} */ }
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(body);
            } else {
              reject(Object.assign(
                new Error(
                  (body && (body.detail || body.title)) ||
                  "Upload failed"
                ),
                { status: xhr.status, problem: body }
              ));
            }
          };
          xhr.onerror = function () {
            reject(new Error("Upload failed"));
          };
          xhr.send(form);
        });
      }
    }
  });
})();
