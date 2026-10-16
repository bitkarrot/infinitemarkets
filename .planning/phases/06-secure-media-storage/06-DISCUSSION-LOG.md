# Phase 6: Secure Media Storage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-16
**Phase:** 6-secure-media-storage
**Areas discussed:** Leftover uploads, Upload batching, Non-HTTPS base URL edge, Quota scope

---

## Prior context carried forward

- Locked owner decisions from milestone-level discussion (one backend per
  upload, first-Blossom-server-only, server-side signing, 20-image product
  cap, 16/25MB/400MB bounds, PNG/JPEG/WebP only, orphan disclosure,
  GET-only redirects, local default without Blossom) were pre-answered and
  not re-asked.
- Codebase scout found `migration_media.py` already implements ~90% of the
  local adapter (namespace under `images/infinitemarkets/`, host `/images`
  mount, exact approved bounds, magic-byte sniff, sidecar ownership), and
  `ext_settings().public_base_url` already provides the canonical public
  HTTPS origin — both pre-answered as reusable assets.

## Area: Leftover uploads

- **Options presented:**
  1. Leave + cleanup control — leave file, disclose unreferenced state,
     add "view unused uploads" listing with explicit local delete (recommended)
  2. Leave, quota only — no cleanup UI
  3. Auto-remove local leftovers on cancel
- **Selected:** Leave + cleanup control
- **Notes:** Remote Blossom blobs are never auto-deleted (locked at
  milestone level); local deletion is permitted via the explicit control.

## Area: Upload batching

- **Options presented:**
  1. One file per request — per-file progress/retry, isolation (recommended)
  2. Batch multipart up to 16 files/request
- **Selected:** One file per request
- **Notes:** The 16-files-per-request bound stays as the service-level
  ceiling; the UI simply sends one at a time.

## Area: Non-HTTPS base URL edge

- **Options presented:**
  1. Block local upload on Nostr-profile fields with a plain-language
     prompt to configure INFINITEMARKETS_PUBLIC_BASE_URL or use external
     HTTPS/Blossom (recommended)
  2. Store anyway and let it fail downstream
- **Selected:** Block with prompt

## Area: Quota scope

- **Options presented:**
  1. Local only — quota counts LNbits-local bytes (recommended)
  2. Track Blossom too (reporting only, no enforcement)
  3. Shared 400 MB quota across both
- **Selected:** Local only

## Claude's discretion (unselected/delegated items)

- Shared-service shape (extract vs parallel `migration_media` internals)
- BUD-11 expiration window and endpoint normalization details
- Upload route naming; spec §5 + registry parity is mandatory
- In-flight concurrency cap; asyncio.to_thread worker policy
- Content-addressed dedup behavior; "unreferenced" computation details

## Deferred ideas

- BUD-04 mirroring, kind-10063 publication, remote deletion, GIF,
  transforms (MEDIA-20…23); Blossom byte-tracking; auto-cancel cleanup.
