# TASK 6 EXTENSION: TransitFlow Optional Database Extensions

This file documents the Task 6 optional extensions implemented in this repository. It lists every Task 6 file modified or added, with the specific database tables, query functions, seed data, and agent/UI integration points.

## Extension Summary

The Task 6 work focuses on database-backed improvements to the TransitFlow assistant:

1. 10-minute seat locking and double-booking prevention.
2. Pending payment confirmation and timeout release.
3. Metro ticket purchase through the assistant.
4. User feedback submission and lookup.
5. Google OAuth user mapping into the relational user schema.
6. RAG policy seed-data extension for richer policy search.

RAG policy work is listed last because the main extension focus is booking, payment, feedback, and account database behaviour.

## 1. 10-Minute Seat Locking and Double-Booking Prevention

### Purpose

This extension prevents two users from selecting or booking the same national rail seat at the same time. A selected seat can be temporarily locked for 10 minutes before payment. During final booking, the code uses row-level locking and checks active reservations/locks before inserting the booking.

### Database Structures

Modified file: `databases/relational/schema.sql`

Tables/indexes/triggers:

- `seat_locks`
- `uq_active_seat_lock`
- `set_seat_lock_expiry()`
- `trg_set_seat_lock_expiry`
- `uq_active_seat_reservation`

Key schema:

```sql
CREATE TABLE seat_locks (
    lock_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    schedule_id TEXT NOT NULL,
    travel_date DATE NOT NULL,
    seat_pk BIGINT NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'released', 'confirmed')),
    CONSTRAINT fk_seat_locks_seat
        FOREIGN KEY (seat_pk) REFERENCES seat_layout_seats(seat_pk) ON DELETE CASCADE,
    CONSTRAINT fk_seat_locks_schedule
        FOREIGN KEY (schedule_id) REFERENCES service_schedules(schedule_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_active_seat_lock
ON seat_locks (schedule_id, travel_date, seat_pk)
WHERE status = 'pending';
```

### Functions

Modified file: `databases/relational/queries.py`

Functions:

- `query_available_seats(schedule_id, travel_date, fare_class)`
- `execute_lock_seat(user_id, schedule_id, travel_date, seat_id)`
- `execute_release_seat(lock_id, user_id)`
- `execute_booking(...)`

Important database operations:

- `query_available_seats()` excludes seats with active `seat_locks`.
- `execute_lock_seat()` deletes expired locks, checks active bookings, uses `SELECT ... FOR UPDATE`, and inserts into `seat_locks`.
- `execute_booking()` uses `SELECT ... FOR UPDATE`, checks active reservations, checks other users' active locks, inserts into `national_rail_bookings`, creates a pending payment, and upgrades the user's lock to `confirmed`.

### Agent Tools

Modified file: `skeleton/agent.py`

Tools:

- `lock_seat(schedule_id, travel_date, seat_id)`
- `release_seat(lock_id)`
- `make_booking(...)`

## 2. Pending Payment Confirmation and Timeout Release

### Purpose

Bookings and metro purchases now create a pending charge first. The user can confirm payment before the 10-minute payment window expires. If the window expires or the user cancels, the pending order is released and payment is marked failed.

### Database Structures

Modified file: `databases/relational/schema.sql`

Tables/views involved:

- `payment_transactions`
- `payment_instruments`
- `travel_orders`
- `travel_journeys`
- `national_rail_bookings`
- `metro_travel_history`
- `seat_locks`

### Functions

Modified file: `databases/relational/queries.py`

Functions:

- `cleanup_expired_pending_orders(user_id=None)`
- `_release_pending_order(cur, order_id)`
- `query_pending_orders(user_id)`
- `confirm_pending_payment(user_id, order_id)`
- `cancel_pending_order(user_id, order_id)`
- `query_payment_info(booking_id, user_id=None)`
- `query_user_payment_methods(user_id)`
- `execute_booking(...)`

Important database operations:

- `query_pending_orders()` reads pending payment rows and computes remaining seconds.
- `confirm_pending_payment()` locks the payment row with `FOR UPDATE OF pt`, checks expiry, and updates `payment_transactions.payment_status` to `paid`.
- `cancel_pending_order()` locks the order row with `FOR UPDATE OF to_tbl`, calls `_release_pending_order()`, and marks payment as failed.
- `_release_pending_order()` cancels rail/metro journey rows and releases related `seat_locks`.

### UI Integration

Modified file: `skeleton/ui.py`

Functions/UI elements:

- `_pending_order_updates(user_id)`
- `refresh_pending_orders(current_user, request)`
- `confirm_selected_pending_order(order_id, current_user, request)`
- `cancel_selected_pending_order(order_id, current_user, request)`
- pending-order dataframe, dropdown, confirm button, cancel button, and timer refresh.

## 3. Metro Ticket Purchase

### Purpose

The assistant can now create a real metro ticket purchase for a logged-in user instead of only showing metro schedules/fare information. The purchase creates a metro journey and a pending payment.

### Database Structures

Modified file: `databases/relational/schema.sql`

Tables/views involved:

- `metro_travel_history`
- `travel_orders`
- `travel_journeys`
- `payment_transactions`
- `ticket_type_network_rules`
- `metro_schedules`
- `metro_schedule_stops`

### Functions

Modified file: `databases/relational/queries.py`

Functions:

- `buy_metro_ticket(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, ticket_type='single', payment_instrument_id=None)`
- `_gen_unique_metro_trip_id(cur)`
- `_gen_unique_payment_id(cur)`

Important database operations:

- Validates the logged-in user through `registered_users`.
- Validates schedule and stop order through `metro_schedules` and `metro_schedule_stops`.
- Calculates fare through `query_metro_fare()`.
- Inserts the trip through `metro_travel_history`.
- Inserts the pending charge into `payment_transactions`.

### Agent Tools

Modified file: `skeleton/agent.py`

Tool:

- `buy_metro_ticket(schedule_id, origin_station_id, destination_station_id, travel_date, ticket_type?, payment_instrument_id?)`

## 4. Feedback Submission and Lookup

### Purpose

Logged-in users can submit feedback for their own national rail bookings or metro trips. The system prevents duplicate feedback for the same journey and prevents users from reviewing journeys they do not own.

### Database Structures

Modified file: `databases/relational/schema.sql`

Tables/views involved:

- `journey_feedback`
- `feedback`
- `travel_journeys`
- `travel_orders`

Key constraint:

```sql
UNIQUE (journey_id, user_id)
```

### Functions

Modified file: `databases/relational/queries.py`

Functions:

- `submit_feedback(user_id, journey_id, rating, comment)`
- `query_feedback(user_id, journey_id=None)`
- `_gen_unique_feedback_id(cur)`

Important database operations:

- `submit_feedback()` checks journey ownership through `travel_journeys` and `travel_orders`.
- It checks existing `journey_feedback` rows to prevent duplicate reviews.
- It inserts into the `feedback` compatibility view, which maps to `journey_feedback`.
- `query_feedback()` returns only feedback owned by the logged-in user.

### Agent Tools

Modified file: `skeleton/agent.py`

Tools:

- `submit_feedback(journey_id, rating, comment?)`
- `get_feedback(journey_id?)`

## 5. Google OAuth User Mapping

### Purpose

Google sign-in is mapped into the existing TransitFlow relational user model. Google accounts are linked to local `user_profiles` rows so authenticated users can use the same booking, payment, and feedback tools as password-based users.

### Database Structures

Modified file: `databases/relational/schema.sql`

Table/indexes:

- `user_oauth_accounts`
- `idx_user_oauth_accounts_user_id`
- `idx_user_oauth_accounts_email_lower`

Key schema:

```sql
CREATE TABLE user_oauth_accounts (
    provider          TEXT NOT NULL,
    provider_user_id  TEXT NOT NULL,
    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    email_verified    BOOLEAN NOT NULL DEFAULT FALSE,
    display_name      TEXT NULL,
    avatar_url        TEXT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at     TIMESTAMPTZ NULL,
    PRIMARY KEY (provider, provider_user_id),
    UNIQUE (provider, user_id)
);
```

### Functions

Modified file: `databases/relational/queries.py`

Functions:

- `login_or_create_google_user(provider_user_id, email, email_verified, display_name=None, avatar_url=None)`
- `complete_google_signup(provider_user_id, email, email_verified, display_name, avatar_url, year_of_birth)`

Important database operations:

- Looks up existing OAuth account mappings in `user_oauth_accounts`.
- Creates or updates local `user_profiles` rows.
- Inserts or updates Google provider mappings.
- Updates `last_login_at` on repeat sign-in.

### UI Integration

Modified file: `skeleton/ui.py`

Functions/routes:

- `google_login(request)`
- `google_callback(request)`
- `google_logout(request)`
- `complete_google_registration(year_of_birth, request)`

## 6. RAG Policy Seed-Data Extension

### Purpose

The policy knowledge base was expanded so semantic policy search can answer more realistic passenger-policy questions. The extended policy entries are embedded and stored in the `policy_documents` pgvector table by `skeleton/seed_vectors.py`.

### Database Structures

Modified file: `databases/relational/schema.sql`

Table/index:

- `policy_documents`
- `idx_policy_documents_category`

Modified file: `skeleton/seed_vectors.py`

Functions:

- `build_documents()`
- `seed()`

Important database operations:

- `build_documents()` reads the policy JSON files and builds document chunks.
- `seed()` embeds each document and calls `store_policy_document()`.
- `store_policy_document()` inserts into `policy_documents`.
- Marker records with `_task6_extension` are skipped so they do not become policy documents.

### Modified Seed Data Files

Modified files:

- `train-mock-data/refund_policy.json`
- `train-mock-data/ticket_types.json`
- `train-mock-data/booking_rules.json`
- `train-mock-data/travel_policies.json`

Added/extended policy content:

- Force majeure refund policy.
- Missed connection guarantee.
- Strike/disruption alternative transport reimbursement.
- Group fare tiers.
- Senior and student fare rules.
- Promotional fare rules.
- Lost property category handling.
- Accessibility, carer discount, and service animal rules.

## Task 6 Marker List

The following files contain both a file-level Task 6 marker near the top and
detailed Task 6 comments near the relevant function, table, trigger, or
seed-data operation:

- `databases/relational/schema.sql` uses a file-level `-- TASK 6 EXTENSION:` marker and detailed `-- TASK 6 EXTENSION:` comments above relevant tables, indexes, and triggers.
- `databases/relational/queries.py` uses a file-level `# TASK 6 EXTENSION:` marker and detailed `# TASK 6 EXTENSION:` comments above relevant query/write functions.
- `skeleton/agent.py` uses a file-level `# TASK 6 EXTENSION:` marker and a detailed `# TASK 6 EXTENSION:` comment above the Task 6 tool dispatch function.
- `skeleton/ui.py` uses a file-level `# TASK 6 EXTENSION:` marker and detailed `# TASK 6 EXTENSION:` comments above relevant pending-payment and Google OAuth UI functions.
- `skeleton/seed_vectors.py` uses a file-level `# TASK 6 EXTENSION:` marker and detailed `# TASK 6 EXTENSION:` comments above relevant RAG seed functions.
- `train-mock-data/refund_policy.json` uses `_task6_extension`.
- `train-mock-data/ticket_types.json` uses `_task6_extension`.
- `train-mock-data/booking_rules.json` uses `_task6_extension`.
- `train-mock-data/travel_policies.json` uses `_task6_extension`.
- `submit_file/TASK6.md` uses this top-level `# TASK 6 EXTENSION:` heading

SQL and JSON use syntax-safe marker formats because raw `#` comments would
break PostgreSQL SQL and JSON parsing.
