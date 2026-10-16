# Phase 7: Shared Image Editors - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-16
**Phase:** 7-shared-image-editors
**Areas discussed:** Gallery UX, Destination picker UX, Unused uploads placement, Upload entry points

---

## Prior context carried forward

- All milestone/Phase-6 locked decisions restated (destination choice
  semantics, 20-image cap, per-file progress/errors, URL preservation,
  disclosure copy) — not re-asked.
- Scout found: product images are a raw newline textarea
  (`images_text`, admin.html:619); `if (images.length) body.images=images`
  in admin_catalog.js:466 makes clear-all unreachable — folded into D-21
  as a required Phase-7 fix (MEDIA-13 already requires clear-all persist).
- Phase 6 supplies `POST /media/upload`, `GET`/`DELETE /media/unused`;
  the `/images/`→`/library/` mount fix (06-04) deferred the two stale
  admin.html label hints into this phase (D-19).

## Area: Gallery UX

- **Options presented:**
  1. Unified list, buttons, first=primary (recommended)
  2. Unified list + drag handles (desktop drag, more a11y work)
  3. Separate URL list + upload strip (least change, split mental model)
- **Selected:** Unified list, buttons, first=primary

## Area: Destination picker UX

- **Options presented:**
  1. In-control selector, local default (recommended)
  2. Per-editor default + in-control override
  3. Global Settings default, read-only in controls
- **Selected:** In-control selector, local default
- **Notes:** Blossom option renders only when servers are configured;
  selector names the server hostname per the disclosure-copy requirement.

## Area: Unused uploads placement

- **Options presented:**
  1. Settings → Media section (recommended)
  2. Link inside each uploader
  3. Catalog header chip
- **Selected:** Settings → Media section
- **Notes:** includes quota usage display.

## Area: Upload entry points

- **Options presented:**
  1. Button + drag-drop zone (recommended)
  2. Button only
  3. You decide
- **Selected:** Button + drag-drop zone

## Claude's discretion (unselected/delegated items)

- Component organization within the no-build-step Vue/Quasar admin
- Remote-URL thumbnails (direct load — no backend proxying, SSRF stands)
- Primary badge = position 0, no separate field
- Destination selector collapse behavior when no Blossom configured
- Per-file progress representation; Media block placement within Settings

## Deferred ideas

- MEDIA-20…23; server-side thumbnails; remote-blob management UI;
  drag-drop reordering.
