---
created: 2026-10-17T21:15:00.000Z
title: Frozen-binary email send-test smoke (Phase 11 release qualification)
area: release
files:
  - tools/package_release.py:116-120
  - infinitemarkets/_vendored.py
  - infinitemarkets/services/email.py
---

## Problem

Phase 9 moves every `email_queue` send onto the extension-owned
`_build_message`/`_smtp_send` path, which builds a stdlib
`email.message.EmailMessage` (default policy). Frozen single-binary (Nuitka)
LNbits builds ship an incomplete standard library. The release already
back-fills `html.parser`/`_markupbase` for that reason. Whether the frozen
host bundles `email.policy`, `email.headerregistry`, `email.contentmanager`,
`email._header_value_parser` and `email._encoded_words` is unverified
(Phase 9 RESEARCH assumption A1). If any of them is missing, every send on
that distribution raises `ModuleNotFoundError`, retries with bounded
backoff, and ends `failed`: email is dead there.

Owner decision 2026-10-17 (Phase 9 CONTEXT D-27): do not vendor
speculatively in Phase 9. Verify during Phase 11 release qualification,
before v1.2 ships.

## Solution

In Phase 11 release qualification, install the packaged extension on the
frozen single-binary LNbits build, configure host SMTP to a capture relay,
and run the Notifications "send test" button. Pass means the queue row
reaches `sent` and the captured message is `multipart/alternative` with
both parts. If it fails with a missing stdlib module, add the missing
`email/*.py` modules to `STDLIB_MODULES`/`STDLIB_FILES` in
`tools/package_release.py` (same mechanism as the `html.parser` back-fill),
re-package, and re-run the smoke. Record the verdict in the Phase 11
verification evidence.
