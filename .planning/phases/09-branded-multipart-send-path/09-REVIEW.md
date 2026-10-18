---
phase: 09-branded-multipart-send-path
reviewed: 2026-10-18T20:02:23Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - infinitemarkets/services/email.py
  - tests/runtime/conftest.py
  - tests/runtime/test_email_render.py
  - tests/runtime/test_email_queue.py
  - tests/runtime/test_email_signin.py
  - tests/runtime/test_financial_review.py
  - harness/email.py
  - tests/qualification/test_p0_10_smtp_boundary.py
findings:
  critical: 0
  warning: 2
  info: 0
  total: 2
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-10-18T20:02:23Z  
**Depth:** standard  
**Files Reviewed:** 8  
**Status:** issues_found

## Summary

Reviewed the eight scoped implementation and test files, tracing SMTP transport and cancellation, MIME assembly, consent checks, token-fragment handling, preview redaction, sample sends, and theme rendering through their callers. Two warnings remain: header text can fail contrast for an accepted accent, and the SMTP timeout does not bound the lifetime of the underlying worker thread or the complete SMTP exchange. The missing explicit table-header scopes and narrow-table concern are advisories rather than substantiated safety/accessibility defects and are not reported as findings.

## Warnings

### WR-01: Accent header text can be unreadable

**Severity:** WARNING  
**File:** `infinitemarkets/services/email.py:368-381, 511-515`  
**Issue:** The wordmark and optional header text inherit `#1f2328` from the outer message table, while the header band uses the merchant accent and accepts any full-match six-digit hex value. For the accepted `#000000` accent, this foreground/background pair has only about 1.3:1 contrast (below even the 3:1 large-text threshold). The separately computed `on_accent` is used for the CTA but not the header, so dark accents can make the merchant identity nearly illegible.  
**Fix:** Set a contrast-safe foreground on the accent header cell (for example, `color:{on_accent}`) so the wordmark, optional header text, and image fallback inherit it. Add a header-specific contrast assertion for `#000000` and the other accepted accent boundary values.

### WR-02: SMTP timeout can return while its thread continues sending

**Severity:** WARNING  
**File:** `infinitemarkets/services/email.py:468-478, 841-859, 871-889`  
**Issue:** `smtplib.SMTP(..., timeout=timeout)` applies a timeout to individual blocking socket operations, not a single deadline for the complete connect/TLS/auth/send exchange. When `asyncio.wait_for` expires, cancelling the `asyncio.to_thread` await does not stop the running thread. The worker treats the timeout as failure and can release the row for retry while the old SMTP thread is still progressing and can later reach `sendmail`, creating overlapping or duplicate deliveries after the first attempt was classified as timed out. This also means the claimed transport bound is not a bound on the underlying send operation.  
**Fix:** Enforce one absolute monotonic deadline across all SMTP protocol I/O, applying only the remaining budget to each blocking operation, and ensure timeout/cancellation closes or joins the worker's socket before the row is retried. Alternatively, use a genuinely cancellable asynchronous transport. Add a slow multi-stage transport test where individual operations finish within their socket timeout but their combined duration exceeds the overall budget; assert no post-timeout send or overlapping retry occurs.

---

_Reviewed: 2026-10-18T20:02:23Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_
