# Deferred items — Phase 6

- `infinitemarkets/templates/infinitemarkets/admin.html` (~lines 2519, 2542):
  field labels still read "Footer logo image URL (https or /images/…)" and
  "Custom share image URL (https or /images/…)" — the `/images/` hint is a
  dead prefix on the qualified host (mount is `/library`). Out of 06-04
  scope (plan's files_modified; UI copy is Phase 7 territory). Out-of-scope
  discovery per executor scope-boundary rule — fix with Phase 7 editor work.
