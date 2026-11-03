# Seller review verification — 2026-11-03

Local PostgreSQL 16, disposable `yefhamak_test` at 127.0.0.1:5433.
Ran `python -m tests.integration` with explicit TEST_DATABASE_URL: **25 passed**
in 4.286s. Includes the previous 14 tests plus these 11 new tests in
`tests/integration/test_postgres.py`:

1. `test_seller_confirm_consumes_multi_item_stock_once` — two quantities across two variants, repeated confirmation, correct stock/reserved counts and preserved totals/items.
2. `test_seller_cancel_pending_releases_all_holds_once` — repeated pending cancellation restores availability, releases linked holds, expiry cannot release again, another customer can reserve the last item.
3. `test_seller_cancel_confirmed_restocks_once_preserving_other_holds` — confirm then repeated cancel restores sold stock while retaining another customer's reservation.
4. `test_cancelled_order_cannot_be_confirmed_or_reopened` — terminal cancellation and unsupported pending transition reject without inventory changes.
5. `test_review_rejects_other_seller_and_missing_orders` — both actions refuse another seller's order or unknown ID without side effects.
6. `test_concurrent_seller_confirmation_consumes_stock_once` — two independent sessions confirm together; both finish successfully, only one deduction.
7. `test_concurrent_seller_cancellation_returns_stock_once` — two sessions cancel a confirmed order together; only one restock.
8. `test_concurrent_confirm_and_cancel_leave_cancelled_stock_available` — confirmation either wins first or receives conflict; final cancellation restores stock.
9. `test_review_inventory_failure_rolls_back_every_item_and_status` — force failure on the last variant; both confirm/cancel roll back earlier variant changes, status and holds.
10. `test_review_refuses_missing_or_mismatched_linked_holds` — detached hold makes item/reservation totals inconsistent; review is rejected without stock change.
11. `test_review_http_auth_status_codes_and_persistence` — real DB HTTP requests: missing/wrong key 401; repeat confirm/cancel 200; confirm cancelled 409; missing ID 404; invalid UUID 422; saved status and decimal total.

Other verification: **41 offline backend tests**, **14 frontend tests**, frontend
production build and TypeScript all passed. Browser used a temporary backend on
8010 pointed at the test DB and built frontend on 3000: pending details -> confirm
-> confirmed -> cancellation review -> cancelled; no further actions displayed;
list showed cancelled; Pending filter showed zero results. Screenshot:
`2026-11-03-seller-order-ui.png`.

Temporary servers stopped. No live provider calls, messages to customers, Neon
access, or local development database reset. The test database is retained for
future disposable runs; each suite run resets its tables. No schema migration.
