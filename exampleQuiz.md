# TransitFlow Example Quiz

This file lists example questions and expected answer points for the current TransitFlow agent.
For login-required examples, log in as Alice first unless another user is explicitly mentioned.

Alice test account:

```text
Email: alice.tan@email.com
Password: alice1990
User ID: RU01
```

Expected answers do not need to match word-for-word. They should include the listed facts or behavior.

---

## PostgreSQL / Relational Database

### National Rail Availability

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_national_rail_availability()` / `check_national_rail_availability` | No | `What national rail trains run from Central (NR01) to Stonehaven (NR05) on 2026-06-11?` | Lists matching national rail schedules, including `schedule_id`, direction/service type, first/last train time, stops travelled, total seats, booked seats, and available seats. |
| `query_national_rail_availability()` / `check_national_rail_availability` | No | `Are there national rail services from NR05 to NR01?` | Lists services only if the schedule serves NR05 before NR01. If no route exists in that order, says no matching service was found. |

### National Rail Fare

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_national_rail_fare()` / `get_national_rail_fare` | No | `What is the standard fare on NR_SCH01 for 4 stops?` | Shows the standard fare calculation for `NR_SCH01`, including base fare, per-stop rate, `stops_travelled = 4`, and total fare. |
| `query_national_rail_fare()` / `get_national_rail_fare` | No | `What is the first class fare on NR_SCH01 for 4 stops?` | Shows the first-class fare calculation for `NR_SCH01`. |

### National Rail Seat Selection

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_available_seats()` / `get_available_seats` | No | `Show available standard seats on NR_SCH01 for 2026-06-11.` | Lists available seats with `seat_id`, `coach`, row, column, and fare class. |
| `auto_select_adjacent_seats()` / `recommend_adjacent_seats` | No | `Recommend 2 adjacent standard seats on NR_SCH01 for 2026-06-11.` | Returns up to 2 selected seat IDs, preferring seats in the same coach and row. |

### National Rail Booking

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `execute_booking()` / `make_booking` | Yes, Alice | `Book a national rail ticket on schedule NR_SCH01 from NR01 to NR05 on 2026-06-11 in standard class. Pick any available seat.` | Creates a booking for Alice. The answer should include a new `booking_id`, `user_id = RU01`, schedule/origin/destination, selected seat, `status = confirmed`, and `payment_status = pending`. |
| `execute_booking()` / `make_booking` | No | Same booking question while logged out. | Refuses the booking and says the user must log in first. |
| `execute_booking()` / `make_booking` | Yes, Alice | `Book seat B05 on NR_SCH01 from NR01 to NR05 on 2026-06-11 in standard class.` | Either creates the booking with `payment_status = pending`, or says the seat is already booked / invalid for that fare class. |

### National Rail Cancellation

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `execute_cancellation()` / `cancel_booking` | Yes, Alice | `Cancel my booking BK-XXXXXX.` | If the booking belongs to Alice and is future `confirmed`, marks it cancelled and returns refund percent, admin fee, refund amount, optional refund payment ID, and policy note. |
| `execute_cancellation()` / `cancel_booking` | Yes, Alice | `Cancel booking BK002.` | If BK002 does not belong to Alice, answer should say the booking does not belong to this user. |
| `execute_cancellation()` / `cancel_booking` | Yes, Alice | `Cancel booking BK001.` | Since BK001 is completed/past data, answer should refuse because only confirmed future bookings can be cancelled. |

### Metro Schedules And Fare

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_metro_schedules()` / `check_metro_availability` | No | `Show me metro schedules from MS01 to MS05.` | Lists the metro schedule that serves MS01 before MS05, including `schedule_id`, line, direction, first/last train time, frequency, and stops travelled. |
| `query_metro_schedules()` / `check_metro_availability` | No | `Show me metro schedules from MS05 to MS01.` | Lists the opposite-direction schedule if available, or says no matching service exists in that order. |
| `query_metro_fare()` / `calculate_metro_fare` | No | `Calculate the metro fare on MS_SCH02 for 1 stop.` | Shows base fare, per-stop rate, stops travelled, and total fare. |
| `query_metro_fare()` / `get_metro_fare` | No | `How much does it cost to travel by metro from MS01 to MS05?` | Uses the matching metro schedule and returns the fare. For MS01 to MS05 on M1 southbound, the expected single fare is about `1.10 USD`. |

### Metro Ticket Purchase

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `buy_metro_ticket()` / `buy_metro_ticket` | Yes, Alice | `Buy me a metro single ticket on schedule MS_SCH02 from MS01 to MS05 on 2026-06-03.` | Creates a metro trip for Alice with a new `trip_id`, `user_id = RU01`, fare amount, `status = completed`, and `payment_status = pending`. Payment method should be `unspecified` if no payment instrument is provided. |
| `buy_metro_ticket()` / `buy_metro_ticket` | No | Same metro ticket question while logged out. | Refuses the purchase and says the user must log in first. |
| `buy_metro_ticket()` / `buy_metro_ticket` | Yes, Alice | `Buy me a metro single ticket on schedule MS_SCH01 from MS01 to MS05 on 2026-06-03.` | Should reject because `MS_SCH01` does not serve MS01 to MS05 in that order. |

### User Bookings And Payments

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_user_profile()` | UI/internal | Log in as Alice. | UI should show Alice as logged in. Internal profile lookup should return `RU01`, Alice's email, full name, active status, and birth date. |
| `query_user_bookings()` / `get_user_bookings` | Yes, Alice | `Show my bookings.` | Lists only Alice's national rail bookings and metro trips. Should not show other users' trips such as RU02-only records. |
| `query_payment_info()` / `get_payment_info` | Yes, Alice | `What is the payment status of BK001?` | Returns Alice's latest payment transaction for BK001, including payment ID, amount, method, status, and paid/processed time. |
| `query_payment_info()` / `get_payment_info` | Yes, Alice | `What is the payment status of BK-XXXXXX?` | For a newly created pending booking, returns `status = pending` and `method = unspecified` if no payment method was selected. |
| `query_user_payment_methods()` / `get_user_payment_methods` | Yes, Alice | `Show me my saved payment methods.` | Lists Alice's active saved payment methods without `token_ref`. If none are seeded, answer should say no saved payment methods were found. |

### Feedback

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `submit_feedback()` / `submit_feedback` | Yes, Alice | `I want to rate booking BK-XXXXXX 5 stars. The comment is: The seat was comfortable.` | If BK-XXXXXX belongs to Alice and has no previous feedback, creates feedback and returns feedback ID, rating, comment, and submitted status. |
| `submit_feedback()` / `submit_feedback` | Yes, Alice | `I want to rate booking BK001 5 stars. The comment is: Smooth trip.` | If Alice already submitted feedback for BK001, returns an error that feedback has already been submitted. |
| `query_feedback()` / `get_feedback` | Yes, Alice | `Show me all feedback I have submitted.` | Lists only Alice's feedback records, including booking/trip reference, rating, comment, and submitted time. |
| `query_feedback()` / `get_feedback` | Yes, Alice | `Show my feedback for MT009.` | Shows Alice's feedback for MT009 if present, or no records if none exists. |

### Login Audit

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_my_login_audit()` / `get_my_login_history` | Yes, Alice | `Show my recent login history.` | Lists Alice's own recent login audit results and occurred times only. It must not expose `ip_hash` or `user_agent_hash`, and must not show other users' audit logs. |
| `query_my_login_audit()` / `get_my_login_history` | Yes, Alice | `Show me all users' login audit logs.` | Should refuse or restrict to Alice's own login history. It should not disclose other users' logs. |

### Authentication And Account Recovery

These functions are normally exercised through the Login/Register/Forgot Password UI, not through general chat tools.

| Function | Login | Example UI action / question | Expected result |
| --- | --- | --- | --- |
| `register_user()` | No | Register a new password user with email, first name, surname, birth year, password, secret question, and answer. | Creates a new active user, stores Argon2 password hash and Argon2 recovery answer hash, and returns a new user ID. Duplicate email should fail. |
| `login_user()` | No | Log in with `alice.tan@email.com / alice1990`. | Login succeeds and records a successful audit row. Wrong password should fail and record a failed audit row. |
| `get_user_secret_question()` | No | Start forgot password for Alice's email. | Returns Alice's stored secret question if the account exists. |
| `verify_secret_answer()` | No | Answer Alice's recovery question. | Returns true only when the answer matches the stored Argon2 hash. |
| `update_password()` | No | Reset password after a correct recovery answer. | Updates the password hash. Empty new password should fail. |
| `login_or_create_google_user()` | Google OAuth | Continue with Google using an existing linked Google account or existing email. | Existing OAuth user logs in; existing local email links Google; new Google-only user is staged for birth-year completion. |
| `complete_google_signup()` | Google OAuth | Complete Google signup by entering birth year. | Creates or reuses a local user and stores the Google OAuth mapping. Invalid birth year fails. |

### RAG / Policy Search

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_policy_vector_search()` / `search_policy` | No | `My train was delayed 45 minutes. What compensation am I entitled to?` | Retrieves relevant policy document chunks and answers using only policy data. Should mention delay compensation rules if present in the RAG documents. |
| `query_policy_vector_search()` / `search_policy` | No | `What is the company policy on travelling with a bicycle on national rail?` | Retrieves bicycle/travel policy chunks and answers with the policy details. |
| `store_policy_document()` | Seed/internal | Run `skeleton/seed_vectors.py`. | Inserts embedded policy chunks into `policy_documents`. This is not a chat question. |

### Relational Helper Functions

These are implementation helpers and are not intended to be asked as UI questions.

| Function | Purpose | Expected behavior |
| --- | --- | --- |
| `example_query()` | PostgreSQL connection smoke test. | Returns the current database name. |
| `_connect()` | Open PostgreSQL connection. | Returns an autocommit connection for read helpers. |
| `_gen_booking_id()` / `_gen_unique_booking_id()` | Generate booking IDs. | Produces `BK-XXXXXX` and retries until unused. |
| `_gen_payment_id()` / `_gen_unique_payment_id()` | Generate payment IDs. | Produces `PM-XXXXXX` and retries until unused. |
| `_gen_unique_metro_trip_id()` | Generate metro trip IDs. | Produces `MT-XXXXXX` and retries until unused. |
| `_gen_unique_feedback_id()` | Generate feedback IDs. | Produces `FB-XXXXXX` and retries until unused. |
| `_gen_user_id()` | Generate local user IDs. | Produces random `RU######`. |
| `_to_jsonable()` | Convert DB rows for JSON. | Converts dates/times/decimals into JSON-safe values. |
| `_validate_birth_year()` | Validate account birth year. | Accepts years from 1900 to current year; rejects invalid input. |

---

## Neo4j / Graph Database

### Fastest, Cheapest, And Cross-Network Routes

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_shortest_route()` / `find_route` | No | `What is the fastest route from MS01 to MS14?` | Returns a found route with station sequence, relationship legs, and total travel time in minutes. |
| `query_cheapest_route()` / `find_route` | No | `What is the cheapest route from NR01 to NR05?` | Returns a found route with station sequence and total estimated fare. |
| `query_interchange_path()` / `find_route` | No | `How do I get from Central Square (MS01) to Stonehaven (NR05)?` | Returns a cross-network route from metro to rail, including station sequence, interchange points, and total time. |

### Alternative Routes And Delay Ripple

| Function / Tool | Login | Example question | Expected answer |
| --- | --- | --- | --- |
| `query_alternative_routes()` / `find_alternative_routes` | No | `If Old Town station (NR03) is closed, what alternative routes exist from NR01 to NR05?` | Returns up to several routes from NR01 to NR05 that do not include NR03, ordered by travel time. |
| `query_delay_ripple()` / `get_delay_ripple` | No | `Show which stations are affected within 2 hops if NR03 is delayed.` | Lists nearby affected stations with station ID, name, hops away, and affected lines. |

### Graph Direct-Only Functions

| Function | Login | Example direct test | Expected result |
| --- | --- | --- | --- |
| `example_count_nodes()` | No | Run the function directly in Python. | Returns the total number of nodes in Neo4j. |
| `query_station_connections()` | No | Direct call: `query_station_connections("MS01")`. | Lists one-hop outgoing connections from MS01 with connected station, relationship type, and travel/transfer time. |

---

## Recommended End-To-End Test Set

Use this small set when you want a quick demo that covers all database types.

1. Relational read:
   ```text
   What national rail trains run from Central (NR01) to Stonehaven (NR05) on 2026-06-11?
   ```

2. Graph route:
   ```text
   What is the fastest route from MS01 to MS14?
   ```

3. RAG policy:
   ```text
   My train was delayed 45 minutes. What compensation am I entitled to?
   ```

4. Alice personal booking history:
   ```text
   Show my bookings.
   ```

5. Alice pending metro purchase:
   ```text
   Buy me a metro single ticket on schedule MS_SCH02 from MS01 to MS05 on 2026-06-03.
   ```

6. Alice pending national rail booking:
   ```text
   Book a national rail ticket on schedule NR_SCH01 from NR01 to NR05 on 2026-06-11 in standard class. Pick any available seat.
   ```

7. Alice payment status:
   ```text
   What is the payment status of BK-XXXXXX?
   ```

Replace `BK-XXXXXX` with the booking ID returned by step 6.
