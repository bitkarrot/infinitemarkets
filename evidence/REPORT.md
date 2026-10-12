# Infinitemarkets Qualification Report

- Generated (UTC): 2026-10-12T22:51:47.475900+00:00
- Verify command: `make verify`
- Profile: Python 3.12.13 (CPython), arm64/darwin, database dialect: sqlite
- Pins: nostr-sdk 0.44.8, LNbits v1.6.2-rc1 at e336fe14b841, NIP-32 namespace `org.infinitemarkets.protocol`
- Tested binary: libnostr_sdk_ffi.dylib (sha256 49b779657adfc809..., 4970368 bytes)
- Result: 982/990 passed (0 failed, 0 errors, 8 skipped), exit status 0

Rerun policy: Single run only (D-10 clean-pass policy): the tooling performs one run per verify command and has no retry loop; a rerun does not flip a recorded outcome.

## FX Float-Boundary Measurement (P0-13)

- Measured maximum relative float error: `7.458852468819816e-17`
- Corresponding absolute sat error: `0`
- Worst-case sample: `rng-16=46257.74717567518`

## P0 Coverage Map (P0-01..P0-14)

| P0 | Status | Tests |
| --- | --- | --- |
| P0-01 | pass | 33 |
| P0-02 | pass | 10 |
| P0-03 | pass | 3 |
| P0-04 | pass | 3 |
| P0-05 | pass | 28 |
| P0-06 | pass | 19 |
| P0-07 | pass | 10 |
| P0-08 | pass | 15 |
| P0-09 | pass | 7 |
| P0-10 | pass | 9 |
| P0-11 | pass | 28 |
| P0-12 | pass | 23 |
| P0-13 | pass | 21 |
| P0-14 | pass | 12 |

### Coverage pointers

- **P0-01**: `tests/qualification/test_p0_01_pins.py::test_evidence_pins_block_matches_recorded_values`, `tests/qualification/test_p0_01_pins.py::test_harness_lock_wheel_parity_with_host_lock`, `tests/qualification/test_p0_01_pins.py::test_host_checkout_head_is_pinned_commit`, `tests/qualification/test_p0_01_pins.py::test_host_lock_and_pypi_are_wheels_only`, `tests/qualification/test_p0_01_pins.py::test_installed_nostr_sdk_is_exactly_pinned`, `tests/qualification/test_p0_01_pins.py::test_installed_wheel_matches_machine_platform`, `tests/qualification/test_p0_01_pins.py::test_native_library_hash_recorded_into_evidence_pins`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[0.44.8-nostr-sdk candidate pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[5dc79c5-Infinitemarkets market-spec pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[APPROVED-approval section (D-11)]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Linux ARM64-blocking platform (ARM64)]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Linux x86_64-blocking platform (x86_64)]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[PostgreSQL-blocking database]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Python 3.12 only-Python 3.12-only claim (D-02)]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[SQLite-blocking database]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[a2494f4f81d46684e5814a9bf35e2b1df978f955-Nostr NIPs pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[a600c2a7186559b371030fe5fc5585c37b3a0931-release-source revision]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[chacha20poly1305-native Cargo dependency pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[e336fe14b841d6f0c940e75b3d343e3ab5cf8433-LNbits commit pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[hashed artifacts-D-15 contingency criterion]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[macOS ARM64-advisory smoke profile]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[owner approval-D-15 contingency criterion]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[pinned native revision-D-15 contingency criterion]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[reproducible build-D-15 contingency criterion]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[rust-nostr/nostr-sdk-ffi-release-source repository]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[secp256k1-native Cargo dependency pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[uv.lock-lockfile identity]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[v1.6.2-rc1-LNbits tag]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[v2 payload only-NIP-44 v2-only pin]`, `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[wheels only-no-sdist provenance fact]`, `tests/qualification/test_p0_01_pins.py::test_release_source_and_native_cargo_provenance`, `tests/qualification/test_p0_01_pins.py::test_requires_python_is_3_12_only`, `tests/qualification/test_p0_01_pins.py::test_running_interpreter_is_3_12`
- **P0-02**: `tests/qualification/test_p0_02_sdk_security.py::test_auth_flood_bounded_with_signing_paused`, `tests/qualification/test_p0_02_sdk_security.py::test_build_sign_and_verify_event`, `tests/qualification/test_p0_02_sdk_security.py::test_d16_subcheck_attribution_recorded`, `tests/qualification/test_p0_02_sdk_security.py::test_ffi_import_and_keypair_generation`, `tests/qualification/test_p0_02_sdk_security.py::test_invalid_events_rejected_before_trusted_processing`, `tests/qualification/test_p0_02_sdk_security.py::test_known_id_repetition_admitted_exactly_once`, `tests/qualification/test_p0_02_sdk_security.py::test_nip44_encrypt_decrypt_roundtrip`, `tests/qualification/test_p0_02_sdk_security.py::test_oversized_nip44_input_rejected_with_bounded_cost`, `tests/qualification/test_p0_02_sdk_security.py::test_tampered_event_fails_verification`, `tests/qualification/test_p0_02_sdk_security.py::test_tested_binary_identity_recorded_into_evidence_pins`
- **P0-03**: `tests/qualification/test_p0_03_host_contract.py::test_invoice_listener_lifecycle_and_owned_handle_cancellation`, `tests/qualification/test_p0_03_host_contract.py::test_invoice_metadata_persisted_and_exactly_queryable`, `tests/qualification/test_p0_03_host_contract.py::test_no_durable_callback_delivery_across_restart`
- **P0-04**: `tests/qualification/test_p0_04_relay_ack.py::test_external_relay_smoke`, `tests/qualification/test_p0_04_relay_ack.py::test_positive_negative_and_timeout_acks_classified_per_relay`, `tests/qualification/test_p0_04_relay_ack.py::test_targeted_send_never_reaches_unlisted_relay`
- **P0-05**: `tests/qualification/test_p0_05_encrypted_fixtures.py::test_copies_route_only_to_their_partys_relays`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_duplicate_common_tag_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_recipient_copy_unwraps_to_golden_rumor`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_sender_copy_unwraps_to_golden_rumor`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_wraps_are_independent_copies`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_no_plaintext_or_key_material_in_logs`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_noncanonical_rumor_id_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_retry_wrap_preserves_rumor_id`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_rumor_seal_pubkey_mismatch_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seal_with_nonempty_tags_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[bit-flipped-signature]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[duplicate-p-tag]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[missing-p-tag]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[noncanonical-outer-id]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[oversized-content]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[truncated-content]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[wrong-outer-kind]`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_signed_rumor_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_outer_content_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_outer_signature_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_seal_content_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_seal_signature_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_valid_wrap_with_undecryptable_content_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_validate_kind16_tags_counts_on_raw_json`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrap_for_other_recipient_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_outer_kind_rejected`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_recipient_key_decrypt_fails`, `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_rumor_kind_rejected`
- **P0-06**: `tests/qualification/test_p0_06_transactions.py::test_adapter_only_transaction_rolls_back_cleanly`, `tests/qualification/test_p0_06_transactions.py::test_adapter_performs_in_transaction_writes_without_host_helpers`, `tests/qualification/test_p0_06_transactions.py::test_concurrent_duplicate_scoped_order_inserts_yield_one_row`, `tests/qualification/test_p0_06_transactions.py::test_dialect_selection_matches_environment`, `tests/qualification/test_p0_06_transactions.py::test_duplicate_scoped_order_insert_conflicts`, `tests/qualification/test_p0_06_transactions.py::test_guard_failure_mid_claim_rolls_back_everything`, `tests/qualification/test_p0_06_transactions.py::test_host_auto_commit_helper_splits_domain_transaction`, `tests/qualification/test_p0_06_transactions.py::test_idempotency_record_scope_conflict`, `tests/qualification/test_p0_06_transactions.py::test_last_unit_concurrency_yields_exactly_one_reservation`, `tests/qualification/test_p0_06_transactions.py::test_lost_cas_rolls_back_the_entire_transaction`, `tests/qualification/test_p0_06_transactions.py::test_order_state_machine_table_exhaustive`, `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[inventory_reservations-params0]`, `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[inventory_reservations-params1]`, `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[order_items-params2]`, `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[order_items-params3]`, `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[relay_publications-params4]`, `tests/qualification/test_p0_06_transactions.py::test_sorted_id_locking_avoids_deadlock`, `tests/qualification/test_p0_06_transactions.py::test_task_lease_fencing_rejects_stale_writes`, `tests/qualification/test_p0_06_transactions.py::test_winning_cas_leaves_one_held_reservation`
- **P0-07**: `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[rejected]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[success]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[unknown]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_awaiting_payment_then_late_settlement`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[rejected]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[success]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[unknown]`, `tests/qualification/test_p0_07_cancellation_saga.py::test_creation_unknown_reconciliation_attaches_exactly_one`, `tests/qualification/test_p0_07_cancellation_saga.py::test_multiple_core_payments_with_one_external_id_quarantines`, `tests/qualification/test_p0_07_cancellation_saga.py::test_zero_matches_after_window_fails_projection_only_for_invoice_pending`
- **P0-08**: `tests/qualification/test_p0_08_recovery_closure.py::test_claim_respects_dependencies_and_supersede`, `tests/qualification/test_p0_08_recovery_closure.py::test_lease_expired_mid_claim_requeues_and_reclaims`, `tests/qualification/test_p0_08_recovery_closure.py::test_merchant_sender_copy_recovered_without_dispatch`, `tests/qualification/test_p0_08_recovery_closure.py::test_order_msg_keeps_stable_rumor_id_across_retries`, `tests/qualification/test_p0_08_recovery_closure.py::test_pre_reservation_crash_resume_is_idempotent`, `tests/qualification/test_p0_08_recovery_closure.py::test_relay_cursors_advance_only_after_eose`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_admitted_not_validated`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_attach_before_enqueue`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_invoice_before_attach`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_reservation_before_invoice_call`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_between_settlement_and_callback`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_claimed_not_published`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_partially_published_retries_only_missing`, `tests/qualification/test_p0_08_recovery_closure.py::test_restart_validated_not_dispatched`, `tests/qualification/test_p0_08_recovery_closure.py::test_zero_positive_oks_backoff_then_failed`
- **P0-09**: `tests/qualification/test_p0_09_email_persistence.py::test_equality_hashes_are_purpose_separated_and_irreversible`, `tests/qualification/test_p0_09_email_persistence.py::test_malformed_and_noncanonical_tokens_rejected_before_lookup`, `tests/qualification/test_p0_09_email_persistence.py::test_no_plaintext_recipients_or_tokens_in_database`, `tests/qualification/test_p0_09_email_persistence.py::test_opt_out_revokes_consent_and_cancels_queued_customer_rows`, `tests/qualification/test_p0_09_email_persistence.py::test_token_rotation_and_revocation_invalidate_immediately`, `tests/qualification/test_p0_09_email_persistence.py::test_token_survives_idempotency_retention_then_expires`, `tests/qualification/test_p0_09_email_persistence.py::test_two_merchant_recipients_two_rows_delivered_independently`
- **P0-10**: `tests/qualification/test_p0_10_smtp_boundary.py::test_crash_after_smtp_acceptance_redelivers_on_resume`, `tests/qualification/test_p0_10_smtp_boundary.py::test_customer_rate_limit_waits_rather_than_delivering`, `tests/qualification/test_p0_10_smtp_boundary.py::test_exhausted_attempts_enter_failed_never_sent`, `tests/qualification/test_p0_10_smtp_boundary.py::test_logs_expose_neither_recipients_nor_bearer_links`, `tests/qualification/test_p0_10_smtp_boundary.py::test_merchant_alert_rate_limit_at_60_per_hour`, `tests/qualification/test_p0_10_smtp_boundary.py::test_only_true_enters_sent_false_retries_with_bound`, `tests/qualification/test_p0_10_smtp_boundary.py::test_raised_exception_and_recipient_rejection_surface_identically`, `tests/qualification/test_p0_10_smtp_boundary.py::test_suppressed_rows_never_touch_smtp`, `tests/qualification/test_p0_10_smtp_boundary.py::test_true_enters_sent_with_sent_at`
- **P0-11**: `tests/qualification/test_p0_11_nip89_route.py::test_foreign_merchant_naddr_rejected`, `tests/qualification/test_p0_11_nip89_route.py::test_golden_naddr_resolves_locally`, `tests/qualification/test_p0_11_nip89_route.py::test_golden_nip89_pair_validates`, `tests/qualification/test_p0_11_nip89_route.py::test_hidden_and_preorder_map_to_quantity_zero`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[bad-alphabet]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[too-long]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[too-short]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[uppercase]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_missing_shipping_id.json-product-shipping-missing-id]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_quantity_float.json-product-quantity-not-int-or-null]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_quantity_string.json-product-quantity-not-int-or-null]`, `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_specs_object.json-product-specs-not-pair-array]`, `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[corrupt-bech32]`, `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[empty]`, `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[npub-not-naddr]`, `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[plain-text]`, `tests/qualification/test_p0_11_nip89_route.py::test_mismatched_currencies_rejected`, `tests/qualification/test_p0_11_nip89_route.py::test_opaque_address_physical_order_shape`, `tests/qualification/test_p0_11_nip89_route.py::test_relay_hint_never_fetched`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[a-tag-not-web]`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-d-equalized]`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-k-tag-wrong]`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-wrong-kind]`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[rec-d-equalized-to-app-id]`, `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[rec-foreign-author]`, `tests/qualification/test_p0_11_nip89_route.py::test_unmapped_product_naddr_rejected`, `tests/qualification/test_p0_11_nip89_route.py::test_valid_stall_and_product_dtos`, `tests/qualification/test_p0_11_nip89_route.py::test_wrong_kind_naddr_rejected`
- **P0-12**: `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_approved_cookie_same_origin_path_passes`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_audit_rows_redact_secrets_and_pii`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_cookie_only_without_origin_rejected`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_cross_origin_cookie_mutation_rejected`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_id_only_login_method_refused`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_mutation_requires_authenticated_session`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_audit_capture_redacts_token`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_requires_x_order_token_header`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_token_in_path_not_routed`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_token_in_query_rejected`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_wrong_token_rejected`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[-1-False-unsupported-dialect:unknown]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[cockroachdb-1-False-unsupported-dialect:cockroachdb]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[postgresql-1-True-supported]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[postgresql-4-True-supported]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-1-True-supported]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-2-False-sqlite-multi-process-refused]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-8-False-sqlite-multi-process-refused]`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_request_header_logging_redacts_order_token`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_sdk_client_cleanup_on_direct_task_cancel`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_startup_registers_only_bounded_tasks`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_stop_hook_cancels_only_owned_handles`, `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_wrong_origin_subdomain_rejected`
- **P0-13**: `tests/qualification/test_p0_13_decimal_fx.py::test_all_providers_failed_rejects_no_provenance`, `tests/qualification/test_p0_13_decimal_fx.py::test_ceiling_applies_per_component_not_on_summed_total`, `tests/qualification/test_p0_13_decimal_fx.py::test_checked_total_sum_and_minimum_one_sat`, `tests/qualification/test_p0_13_decimal_fx.py::test_empty_quote_rejected`, `tests/qualification/test_p0_13_decimal_fx.py::test_failed_nonfinite_nonpositive_providers_filtered`, `tests/qualification/test_p0_13_decimal_fx.py::test_float_boundary_measurement_is_deterministic_and_recorded`, `tests/qualification/test_p0_13_decimal_fx.py::test_fractional_minor_unit_conversion_ceils`, `tests/qualification/test_p0_13_decimal_fx.py::test_invalid_quote_inputs_rejected`, `tests/qualification/test_p0_13_decimal_fx.py::test_mixed_currency_cart_converts_each_line_with_own_quote`, `tests/qualification/test_p0_13_decimal_fx.py::test_mixed_currency_shipping_components`, `tests/qualification/test_p0_13_decimal_fx.py::test_model_never_calls_host_cached_fiat_helper`, `tests/qualification/test_p0_13_decimal_fx.py::test_nonfinite_rate_rejected`, `tests/qualification/test_p0_13_decimal_fx.py::test_order_fx_quotes_persists_decimal_strings`, `tests/qualification/test_p0_13_decimal_fx.py::test_order_fx_quotes_unique_per_currency`, `tests/qualification/test_p0_13_decimal_fx.py::test_provenance_free_quote_rejected`, `tests/qualification/test_p0_13_decimal_fx.py::test_provider_floats_cross_once_via_decimal_str`, `tests/qualification/test_p0_13_decimal_fx.py::test_quote_ttl_is_five_minutes`, `tests/qualification/test_p0_13_decimal_fx.py::test_rejection_leaves_no_reservation_or_stock_or_quote_rows`, `tests/qualification/test_p0_13_decimal_fx.py::test_stale_quote_rejected_at_conversion_edge`, `tests/qualification/test_p0_13_decimal_fx.py::test_valid_quote_then_reservation_flow`, `tests/qualification/test_p0_13_decimal_fx.py::test_zero_and_negative_rate_rejected`
- **P0-14**: `tests/qualification/test_p0_14_contract_closure.py::test_fixture_coverage_for_required_kinds`, `tests/qualification/test_p0_14_contract_closure.py::test_identifier_closure`, `tests/qualification/test_p0_14_contract_closure.py::test_p0_evidence_closure`, `tests/qualification/test_p0_14_contract_closure.py::test_registered_literals_appear_in_spec`, `tests/qualification/test_p0_14_contract_closure.py::test_release_gates_scope_event_kinds`, `tests/qualification/test_p0_14_contract_closure.py::test_routes_match_spec_bidirectional`, `tests/qualification/test_p0_14_contract_closure.py::test_schema_fields_match_registry_bidirectional`, `tests/qualification/test_p0_14_contract_closure.py::test_section4_table_classification_complete`, `tests/qualification/test_p0_14_contract_closure.py::test_state_machines_match_spec_bidirectional`, `tests/qualification/test_p0_14_contract_closure.py::test_state_tables_match_registry`, `tests/qualification/test_p0_14_contract_closure.py::test_topology_refusal_registered`, `tests/qualification/test_p0_14_contract_closure.py::test_transitions_classified_exhaustively`

## Results

| Test | P0 | Markers | Outcome | Duration (s) |
| --- | --- | --- | --- | --- |
| `tests/qualification/test_p0_01_pins.py::test_evidence_pins_block_matches_recorded_values` | P0-01 | fast | passed | 0.136 |
| `tests/qualification/test_p0_01_pins.py::test_harness_lock_wheel_parity_with_host_lock` | P0-01 | fast | passed | 0.049 |
| `tests/qualification/test_p0_01_pins.py::test_host_checkout_head_is_pinned_commit` | P0-01 | fast | passed | 0.020 |
| `tests/qualification/test_p0_01_pins.py::test_host_lock_and_pypi_are_wheels_only` | P0-01 | fast | passed | 0.034 |
| `tests/qualification/test_p0_01_pins.py::test_installed_nostr_sdk_is_exactly_pinned` | P0-01 | fast | passed | 0.001 |
| `tests/qualification/test_p0_01_pins.py::test_installed_wheel_matches_machine_platform` | P0-01 | fast | passed | 0.001 |
| `tests/qualification/test_p0_01_pins.py::test_native_library_hash_recorded_into_evidence_pins` | P0-01 | fast | passed | 0.022 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[0.44.8-nostr-sdk candidate pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[5dc79c5-Infinitemarkets market-spec pin]` | P0-01 | fast, parametrize | passed | 0.001 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[APPROVED-approval section (D-11)]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Linux ARM64-blocking platform (ARM64)]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Linux x86_64-blocking platform (x86_64)]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[PostgreSQL-blocking database]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[Python 3.12 only-Python 3.12-only claim (D-02)]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[SQLite-blocking database]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[a2494f4f81d46684e5814a9bf35e2b1df978f955-Nostr NIPs pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[a600c2a7186559b371030fe5fc5585c37b3a0931-release-source revision]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[chacha20poly1305-native Cargo dependency pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[e336fe14b841d6f0c940e75b3d343e3ab5cf8433-LNbits commit pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[hashed artifacts-D-15 contingency criterion]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[macOS ARM64-advisory smoke profile]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[owner approval-D-15 contingency criterion]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[pinned native revision-D-15 contingency criterion]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[reproducible build-D-15 contingency criterion]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[rust-nostr/nostr-sdk-ffi-release-source repository]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[secp256k1-native Cargo dependency pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[uv.lock-lockfile identity]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[v1.6.2-rc1-LNbits tag]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[v2 payload only-NIP-44 v2-only pin]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_pins_md_records_the_pinned_identities[wheels only-no-sdist provenance fact]` | P0-01 | fast, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_release_source_and_native_cargo_provenance` | P0-01 | fast | passed | 0.052 |
| `tests/qualification/test_p0_01_pins.py::test_requires_python_is_3_12_only` | P0-01 | fast | passed | 0.000 |
| `tests/qualification/test_p0_01_pins.py::test_running_interpreter_is_3_12` | P0-01 | fast | passed | 0.000 |
| `tests/qualification/test_p0_02_sdk_security.py::test_auth_flood_bounded_with_signing_paused` | P0-02 | asyncio, sdk | passed | 1.174 |
| `tests/qualification/test_p0_02_sdk_security.py::test_build_sign_and_verify_event` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_d16_subcheck_attribution_recorded` | P0-02 | asyncio, sdk | passed | 0.002 |
| `tests/qualification/test_p0_02_sdk_security.py::test_ffi_import_and_keypair_generation` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_invalid_events_rejected_before_trusted_processing` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_known_id_repetition_admitted_exactly_once` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_nip44_encrypt_decrypt_roundtrip` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_oversized_nip44_input_rejected_with_bounded_cost` | P0-02 | asyncio, sdk | passed | 2.765 |
| `tests/qualification/test_p0_02_sdk_security.py::test_tampered_event_fails_verification` | P0-02 | asyncio, sdk | passed | 0.001 |
| `tests/qualification/test_p0_02_sdk_security.py::test_tested_binary_identity_recorded_into_evidence_pins` | P0-02 | asyncio, sdk | passed | 0.039 |
| `tests/qualification/test_p0_03_host_contract.py::test_invoice_listener_lifecycle_and_owned_handle_cancellation` | P0-03 | asyncio, host | passed | 2.414 |
| `tests/qualification/test_p0_03_host_contract.py::test_invoice_metadata_persisted_and_exactly_queryable` | P0-03 | asyncio, host | passed | 1.972 |
| `tests/qualification/test_p0_03_host_contract.py::test_no_durable_callback_delivery_across_restart` | P0-03 | asyncio, host | passed | 5.188 |
| `tests/qualification/test_p0_04_relay_ack.py::test_external_relay_smoke` | P0-04 | asyncio, protocol, skipif | skipped | 0.000 |
| `tests/qualification/test_p0_04_relay_ack.py::test_positive_negative_and_timeout_acks_classified_per_relay` | P0-04 | asyncio, protocol | passed | 10.022 |
| `tests/qualification/test_p0_04_relay_ack.py::test_targeted_send_never_reaches_unlisted_relay` | P0-04 | asyncio, protocol | passed | 0.008 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_copies_route_only_to_their_partys_relays` | P0-05 | asyncio, protocol | passed | 0.003 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_duplicate_common_tag_rejected` | P0-05 | asyncio, protocol | passed | 0.003 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_recipient_copy_unwraps_to_golden_rumor` | P0-05 | asyncio, protocol | passed | 0.005 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_sender_copy_unwraps_to_golden_rumor` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_golden_wraps_are_independent_copies` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_no_plaintext_or_key_material_in_logs` | P0-05 | asyncio, protocol | passed | 0.006 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_noncanonical_rumor_id_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_retry_wrap_preserves_rumor_id` | P0-05 | asyncio, protocol | passed | 0.003 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_rumor_seal_pubkey_mismatch_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seal_with_nonempty_tags_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[bit-flipped-signature]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[duplicate-p-tag]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[missing-p-tag]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[noncanonical-outer-id]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[oversized-content]` | P0-05 | asyncio, parametrize, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[truncated-content]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_seeded_generated_mutations_rejected[wrong-outer-kind]` | P0-05 | asyncio, parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_signed_rumor_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_outer_content_rejected` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_outer_signature_rejected` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_seal_content_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_tampered_seal_signature_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_valid_wrap_with_undecryptable_content_rejected` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_validate_kind16_tags_counts_on_raw_json` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrap_for_other_recipient_rejected` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_outer_kind_rejected` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_recipient_key_decrypt_fails` | P0-05 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_05_encrypted_fixtures.py::test_wrong_rumor_kind_rejected` | P0-05 | asyncio, protocol | passed | 0.002 |
| `tests/qualification/test_p0_06_transactions.py::test_adapter_only_transaction_rolls_back_cleanly` | P0-06 | asyncio, db | passed | 0.014 |
| `tests/qualification/test_p0_06_transactions.py::test_adapter_performs_in_transaction_writes_without_host_helpers` | P0-06 | asyncio, db | passed | 0.016 |
| `tests/qualification/test_p0_06_transactions.py::test_concurrent_duplicate_scoped_order_inserts_yield_one_row` | P0-06 | asyncio, db | passed | 0.022 |
| `tests/qualification/test_p0_06_transactions.py::test_dialect_selection_matches_environment` | P0-06 | db | passed | 0.000 |
| `tests/qualification/test_p0_06_transactions.py::test_duplicate_scoped_order_insert_conflicts` | P0-06 | asyncio, db | passed | 0.022 |
| `tests/qualification/test_p0_06_transactions.py::test_guard_failure_mid_claim_rolls_back_everything` | P0-06 | asyncio, db | passed | 0.021 |
| `tests/qualification/test_p0_06_transactions.py::test_host_auto_commit_helper_splits_domain_transaction` | P0-06 | asyncio, db | passed | 0.018 |
| `tests/qualification/test_p0_06_transactions.py::test_idempotency_record_scope_conflict` | P0-06 | asyncio, db | passed | 0.018 |
| `tests/qualification/test_p0_06_transactions.py::test_last_unit_concurrency_yields_exactly_one_reservation` | P0-06 | asyncio, db | passed | 0.035 |
| `tests/qualification/test_p0_06_transactions.py::test_lost_cas_rolls_back_the_entire_transaction` | P0-06 | asyncio, db | passed | 0.016 |
| `tests/qualification/test_p0_06_transactions.py::test_order_state_machine_table_exhaustive` | P0-06 | asyncio, db | passed | 0.390 |
| `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[inventory_reservations-params0]` | P0-06 | asyncio, db, parametrize | passed | 0.019 |
| `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[inventory_reservations-params1]` | P0-06 | asyncio, db, parametrize | passed | 0.018 |
| `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[order_items-params2]` | P0-06 | asyncio, db, parametrize | passed | 0.023 |
| `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[order_items-params3]` | P0-06 | asyncio, db, parametrize | passed | 0.025 |
| `tests/qualification/test_p0_06_transactions.py::test_orphan_inserts_violate_foreign_keys[relay_publications-params4]` | P0-06 | asyncio, db, parametrize | passed | 0.019 |
| `tests/qualification/test_p0_06_transactions.py::test_sorted_id_locking_avoids_deadlock` | P0-06 | asyncio, db | passed | 0.373 |
| `tests/qualification/test_p0_06_transactions.py::test_task_lease_fencing_rejects_stale_writes` | P0-06 | asyncio, db | passed | 0.020 |
| `tests/qualification/test_p0_06_transactions.py::test_winning_cas_leaves_one_held_reservation` | P0-06 | asyncio, db | passed | 0.048 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[rejected]` | P0-07 | asyncio, db, parametrize | passed | 0.026 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[success]` | P0-07 | asyncio, db, parametrize | passed | 0.026 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_during_inflight_invoice_creation[unknown]` | P0-07 | asyncio, db, parametrize | passed | 0.028 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_awaiting_payment_then_late_settlement` | P0-07 | asyncio, db | passed | 0.044 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[rejected]` | P0-07 | asyncio, db, parametrize | passed | 0.021 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[success]` | P0-07 | asyncio, db, parametrize | passed | 0.025 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_cancel_from_received_never_creates_an_invoice[unknown]` | P0-07 | asyncio, db, parametrize | passed | 0.022 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_creation_unknown_reconciliation_attaches_exactly_one` | P0-07 | asyncio, db | passed | 0.029 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_multiple_core_payments_with_one_external_id_quarantines` | P0-07 | asyncio, db | passed | 0.025 |
| `tests/qualification/test_p0_07_cancellation_saga.py::test_zero_matches_after_window_fails_projection_only_for_invoice_pending` | P0-07 | asyncio, db | passed | 0.039 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_claim_respects_dependencies_and_supersede` | P0-08 | asyncio, db | passed | 0.046 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_lease_expired_mid_claim_requeues_and_reclaims` | P0-08 | asyncio, db | passed | 0.019 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_merchant_sender_copy_recovered_without_dispatch` | P0-08 | asyncio, db | passed | 0.052 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_order_msg_keeps_stable_rumor_id_across_retries` | P0-08 | asyncio, db | passed | 0.069 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_pre_reservation_crash_resume_is_idempotent` | P0-08 | asyncio, db | passed | 0.037 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_relay_cursors_advance_only_after_eose` | P0-08 | asyncio, db | passed | 0.026 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_admitted_not_validated` | P0-08 | asyncio, db | passed | 0.026 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_attach_before_enqueue` | P0-08 | asyncio, db | passed | 0.029 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_invoice_before_attach` | P0-08 | asyncio, db | passed | 0.029 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_after_reservation_before_invoice_call` | P0-08 | asyncio, db | passed | 0.030 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_between_settlement_and_callback` | P0-08 | asyncio, db | passed | 0.036 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_claimed_not_published` | P0-08 | asyncio, db | passed | 0.032 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_partially_published_retries_only_missing` | P0-08 | asyncio, db | passed | 0.030 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_restart_validated_not_dispatched` | P0-08 | asyncio, db | passed | 0.040 |
| `tests/qualification/test_p0_08_recovery_closure.py::test_zero_positive_oks_backoff_then_failed` | P0-08 | asyncio, db | passed | 0.042 |
| `tests/qualification/test_p0_09_email_persistence.py::test_equality_hashes_are_purpose_separated_and_irreversible` | P0-09 | asyncio, db | passed | 0.015 |
| `tests/qualification/test_p0_09_email_persistence.py::test_malformed_and_noncanonical_tokens_rejected_before_lookup` | P0-09 | asyncio, db | passed | 0.013 |
| `tests/qualification/test_p0_09_email_persistence.py::test_no_plaintext_recipients_or_tokens_in_database` | P0-09 | asyncio, db | passed | 0.027 |
| `tests/qualification/test_p0_09_email_persistence.py::test_opt_out_revokes_consent_and_cancels_queued_customer_rows` | P0-09 | asyncio, db | passed | 0.033 |
| `tests/qualification/test_p0_09_email_persistence.py::test_token_rotation_and_revocation_invalidate_immediately` | P0-09 | asyncio, db | passed | 0.025 |
| `tests/qualification/test_p0_09_email_persistence.py::test_token_survives_idempotency_retention_then_expires` | P0-09 | asyncio, db | passed | 0.028 |
| `tests/qualification/test_p0_09_email_persistence.py::test_two_merchant_recipients_two_rows_delivered_independently` | P0-09 | asyncio, db | passed | 0.039 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_crash_after_smtp_acceptance_redelivers_on_resume` | P0-10 | asyncio, db | passed | 0.025 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_customer_rate_limit_waits_rather_than_delivering` | P0-10 | asyncio, db | passed | 0.093 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_exhausted_attempts_enter_failed_never_sent` | P0-10 | asyncio, db | passed | 0.028 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_logs_expose_neither_recipients_nor_bearer_links` | P0-10 | asyncio, db | passed | 0.028 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_merchant_alert_rate_limit_at_60_per_hour` | P0-10 | asyncio, db | passed | 0.191 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_only_true_enters_sent_false_retries_with_bound` | P0-10 | asyncio, db | passed | 0.024 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_raised_exception_and_recipient_rejection_surface_identically` | P0-10 | asyncio, db | passed | 0.022 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_suppressed_rows_never_touch_smtp` | P0-10 | asyncio, db | passed | 0.079 |
| `tests/qualification/test_p0_10_smtp_boundary.py::test_true_enters_sent_with_sent_at` | P0-10 | asyncio, db | passed | 0.021 |
| `tests/qualification/test_p0_11_nip89_route.py::test_foreign_merchant_naddr_rejected` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_golden_naddr_resolves_locally` | P0-11 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_11_nip89_route.py::test_golden_nip89_pair_validates` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_hidden_and_preorder_map_to_quantity_zero` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[bad-alphabet]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[too-long]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[too-short]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_d_naddr_rejected[uppercase]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_missing_shipping_id.json-product-shipping-missing-id]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_quantity_float.json-product-quantity-not-int-or-null]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_quantity_string.json-product-quantity-not-int-or-null]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_invalid_product_variants_rejected[invalid_specs_object.json-product-specs-not-pair-array]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[corrupt-bech32]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[empty]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[npub-not-naddr]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_malformed_naddr_rejected[plain-text]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_mismatched_currencies_rejected` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_opaque_address_physical_order_shape` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_relay_hint_never_fetched` | P0-11 | asyncio, protocol | passed | 0.001 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[a-tag-not-web]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-d-equalized]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-k-tag-wrong]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[handler-wrong-kind]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[rec-d-equalized-to-app-id]` | P0-11 | parametrize, protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_tampered_nip89_pair_rejected[rec-foreign-author]` | P0-11 | parametrize, protocol | passed | 0.001 |
| `tests/qualification/test_p0_11_nip89_route.py::test_unmapped_product_naddr_rejected` | P0-11 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_11_nip89_route.py::test_valid_stall_and_product_dtos` | P0-11 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_11_nip89_route.py::test_wrong_kind_naddr_rejected` | P0-11 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_approved_cookie_same_origin_path_passes` | P0-12 | asyncio, host | passed | 0.228 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_audit_rows_redact_secrets_and_pii` | P0-12 | asyncio, host | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_cookie_only_without_origin_rejected` | P0-12 | asyncio, host | passed | 0.240 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_cross_origin_cookie_mutation_rejected` | P0-12 | asyncio, host | passed | 0.229 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_id_only_login_method_refused` | P0-12 | asyncio, host | passed | 0.650 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_mutation_requires_authenticated_session` | P0-12 | asyncio, host | passed | 0.002 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_audit_capture_redacts_token` | P0-12 | asyncio, host | passed | 0.001 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_requires_x_order_token_header` | P0-12 | asyncio, host | passed | 0.002 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_token_in_path_not_routed` | P0-12 | asyncio, host | passed | 0.002 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_token_in_query_rejected` | P0-12 | asyncio, host | passed | 0.002 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_order_status_wrong_token_rejected` | P0-12 | asyncio, host | passed | 0.001 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[-1-False-unsupported-dialect:unknown]` | P0-12 | asyncio, host, parametrize | passed | 0.102 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[cockroachdb-1-False-unsupported-dialect:cockroachdb]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[postgresql-1-True-supported]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[postgresql-4-True-supported]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-1-True-supported]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-2-False-sqlite-multi-process-refused]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_production_topology_refusal[sqlite-8-False-sqlite-multi-process-refused]` | P0-12 | asyncio, host, parametrize | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_request_header_logging_redacts_order_token` | P0-12 | asyncio, host | passed | 0.000 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_sdk_client_cleanup_on_direct_task_cancel` | P0-12 | asyncio, host | passed | 0.155 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_startup_registers_only_bounded_tasks` | P0-12 | asyncio, host | passed | 0.051 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_stop_hook_cancels_only_owned_handles` | P0-12 | asyncio, host | passed | 0.102 |
| `tests/qualification/test_p0_12_auth_privacy_lifecycle.py::test_wrong_origin_subdomain_rejected` | P0-12 | asyncio, host | passed | 0.236 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_all_providers_failed_rejects_no_provenance` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_ceiling_applies_per_component_not_on_summed_total` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_checked_total_sum_and_minimum_one_sat` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_empty_quote_rejected` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_failed_nonfinite_nonpositive_providers_filtered` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_float_boundary_measurement_is_deterministic_and_recorded` | P0-13 | db | passed | 0.001 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_fractional_minor_unit_conversion_ceils` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_invalid_quote_inputs_rejected` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_mixed_currency_cart_converts_each_line_with_own_quote` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_mixed_currency_shipping_components` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_model_never_calls_host_cached_fiat_helper` | P0-13 | db | passed | 0.002 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_nonfinite_rate_rejected` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_order_fx_quotes_persists_decimal_strings` | P0-13 | asyncio, db | passed | 0.015 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_order_fx_quotes_unique_per_currency` | P0-13 | asyncio, db | passed | 0.025 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_provenance_free_quote_rejected` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_provider_floats_cross_once_via_decimal_str` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_quote_ttl_is_five_minutes` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_rejection_leaves_no_reservation_or_stock_or_quote_rows` | P0-13 | asyncio, db | passed | 0.022 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_stale_quote_rejected_at_conversion_edge` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_valid_quote_then_reservation_flow` | P0-13 | asyncio, db | passed | 0.016 |
| `tests/qualification/test_p0_13_decimal_fx.py::test_zero_and_negative_rate_rejected` | P0-13 | db | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_fixture_coverage_for_required_kinds` | P0-14 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_14_contract_closure.py::test_identifier_closure` | P0-14 | protocol | passed | 0.016 |
| `tests/qualification/test_p0_14_contract_closure.py::test_p0_evidence_closure` | P0-14 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_14_contract_closure.py::test_registered_literals_appear_in_spec` | P0-14 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_release_gates_scope_event_kinds` | P0-14 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_routes_match_spec_bidirectional` | P0-14 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_schema_fields_match_registry_bidirectional` | P0-14 | protocol | passed | 0.005 |
| `tests/qualification/test_p0_14_contract_closure.py::test_section4_table_classification_complete` | P0-14 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_14_contract_closure.py::test_state_machines_match_spec_bidirectional` | P0-14 | protocol | passed | 0.001 |
| `tests/qualification/test_p0_14_contract_closure.py::test_state_tables_match_registry` | P0-14 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_topology_refusal_registered` | P0-14 | protocol | passed | 0.000 |
| `tests/qualification/test_p0_14_contract_closure.py::test_transitions_classified_exhaustively` | P0-14 | protocol | passed | 0.000 |
| `tests/runtime/test_admin_ui.py::test_admin_js_legal_actions` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_admin_ui.py::test_admin_no_secrets` | - | asyncio, runtime | passed | 0.125 |
| `tests/runtime/test_admin_ui.py::test_admin_notifications_copy` | - | asyncio, runtime | passed | 0.130 |
| `tests/runtime/test_admin_ui.py::test_admin_publications_copy` | - | asyncio, runtime | passed | 0.122 |
| `tests/runtime/test_admin_ui.py::test_admin_shell_document` | - | asyncio, runtime | passed | 2.205 |
| `tests/runtime/test_admin_ui.py::test_admin_theme_editor` | - | asyncio, runtime | passed | 0.004 |
| `tests/runtime/test_admin_ui.py::test_admin_verbatim_copy` | - | asyncio, runtime | passed | 0.121 |
| `tests/runtime/test_admin_ui.py::test_admin_workspace_layout` | - | asyncio, runtime | passed | 0.128 |
| `tests/runtime/test_admin_ui.py::test_messages_health_and_relay_auth` | - | asyncio, runtime | passed | 0.136 |
| `tests/runtime/test_admin_ui.py::test_messages_workspace` | - | asyncio, runtime | passed | 0.345 |
| `tests/runtime/test_admin_ui.py::test_migration_admin_surface` | - | asyncio, runtime | passed | 0.126 |
| `tests/runtime/test_admin_ui.py::test_product_actions_precede_title` | - | asyncio, runtime | passed | 0.121 |
| `tests/runtime/test_admin_ui.py::test_product_editor_shipping_options` | - | asyncio, runtime | passed | 0.122 |
| `tests/runtime/test_admin_ui.py::test_product_table_columns_sortable` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_admin_ui.py::test_settings_key_reveal` | - | asyncio, runtime | passed | 0.133 |
| `tests/runtime/test_buyer_accounts.py::test_checkout_attribution_verified_email` | - | asyncio, runtime | passed | 0.307 |
| `tests/runtime/test_buyer_accounts.py::test_claim_binds_email_and_keeps_no_oracle` | - | asyncio, runtime | passed | 0.168 |
| `tests/runtime/test_buyer_accounts.py::test_email_only_session_profile_and_orders` | - | asyncio, runtime | passed | 0.114 |
| `tests/runtime/test_buyer_accounts.py::test_legacy_session_still_resolves` | - | asyncio, runtime | passed | 0.018 |
| `tests/runtime/test_buyer_accounts.py::test_m008_backfill_restores_nulled_hash` | - | asyncio, runtime | passed | 0.089 |
| `tests/runtime/test_buyer_accounts.py::test_m008_rebuild_preserves_and_backfills` | - | asyncio, runtime | passed | 0.090 |
| `tests/runtime/test_buyer_accounts.py::test_m008_schema_shape` | - | asyncio, runtime | passed | 1.686 |
| `tests/runtime/test_buyer_accounts.py::test_session_fails_closed_on_retired_account` | - | asyncio, runtime | passed | 0.009 |
| `tests/runtime/test_buyer_accounts.py::test_signin_creates_and_reuses_account` | - | asyncio, runtime | passed | 0.053 |
| `tests/runtime/test_buyer_accounts.py::test_union_history_dual_identity` | - | asyncio, runtime | passed | 0.253 |
| `tests/runtime/test_buyer_ui.py::test_digital_product_hides_address_fields` | - | asyncio, runtime | passed | 0.045 |
| `tests/runtime/test_buyer_ui.py::test_gallery_listing_cards_and_editorial_baseline` | - | asyncio, runtime | passed | 0.483 |
| `tests/runtime/test_buyer_ui.py::test_order_page_shell` | - | asyncio, runtime | passed | 0.011 |
| `tests/runtime/test_buyer_ui.py::test_product_page_checkout_card` | - | asyncio, runtime | passed | 1.854 |
| `tests/runtime/test_buyer_ui.py::test_public_js_contracts` | - | asyncio, runtime | passed | 0.008 |
| `tests/runtime/test_buyer_ui.py::test_theme_emission_scoped` | - | asyncio, runtime | passed | 0.211 |
| `tests/runtime/test_catalog_api.py::test_bulk_product_updates_are_atomic_and_publication_safe` | - | asyncio, runtime | passed | 0.524 |
| `tests/runtime/test_catalog_api.py::test_categories_have_no_legacy_api_alias` | - | asyncio, runtime | passed | 0.012 |
| `tests/runtime/test_catalog_api.py::test_category_crud` | - | asyncio, runtime | passed | 1.587 |
| `tests/runtime/test_catalog_api.py::test_category_delete_guards` | - | asyncio, runtime | passed | 0.122 |
| `tests/runtime/test_catalog_api.py::test_collection_zero_members_no_intent` | - | asyncio, runtime | passed | 0.021 |
| `tests/runtime/test_catalog_api.py::test_delete_reference_report_and_strip` | - | asyncio, runtime | passed | 0.030 |
| `tests/runtime/test_catalog_api.py::test_draft_produces_no_intent` | - | asyncio, runtime | passed | 0.029 |
| `tests/runtime/test_catalog_api.py::test_dry_run_deterministic` | - | asyncio, runtime | passed | 0.041 |
| `tests/runtime/test_catalog_api.py::test_membership_enqueues_collection_and_product_dep` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_catalog_api.py::test_owner_scoping` | - | asyncio, runtime | passed | 0.608 |
| `tests/runtime/test_catalog_api.py::test_product_crud_and_outbox_intent` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_catalog_api.py::test_product_delete_enqueues_tombstone` | - | asyncio, runtime | passed | 0.025 |
| `tests/runtime/test_catalog_api.py::test_product_image_incremental_limit` | - | asyncio, runtime | passed | 0.643 |
| `tests/runtime/test_catalog_api.py::test_product_validation_bounds` | - | asyncio, runtime | passed | 0.412 |
| `tests/runtime/test_catalog_api.py::test_published_at_preserved_across_edits` | - | asyncio, runtime | passed | 0.051 |
| `tests/runtime/test_catalog_api.py::test_shipping_validation` | - | asyncio, runtime | passed | 0.063 |
| `tests/runtime/test_catalog_api.py::test_variation_rules` | - | asyncio, runtime | passed | 0.115 |
| `tests/runtime/test_catalog_events.py::test_collection_event` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_hard04_edge_binds_intended_revision_row` | - | asyncio, runtime | passed | 0.007 |
| `tests/runtime/test_catalog_events.py::test_identity_and_handler_events_have_no_labels` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_nip15_currency_mismatch_is_error` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_nip15_hidden_and_digital` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_nip15_projection` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_nip15_variation_id_composition_and_fallback` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_outbox_dependency_edges` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_catalog_events.py::test_outbox_enqueue_and_supersession` | - | asyncio, runtime | passed | 0.207 |
| `tests/runtime/test_catalog_events.py::test_product_event_deterministic` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_catalog_events.py::test_product_event_recurring_and_sold` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_product_event_required_tags` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_product_event_unlimited_stock_omits_stock_tag` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_product_event_variation_single_parent_a` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_shipping_event` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_events.py::test_tombstone_descriptor` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_catalog_variants.py::test_hard03_accept_lockset_finishes_once[same_order]` | - | asyncio, parametrize, runtime | passed | 0.176 |
| `tests/runtime/test_catalog_variants.py::test_hard03_accept_lockset_finishes_once[shared_parent]` | - | asyncio, parametrize, runtime | passed | 0.375 |
| `tests/runtime/test_catalog_variants.py::test_hard03_variation_competing_capacity[accept]` | - | asyncio, parametrize, runtime | passed | 2.276 |
| `tests/runtime/test_catalog_variants.py::test_hard03_variation_competing_capacity[checkout]` | - | asyncio, parametrize, runtime | passed | 0.273 |
| `tests/runtime/test_checkout.py::test_boolean_quantity_is_rejected[False]` | - | asyncio, parametrize, runtime | passed | 0.012 |
| `tests/runtime/test_checkout.py::test_boolean_quantity_is_rejected[True]` | - | asyncio, parametrize, runtime | passed | 0.011 |
| `tests/runtime/test_checkout.py::test_changed_quote_creates_no_order_or_invoice` | - | asyncio, runtime | passed | 0.142 |
| `tests/runtime/test_checkout.py::test_checkout_caps_are_transactional[held]` | - | asyncio, parametrize, runtime | passed | 0.145 |
| `tests/runtime/test_checkout.py::test_checkout_caps_are_transactional[open]` | - | asyncio, parametrize, runtime | passed | 0.130 |
| `tests/runtime/test_checkout.py::test_checkout_crash_keeps_idempotency_link[after_invoice]` | - | asyncio, parametrize, runtime | passed | 0.050 |
| `tests/runtime/test_checkout.py::test_checkout_crash_keeps_idempotency_link[before_invoice]` | - | asyncio, parametrize, runtime | passed | 0.058 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_product_after_quote[draft-True]` | - | asyncio, parametrize, runtime | passed | 0.057 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_product_after_quote[nip99_status-deleted]` | - | asyncio, parametrize, runtime | passed | 0.056 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_product_after_quote[recurring_frequency-monthly]` | - | asyncio, parametrize, runtime | passed | 0.057 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_product_after_quote[visibility-hidden]` | - | asyncio, parametrize, runtime | passed | 0.055 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_variation_parent_after_quote[draft]` | - | asyncio, parametrize, runtime | passed | 0.086 |
| `tests/runtime/test_checkout.py::test_claim_rechecks_variation_parent_after_quote[hidden]` | - | asyncio, parametrize, runtime | passed | 0.089 |
| `tests/runtime/test_checkout.py::test_duplicate_cart_items_are_rejected_before_intake` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_checkout.py::test_fresh_checkout_creates_order` | - | asyncio, runtime | passed | 0.050 |
| `tests/runtime/test_checkout.py::test_fx_usd_conversion` | - | asyncio, runtime | passed | 0.046 |
| `tests/runtime/test_checkout.py::test_idempotency_crash_resume` | - | asyncio, runtime | passed | 0.057 |
| `tests/runtime/test_checkout.py::test_idempotency_replay_and_conflict` | - | asyncio, runtime | passed | 0.060 |
| `tests/runtime/test_checkout.py::test_import_marker_sells_normally` | - | asyncio, runtime | passed | 0.085 |
| `tests/runtime/test_checkout.py::test_intake_rejects_bad_items` | - | asyncio, runtime | passed | 2.124 |
| `tests/runtime/test_checkout.py::test_intake_rejects_unpurchasable` | - | asyncio, runtime | passed | 0.022 |
| `tests/runtime/test_checkout.py::test_missing_fx_rejected` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_checkout.py::test_non_utc_database_blocks_financial_operations` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_checkout.py::test_oversell_rejected` | - | asyncio, runtime | passed | 0.023 |
| `tests/runtime/test_checkout.py::test_reclaimed_checkout_fences_stale_admission` | - | asyncio, runtime | passed | 0.103 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[JPY-7-fees3-None-700]` | - | asyncio, parametrize, runtime | passed | 0.145 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[SAT-10-fees4-None-110]` | - | asyncio, parametrize, runtime | passed | 0.149 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[SAT-10-fees5-None-231]` | - | asyncio, parametrize, runtime | passed | 0.216 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[SAT-10-fees6-None-4010]` | - | asyncio, parametrize, runtime | passed | 0.156 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[SAT-10-fees7-7-24]` | - | asyncio, parametrize, runtime | passed | 0.161 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[SAT-500-fees0-None-500]` | - | asyncio, parametrize, runtime | passed | 0.130 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[USD-550-fees1-None-550]` | - | asyncio, parametrize, runtime | passed | 0.215 |
| `tests/runtime/test_checkout.py::test_shipping_quotes_include_precision_and_components[USD-550-fees2-7-564]` | - | asyncio, parametrize, runtime | passed | 0.143 |
| `tests/runtime/test_checkout.py::test_shipping_rejects_invalid_coverage[missing-region]` | - | asyncio, parametrize, runtime | passed | 0.058 |
| `tests/runtime/test_checkout.py::test_shipping_rejects_invalid_coverage[region-country-mismatch]` | - | asyncio, parametrize, runtime | passed | 0.058 |
| `tests/runtime/test_checkout.py::test_shipping_rejects_invalid_coverage[unassigned]` | - | asyncio, parametrize, runtime | passed | 0.064 |
| `tests/runtime/test_checkout.py::test_shipping_weight_constraints_normalize_units[g-500]` | - | asyncio, parametrize, runtime | passed | 0.000 |
| `tests/runtime/test_checkout.py::test_shipping_weight_constraints_normalize_units[lb-2]` | - | asyncio, parametrize, runtime | passed | 0.000 |
| `tests/runtime/test_checkout.py::test_stock_rejection_does_not_leave_recoverable_received_order` | - | asyncio, runtime | passed | 0.060 |
| `tests/runtime/test_crypto_keystore.py::test_envelope_prefix_ambiguity_blocked` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_envelope_rejects_wrong_aad_parts` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_envelope_roundtrip_and_layout` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_envelope_version_absent_from_keyring` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_hmac_index_normalization` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_hmac_index_purpose_separation` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_imported_nsec_never_stored_plaintext` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_crypto_keystore.py::test_keyring_validation_via_env` | - | runtime | passed | 0.001 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_backup_restore_drill` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_generate_sign_roundtrip` | - | asyncio, runtime | passed | 0.194 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_import_validates_nsec` | - | asyncio, runtime | passed | 0.002 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_release_gated_methods` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_rewrap_resume_drill` | - | asyncio, runtime | passed | 0.028 |
| `tests/runtime/test_crypto_keystore.py::test_keystore_rewrap_rotation_drill` | - | asyncio, runtime | passed | 0.012 |
| `tests/runtime/test_crypto_keystore.py::test_merchant_and_key_rollback_together` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_crypto_keystore.py::test_public_base_url_must_be_canonical_https` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_public_token_rejects_noncanonical` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_public_token_roundtrip` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_relay_url_validation` | - | runtime | passed | 0.000 |
| `tests/runtime/test_crypto_keystore.py::test_start_hook_fails_before_activation` | - | runtime | passed | 0.000 |
| `tests/runtime/test_db.py::test_cancelled_transaction_entry_releases_sqlite_lock` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_db.py::test_categories_upgrade_keeps_products_and_publication_history` | - | asyncio, runtime | passed | 0.028 |
| `tests/runtime/test_db.py::test_checkout_safety_upgrade_preserves_financial_values` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_db.py::test_commit_persists` | - | asyncio, runtime | passed | 0.020 |
| `tests/runtime/test_db.py::test_concurrent_writers_serialize` | - | asyncio, runtime | passed | 0.117 |
| `tests/runtime/test_db.py::test_domain_transaction_allows_separate_read_connection` | - | asyncio, runtime | passed | 0.002 |
| `tests/runtime/test_db.py::test_fencing_update_inside_tx` | - | asyncio, runtime | passed | 0.004 |
| `tests/runtime/test_db.py::test_fk_enforced_inside_tx` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_db.py::test_inbox_scope_backlog_index_upgrade` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_db.py::test_rollback_discards` | - | asyncio, runtime | passed | 0.002 |
| `tests/runtime/test_email_queue.py::test_claim_token_fencing` | - | asyncio, runtime | passed | 0.050 |
| `tests/runtime/test_email_queue.py::test_concurrent_email_claims_do_not_overlap` | - | asyncio, runtime | skipped | 0.000 |
| `tests/runtime/test_email_queue.py::test_consent_revocation_suppresses` | - | asyncio, runtime | passed | 0.060 |
| `tests/runtime/test_email_queue.py::test_email_rate_limit_is_atomic` | - | asyncio, runtime | skipped | 0.102 |
| `tests/runtime/test_email_queue.py::test_enqueue_dedupes` | - | asyncio, runtime | passed | 0.046 |
| `tests/runtime/test_email_queue.py::test_expired_claim_never_calls_smtp` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[absent-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.116 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[absent-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.115 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[absent-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[hash-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.122 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[hash-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.120 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[hash-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.123 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[healthy-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.126 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[healthy-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.131 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[healthy-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[partial-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.129 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[partial-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.123 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[partial-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.131 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[snapshot-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.122 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[snapshot-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[snapshot-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.114 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[unpaid-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.082 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[unpaid-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 1.961 |
| `tests/runtime/test_email_queue.py::test_hard01_settled_without_accounting_email[unpaid-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.084 |
| `tests/runtime/test_email_queue.py::test_orderless_test_send` | - | asyncio, runtime | passed | 0.028 |
| `tests/runtime/test_email_queue.py::test_send_classification` | - | asyncio, runtime | passed | 0.173 |
| `tests/runtime/test_email_queue.py::test_subject_has_no_pii` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_email_queue.py::test_suppression_taxonomy` | - | asyncio, runtime | passed | 0.058 |
| `tests/runtime/test_email_queue.py::test_worker_errors_do_not_log_private_exception_text` | - | asyncio, runtime | passed | 0.008 |
| `tests/runtime/test_email_signin.py::test_account_channel_uses_email_account_bucket` | - | asyncio, runtime | passed | 0.032 |
| `tests/runtime/test_email_signin.py::test_auth_email_page_serves_shell` | - | asyncio, runtime | passed | 0.023 |
| `tests/runtime/test_email_signin.py::test_challenge_capability_flags` | - | asyncio, runtime | passed | 0.010 |
| `tests/runtime/test_email_signin.py::test_legacy_session_lazy_materialization` | - | asyncio, runtime | passed | 0.019 |
| `tests/runtime/test_email_signin.py::test_link_email_from_nostr_session` | - | asyncio, runtime | passed | 0.063 |
| `tests/runtime/test_email_signin.py::test_link_endpoints_require_session_and_origin` | - | asyncio, runtime | passed | 0.059 |
| `tests/runtime/test_email_signin.py::test_link_nostr_from_email_session` | - | asyncio, runtime | passed | 0.056 |
| `tests/runtime/test_email_signin.py::test_link_token_repointed_by_midflight_merge` | - | asyncio, runtime | passed | 0.104 |
| `tests/runtime/test_email_signin.py::test_link_token_retired_target_is_signin_invalid` | - | asyncio, runtime | passed | 0.015 |
| `tests/runtime/test_email_signin.py::test_magic_link_send_renders_fragment_and_wipes` | - | asyncio, runtime | passed | 0.008 |
| `tests/runtime/test_email_signin.py::test_magic_link_suppressed_when_email_disabled` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_email_signin.py::test_magic_link_suppressed_when_host_unconfigured` | - | asyncio, runtime | passed | 1.661 |
| `tests/runtime/test_email_signin.py::test_merge_conflict_moves_nothing` | - | asyncio, runtime | passed | 0.104 |
| `tests/runtime/test_email_signin.py::test_public_auth_email_js_safety` | - | asyncio, runtime | passed | 0.000 |
| `tests/runtime/test_email_signin.py::test_request_per_email_cap_silently_skips` | - | asyncio, runtime | passed | 0.046 |
| `tests/runtime/test_email_signin.py::test_request_per_ip_bucket_is_honest_429` | - | asyncio, runtime | passed | 0.116 |
| `tests/runtime/test_email_signin.py::test_request_uniform_body_no_oracle` | - | asyncio, runtime | passed | 0.134 |
| `tests/runtime/test_email_signin.py::test_signin_affordance_follows_either_method` | - | asyncio, runtime | passed | 0.141 |
| `tests/runtime/test_email_signin.py::test_union_merge_moves_identity_sessions_orders` | - | asyncio, runtime | passed | 0.188 |
| `tests/runtime/test_email_signin.py::test_verify_failures_share_identical_401` | - | asyncio, runtime | passed | 0.051 |
| `tests/runtime/test_email_signin.py::test_verify_requires_exact_origin` | - | asyncio, runtime | passed | 0.027 |
| `tests/runtime/test_email_signin.py::test_verify_signin_cookie_contract_and_bound_orders` | - | asyncio, runtime | passed | 0.118 |
| `tests/runtime/test_email_signin.py::test_wrong_purpose_challenges_fail_identically` | - | asyncio, runtime | passed | 0.063 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[branch]` | - | asyncio, parametrize, runtime | passed | 0.138 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[changed_quantity]` | - | asyncio, parametrize, runtime | passed | 0.195 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[cycle]` | - | asyncio, parametrize, runtime | passed | 0.154 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[future]` | - | asyncio, parametrize, runtime | passed | 0.166 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[items_string]` | - | asyncio, parametrize, runtime | passed | 0.138 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[missing_parent]` | - | asyncio, parametrize, runtime | passed | 0.155 |
| `tests/runtime/test_financial_review.py::test_review_accept_lineage_damage_is_readonly_hold[parent_list]` | - | asyncio, parametrize, runtime | passed | 0.120 |
| `tests/runtime/test_financial_review.py::test_review_accept_stock_intent_uses_database_clock` | - | asyncio, runtime | passed | 0.127 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[boolean-accepted_allocated_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.113 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[boolean-backordered_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.113 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[boolean-consumed_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.114 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[boolean-quantity]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.129 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[float-accepted_allocated_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.113 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[float-backordered_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.112 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[float-consumed_qty]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.114 |
| `tests/runtime/test_financial_review.py::test_review_ancestor_quantity_types_fail_closed[float-quantity]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.113 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[bolt11-]` | - | asyncio, parametrize, runtime | passed | 0.094 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[checking_id-]` | - | asyncio, parametrize, runtime | passed | 0.096 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[expiry-None]` | - | asyncio, parametrize, runtime | passed | 0.090 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[extra-value3]` | - | asyncio, parametrize, runtime | passed | 0.089 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[extra-value4]` | - | asyncio, parametrize, runtime | passed | 0.089 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[payment_hash-dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd]` | - | asyncio, parametrize, runtime | passed | 0.098 |
| `tests/runtime/test_financial_review.py::test_review_callback_identity_matches_canonical_core[wallet_id-foreign-wallet]` | - | asyncio, parametrize, runtime | passed | 0.096 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[bolt11_corrupt]` | - | asyncio, parametrize, runtime | passed | 0.163 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[bolt11_null]` | - | asyncio, parametrize, runtime | passed | 0.144 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[checking_null]` | - | asyncio, parametrize, runtime | passed | 0.170 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[expiry_null]` | - | asyncio, parametrize, runtime | passed | 0.285 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[expiry_other]` | - | asyncio, parametrize, runtime | passed | 0.142 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[order_hash_malformed]` | - | asyncio, parametrize, runtime | passed | 0.153 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[order_hash_null]` | - | asyncio, parametrize, runtime | passed | 0.160 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[order_hash_other]` | - | asyncio, parametrize, runtime | passed | 0.161 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[projection_hash_null]` | - | asyncio, parametrize, runtime | passed | 0.151 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[projection_hash_other]` | - | asyncio, parametrize, runtime | passed | 0.179 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[resolution_other]` | - | asyncio, parametrize, runtime | passed | 0.141 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[source_hash_malformed]` | - | asyncio, parametrize, runtime | passed | 0.143 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[source_hash_null]` | - | asyncio, parametrize, runtime | passed | 0.148 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[wallet_hash_malformed]` | - | asyncio, parametrize, runtime | passed | 0.149 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[wallet_refs_corrupt]` | - | asyncio, parametrize, runtime | passed | 0.156 |
| `tests/runtime/test_financial_review.py::test_review_corrupt_paid_identity_is_readonly_denied[wallet_refs_null]` | - | asyncio, parametrize, runtime | passed | 0.177 |
| `tests/runtime/test_financial_review.py::test_review_deadline_after_financial_lock_wait[orders-attachment]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.075 |
| `tests/runtime/test_financial_review.py::test_review_deadline_after_financial_lock_wait[orders-settlement]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.090 |
| `tests/runtime/test_financial_review.py::test_review_deadline_after_financial_lock_wait[products-attachment]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.073 |
| `tests/runtime/test_financial_review.py::test_review_deadline_after_financial_lock_wait[products-settlement]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.089 |
| `tests/runtime/test_financial_review.py::test_review_direct_confirmation_requires_attached_identity` | - | asyncio, runtime | passed | 0.091 |
| `tests/runtime/test_financial_review.py::test_review_fresh_creating_without_hold_is_not_payable[corrupt]` | - | asyncio, parametrize, runtime | passed | 0.103 |
| `tests/runtime/test_financial_review.py::test_review_fresh_creating_without_hold_is_not_payable[expired]` | - | asyncio, parametrize, runtime | passed | 0.103 |
| `tests/runtime/test_financial_review.py::test_review_fresh_creating_without_hold_is_not_payable[missing]` | - | asyncio, parametrize, runtime | passed | 0.140 |
| `tests/runtime/test_financial_review.py::test_review_fresh_creating_without_hold_is_not_payable[partial]` | - | asyncio, parametrize, runtime | passed | 0.121 |
| `tests/runtime/test_financial_review.py::test_review_fresh_creating_without_hold_is_not_payable[released]` | - | asyncio, parametrize, runtime | passed | 0.139 |
| `tests/runtime/test_financial_review.py::test_review_gamma_discards_stale_caller_invoice` | - | asyncio, runtime | passed | 0.210 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[corrupt]` | - | asyncio, parametrize, runtime | passed | 0.171 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[expired]` | - | asyncio, parametrize, runtime | passed | 0.239 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[healthy]` | - | asyncio, parametrize, runtime | passed | 0.418 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[identity]` | - | asyncio, parametrize, runtime | passed | 0.172 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[lost]` | - | asyncio, parametrize, runtime | passed | 0.165 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[manual]` | - | asyncio, parametrize, runtime | passed | 0.325 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[reasonless]` | - | asyncio, parametrize, runtime | passed | 0.218 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[status]` | - | asyncio, parametrize, runtime | passed | 0.169 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[strong]` | - | asyncio, parametrize, runtime | passed | 0.152 |
| `tests/runtime/test_financial_review.py::test_review_gamma_request_admission[unknown]` | - | asyncio, parametrize, runtime | passed | 0.299 |
| `tests/runtime/test_financial_review.py::test_review_gamma_selection_before_cancellation[cancel]` | - | asyncio, parametrize, runtime | passed | 0.083 |
| `tests/runtime/test_financial_review.py::test_review_gamma_selection_before_cancellation[deadline]` | - | asyncio, parametrize, runtime | passed | 0.073 |
| `tests/runtime/test_financial_review.py::test_review_gamma_selection_before_cancellation[projection]` | - | asyncio, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_financial_review.py::test_review_later_reconciliation_candidate_uses_current_clock` | - | asyncio, runtime | passed | 0.208 |
| `tests/runtime/test_financial_review.py::test_review_normal_callback_requires_snapshot[bolt11]` | - | asyncio, parametrize, runtime | passed | 0.160 |
| `tests/runtime/test_financial_review.py::test_review_normal_callback_requires_snapshot[checking]` | - | asyncio, parametrize, runtime | passed | 0.119 |
| `tests/runtime/test_financial_review.py::test_review_normal_callback_requires_snapshot[order_hash]` | - | asyncio, parametrize, runtime | passed | 0.146 |
| `tests/runtime/test_financial_review.py::test_review_normal_callback_requires_snapshot[projection_hash]` | - | asyncio, parametrize, runtime | passed | 0.150 |
| `tests/runtime/test_financial_review.py::test_review_normal_callback_requires_snapshot[refs]` | - | asyncio, parametrize, runtime | passed | 0.274 |
| `tests/runtime/test_financial_review.py::test_review_paid_expiry_and_wallet_switch_preserve_original_authority` | - | asyncio, runtime | passed | 0.141 |
| `tests/runtime/test_financial_review.py::test_review_paid_snapshot_survives_legitimate_wallet_switch` | - | asyncio, runtime | passed | 1.802 |
| `tests/runtime/test_financial_review.py::test_review_pg_checkout_email_fk_cycle_completes` | - | asyncio, runtime | skipped | 0.001 |
| `tests/runtime/test_financial_review.py::test_review_public_delivery_snapshot_serializes_cancellation[email]` | - | asyncio, parametrize, runtime | skipped | 0.001 |
| `tests/runtime/test_financial_review.py::test_review_public_delivery_snapshot_serializes_cancellation[history]` | - | asyncio, parametrize, runtime | skipped | 0.001 |
| `tests/runtime/test_financial_review.py::test_review_public_delivery_snapshot_serializes_cancellation[public]` | - | asyncio, parametrize, runtime | skipped | 0.001 |
| `tests/runtime/test_financial_review.py::test_review_public_invoice_requires_live_identity[checking]` | - | asyncio, parametrize, runtime | passed | 0.088 |
| `tests/runtime/test_financial_review.py::test_review_public_invoice_requires_live_identity[corrupt]` | - | asyncio, parametrize, runtime | passed | 0.082 |
| `tests/runtime/test_financial_review.py::test_review_public_invoice_requires_live_identity[expired]` | - | asyncio, parametrize, runtime | passed | 0.081 |
| `tests/runtime/test_financial_review.py::test_review_public_invoice_requires_live_identity[lost]` | - | asyncio, parametrize, runtime | passed | 0.084 |
| `tests/runtime/test_financial_review.py::test_review_public_invoice_requires_live_identity[status]` | - | asyncio, parametrize, runtime | passed | 0.080 |
| `tests/runtime/test_financial_review.py::test_review_reservation_cardinality_fails_closed[accept]` | - | asyncio, parametrize, runtime | passed | 0.130 |
| `tests/runtime/test_financial_review.py::test_review_reservation_cardinality_fails_closed[coverage]` | - | asyncio, parametrize, runtime | passed | 0.097 |
| `tests/runtime/test_financial_review.py::test_review_reservation_cardinality_fails_closed[release]` | - | asyncio, parametrize, runtime | passed | 0.091 |
| `tests/runtime/test_financial_review.py::test_review_snapshot_boolean_version_is_not_authority[amount_sat]` | - | asyncio, parametrize, runtime | passed | 0.124 |
| `tests/runtime/test_financial_review.py::test_review_snapshot_boolean_version_is_not_authority[expiry]` | - | asyncio, parametrize, runtime | passed | 0.112 |
| `tests/runtime/test_financial_review.py::test_review_snapshot_boolean_version_is_not_authority[user_id]` | - | asyncio, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_financial_review.py::test_review_snapshot_boolean_version_is_not_authority[version]` | - | asyncio, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_inbox_activation.py::test_activation_error` | - | asyncio, runtime | passed | 19.912 |
| `tests/runtime/test_inbox_activation.py::test_activation_vertical` | - | asyncio, runtime | passed | 14.915 |
| `tests/runtime/test_inbox_activation.py::test_build_kind10050_deterministic` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_inbox_activation.py::test_disable_off_is_noop` | - | asyncio, runtime | passed | 0.038 |
| `tests/runtime/test_inbox_activation.py::test_enable_requires_inbox_relay` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_inbox_activation.py::test_inbox_routes_owner_scoped` | - | asyncio, runtime | passed | 0.136 |
| `tests/runtime/test_inbox_activation.py::test_m006_schema_present` | - | asyncio, runtime | passed | 1.561 |
| `tests/runtime/test_inbox_transport.py::test_admission_rejections` | - | asyncio, runtime | passed | 0.041 |
| `tests/runtime/test_inbox_transport.py::test_answer_auth_challenge_bounds` | - | asyncio, runtime | passed | 0.038 |
| `tests/runtime/test_inbox_transport.py::test_duplicate_and_retry_wraps_are_noops` | - | asyncio, runtime | passed | 0.053 |
| `tests/runtime/test_inbox_transport.py::test_nip42_auth_roundtrip` | - | asyncio, runtime | passed | 1.109 |
| `tests/runtime/test_inbox_transport.py::test_nip42_oversize_challenge_ignored` | - | asyncio, runtime | passed | 2.176 |
| `tests/runtime/test_inbox_transport.py::test_no_signer_on_owned_transports` | - | asyncio, runtime | passed | 0.105 |
| `tests/runtime/test_inbox_transport.py::test_paid_relay_evidence_is_never_delivery` | - | asyncio, runtime | passed | 0.056 |
| `tests/runtime/test_inbox_transport.py::test_peer_relay_discovery_and_cache` | - | asyncio, runtime | passed | 0.037 |
| `tests/runtime/test_inbox_transport.py::test_peer_relay_no_route_sentinel` | - | asyncio, runtime | passed | 0.056 |
| `tests/runtime/test_inbox_transport.py::test_peer_relay_refresh` | - | asyncio, runtime | passed | 0.047 |
| `tests/runtime/test_inbox_transport.py::test_relay_auth_endpoints` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_inbox_transport.py::test_relay_io_off_holds_no_sockets` | - | asyncio, runtime | passed | 1.948 |
| `tests/runtime/test_inbox_transport.py::test_subscription_admission_and_cursor` | - | asyncio, runtime | passed | 0.697 |
| `tests/runtime/test_inbox_transport.py::test_validate_peer_relay_target` | - | asyncio, runtime | passed | 0.005 |
| `tests/runtime/test_install.py::test_admin_page_renders_template` | - | asyncio, runtime | passed | 0.134 |
| `tests/runtime/test_install.py::test_admin_page_requires_auth` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_install.py::test_deactivation_404s_routes` | - | asyncio, runtime | passed | 0.130 |
| `tests/runtime/test_install.py::test_demo_product_images_are_packaged_and_served` | - | asyncio, runtime | passed | 0.057 |
| `tests/runtime/test_install.py::test_discovered_and_registered` | - | asyncio, runtime | passed | 1.808 |
| `tests/runtime/test_install.py::test_m001_tables_created` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_install.py::test_m006_columns_created` | - | asyncio, runtime | passed | 0.005 |
| `tests/runtime/test_install.py::test_modeled_columns_match_registry` | - | asyncio, runtime | passed | 0.025 |
| `tests/runtime/test_install.py::test_reactivation_reruns_start_hook` | - | asyncio, runtime | passed | 0.104 |
| `tests/runtime/test_install.py::test_static_probe_mounted` | - | asyncio, runtime | passed | 0.005 |
| `tests/runtime/test_intake_abuse.py::test_admission_bound_kind_ptag_sig_order` | - | asyncio, runtime | passed | 1.589 |
| `tests/runtime/test_intake_abuse.py::test_hard06_concurrent_admission_at999` | - | asyncio, runtime | passed | 0.154 |
| `tests/runtime/test_intake_abuse.py::test_hard06_pending_scope_cap_rejects_before_decrypt` | - | asyncio, runtime | passed | 0.094 |
| `tests/runtime/test_intake_abuse.py::test_muted_author_bounded_growth` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_intake_abuse.py::test_no_route_refresh_and_48h_deadline` | - | asyncio, runtime | passed | 0.338 |
| `tests/runtime/test_intake_abuse.py::test_per_author_flood_drop_before_validation` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_intake_abuse.py::test_process_pending_twice_no_duplicate_domain` | - | asyncio, runtime | passed | 0.173 |
| `tests/runtime/test_intake_abuse.py::test_reconcile_resumes_inbox_rows` | - | asyncio, runtime | passed | 0.187 |
| `tests/runtime/test_intake_abuse.py::test_rejected_intake_admin_surface_and_mute` | - | asyncio, runtime | passed | 0.065 |
| `tests/runtime/test_intake_abuse.py::test_retention_erases_rejected_quarantined` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_intake_abuse.py::test_same_rumor_two_relays_single_message` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_intake_abuse.py::test_wrap_relay_flood_bucket` | - | asyncio, runtime | passed | 0.053 |
| `tests/runtime/test_keystore_nip17.py::test_golden_kind14_and_kind17` | - | asyncio, runtime | passed | 0.017 |
| `tests/runtime/test_keystore_nip17.py::test_golden_recipient_copy_unwraps` | - | asyncio, runtime | passed | 0.309 |
| `tests/runtime/test_keystore_nip17.py::test_golden_retry_wrap_same_rumor` | - | asyncio, runtime | passed | 0.010 |
| `tests/runtime/test_keystore_nip17.py::test_golden_sender_copy_unwraps` | - | asyncio, runtime | passed | 0.010 |
| `tests/runtime/test_keystore_nip17.py::test_nip04_still_release_gated` | - | asyncio, runtime | passed | 0.009 |
| `tests/runtime/test_keystore_nip17.py::test_no_key_plaintext_or_ciphertext_in_logs` | - | asyncio, runtime | passed | 0.020 |
| `tests/runtime/test_keystore_nip17.py::test_nsec_deleted_in_finally_source` | - | asyncio, runtime | passed | 0.002 |
| `tests/runtime/test_keystore_nip17.py::test_tamper_matrix` | - | asyncio, runtime | passed | 0.049 |
| `tests/runtime/test_keystore_nip17.py::test_wrap_roundtrip_stable_rumor_fresh_wrap` | - | asyncio, runtime | passed | 0.016 |
| `tests/runtime/test_merchant_api.py::test_audit_posture_qualified_and_flagged` | - | asyncio, runtime | passed | 0.130 |
| `tests/runtime/test_merchant_api.py::test_bearer_mutation_passes_without_origin` | - | asyncio, runtime | passed | 0.011 |
| `tests/runtime/test_merchant_api.py::test_cookie_mutation_requires_origin_and_csrf` | - | asyncio, runtime | passed | 0.020 |
| `tests/runtime/test_merchant_api.py::test_cookie_with_forged_bearer_still_enforces_origin` | - | asyncio, runtime | passed | 0.023 |
| `tests/runtime/test_merchant_api.py::test_current_merchant_projection` | - | asyncio, runtime | passed | 0.021 |
| `tests/runtime/test_merchant_api.py::test_deactivation_enqueues_tombstones` | - | asyncio, runtime | passed | 0.025 |
| `tests/runtime/test_merchant_api.py::test_duplicate_merchant_rejected` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_merchant_api.py::test_foreign_merchant_is_404` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_merchant_api.py::test_idempotency_key_accepted_and_shape_validated` | - | asyncio, runtime | passed | 0.026 |
| `tests/runtime/test_merchant_api.py::test_key_export_reveals_nsec_to_owner` | - | asyncio, runtime | passed | 0.033 |
| `tests/runtime/test_merchant_api.py::test_key_import_replaces_identity` | - | asyncio, runtime | passed | 0.013 |
| `tests/runtime/test_merchant_api.py::test_notification_config` | - | asyncio, runtime | passed | 0.024 |
| `tests/runtime/test_merchant_api.py::test_profile_identity_fields` | - | asyncio, runtime | passed | 0.043 |
| `tests/runtime/test_merchant_api.py::test_publish_enqueues_outbox_intents` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_merchant_api.py::test_relay_config_validation` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_merchant_api.py::test_safe_get_requires_auth` | - | asyncio, runtime | passed | 1.467 |
| `tests/runtime/test_merchant_api.py::test_user_id_only_mutation_rejected` | - | asyncio, runtime | passed | 0.004 |
| `tests/runtime/test_merchant_api.py::test_wallet_binding_rejects_foreign_wallet` | - | asyncio, runtime | passed | 0.010 |
| `tests/runtime/test_migration_export_media.py::test_export_is_merchant_scoped` | - | asyncio, runtime | passed | 0.033 |
| `tests/runtime/test_migration_export_media.py::test_export_reimport_and_activation[bulk]` | - | asyncio, parametrize, runtime | passed | 0.394 |
| `tests/runtime/test_migration_export_media.py::test_export_reimport_and_activation[patch]` | - | asyncio, parametrize, runtime | passed | 1.923 |
| `tests/runtime/test_migration_export_media.py::test_lightnin_dark_storefront_profile` | - | asyncio, runtime | passed | 0.176 |
| `tests/runtime/test_migration_export_media.py::test_media_upload_and_relink` | - | asyncio, runtime | passed | 0.092 |
| `tests/runtime/test_migration_export_media.py::test_media_upload_rejects_foreign_and_mismatched` | - | asyncio, runtime | passed | 0.100 |
| `tests/runtime/test_migration_import.py::test_any_unknown_variant_blocks_product_stock` | - | - | passed | 0.000 |
| `tests/runtime/test_migration_import.py::test_classic_shopify_image_only_rows_and_missing_inventory` | - | - | passed | 0.001 |
| `tests/runtime/test_migration_import.py::test_custom_csv_mapping_is_explicit_and_pinned` | - | - | passed | 0.001 |
| `tests/runtime/test_migration_import.py::test_imported_drafts_publish_after_review` | - | asyncio | passed | 2.412 |
| `tests/runtime/test_migration_import.py::test_imported_product_publishes_normally` | - | asyncio | passed | 0.199 |
| `tests/runtime/test_migration_import.py::test_modern_shopify_groups_variants_and_unknown_stock` | - | - | passed | 0.002 |
| `tests/runtime/test_migration_import.py::test_nip15_signed_events_and_ndjson_only_allowed_kinds` | - | - | passed | 0.003 |
| `tests/runtime/test_migration_import.py::test_nostrmarket_export_imports_only_catalog` | - | - | passed | 0.001 |
| `tests/runtime/test_migration_import.py::test_private_three_product_sample_import` | - | asyncio | skipped | 0.103 |
| `tests/runtime/test_migration_import.py::test_shopify_rejects_overflow_and_bad_urls` | - | - | passed | 0.002 |
| `tests/runtime/test_migration_import.py::test_shopify_requires_explicit_currency` | - | - | passed | 0.001 |
| `tests/runtime/test_migration_import.py::test_three_product_stock_fixture_with_variant_total` | - | - | passed | 0.000 |
| `tests/runtime/test_nip17_inbox.py::test_admin_compose_dm_dual_copy` | - | asyncio, runtime | passed | 0.010 |
| `tests/runtime/test_nip17_inbox.py::test_buyer_cancel_on_awaiting_payment` | - | asyncio, runtime | passed | 0.133 |
| `tests/runtime/test_nip17_inbox.py::test_buyer_cancel_on_confirmed_illegal` | - | asyncio, runtime | passed | 0.160 |
| `tests/runtime/test_nip17_inbox.py::test_buyer_status_confirmed_audit_only` | - | asyncio, runtime | passed | 0.129 |
| `tests/runtime/test_nip17_inbox.py::test_buyer_type2_rejected` | - | asyncio, runtime | passed | 0.027 |
| `tests/runtime/test_nip17_inbox.py::test_cross_merchant_item_rejected` | - | asyncio, runtime | passed | 0.063 |
| `tests/runtime/test_nip17_inbox.py::test_disallowed_rumor_kind_rejected` | - | asyncio, runtime | passed | 0.020 |
| `tests/runtime/test_nip17_inbox.py::test_dm_rate_cap` | - | asyncio, runtime | passed | 0.303 |
| `tests/runtime/test_nip17_inbox.py::test_duplicate_wrap_and_rumor_retry_single_order` | - | asyncio, runtime | passed | 0.101 |
| `tests/runtime/test_nip17_inbox.py::test_external_id_charset_violation_rejected` | - | asyncio, runtime | passed | 0.063 |
| `tests/runtime/test_nip17_inbox.py::test_foreign_buyer_cancel_no_oracle` | - | asyncio, runtime | passed | 0.138 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_cancel_releases_once_without_relay_io` | - | asyncio, runtime | passed | 0.100 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[absent]` | - | asyncio, parametrize, runtime | passed | 0.228 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[hash]` | - | asyncio, parametrize, runtime | passed | 0.133 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[healthy]` | - | asyncio, parametrize, runtime | passed | 0.167 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[legacy_paid_awaiting]` | - | asyncio, parametrize, runtime | passed | 0.132 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[partial]` | - | asyncio, parametrize, runtime | passed | 0.170 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[snapshot]` | - | asyncio, parametrize, runtime | passed | 0.129 |
| `tests/runtime/test_nip17_inbox.py::test_hard01_gamma_delivery_requires_payment_and_inventory[unpaid]` | - | asyncio, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_nip17_inbox.py::test_inbound_type3_unknown_order_audit_only` | - | asyncio, runtime | passed | 0.030 |
| `tests/runtime/test_nip17_inbox.py::test_kind14_dm_threads_unknown` | - | asyncio, runtime | passed | 0.031 |
| `tests/runtime/test_nip17_inbox.py::test_kind14_threads_order_when_sender_matches` | - | asyncio, runtime | passed | 0.144 |
| `tests/runtime/test_nip17_inbox.py::test_kind17_bad_preimage_no_verify` | - | asyncio, runtime | passed | 0.141 |
| `tests/runtime/test_nip17_inbox.py::test_kind17_receipt_verified` | - | asyncio, runtime | passed | 0.181 |
| `tests/runtime/test_nip17_inbox.py::test_missing_buyer_10050_rejected` | - | asyncio, runtime | passed | 0.069 |
| `tests/runtime/test_nip17_inbox.py::test_opaque_address_physical_rejected` | - | asyncio, runtime | passed | 0.067 |
| `tests/runtime/test_nip17_inbox.py::test_order_msg_revision0_never_supersedes` | - | asyncio, runtime | passed | 0.207 |
| `tests/runtime/test_nip17_inbox.py::test_reply_dm_resolves_unknown_counterparty` | - | asyncio, runtime | passed | 0.039 |
| `tests/runtime/test_nip17_inbox.py::test_sender_copy_recovery_no_dispatch` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_nip17_inbox.py::test_type1_creates_gamma_order_and_type2_intent` | - | asyncio, runtime | passed | 1.918 |
| `tests/runtime/test_nip17_outbox.py::test_dual_copy_publication_runtime` | - | asyncio, runtime | passed | 1.661 |
| `tests/runtime/test_nip17_outbox.py::test_hard05_real_send_failures_still_exhaust_budget` | - | asyncio, runtime | passed | 0.493 |
| `tests/runtime/test_nip17_outbox.py::test_hard05_route_after_twenty_waits_still_delivers` | - | asyncio, runtime | passed | 0.433 |
| `tests/runtime/test_nip17_outbox.py::test_no_buyer_10050_no_route_policy` | - | asyncio, runtime | passed | 0.109 |
| `tests/runtime/test_nip17_outbox.py::test_partial_acceptance_retries_missing_class_only` | - | asyncio, runtime | passed | 0.158 |
| `tests/runtime/test_nip89.py::test_hidden_variation_is_not_exposed_by_public_parent` | - | asyncio, runtime | passed | 0.107 |
| `tests/runtime/test_nip89.py::test_invalid_naddr_variants_render_invalid_link` | - | asyncio, runtime | passed | 0.037 |
| `tests/runtime/test_nip89.py::test_private_product_never_leaks_through_public_json[deleted]` | - | asyncio, parametrize, runtime | passed | 0.068 |
| `tests/runtime/test_nip89.py::test_private_product_never_leaks_through_public_json[draft]` | - | asyncio, parametrize, runtime | passed | 0.054 |
| `tests/runtime/test_nip89.py::test_private_product_never_leaks_through_public_json[hidden]` | - | asyncio, parametrize, runtime | passed | 0.053 |
| `tests/runtime/test_nip89.py::test_product_currency_precision_is_explicit[JPY-0]` | - | asyncio, parametrize, runtime | passed | 0.052 |
| `tests/runtime/test_nip89.py::test_product_currency_precision_is_explicit[SAT-0]` | - | asyncio, parametrize, runtime | passed | 0.064 |
| `tests/runtime/test_nip89.py::test_product_currency_precision_is_explicit[USD-2]` | - | asyncio, parametrize, runtime | passed | 0.053 |
| `tests/runtime/test_nip89.py::test_public_product_json_contract` | - | asyncio, runtime | passed | 0.060 |
| `tests/runtime/test_nip89.py::test_public_product_page_states` | - | asyncio, runtime | passed | 0.200 |
| `tests/runtime/test_nip89.py::test_rate_limit_enforced_on_public_routes` | - | asyncio, runtime | passed | 0.762 |
| `tests/runtime/test_nip89.py::test_valid_naddr_redirects_to_canonical` | - | asyncio, runtime | passed | 1.647 |
| `tests/runtime/test_nostr_signin.py::test_attributed_web_checkout` | - | asyncio, runtime | passed | 0.218 |
| `tests/runtime/test_nostr_signin.py::test_attributed_web_order_wraps_to_buyer_relays` | - | asyncio, runtime | passed | 0.474 |
| `tests/runtime/test_nostr_signin.py::test_challenge_issue_posture` | - | asyncio, runtime | passed | 1.711 |
| `tests/runtime/test_nostr_signin.py::test_claim_binds_buyer_and_audits` | - | asyncio, runtime | passed | 0.124 |
| `tests/runtime/test_nostr_signin.py::test_claim_failures_share_identical_outcome` | - | asyncio, runtime | passed | 0.202 |
| `tests/runtime/test_nostr_signin.py::test_claim_requires_session` | - | asyncio, runtime | passed | 0.079 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[absent-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.151 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[absent-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.132 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[absent-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.165 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[hash-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.170 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[hash-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.172 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[hash-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.175 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[partial-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.146 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[partial-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.148 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[partial-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.151 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[snapshot-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.158 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[snapshot-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.169 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[snapshot-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.179 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[unpaid-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.110 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[unpaid-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_nostr_signin.py::test_hard01_settled_without_accounting_history[unpaid-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.100 |
| `tests/runtime/test_nostr_signin.py::test_logout_revokes_session` | - | asyncio, runtime | passed | 0.028 |
| `tests/runtime/test_nostr_signin.py::test_nsec_signin_gated_and_mints_session` | - | asyncio, runtime | passed | 0.138 |
| `tests/runtime/test_nostr_signin.py::test_orders_requires_session` | - | asyncio, runtime | passed | 0.007 |
| `tests/runtime/test_nostr_signin.py::test_orders_scoped_to_buyer_and_delivery_gated` | - | asyncio, runtime | passed | 0.273 |
| `tests/runtime/test_nostr_signin.py::test_public_nostr_js_safety` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_nostr_signin.py::test_signin_affordance_follows_inbox_state` | - | asyncio, runtime | passed | 0.044 |
| `tests/runtime/test_nostr_signin.py::test_verify_rejections_share_identical_outcome` | - | asyncio, runtime | passed | 0.060 |
| `tests/runtime/test_nostr_signin.py::test_verify_requires_exact_origin` | - | asyncio, runtime | passed | 0.020 |
| `tests/runtime/test_nostr_signin.py::test_verify_sets_cookie_and_hashed_session` | - | asyncio, runtime | passed | 0.023 |
| `tests/runtime/test_order_admin.py::test_admin_idempotency_key_accepted` | - | asyncio, runtime | passed | 0.212 |
| `tests/runtime/test_order_admin.py::test_archived_late_payment_returns_to_active_attention` | - | asyncio, runtime | passed | 0.131 |
| `tests/runtime/test_order_admin.py::test_bulk_archive_and_restore_closed_orders` | - | asyncio, runtime | passed | 0.246 |
| `tests/runtime/test_order_admin.py::test_cancel_releases_stock_once` | - | asyncio, runtime | passed | 0.086 |
| `tests/runtime/test_order_admin.py::test_decrypted_pii_owner_only` | - | asyncio, runtime | passed | 0.552 |
| `tests/runtime/test_order_admin.py::test_events_chronology` | - | asyncio, runtime | passed | 0.099 |
| `tests/runtime/test_order_admin.py::test_exception_refund_attestation` | - | asyncio, runtime | passed | 0.098 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[confirmed-processing-absent]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.116 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[confirmed-processing-bad_item]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.111 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[confirmed-processing-extra]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.110 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[confirmed-processing-partial]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[processing-completed-absent]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.115 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[processing-completed-bad_item]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[processing-completed-extra]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.115 |
| `tests/runtime/test_order_admin.py::test_hard01_settled_without_accounting_status[processing-completed-partial]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.110 |
| `tests/runtime/test_order_admin.py::test_hard01_unpaid_status_cannot_unlock_delivery` | - | asyncio, runtime | passed | 0.085 |
| `tests/runtime/test_order_admin.py::test_list_and_detail` | - | asyncio, runtime | passed | 1.873 |
| `tests/runtime/test_order_admin.py::test_token_reissue` | - | asyncio, runtime | passed | 0.086 |
| `tests/runtime/test_order_admin.py::test_transition_matrix` | - | asyncio, runtime | passed | 0.129 |
| `tests/runtime/test_order_saga.py::test_amount_and_wallet_mismatch_quarantine` | - | asyncio, runtime | passed | 0.183 |
| `tests/runtime/test_order_saga.py::test_buyer_cancel_before_payment` | - | asyncio, runtime | passed | 0.075 |
| `tests/runtime/test_order_saga.py::test_delivery_content_rejected_for_physical_products` | - | asyncio, runtime | passed | 0.013 |
| `tests/runtime/test_order_saga.py::test_digital_delivery_revealed_only_after_confirmed_payment` | - | asyncio, runtime | passed | 0.173 |
| `tests/runtime/test_order_saga.py::test_duplicate_attachment_preserves_settled_projection` | - | asyncio, runtime | passed | 0.104 |
| `tests/runtime/test_order_saga.py::test_hard01_cancel_rolls_back_inventory_and_intents` | - | asyncio, runtime | passed | 0.074 |
| `tests/runtime/test_order_saga.py::test_hard01_concurrent_cancel_releases_once` | - | asyncio, runtime | passed | 0.076 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[absent]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[ambiguous_latest]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[boolean]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[digital_shortfall]` | - | asyncio, parametrize, runtime | passed | 0.114 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[double_count]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[duplicate]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[extra]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[foreign_item]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[foreign_product]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[malformed]` | - | asyncio, parametrize, runtime | passed | 0.122 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[missing]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[negative]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[valid]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[wrong_actor]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[wrong_backorder]` | - | asyncio, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[wrong_lineage]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[wrong_total]` | - | asyncio, parametrize, runtime | passed | 0.119 |
| `tests/runtime/test_order_saga.py::test_hard01_explicit_accepted_accounting_proof[wrong_version]` | - | asyncio, parametrize, runtime | passed | 0.118 |
| `tests/runtime/test_order_saga.py::test_hard01_fresh_accept_retains_authoritative_fulfillment` | - | asyncio, runtime | passed | 0.113 |
| `tests/runtime/test_order_saga.py::test_hard01_paid_cancellation_requires_reason` | - | asyncio, runtime | passed | 0.152 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.145 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.111 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-processing-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.081 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.114 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.080 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[exception-shipped-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.085 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.101 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.100 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.100 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.073 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.098 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.101 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.097 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[pending-processing-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.074 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.104 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-exception-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.104 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[processing-shipped-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.203 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-delivered-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-completed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-completed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-completed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-completed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.080 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-confirmed-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-confirmed-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-confirmed-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-confirmed-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.080 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-processing-absent]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-processing-hold]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-processing-partial]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_hard01_settled_without_accounting_shipping[shipped-exception-processing-unpaid]` | - | asyncio, parametrize, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_order_saga.py::test_hard01_status_cancellation_releases_atomically` | - | asyncio, runtime | passed | 0.103 |
| `tests/runtime/test_order_saga.py::test_hard02_already_settled_legacy_is_pure_noop[None-refund_requested]` | - | asyncio, parametrize, runtime | passed | 0.158 |
| `tests/runtime/test_order_saga.py::test_hard02_already_settled_legacy_is_pure_noop[invoice-creation-unknown-None]` | - | asyncio, parametrize, runtime | passed | 0.157 |
| `tests/runtime/test_order_saga.py::test_hard02_already_settled_legacy_is_pure_noop[settlement-wallet-mismatch-unresolved]` | - | asyncio, parametrize, runtime | passed | 0.162 |
| `tests/runtime/test_order_saga.py::test_hard02_attachment_does_not_clear_outside_new_active_coverage[cancelled]` | - | asyncio, parametrize, runtime | passed | 0.075 |
| `tests/runtime/test_order_saga.py::test_hard02_attachment_does_not_clear_outside_new_active_coverage[duplicate]` | - | asyncio, parametrize, runtime | passed | 0.081 |
| `tests/runtime/test_order_saga.py::test_hard02_attachment_does_not_clear_outside_new_active_coverage[expired]` | - | asyncio, parametrize, runtime | passed | 0.071 |
| `tests/runtime/test_order_saga.py::test_hard02_attachment_does_not_clear_outside_new_active_coverage[unallocated]` | - | asyncio, parametrize, runtime | passed | 0.083 |
| `tests/runtime/test_order_saga.py::test_hard02_callback_before_timeout_is_mutation_free` | - | asyncio, runtime | passed | 0.097 |
| `tests/runtime/test_order_saga.py::test_hard02_concurrent_timeout_manual_decision_attachment` | - | asyncio, runtime | passed | 0.078 |
| `tests/runtime/test_order_saga.py::test_hard02_new_settlement_resolves_before_notification_snapshots[None]` | - | asyncio, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard02_new_settlement_resolves_before_notification_snapshots[unresolved]` | - | asyncio, parametrize, runtime | passed | 0.104 |
| `tests/runtime/test_order_saga.py::test_hard02_recovered_original_invoice_is_payable_and_fulfillable` | - | asyncio, runtime | passed | 0.260 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[False-None-refund_confirmed-incomplete]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.101 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[False-None-refund_confirmed-late]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.096 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[False-None-refund_confirmed-mismatch]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.072 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-None-None-incomplete]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-None-None-late]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.103 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-None-None-mismatch]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.077 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-inventory-reservation-counters-incoherent-unresolved-incomplete]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-inventory-reservation-counters-incoherent-unresolved-late]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.101 |
| `tests/runtime/test_order_saga.py::test_hard02_review_does_not_replace_protected_authority[True-inventory-reservation-counters-incoherent-unresolved-mismatch]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.075 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[False-None-refund_confirmed]` | - | asyncio, parametrize, runtime | passed | 0.093 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[False-None-refund_requested]` | - | asyncio, parametrize, runtime | passed | 0.095 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-None-None]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-inventory-reservation-counters-incoherent-unresolved]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-invoice-correlation-failed-None]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-invoice-creation-unknown-accepted]` | - | asyncio, parametrize, runtime | passed | 0.098 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-invoice-creation-unknown-refund_confirmed]` | - | asyncio, parametrize, runtime | passed | 0.100 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-invoice-creation-unknown-refund_requested]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-multiple-core-payments-unresolved]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-settlement-amount-mismatch-None]` | - | asyncio, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_order_saga.py::test_hard02_timeout_preserves_protected_hold[True-settlement-wallet-mismatch-unresolved]` | - | asyncio, parametrize, runtime | passed | 0.098 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_cumulative_accounting_once[consumed]` | - | asyncio, parametrize, runtime | passed | 0.170 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_cumulative_accounting_once[partial]` | - | asyncio, parametrize, runtime | passed | 0.213 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_cumulative_accounting_once[residual]` | - | asyncio, parametrize, runtime | passed | 0.211 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_cumulative_accounting_once[unlimited]` | - | asyncio, parametrize, runtime | passed | 0.188 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_rejects_unproven_history_without_mutation[backorder]` | - | asyncio, parametrize, runtime | passed | 0.106 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_rejects_unproven_history_without_mutation[malformed]` | - | asyncio, parametrize, runtime | passed | 0.113 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_rejects_unproven_history_without_mutation[reason_only]` | - | asyncio, parametrize, runtime | passed | 0.111 |
| `tests/runtime/test_order_saga.py::test_hard03_accept_rejects_unproven_history_without_mutation[wrong_consumed]` | - | asyncio, parametrize, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_hard03_complete_multi_item_consumption` | - | asyncio, runtime | passed | 0.230 |
| `tests/runtime/test_order_saga.py::test_hard03_inventory_review_preserves_independent_hold[None-None]` | - | asyncio, parametrize, runtime | passed | 0.105 |
| `tests/runtime/test_order_saga.py::test_hard03_inventory_review_preserves_independent_hold[manual attestation-refund_confirmed]` | - | asyncio, parametrize, runtime | passed | 0.088 |
| `tests/runtime/test_order_saga.py::test_hard03_inventory_review_preserves_independent_hold[manual review-refund_requested]` | - | asyncio, parametrize, runtime | passed | 0.089 |
| `tests/runtime/test_order_saga.py::test_hard03_inventory_review_preserves_independent_hold[settlement-wallet-mismatch-unresolved]` | - | asyncio, parametrize, runtime | passed | 0.095 |
| `tests/runtime/test_order_saga.py::test_hard03_missing_coverage_settles_into_inventory_review[counter]` | - | asyncio, parametrize, runtime | passed | 0.158 |
| `tests/runtime/test_order_saga.py::test_hard03_missing_coverage_settles_into_inventory_review[expired]` | - | asyncio, parametrize, runtime | passed | 0.160 |
| `tests/runtime/test_order_saga.py::test_hard03_missing_coverage_settles_into_inventory_review[extra]` | - | asyncio, parametrize, runtime | passed | 0.161 |
| `tests/runtime/test_order_saga.py::test_hard03_missing_coverage_settles_into_inventory_review[missing]` | - | asyncio, parametrize, runtime | passed | 0.160 |
| `tests/runtime/test_order_saga.py::test_hard03_missing_coverage_settles_into_inventory_review[partial]` | - | asyncio, parametrize, runtime | passed | 0.160 |
| `tests/runtime/test_order_saga.py::test_hard03_pending_expiry_retains_correlation_without_payable_invoice` | - | asyncio, runtime | passed | 0.117 |
| `tests/runtime/test_order_saga.py::test_hard03_stale_expiry_selection_rechecks_current_truth[attachment]` | - | asyncio, parametrize, runtime | passed | 0.087 |
| `tests/runtime/test_order_saga.py::test_hard03_stale_expiry_selection_rechecks_current_truth[settlement]` | - | asyncio, parametrize, runtime | passed | 0.108 |
| `tests/runtime/test_order_saga.py::test_invoice_creation_unknown_never_duplicates` | - | asyncio, runtime | passed | 0.122 |
| `tests/runtime/test_order_saga.py::test_invoice_listener_redacts_error_context` | - | asyncio, runtime | passed | 0.003 |
| `tests/runtime/test_order_saga.py::test_kill_before_callback_reconcile_confirms` | - | asyncio, runtime | passed | 0.178 |
| `tests/runtime/test_order_saga.py::test_late_settlement_on_expired_order` | - | asyncio, runtime | passed | 0.107 |
| `tests/runtime/test_order_saga.py::test_lease_fencing` | - | asyncio, runtime | passed | 0.006 |
| `tests/runtime/test_order_saga.py::test_reconcile_resumes_received_order` | - | asyncio, runtime | passed | 0.110 |
| `tests/runtime/test_order_saga.py::test_reconciliation_recovers_late_payment_without_callback` | - | asyncio, runtime | passed | 0.131 |
| `tests/runtime/test_order_saga.py::test_reconciliation_verifies_payment_amount` | - | asyncio, runtime | passed | 0.143 |
| `tests/runtime/test_order_saga.py::test_reservation_expiry_releases_once` | - | asyncio, runtime | passed | 0.111 |
| `tests/runtime/test_order_saga.py::test_retention_erases_all_terminal_order_private_copies[False]` | - | asyncio, parametrize, runtime | passed | 0.081 |
| `tests/runtime/test_order_saga.py::test_retention_erases_all_terminal_order_private_copies[True]` | - | asyncio, parametrize, runtime | passed | 0.080 |
| `tests/runtime/test_order_saga.py::test_settlement_confirms_once` | - | asyncio, runtime | passed | 1.572 |
| `tests/runtime/test_order_saga.py::test_settlement_enqueues_addressed_stock_publication` | - | asyncio, runtime | passed | 0.109 |
| `tests/runtime/test_order_saga.py::test_settlement_foreign_payment_ignored` | - | asyncio, runtime | passed | 0.065 |
| `tests/runtime/test_order_saga.py::test_stale_expiry_worker_cannot_release_inventory` | - | asyncio, runtime | passed | 0.071 |
| `tests/runtime/test_order_saga.py::test_unverified_lnbits_invoice_is_not_offered_to_buyer[amount]` | - | asyncio, parametrize, runtime | passed | 0.066 |
| `tests/runtime/test_order_saga.py::test_unverified_lnbits_invoice_is_not_offered_to_buyer[wallet]` | - | asyncio, parametrize, runtime | passed | 0.063 |
| `tests/runtime/test_outbox.py::test_accepted_targets_are_never_resent` | - | asyncio, runtime | passed | 20.112 |
| `tests/runtime/test_outbox.py::test_dead_relay_isolated_one_failure_never_crashes_batch` | - | asyncio, runtime | passed | 10.069 |
| `tests/runtime/test_outbox.py::test_dependency_gate_blocks_until_published` | - | asyncio, runtime | passed | 0.026 |
| `tests/runtime/test_outbox.py::test_dependency_met_when_aggregate_has_published_revision` | - | asyncio, runtime | passed | 0.091 |
| `tests/runtime/test_outbox.py::test_expired_publication_claim_cannot_write` | - | asyncio, runtime | passed | 0.013 |
| `tests/runtime/test_outbox.py::test_hard04_dependency_scope_kind_merchant_and_failed` | - | asyncio, runtime | passed | 0.072 |
| `tests/runtime/test_outbox.py::test_hard04_prune_preserves_retained_dependencies` | - | asyncio, runtime | passed | 0.071 |
| `tests/runtime/test_outbox.py::test_hard04_reference_removal_republish_before_tombstone` | - | asyncio, runtime | passed | 0.121 |
| `tests/runtime/test_outbox.py::test_hard04_stale_revision_cannot_publish_dependent` | - | asyncio, runtime | passed | 0.101 |
| `tests/runtime/test_outbox.py::test_lease_expiry_during_send_cannot_commit_evidence` | - | asyncio, runtime | passed | 2.027 |
| `tests/runtime/test_outbox.py::test_network_send_does_not_hold_database_write_lock` | - | asyncio, runtime | passed | 0.022 |
| `tests/runtime/test_outbox.py::test_newer_live_revision_supersedes_stale_intent` | - | asyncio, runtime | passed | 0.035 |
| `tests/runtime/test_outbox.py::test_no_targets_cannot_be_published_or_activate_merchant` | - | asyncio, runtime | passed | 0.019 |
| `tests/runtime/test_outbox.py::test_oq6_send_to_dead_relay_is_timeout_not_exception` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_outbox.py::test_oq6_send_to_unconnected_client_times_out` | - | asyncio, runtime | passed | 0.004 |
| `tests/runtime/test_outbox.py::test_oq6_send_to_unregistered_relay_is_safe` | - | asyncio, runtime | passed | 0.001 |
| `tests/runtime/test_outbox.py::test_publish_accepted_marks_published_and_records_evidence` | - | asyncio, runtime | passed | 0.199 |
| `tests/runtime/test_outbox.py::test_rejected_and_timeout_relays_leave_intent_pending` | - | asyncio, runtime | passed | 10.064 |
| `tests/runtime/test_outbox.py::test_relay_targets_direction_and_defaults` | - | asyncio, runtime | passed | 0.029 |
| `tests/runtime/test_outbox.py::test_retry_intent_resets_failed_and_skips_accepted` | - | asyncio, runtime | passed | 0.018 |
| `tests/runtime/test_outbox.py::test_stale_claim_recovery_requeues_with_evidence` | - | asyncio, runtime | passed | 0.011 |
| `tests/runtime/test_public_contract.py::test_checkout_rate_limits` | - | asyncio, runtime | passed | 0.102 |
| `tests/runtime/test_public_contract.py::test_end_to_end_journey` | - | asyncio, runtime | passed | 0.218 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[absent-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.098 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[absent-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.103 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[absent-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.099 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[missing_payment-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.073 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[missing_payment-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.082 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[missing_payment-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.079 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[partial-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.101 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[partial-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.097 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[partial-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.103 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[unpaid-completed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[unpaid-confirmed]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.076 |
| `tests/runtime/test_public_contract.py::test_hard01_settled_without_accounting_token[unpaid-processing]` | - | asyncio, parametrize, parametrize, runtime | passed | 0.078 |
| `tests/runtime/test_public_contract.py::test_order_status_exact_field_set` | - | asyncio, runtime | passed | 0.064 |
| `tests/runtime/test_public_contract.py::test_protective_headers_everywhere` | - | asyncio, runtime | passed | 0.022 |
| `tests/runtime/test_public_contract.py::test_route_table_has_no_token_param` | - | asyncio, runtime | passed | 1.734 |
| `tests/runtime/test_public_contract.py::test_token_failures_indistinguishable` | - | asyncio, runtime | passed | 0.016 |
| `tests/runtime/test_public_pages.py::test_browse_categories_sort_and_collection_filters` | - | asyncio, runtime | passed | 0.452 |
| `tests/runtime/test_public_pages.py::test_browse_pagination_keeps_category_and_sort` | - | asyncio, runtime | passed | 0.845 |
| `tests/runtime/test_public_pages.py::test_browse_prices_require_one_currency` | - | asyncio, runtime | passed | 0.153 |
| `tests/runtime/test_public_pages.py::test_collection_and_merchant_pages` | - | asyncio, runtime | passed | 0.176 |
| `tests/runtime/test_public_pages.py::test_compact_fallback_and_gm_public_css` | - | asyncio, runtime | passed | 0.008 |
| `tests/runtime/test_public_pages.py::test_draft_preview_page_authed` | - | asyncio, runtime | passed | 0.100 |
| `tests/runtime/test_public_pages.py::test_draft_preview_requires_owner` | - | asyncio, runtime | passed | 0.061 |
| `tests/runtime/test_public_pages.py::test_embed_listing_drops_chrome_and_allows_same_origin_framing` | - | asyncio, runtime | passed | 0.135 |
| `tests/runtime/test_public_pages.py::test_hidden_and_sold_and_preorder_states` | - | asyncio, runtime | passed | 0.208 |
| `tests/runtime/test_public_pages.py::test_low_stock_and_sold_out_copy` | - | asyncio, runtime | passed | 0.252 |
| `tests/runtime/test_public_pages.py::test_not_found_and_invalid_d_tag` | - | asyncio, runtime | passed | 0.019 |
| `tests/runtime/test_public_pages.py::test_order_page_shell` | - | asyncio, runtime | passed | 0.009 |
| `tests/runtime/test_public_pages.py::test_price_slider_bounds_stay_stable_when_category_or_price_changes` | - | asyncio, runtime | passed | 0.172 |
| `tests/runtime/test_public_pages.py::test_prices_render_in_major_units` | - | asyncio, runtime | passed | 0.186 |
| `tests/runtime/test_public_pages.py::test_product_gallery_exposes_all_supported_images` | - | asyncio, runtime | passed | 0.082 |
| `tests/runtime/test_public_pages.py::test_product_page_headers_and_scoping` | - | asyncio, runtime | passed | 1.624 |
| `tests/runtime/test_public_pages.py::test_public_products_api_feeds_embed_widget` | - | asyncio, runtime | passed | 0.099 |
| `tests/runtime/test_public_pages.py::test_variable_parent_stock_is_children_sum` | - | asyncio, runtime | passed | 0.128 |
| `tests/runtime/test_relay_config_api.py::test_blossom_servers_configurable_with_https_only` | - | asyncio, runtime | passed | 0.043 |
| `tests/runtime/test_relay_config_api.py::test_catalog_relay_check` | - | asyncio, runtime | passed | 0.499 |
| `tests/runtime/test_relay_config_api.py::test_inbox_direction_requires_public_dns` | - | asyncio, runtime | passed | 0.028 |
| `tests/runtime/test_relay_config_api.py::test_outbox_listing_and_retry_routes` | - | asyncio, runtime | passed | 0.049 |
| `tests/runtime/test_relay_config_api.py::test_outbox_prune_history` | - | asyncio, runtime | passed | 0.052 |
| `tests/runtime/test_relay_config_api.py::test_relay_config_accepts_public_inbox_both` | - | asyncio, runtime | passed | 1.465 |
| `tests/runtime/test_relay_config_api.py::test_relay_config_rejects_invalid_and_duplicates` | - | asyncio, runtime | passed | 0.042 |
| `tests/runtime/test_release_a_journey.py::test_release_a_journey` | - | asyncio, runtime | passed | 1.958 |
| `tests/runtime/test_release_b_drills.py::test_auth_challenge_foreign_connection_never_signed` | - | asyncio, runtime | passed | 0.011 |
| `tests/runtime/test_release_b_drills.py::test_auth_challenge_oversize_never_signed` | - | asyncio, runtime | passed | 1.079 |
| `tests/runtime/test_release_b_drills.py::test_backlog_drains_in_bounded_batches` | - | asyncio, runtime | passed | 11.667 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[0.0.0.0]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[10.0.0.9]` | - | asyncio, parametrize, runtime | passed | 0.023 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[100.64.0.1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[127.0.0.1]` | - | asyncio, parametrize, runtime | passed | 0.024 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[169.254.1.1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[169.254.169.254]` | - | asyncio, parametrize, runtime | passed | 0.021 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[172.16.5.5]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[192.0.0.1]` | - | asyncio, parametrize, runtime | passed | 0.023 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[192.168.1.9]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[198.18.0.1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[2001:db8::1]` | - | asyncio, parametrize, runtime | passed | 0.023 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[224.0.0.1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[240.0.0.1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[::1]` | - | asyncio, parametrize, runtime | passed | 0.021 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[::]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[::ffff:10.0.0.1]` | - | asyncio, parametrize, runtime | passed | 0.023 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[fc00::1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[fd00::1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[fe80::1]` | - | asyncio, parametrize, runtime | passed | 0.022 |
| `tests/runtime/test_release_b_drills.py::test_egress_dns_matrix_rejects_non_public[ff02::1]` | - | asyncio, parametrize, runtime | passed | 0.023 |
| `tests/runtime/test_release_b_drills.py::test_egress_revalidation_on_reconnect` | - | asyncio, runtime | passed | 0.102 |
| `tests/runtime/test_release_b_drills.py::test_hard06_minute_rollover_keeps_backlog_cap` | - | asyncio, runtime | passed | 0.262 |
| `tests/runtime/test_release_b_drills.py::test_nip42_auth_challenge_roundtrip` | - | asyncio, runtime | passed | 2.643 |
| `tests/runtime/test_release_b_drills.py::test_paid_write_negative_ok_surfaces_and_retries` | - | asyncio, runtime | passed | 0.038 |
| `tests/runtime/test_release_b_drills.py::test_reference_gated_relay_environment` | - | asyncio, runtime, skipif | passed | 38.856 |
| `tests/runtime/test_release_b_drills.py::test_relay_wrap_rate_cap_drops_pre_decrypt` | - | asyncio, runtime | passed | 0.708 |
| `tests/runtime/test_release_b_journey.py::test_release_b_journey` | - | asyncio, runtime | passed | 2.126 |
| `tests/runtime/test_status_api.py::test_checkout_gated_by_readiness` | - | asyncio, runtime | passed | 0.107 |
| `tests/runtime/test_status_api.py::test_checkout_happy_path` | - | asyncio, runtime | passed | 0.090 |
| `tests/runtime/test_status_api.py::test_checkout_requires_idempotency_key` | - | asyncio, runtime | passed | 1.640 |
| `tests/runtime/test_status_api.py::test_email_opt_out` | - | asyncio, runtime | passed | 0.016 |
| `tests/runtime/test_status_api.py::test_order_status_after_confirmation` | - | asyncio, runtime | passed | 0.036 |
| `tests/runtime/test_status_api.py::test_order_status_token_contract` | - | asyncio, runtime | passed | 0.018 |
| `tests/runtime/test_storefront_modes.py::test_browse_only_pauses_catalog_render` | - | asyncio, runtime | passed | 0.057 |
| `tests/runtime/test_storefront_modes.py::test_collection_links_stay_out_of_shared_header` | - | asyncio, runtime | passed | 1.695 |
| `tests/runtime/test_storefront_modes.py::test_mode_api_shape_and_d10_gate` | - | asyncio, runtime | passed | 0.054 |
| `tests/runtime/test_storefront_modes.py::test_mode_matrix` | - | asyncio, runtime | passed | 0.824 |
| `tests/runtime/test_storefront_modes.py::test_mode_persists` | - | asyncio, runtime | passed | 0.120 |
| `tests/runtime/test_themes.py::test_advanced_token_allowlist` | - | asyncio, runtime | passed | 0.047 |
| `tests/runtime/test_themes.py::test_advanced_tokens_preserve_secondary_text_and_focus[tokens0]` | - | asyncio, parametrize, runtime | passed | 0.014 |
| `tests/runtime/test_themes.py::test_advanced_tokens_preserve_secondary_text_and_focus[tokens1]` | - | asyncio, parametrize, runtime | passed | 0.014 |
| `tests/runtime/test_themes.py::test_advanced_tokens_preserve_secondary_text_and_focus[tokens2]` | - | asyncio, parametrize, runtime | passed | 0.015 |
| `tests/runtime/test_themes.py::test_advanced_tokens_preserve_secondary_text_and_focus[tokens3]` | - | asyncio, parametrize, runtime | passed | 0.016 |
| `tests/runtime/test_themes.py::test_advanced_tokens_require_opt_in` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_themes.py::test_brand_basics_bounds` | - | asyncio, runtime | passed | 0.059 |
| `tests/runtime/test_themes.py::test_brand_logo_and_footer_copy` | - | asyncio, runtime | passed | 0.177 |
| `tests/runtime/test_themes.py::test_brand_name_overrides_display_name_in_hero` | - | asyncio, runtime | passed | 0.175 |
| `tests/runtime/test_themes.py::test_contrast_gate_blocks_failing_pairs` | - | asyncio, runtime | passed | 0.014 |
| `tests/runtime/test_themes.py::test_dark_scheme_tokens_meet_the_same_contrast_gate` | - | runtime | passed | 0.001 |
| `tests/runtime/test_themes.py::test_gallery_layout_is_opt_in_and_reaches_every_page` | - | asyncio, runtime | passed | 0.074 |
| `tests/runtime/test_themes.py::test_hero_renders_on_index_only_and_validates` | - | asyncio, runtime | passed | 0.323 |
| `tests/runtime/test_themes.py::test_invalid_preset_and_layout_rejected` | - | asyncio, runtime | passed | 0.029 |
| `tests/runtime/test_themes.py::test_layout_compact_fallback_in_css` | - | asyncio, runtime | passed | 0.004 |
| `tests/runtime/test_themes.py::test_preset_and_layout_persist` | - | asyncio, runtime | passed | 1.527 |
| `tests/runtime/test_themes.py::test_public_pages_carry_scheme_toggle_and_dark_tokens` | - | asyncio, runtime | passed | 0.026 |
| `tests/runtime/test_themes.py::test_reset_to_preset_clears_overrides` | - | asyncio, runtime | passed | 0.036 |
| `tests/runtime/test_themes.py::test_theme_reaches_public_page_only` | - | asyncio, runtime | passed | 0.264 |
| `tests/test_runtime_process_exit.py::test_hard07_db_install_orders_exit_cleanly[db-then-install]` | - | parametrize, runtime | passed | 4.361 |
| `tests/test_runtime_process_exit.py::test_hard07_db_install_orders_exit_cleanly[install-then-db]` | - | parametrize, runtime | passed | 3.981 |

## Failures

None.

## D-16 Disclosure — Subcheck Attribution

P0-02 subchecks are attributed as `sdk-internal` (blocking under D-13/D-16: an SDK-internal regression cannot be waived) or `admission-modeled` (extension-side defense in depth only).

| Test | Subcheck | Attribution |
| --- | --- | --- |
| `tests/qualification/test_p0_02_sdk_security.py::test_auth_flood_bounded_with_signing_paused` | paused-signing-auth-boundedness | sdk-internal |
| `tests/qualification/test_p0_02_sdk_security.py::test_invalid_events_rejected_before_trusted_processing` | invalid-event-rejection | sdk-internal |
| `tests/qualification/test_p0_02_sdk_security.py::test_known_id_repetition_admitted_exactly_once` | known-id-repetition-dedupe | admission-modeled |
| `tests/qualification/test_p0_02_sdk_security.py::test_oversized_nip44_input_rejected_with_bounded_cost` | oversized-nip44-input | sdk-internal |
| `tests/qualification/test_p0_02_sdk_security.py::test_tested_binary_identity_recorded_into_evidence_pins` | tested-binary-recorded | sdk-internal |

P0-02 SDK security/FFI/crypto status this run: **pass**.

## Platform Claims (D-12)

Blocking claims are Linux x86_64 and Linux ARM64 on SQLite AND PostgreSQL; macOS runs are advisory developer checks only. This report records only what THIS run's profile observed — see the CI artifacts below for the full blocking matrix.

## CI Artifacts

For each blocking profile (Linux x86_64 + SQLite, Linux x86_64 + PostgreSQL, Linux ARM64 + SQLite, Linux ARM64 + PostgreSQL) and the advisory macOS profile, CI uploads: the raw pytest output, the generated `evidence/REPORT.md`, and the canonical `evidence/manifest.json`.

External relay smoke is opt-in only (`GAMMA_QUAL_SMOKE_RELAY`) and is never the authoritative source of a pass.

## Approval Status (D-11)

Evidence record only — **owner approval of `PINS.md` remains explicitly pending** and is required before Phase 2. Nothing in this report constitutes approval.
