# AI Session Context - TransitFlow

**How to use this file:**
At the start of every AI coding session, paste the full contents of this file as your first message to the AI assistant. This file is a team contract: generated code must fit the current architecture instead of inventing a parallel design.

**Current status:**
The project is no longer at the workshop/TODO stage. Relational schema, graph schema, vector/RAG seeding, agent tool routing, booking flows, payment lookup, feedback, login audit, OAuth user creation, and temporary seat locking are already implemented. Future edits should preserve this structure unless the team explicitly agrees to change it.

---

## Project Overview

TransitFlow is a Python AI chat assistant for a fictional dual-network transit operator.

It uses:

- PostgreSQL for relational data and pgvector policy search
- Neo4j for route graph queries
- A Gradio web UI
- Gemini or Ollama for chat/tool routing and embeddings

The assistant answers schedules, fares, routes, bookings, cancellations, payments, feedback, login history, and policy/RAG questions by routing natural language requests to Python query functions.

---

## Tech Stack

- Language: Python 3.11+
- Relational DB: PostgreSQL via `psycopg2` and `RealDictCursor`
- Vector DB: PostgreSQL `pgvector`, table `policy_documents`
- Graph DB: Neo4j via the `neo4j` Python driver and APOC Dijkstra
- UI: Gradio in `skeleton/ui.py`
- Agent: `skeleton/agent.py`
- LLM provider abstraction: `skeleton/llm_provider.py`
- Config: `.env` loaded through `skeleton/config.py`

---

## Architecture Rules

- Preserve the current module boundaries.
- Relational work belongs in `databases/relational/schema.sql` and `databases/relational/queries.py`.
- Graph work belongs in `skeleton/seed_neo4j.py` and `databases/graph/queries.py`.
- Agent tool exposure belongs in `skeleton/agent.py`.
- RAG content comes from policy JSON files in `train-mock-data/` and is seeded by `skeleton/seed_vectors.py`.
- Do not create a second schema or a second query layer to bypass the current design.
- Do not hand-format each tool result in the agent unless routing truly requires it. The agent already normalises tool JSON through its generic result pipeline.
- User-specific tools must use the logged-in user identity from the UI/session. Do not ask the LLM to provide user IDs or emails for protected actions.

---

## Coding Conventions

- Python names and SQL identifiers use `snake_case`.
- Use type hints on query functions.
- Read-only functions should return `list[dict]`, `dict`, or `Optional[dict]` as documented.
- Empty read results should return `[]` or `None`, not raise a "not found" exception.
- SQL user inputs must use `%s` placeholders. Do not format user input directly into SQL.
- Cypher user inputs must use Neo4j parameters. Do not interpolate user input into Cypher strings.
- Use `_connect()` in relational queries.
- Use the module-level Neo4j driver/session pattern in graph queries.
- Keep comments useful and short; avoid comments that only repeat the code.

Relational query pattern:

```python
with _connect() as conn:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT ... WHERE id = %s", (value,))
        return [dict(row) for row in cur.fetchall()]
```

Graph query pattern:

```python
with _DRIVER.session() as session:
    result = session.run("MATCH (n {station_id: $station_id}) RETURN n", station_id=station_id)
    return [dict(record) for record in result]
```

---

## Relational Schema - Current Implementation

Canonical source: `databases/relational/schema.sql`.

The schema is implemented as a normalised core plus compatibility views for existing query code.

### Core tables

- Network data: `lines`, `stations`, `station_lines`, `station_transfers`, `station_adjacencies`
- Schedules/stops: `service_schedules`, `schedule_operating_days`, `schedule_stations`
- Fares/tickets: `ticket_types`, `ticket_type_network_rules`, `schedule_fares`
- Seat layouts: `seat_layouts`, `seat_layout_coaches`, `seat_layout_seats`
- Users/auth: `user_profiles`, `user_auth_credentials`, `user_recovery_factors`, `auth_login_audit`, `user_oauth_accounts`
- Orders/journeys: `travel_orders`, `travel_journeys`, `rail_journey_reservations`
- Seat locking: `seat_locks`
- Payments: `payment_instruments`, `payment_transactions`
- Feedback: `journey_feedback`
- RAG: `policy_documents`

### Compatibility views

These views keep older/query-facing names stable:

- `metro_stations`
- `national_rail_stations`
- `metro_schedules`
- `metro_schedule_stops`
- `national_rail_schedules`
- `national_rail_schedule_stops`
- `national_rail_fare_classes`
- `national_rail_seat_layouts`
- `national_rail_seats`
- `registered_users`
- `user_credentials`
- `national_rail_bookings`
- `metro_travel_history`
- `payments`
- `feedback`

Some compatibility views have `INSTEAD OF` triggers so existing insert/update query code can write through the view while the database stores data in normalised tables.

### Important relational decisions

- Text business keys are used for externally meaningful IDs such as stations, schedules, users, orders, journeys, payments, and layouts.
- Surrogate `BIGSERIAL` keys are used for internal/high-write relation rows such as adjacencies, seats, coaches, and login audit.
- Master data uses soft delete via `is_active`.
- Dependent tables use explicit `ON DELETE CASCADE`, `ON DELETE RESTRICT`, or `ON DELETE SET NULL`.
- National rail seat reservations are protected by a partial unique index on active reservations.
- Temporary seat locks use `seat_locks`, a partial unique index on pending locks, and a trigger that sets a 10-minute expiry.
- `policy_documents.embedding` uses unconstrained `VECTOR` so the table can support either Ollama or Gemini embeddings. If a fixed production index is added later, the provider dimension must be standardised first.

---

## Graph Schema - Current Implementation

Canonical sources:

- `skeleton/seed_neo4j.py`
- `databases/graph/queries.py`

### Node labels

- `MetroStation`
- `NationalRailStation`

### Node properties

- `station_id`
- `name`
- `lines`

### Relationship types

- `METRO_LINK`
- `RAIL_LINK`
- `INTERCHANGE_TO`

### Relationship properties

- `line`
- `travel_time_min`
- `transfer_time_min`
- `standard_fare_usd`
- `first_fare_usd`

### Graph behaviour

- Metro and rail stations are seeded from `train-mock-data/metro_stations.json` and `train-mock-data/national_rail_stations.json`.
- Metro and rail adjacency relationships are directional; reverse travel depends on reverse edges from the seed data.
- Interchange links are created both ways between mapped metro and national rail stations.
- Constraints enforce unique `station_id` for both station labels.
- Route queries use APOC Dijkstra over `METRO_LINK|RAIL_LINK|INTERCHANGE_TO`.

---

## Vector/RAG Implementation

Canonical sources:

- `skeleton/seed_vectors.py`
- `databases/relational/queries.py`
- policy JSON files in `train-mock-data/`

Current RAG policy files:

- `refund_policy.json`
- `ticket_types.json`
- `booking_rules.json`
- `travel_policies.json`

Workflow:

1. `skeleton/seed_vectors.py` reads policy entries from the JSON files.
2. The active LLM provider creates embeddings through `llm.embed(...)`.
3. `store_policy_document(...)` inserts title, category, content, embedding, and source file into `policy_documents`.
4. The agent uses `search_policy`.
5. `query_policy_vector_search(...)` runs cosine similarity using pgvector `<=>`.
6. Retrieved policy chunks are passed back to the LLM as database context.

Important:

- If the team switches between Ollama and Gemini, reset/reseed vector data. Stored vectors must match the provider used for queries.
- Do not edit `query_policy_vector_search` or `store_policy_document` unless the team is intentionally changing the RAG architecture.

---

## Relational Function Signatures - Current Implementation

Canonical source: `databases/relational/queries.py`.

```python
def query_national_rail_availability(origin_id: str, destination_id: str, travel_date: Optional[str] = None) -> list[dict]: ...
def query_national_rail_fare(schedule_id: str, fare_class: str, stops_travelled: int) -> Optional[dict]: ...
def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]: ...
def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]: ...
def query_available_seats(schedule_id: str, travel_date: str, fare_class: str) -> list[dict]: ...
def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]: ...

def query_user_profile(user_email: str) -> Optional[dict]: ...
def query_user_bookings(user_email: str) -> dict: ...
def query_payment_info(booking_id: str, user_id: str | None = None) -> Optional[dict]: ...
def query_pending_orders(user_id: str) -> list[dict]: ...
def query_user_payment_methods(user_id: str) -> list[dict]: ...
def submit_feedback(user_id: str, journey_id: str, rating: int, comment: str | None) -> tuple[bool, dict | str]: ...
def query_feedback(user_id: str, journey_id: str | None = None) -> list[dict]: ...
def buy_metro_ticket(user_id: str, schedule_id: str, origin_station_id: str, destination_station_id: str, travel_date: str, ticket_type: str = "single", payment_instrument_id: str | None = None) -> tuple[bool, dict | str]: ...
def query_my_login_audit(user_id: str, limit: int = 10) -> list[dict]: ...

def execute_booking_by_route(user_id: str, origin_station_id: str, destination_station_id: str, travel_date: str, fare_class: str, seat_id: str = "any", ticket_type: str = "single", payment_instrument_id: str | None = None) -> tuple[bool, dict | str]: ...
def execute_lock_seat(user_id: str, schedule_id: str, travel_date: str, seat_id: str) -> tuple[bool, str]: ...
def execute_release_seat(lock_id: str, user_id: str) -> bool: ...
def execute_booking(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, fare_class, seat_id, ticket_type="single", payment_instrument_id=None) -> tuple[bool, dict | str]: ...
def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]: ...

def register_user(email, first_name, surname, year_of_birth, password, secret_question, secret_answer) -> tuple[bool, str]: ...
def login_user(email: str, password: str) -> Optional[dict]: ...
def login_or_create_google_user(provider_user_id: str, email: str, email_verified: bool, display_name: str | None = None, avatar_url: str | None = None) -> dict: ...
def get_user_secret_question(email: str) -> Optional[str]: ...
def verify_secret_answer(email: str, answer: str) -> bool: ...
def update_password(email: str, new_password: str) -> bool: ...

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]: ...
def store_policy_document(title: str, category: str, content: str, embedding: list[float], source_file: str = "") -> int: ...
```

---

## Graph Function Signatures - Current Implementation

Canonical source: `databases/graph/queries.py`.

```python
def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> dict: ...
def query_cheapest_route(origin_id: str, destination_id: str, network: str = "auto", fare_class: str = "standard") -> dict: ...
def query_alternative_routes(origin_id: str, destination_id: str, avoid_station_id: str, network: str = "auto", max_routes: int = 3) -> list[list[dict]]: ...
def query_interchange_path(origin_id: str, destination_id: str) -> dict: ...
def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]: ...
def query_station_connections(station_id: str) -> list[dict]: ...
```

---

## Agent Tools - Current Implementation

Canonical source: `skeleton/agent.py`.

Registered tool names:

- `find_route`
- `check_national_rail_availability`
- `get_national_rail_fare`
- `check_metro_availability`
- `calculate_metro_fare`
- `get_metro_fare`
- `get_available_seats`
- `recommend_adjacent_seats`
- `make_booking`
- `make_booking_by_route`
- `cancel_booking`
- `get_user_bookings`
- `get_payment_info`
- `get_user_payment_methods`
- `submit_feedback`
- `get_feedback`
- `buy_metro_ticket`
- `get_my_login_history`
- `search_policy`
- `find_alternative_routes`
- `get_delay_ripple`
- `lock_seat`
- `release_seat`

Agent routing details:

- Station names are normalised to IDs through `_STATION_INDEX` and `_inject_station_ids`.
- Policy/RAG intent has explicit routing priority to `search_policy`.
- Delay ripple intent has deterministic fallback routing to `get_delay_ripple`.
- Login-protected tools resolve the current user's profile internally.
- `TOOLS_SCHEMA` must be updated whenever tools are added/renamed for Gemini routing.
- Ollama tool hints must be updated when a new intent is easy for small local models to misroute.

---

## Seed / Reset Order

When schema or seed data changes:

```bash
docker compose down -v
docker compose up -d
python skeleton/seed_postgres.py
python skeleton/seed_neo4j.py
python skeleton/seed_vectors.py
```

Use `python3` instead of `python` on systems where needed.

Important:

- `docker compose down -v` wipes PostgreSQL and Neo4j Docker volumes.
- After a reset, re-run both Neo4j and vector seed scripts.
- If only policy JSON changes, re-run `python skeleton/seed_vectors.py`.
- If only graph station adjacency data changes, re-run `python skeleton/seed_neo4j.py`.

---

## Team Decisions Log

- Relational schema is normalised around lines, stations, schedules, fares, users, orders, journeys, reservations, payments, feedback, and policy documents.
- Compatibility views preserve the original teaching/query names while allowing a stronger internal schema.
- Write compatibility for booking/travel/payment/feedback views is handled through `INSTEAD OF` triggers where needed.
- Seat reservation integrity uses partial unique indexes for active reservations and pending seat locks.
- Temporary seat locks expire after 10 minutes through a database trigger.
- User credentials are separated from profile data, and login audit does not expose IP/user-agent hashes through user-facing queries.
- Google OAuth maps external Google identities to local TransitFlow users through `user_oauth_accounts`.
- Graph route finding uses Neo4j station nodes and weighted relationships instead of deriving routes from relational schedules.
- RAG policy answers use pgvector semantic search over seeded policy JSON documents.

---

## Good Prompts For Future Sessions

### Schema-safe change prompt

```text
Please inspect databases/relational/schema.sql and databases/relational/queries.py first.
Keep the current normalised schema + compatibility view architecture.
Do not introduce duplicate tables or bypass existing views/triggers.
Then make the smallest change needed for: <task>.
```

### Agent tool change prompt

```text
Please inspect skeleton/agent.py and the target query function first.
Register the tool using the existing TOOLS, TOOLS_SCHEMA, _execute_tool, and fallback-routing patterns.
Do not add custom result formatting unless the existing _normalise_result pipeline cannot represent the return value.
```
