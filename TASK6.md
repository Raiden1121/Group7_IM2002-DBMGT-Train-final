# TASK 6 EXTENSION: Modified Files and Database Objects

This file lists every file modified or added for Task 6, with the specific table, index, trigger, function, and tool names required for grading.

## `databases/relational/schema.sql`

Tables / views / indexes / triggers involved:

- `seat_locks`
- `uq_active_seat_lock`
- `set_seat_lock_expiry()`
- `trg_set_seat_lock_expiry`
- `uq_active_seat_reservation`
- `payment_transactions`
- `payment_instruments`
- `travel_orders`
- `travel_journeys`
- `rail_journey_reservations`
- `national_rail_bookings`
- `metro_travel_history`
- `journey_feedback`
- `feedback`
- `user_oauth_accounts`
- `idx_user_oauth_accounts_user_id`
- `idx_user_oauth_accounts_email_lower`
- `auth_login_audit`
- `policy_documents`
- `idx_policy_documents_category`

## `databases/relational/queries.py`

Functions involved:

- `query_available_seats(schedule_id, travel_date, fare_class)`
- `execute_lock_seat(user_id, schedule_id, travel_date, seat_id)`
- `execute_release_seat(lock_id, user_id)`
- `execute_booking(...)`
- `execute_booking_by_route(...)`
- `query_payment_info(booking_id, user_id=None)`
- `cleanup_expired_pending_orders(user_id=None)`
- `_release_pending_order(cur, order_id)`
- `query_pending_orders(user_id)`
- `confirm_pending_payment(user_id, order_id)`
- `cancel_pending_order(user_id, order_id)`
- `query_user_payment_methods(user_id)`
- `buy_metro_ticket(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, ticket_type='single', payment_instrument_id=None)`
- `_gen_unique_metro_trip_id(cur)`
- `_gen_unique_payment_id(cur)`
- `submit_feedback(user_id, journey_id, rating, comment)`
- `query_feedback(user_id, journey_id=None)`
- `_gen_unique_feedback_id(cur)`
- `login_user(email, password)`
- `query_my_login_audit(user_id, limit=10)`
- `login_or_create_google_user(provider_user_id, email, email_verified, display_name=None, avatar_url=None)`
- `complete_google_signup(provider_user_id, email, email_verified, display_name, avatar_url, year_of_birth)`
- `query_policy_vector_search(embedding, top_k=VECTOR_TOP_K)`
- `store_policy_document(title, category, content, embedding, source_file='')`

## `skeleton/agent.py`

Assistant tools / dispatch paths involved:

- `lock_seat(schedule_id, travel_date, seat_id)`
- `release_seat(lock_id)`
- `make_booking(...)`
- `make_booking_by_route(...)`
- `buy_metro_ticket(schedule_id, origin_station_id, destination_station_id, travel_date, ticket_type?, payment_instrument_id?)`
- `submit_feedback(journey_id, rating, comment?)`
- `get_feedback(journey_id?)`
- `get_payment_info(booking_id)`
- `get_my_login_history(limit?)`
- `search_policy(query)`

## `skeleton/ui.py`

UI functions / routes involved:

- `_pending_order_updates(user_id)`
- `refresh_pending_orders(current_user, request)`
- `confirm_selected_pending_order(order_id, current_user, request)`
- `cancel_selected_pending_order(order_id, current_user, request)`
- `google_login(request)`
- `google_callback(request)`
- `google_logout(request)`
- `complete_google_registration(year_of_birth, request)`

## `skeleton/seed_vectors.py`

Functions involved:

- `build_documents()`
- `seed()`

## `train-mock-data/refund_policy.json`

Task 6 seed-data changes:

- `_task6_extension` marker
- Force majeure refund policy
- Missed connection guarantee
- Strike / disruption reimbursement policy

## `train-mock-data/ticket_types.json`

Task 6 seed-data changes:

- `_task6_extension` marker
- Group fare tier rules
- Extended ticket conditions for RAG policy search

## `train-mock-data/booking_rules.json`

Task 6 seed-data changes:

- `_task6_extension` marker
- Senior fare rules
- Student fare rules
- Group booking and fare eligibility rules
- Early Bird / Off-Peak promotional fare rules

## `train-mock-data/travel_policies.json`

Task 6 seed-data changes:

- `_task6_extension` marker
- Lost property category handling
- Accessibility rules
- Carer discount rules
- Service animal rules

## `submit_file/TASK6.md`

Section 7 style Task 6 write-up containing:

- motivation
- database changes
- example queries
- testing evidence

## Marker Formats

- SQL files use `-- TASK 6 EXTENSION:`.
- Python files use `# TASK 6 EXTENSION:`.
- JSON files use `_task6_extension` because JSON does not support comments.
