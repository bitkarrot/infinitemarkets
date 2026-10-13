---
phase: 05-correctness-recovery-and-security-hardening
plan: "03"
status: complete
recorded: 2026-10-13
requirements-completed: [HARD-02]
requirements-repaired: [PAY-01, PAY-02, GAM-02]
---

# 05-03 — F2 invoice-creation uncertainty recovery

Recovered invoice timeouts resolve only against strict snapshot correlation;
independent holds and exceptions are preserved; a `creation_unknown` order
becomes fulfillable after verified settlement. Source/runtime implemented and
independently reviewed; runtime regressions plus the `hard02` buyer browser
test (3 scenarios, strict pageerror assertions unchanged) are green.

**Residual disposition (WR-01):** the original browser RED for this path was
captured retrospectively against archived `bf99ec0` baseline code, not before
the fix — the test-first chronology evidence is absent and cannot be
fabricated. Recorded as a permanent honesty note in `05-REVIEW.md` and
`05-BROWSER-BASELINE-EVIDENCE.json`. The operator accepted this caveat in
writing on 2026-10-13; actual regression coverage and independent review
stand on their own.

Governing record: [05-VERIFICATION.md](05-VERIFICATION.md), progress file
`05-03-PROGRESS.json`, RED records `05-03-RED-*.json`.
