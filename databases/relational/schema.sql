-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
-- TASK 6 EXTENSION:
-- This schema includes Task 6 database structures for OAuth user mapping,
-- temporary seat locks, pending payment workflows, journey feedback, and
-- pgvector policy storage. Detailed comments are placed near each structure.
--
--  Start from the mock data in train-mock-data/:
--    metro_stations.json, national_rail_stations.json
--    metro_schedules.json, national_rail_schedules.json
--    national_rail_seat_layouts.json
--    registered_users.json
--    bookings.json, metro_travel_history.json
--    payments.json, feedback.json
--
--  Think about:
--    - What tables do you need?
--    - What columns and data types?
--    - Which fields are primary keys? Which are foreign keys?
--    - What constraints make sense?
--
--  Apply your schema with:
--    docker-compose down -v && docker-compose up -d
-- ============================================================
-- 0529 ver.
-- Compatible with the current agent.py / databases/relational/queries.py table names.
-- Design goal:
--   1. Keep the Python query layer working with names such as metro_schedules,
--      national_rail_schedules, national_rail_bookings, registered_users, etc.
--   2. Still keep the core structure reasonably normalized:
--      lines / stations / service_schedules / schedule_stations / schedule_fares
--      plus seat layout tables and policy/refund support tables.
--
-- 
-- ===========================================================================
-- DATABASE DESIGN DECISIONS
-- ===========================================================================
--
-- 1. Primary Key Choices:
--    - Tables using TEXT for PKs (e.g., stations, lines, service_schedules, user_profiles, travel_orders, travel_journeys, payment_instruments, payment_transactions):
--      * Why: These are natural keys or standard business codes from external systems (like station code "MS01" or order ID "BK-A3F9D1").
--      * Pros: It makes logs(日誌) and debugging way easier to read, simplifies cross-system API integration, and avoids the gaps you sometimes get with auto-incrementing numbers.
--    - Tables using BIGSERIAL / SERIAL for PKs (e.g., station_adjacencies, seat_layout_coaches, seat_layout_seats, auth_login_audit):
--      * Why: These tables handle high-frequency writes, are system-generated, and mostly just track internal relations or audit logs.
--      * Pros: Using surrogate keys keeps index sizes small, boosts JOIN query speeds and insert performance, and saves us from having to generate unique IDs on the app side.
--
-- 2. Delete Strategy Decisions:
--    - We’re using a "Hybrid Delete Strategy" to manage data:
--      - Soft Delete - is_active BOOLEAN:
--        * Where we use it: Core master data and main entities like lines, stations, service_schedules, ticket_types, user_profiles, and payment_instruments.
--        * Why: Even if a line or station gets deactivated, we still need to keep old orders and journeys around forever for historical reconciliation(對帳), refunds, and audits(審計).
--      - Hard Delete - ON DELETE CASCADE / RESTRICT:
--        * Where we use it: Dependent child tables that don't have their own independent lifecycle, like station_lines, schedule_operating_days, schedule_stations, seat_layouts, user_auth_credentials, and user_recovery_factors.
--        * Why: If the parent entity is gone, these dependent records don't make sense on their own. Nuking them with ON DELETE CASCADE keeps our referential integrity clean and prevents leftover junk data.
--
-- 3. Foreign Key Cascade Behaviour:
--    - All foreign keys must explicitly state their cascade behavior:
--      - ON DELETE CASCADE: Used for weak/dependent tables (like seat selections or coach layouts). If the parent record is deleted, the child records go away with it.
--      - ON DELETE RESTRICT: Used for relationships between strong entities (like a journey referencing a station or schedule). If a station is currently linked to a journey, the system will block you from deleting that station. This keeps us safe from dangling references.
--      - ON DELETE SET NULL: Used for loosely coupled tables like logs or external transactions. For example, if a payment instrument is removed, we just set the instrument field in the transaction log to NULL so we can still keep the transaction amount for auditing.
--
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Drop views first because they depend on base tables
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS user_credentials CASCADE;
DROP VIEW IF EXISTS registered_users CASCADE;
DROP VIEW IF EXISTS metro_travel_history CASCADE;
DROP VIEW IF EXISTS national_rail_bookings CASCADE;
DROP VIEW IF EXISTS payments CASCADE;
DROP VIEW IF EXISTS feedback CASCADE;
DROP VIEW IF EXISTS national_rail_seats CASCADE;
DROP VIEW IF EXISTS national_rail_seat_layouts CASCADE;
DROP VIEW IF EXISTS national_rail_fare_classes CASCADE;
DROP VIEW IF EXISTS national_rail_schedule_stops CASCADE;
DROP VIEW IF EXISTS national_rail_schedules CASCADE;
DROP VIEW IF EXISTS metro_schedule_stops CASCADE;
DROP VIEW IF EXISTS metro_schedules CASCADE;
DROP VIEW IF EXISTS national_rail_stations CASCADE;
DROP VIEW IF EXISTS metro_stations CASCADE;

-- ---------------------------------------------------------------------------
-- Drop tables
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS journey_feedback CASCADE;
DROP TABLE IF EXISTS payment_transactions CASCADE;
DROP TABLE IF EXISTS payment_instruments CASCADE;
DROP TABLE IF EXISTS rail_journey_reservations CASCADE;
DROP TABLE IF EXISTS travel_journeys CASCADE;
DROP TABLE IF EXISTS travel_orders CASCADE;
DROP TABLE IF EXISTS seat_locks CASCADE;

DROP TABLE IF EXISTS refund_policy_windows CASCADE;
DROP TABLE IF EXISTS refund_policy_ticket_types CASCADE;
DROP TABLE IF EXISTS refund_policies CASCADE;

DROP TABLE IF EXISTS policy_documents CASCADE;

DROP TABLE IF EXISTS auth_login_audit CASCADE;
DROP TABLE IF EXISTS user_recovery_factors CASCADE;
DROP TABLE IF EXISTS user_auth_credentials CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;
DROP TABLE IF EXISTS user_oauth_accounts CASCADE;

DROP TABLE IF EXISTS seat_locks CASCADE;
DROP TABLE IF EXISTS seat_layout_seats CASCADE;
DROP TABLE IF EXISTS seat_layout_coaches CASCADE;
DROP TABLE IF EXISTS seat_layouts CASCADE;

DROP TABLE IF EXISTS ticket_type_network_rules CASCADE;
DROP TABLE IF EXISTS ticket_types CASCADE;
DROP TABLE IF EXISTS schedule_fares CASCADE;
DROP TABLE IF EXISTS schedule_operating_days CASCADE;
DROP TABLE IF EXISTS schedule_stations CASCADE;
DROP TABLE IF EXISTS service_schedules CASCADE;

DROP TABLE IF EXISTS station_adjacencies CASCADE;
DROP TABLE IF EXISTS station_transfers CASCADE;
DROP TABLE IF EXISTS station_lines CASCADE;
DROP TABLE IF EXISTS stations CASCADE;
DROP TABLE IF EXISTS lines CASCADE;

-- ---------------------------------------------------------------------------
-- A. Basic network data
-- ---------------------------------------------------------------------------

CREATE TABLE lines (
    -- [PK design decision: TEXT] Using externally defined standard route codes as the TEXT PK makes logs way easier to read and simplifies system integration
    line_id        TEXT PRIMARY KEY,
    network_type   TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    line_name      TEXT NOT NULL,
    -- [Delete strategy: Soft Delete] Setting is_active to FALSE when a line is deactivated ensures that historical ticket and travel records can still be audited
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_lines_id_network UNIQUE (line_id, network_type)
);

CREATE TABLE stations (
    -- [PK design decision: TEXT] Using standard station natural business codes (like 'MS01') as the TEXT PK makes debugging easier and simplifies network modeling
    station_id      TEXT PRIMARY KEY,
    network_type    TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    station_name    TEXT NOT NULL,
    -- [Delete strategy: Soft Delete] Setting is_active to FALSE when a station is deactivated prevents damage to existing travel history records
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_stations_id_network UNIQUE (station_id, network_type)
);

CREATE TABLE station_lines (
    -- [PK design decision: Composite] Composite primary key defined by the station and route together, naturally unique
    -- [FK cascade behaviour: ON DELETE CASCADE] When the corresponding station or route is hard deleted, its subordinate relationship with the station and route is no longer meaningful, so it is cascaded and deleted
    station_id    TEXT NOT NULL,
    line_id       TEXT NOT NULL,
    network_type  TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),

    PRIMARY KEY (station_id, line_id),

    CONSTRAINT fk_station_lines_station_network
        FOREIGN KEY (station_id, network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT fk_station_lines_line_network
        FOREIGN KEY (line_id, network_type)
        REFERENCES lines(line_id, network_type)
        ON DELETE CASCADE
);

-- Cross-network transfer, e.g. MS01 <-> NR01.
-- Same-system interchange does not need to be stored here; it is represented by station_lines.
CREATE TABLE station_transfers (
    -- [PK design decision: Composite] Composite primary key, uniquely identifying the transfer path from station A to station B
    -- [FK cascade behaviour: ON DELETE CASCADE] When a station is hard deleted, the related transfer path definition is also deleted
    from_station_id    TEXT NOT NULL,
    to_station_id      TEXT NOT NULL,
    transfer_type      TEXT NOT NULL CHECK (
        transfer_type IN ('metro_to_rail', 'rail_to_metro', 'metro_to_metro', 'rail_to_rail')
    ),
    -- Generated from transfer_type so existing inserts still provide only station IDs and transfer_type.
    from_network_type  TEXT GENERATED ALWAYS AS (
        CASE
            WHEN transfer_type IN ('metro_to_rail', 'metro_to_metro') THEN 'metro'
            WHEN transfer_type IN ('rail_to_metro', 'rail_to_rail') THEN 'national_rail'
        END
    ) STORED,
    to_network_type    TEXT GENERATED ALWAYS AS (
        CASE
            WHEN transfer_type IN ('metro_to_rail', 'rail_to_rail') THEN 'national_rail'
            WHEN transfer_type IN ('rail_to_metro', 'metro_to_metro') THEN 'metro'
        END
    ) STORED,
    walking_time_min   INTEGER NOT NULL DEFAULT 0 CHECK (walking_time_min >= 0),
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (from_station_id, to_station_id),

    CONSTRAINT fk_transfer_from_station_network
        FOREIGN KEY (from_station_id, from_network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT fk_transfer_to_station_network
        FOREIGN KEY (to_station_id, to_network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE CASCADE
);

-- Directed adjacency: A -> B and B -> A should be inserted as separate rows.
CREATE TABLE station_adjacencies (
    -- [PK design decision: BIGSERIAL] Using Bigserial as the surrogate primary key for high-frequency network edges improves join performance
    adjacency_id      BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When the subordinate station or route is hard deleted, the adjacency edge is also cascaded and deleted
    from_station_id   TEXT NOT NULL,
    to_station_id     TEXT NOT NULL,
    line_id           TEXT NOT NULL,
    network_type      TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    travel_time_min   INTEGER NOT NULL CHECK (travel_time_min > 0),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT fk_adj_from_station_network
        FOREIGN KEY (from_station_id, network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT fk_adj_to_station_network
        FOREIGN KEY (to_station_id, network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT fk_adj_line_network
        FOREIGN KEY (line_id, network_type)
        REFERENCES lines(line_id, network_type)
        ON DELETE CASCADE,

    UNIQUE (from_station_id, to_station_id, line_id)
);

-- ---------------------------------------------------------------------------
-- B. Schedules and stops
-- ---------------------------------------------------------------------------

CREATE TABLE service_schedules (
    -- [PK design decision: TEXT] Using natural schedule/train codes (like 'NR_SCH01') as the TEXT PK facilitates operational dispatch and customer inquiries
    schedule_id             TEXT PRIMARY KEY,
    line_id                 TEXT NOT NULL,
    network_type            TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    service_type            TEXT NULL CHECK (service_type IS NULL OR service_type IN ('normal', 'express')),
    direction               TEXT NOT NULL,
    origin_station_id       TEXT NOT NULL,
    destination_station_id  TEXT NOT NULL,
    first_train_time        TIME NOT NULL,
    last_train_time         TIME NOT NULL,
    frequency_min           INTEGER NOT NULL CHECK (frequency_min > 0),
    -- [Delete strategy: Soft Delete] Setting is_active to FALSE when a schedule is deactivated facilitates the analysis of historical schedule performance
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_schedules_id_network UNIQUE (schedule_id, network_type),
    -- [FK cascade behaviour: ON DELETE CASCADE] When a route is hard deleted, its subordinate schedules are automatically cascaded and deleted
    CONSTRAINT fk_schedules_line_network FOREIGN KEY (line_id, network_type) REFERENCES lines(line_id, network_type) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE RESTRICT] If a station is the origin or destination of a schedule, it is strictly prohibited to delete the station directly to ensure the integrity of the referenced reference.
    CONSTRAINT fk_schedules_origin_station_network FOREIGN KEY (origin_station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT,
    CONSTRAINT fk_schedules_dest_station_network FOREIGN KEY (destination_station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT
);

CREATE TABLE schedule_operating_days (
    -- [PK design decision: Composite] Composite primary key composed of schedule ID and day of week, accurately expressing its service cycle
    -- [FK cascade behaviour: ON DELETE CASCADE] When a schedule is hard deleted, the associated operating day definition is automatically cascaded and deleted
    schedule_id   TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week   TEXT NOT NULL CHECK (day_of_week IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

CREATE TABLE schedule_stations (
    -- [PK design decision: Composite] Composite primary key composed of schedule ID and stop sequence number
    schedule_id                  TEXT NOT NULL,
    network_type                 TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    sequence_no                  INTEGER NOT NULL CHECK (sequence_no >= 1),
    station_id                   TEXT NOT NULL,
    stops_here                   BOOLEAN NOT NULL DEFAULT TRUE,
    travel_time_from_origin_min  INTEGER NOT NULL CHECK (travel_time_from_origin_min >= 0),
    PRIMARY KEY (schedule_id, sequence_no),
    UNIQUE (schedule_id, station_id),
    -- [FK cascade behaviour: ON DELETE CASCADE] When a schedule is deleted, all its stop sequence definitions are automatically cascaded and deleted
    CONSTRAINT fk_schedule_stations_schedule_network FOREIGN KEY (schedule_id, network_type) REFERENCES service_schedules(schedule_id, network_type) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE RESTRICT] If a station is a stop in a route schedule, it is strictly prohibited to delete the station directly, and the schedule must be modified first
    CONSTRAINT fk_schedule_stations_station_network FOREIGN KEY (station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------------
-- C. Fares and ticket types
-- ---------------------------------------------------------------------------

CREATE TABLE ticket_types (
    -- [PK design decision: TEXT] Using ticket type business unique identifier codes (such as 'single', 'return') prevents ambiguity in fare policies.
    ticket_type   TEXT PRIMARY KEY CHECK (ticket_type IN ('single', 'return', 'day_pass')),
    display_name  TEXT NOT NULL,
    description   TEXT NULL,
    -- [Delete strategy: Soft Delete] Setting is_active to FALSE when a ticket type is retired and discontinued allows historical orders to be traced back to their fare attributes.
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO ticket_types (ticket_type, display_name, description) VALUES
('single', 'Single Ticket', 'One-way travel between two stations'),
('return', 'Return Ticket', 'Round-trip travel between two stations'),
('day_pass', 'Day Pass', 'Unlimited travel for a single calendar day')
ON CONFLICT (ticket_type) DO NOTHING;

CREATE TABLE ticket_type_network_rules (
    -- [PK design decision: Composite] Composite primary key composed of ticket type and network type uniquely determining a set of rules.
    -- [FK cascade behaviour: ON DELETE CASCADE] When a ticket type is deleted, the derived fare rules under its network type are automatically cascaded and deleted.
    ticket_type                   TEXT NOT NULL REFERENCES ticket_types(ticket_type) ON DELETE CASCADE,
    network_type                  TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    pricing_model                 TEXT NOT NULL CHECK (
        pricing_model IN ('stops_based', 'stops_based_with_fare_class', 'fixed')
    ),
    seat_assignment_required      BOOLEAN NOT NULL DEFAULT FALSE,
    advance_purchase_allowed      BOOLEAN NOT NULL DEFAULT TRUE,
    advance_purchase_max_days     INTEGER NULL CHECK (advance_purchase_max_days IS NULL OR advance_purchase_max_days >= 0),
    changes_allowed               BOOLEAN NOT NULL DEFAULT FALSE,
    change_fee_usd                NUMERIC(10,2) NULL CHECK (change_fee_usd IS NULL OR change_fee_usd >= 0),
    change_deadline_hours         INTEGER NULL CHECK (change_deadline_hours IS NULL OR change_deadline_hours >= 0),
    refundable                    BOOLEAN NOT NULL DEFAULT FALSE,
    validity_text                 TEXT NULL,
    PRIMARY KEY (ticket_type, network_type)
);

-- Seed valid ticket type rules for each transport network.
-- This table enforces that each order uses a ticket type valid for its network.
INSERT INTO ticket_type_network_rules (
    ticket_type,
    network_type,
    pricing_model,
    seat_assignment_required,
    advance_purchase_allowed,
    refundable,
    validity_text
) VALUES
('single', 'metro', 'stops_based', FALSE, FALSE, TRUE, 'Valid for one metro journey'),
('day_pass', 'metro', 'fixed', FALSE, FALSE, TRUE, 'Unlimited metro travel for one calendar day'),
('single', 'national_rail', 'stops_based_with_fare_class', TRUE, TRUE, TRUE, 'One-way national rail journey'),
('return', 'national_rail', 'stops_based_with_fare_class', TRUE, TRUE, TRUE, 'Round-trip national rail journey')
ON CONFLICT (ticket_type, network_type) DO NOTHING;

-- fare_class_code:
--   national rail: 'standard', 'first'
--   metro:         'metro_single'
CREATE TABLE schedule_fares (
    -- [PK design decision: Composite] Composite primary key combining schedule ID and fare class code.
    -- [FK cascade behaviour: ON DELETE CASCADE] When a schedule is hard deleted, the associated fare class price definitions are automatically cascaded and deleted.
    schedule_id        TEXT NOT NULL ,
    network_type       TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    fare_class_code    TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first', 'metro_single')),
    base_fare_usd      NUMERIC(10,2) NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd  NUMERIC(10,2) NOT NULL CHECK (per_stop_rate_usd >= 0),
    currency_code      CHAR(3) NOT NULL DEFAULT 'USD',

    PRIMARY KEY (schedule_id, fare_class_code),

    CONSTRAINT fk_schedule_fares_schedule_network
        FOREIGN KEY (schedule_id, network_type)
        REFERENCES service_schedules(schedule_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT chk_schedule_fares_network_class
        CHECK (
            (network_type = 'metro' AND fare_class_code = 'metro_single')
            OR
            (network_type = 'national_rail' AND fare_class_code IN ('standard', 'first'))
        )
);

-- ---------------------------------------------------------------------------
-- D. National rail seat layouts
-- ---------------------------------------------------------------------------

--  Debugging: making sure the search will focus on 'national_rail'
CREATE TABLE seat_layouts (
    -- [PK design decision: TEXT] Using seat layout physical natural codes (such as 'SL_LAYOUT_A') corresponding to vehicle configuration models.
    layout_id      TEXT PRIMARY KEY,
    schedule_id    TEXT NOT NULL UNIQUE,
    network_type   TEXT NOT NULL DEFAULT 'national_rail' CHECK (network_type = 'national_rail'),
    layout_version TEXT NOT NULL DEFAULT '1.0',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- [FK cascade behaviour: ON DELETE CASCADE] When a schedule is hard deleted, the corresponding seat layout information is automatically cascaded and deleted.
    CONSTRAINT uq_seat_layouts_layout_schedule
        UNIQUE (layout_id, schedule_id),

    CONSTRAINT fk_seat_layouts_schedule_network
        FOREIGN KEY (schedule_id, network_type)
        REFERENCES service_schedules(schedule_id, network_type)
        ON DELETE CASCADE
);

CREATE TABLE seat_layout_coaches (
    -- [PK design decision: BIGSERIAL] Using BIGSERIAL as the surrogate primary key to obtain the best performance when associating seats later.
    coach_id         BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When a seat layout configuration is hard deleted, all its coach configurations are automatically cascaded and deleted.
    layout_id        TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_code       TEXT NOT NULL,
    fare_class_code  TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    UNIQUE (layout_id, coach_code),
    UNIQUE (coach_id, layout_id),
    UNIQUE (coach_id, fare_class_code)
);

CREATE TABLE seat_layout_seats (
    -- [PK design decision: BIGSERIAL] Single seat surrogate primary key for high-frequency cross-day booking and Lock query.
    seat_pk      BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When a coach or layout is hard deleted, all its specific physical seats are automatically cascaded and deleted.
    layout_id    TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_id     BIGINT NOT NULL REFERENCES seat_layout_coaches(coach_id) ON DELETE CASCADE,
    seat_code    TEXT NOT NULL,
    seat_row     INTEGER NOT NULL CHECK (seat_row >= 1),
    seat_column  TEXT NOT NULL,
    UNIQUE (layout_id, seat_code),
    UNIQUE (coach_id, seat_code),
    UNIQUE (seat_pk, coach_id),
    UNIQUE (seat_pk, layout_id, coach_id),

    CONSTRAINT fk_seat_layout_seats_coach_layout
        FOREIGN KEY (coach_id, layout_id)
        REFERENCES seat_layout_coaches(coach_id, layout_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- E. Users and authentication
-- ---------------------------------------------------------------------------

CREATE TABLE user_profiles (
    -- [PK design decision: TEXT] Using fixed-prefix auto-increment business natural keys (such as 'RU100234') for easy identification in customer service systems and by users.
    user_id        TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    first_name     TEXT NOT NULL,
    surname        TEXT NOT NULL,
    phone          TEXT NULL,
    date_of_birth  DATE NOT NULL,
    -- [Delete strategy: Soft Delete] Setting is_active to FALSE when a user is deactivated ensures that historical travel order records still comply with accounting legal retention periods.
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_auth_credentials (
    -- [PK design decision: Shared Primary Key (TEXT)] Sharing a one-to-one primary key with user_profiles strengthens the architectural security.
    -- [FK cascade behaviour: ON DELETE CASCADE] When a user's basic information is permanently hard deleted, sensitive security credential data is automatically cascaded and deleted to prevent privacy leaks.
    user_id               TEXT PRIMARY KEY REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    login_email           TEXT NOT NULL,
    password_hash         TEXT NOT NULL,
    password_algo         TEXT NOT NULL DEFAULT 'argon2id',
    password_hash_params  TEXT NOT NULL DEFAULT 'm=65536,t=3,p=4',
    password_changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    email_verified_at     TIMESTAMPTZ NULL,
    failed_login_count    INTEGER NOT NULL DEFAULT 0,
    locked_until          TIMESTAMPTZ NULL,
    last_login_at         TIMESTAMPTZ NULL
);

-- Case-insensitive uniqueness for login email.
CREATE UNIQUE INDEX idx_user_auth_credentials_email_lower
ON user_auth_credentials (LOWER(login_email));

CREATE TABLE user_recovery_factors (
    -- [PK design decision: TEXT] Natural recovery factor ID (such as 'RF-RU100234').
    recovery_factor_id  TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When a user is deleted, their password recovery security questions are automatically cascaded and deleted.
    user_id             TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    factor_type         TEXT NOT NULL DEFAULT 'security_question',
    question_text       TEXT NOT NULL,
    answer_hash         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at          TIMESTAMPTZ NULL
);

CREATE TABLE auth_login_audit (
    -- [PK design decision: BIGSERIAL] Logging security audit records, using an auto-increment serial number to provide high-efficiency write performance.
    audit_id               BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE SET NULL] If the user profile is deleted, this login security audit record is retained and set to NULL to maintain the integrity of the overall log analysis.
    user_id                TEXT NULL REFERENCES user_profiles(user_id) ON DELETE SET NULL,
    login_email_attempted  TEXT NOT NULL,
    ip_hash                TEXT NULL,
    user_agent_hash        TEXT NULL,
    result                 TEXT NOT NULL CHECK (result IN ('success', 'failed', 'locked')),
    occurred_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- TASK 6 EXTENSION: Google OAuth user mapping table links external Google
-- accounts to local TransitFlow user_profiles for database-backed login.
CREATE TABLE user_oauth_accounts (
    -- Google OAuth account mapped to a local TransitFlow user.
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

CREATE INDEX idx_user_oauth_accounts_user_id
ON user_oauth_accounts (user_id);

CREATE INDEX idx_user_oauth_accounts_email_lower
ON user_oauth_accounts (LOWER(email));

-- ---------------------------------------------------------------------------
-- F. Booking / travel history
-- ---------------------------------------------------------------------------

CREATE TABLE travel_orders (
    -- [PK design decision: TEXT] Order unique natural number (such as 'ORD-BK-123456') for easy integration with invoices and accounts.
    order_id          TEXT PRIMARY KEY,
    order_code        TEXT NOT NULL UNIQUE,
    -- [FK cascade behaviour: ON DELETE CASCADE] When a member profile is permanently hard deleted, its order data is automatically deleted.
    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    network_type      TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    -- [FK cascade behaviour: ON DELETE RESTRICT] Never hard delete a ticket type if it’s still associated with any orders."
    product_type      TEXT NOT NULL ,
    order_status      TEXT NOT NULL CHECK (order_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    total_amount_usd  NUMERIC(10,2) NOT NULL CHECK (total_amount_usd >= 0),
    currency_code     CHAR(3) NOT NULL DEFAULT 'USD',
    purchased_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_travel_orders_id_network
        UNIQUE (order_id, network_type),

    CONSTRAINT fk_travel_orders_ticket_network
        FOREIGN KEY (product_type, network_type)
        REFERENCES ticket_type_network_rules(ticket_type, network_type)
        ON DELETE RESTRICT
);

CREATE TABLE travel_journeys (
    -- [PK design decision: TEXT] Journey unique natural identifier code (such as 'BK-3J8F4A') usually used as the encoding for travel electronic vouchers (QR Codes).
    journey_id              TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When an order is deleted, the journeys contained within it are automatically cascaded and deleted.
    order_id                TEXT NOT NULL,
    journey_sequence_no     INTEGER NOT NULL CHECK (journey_sequence_no >= 1),
    -- [FK cascade behaviour: ON DELETE RESTRICT] Never hard delete a schedule if it is still assigned to any journeys; related reservations must be canceled first.
    schedule_id             TEXT NOT NULL ,
    -- [FK cascade behaviour: ON DELETE RESTRICT] Never delete a station if it’s still referenced as an origin or destination station for any journeys.
    origin_station_id       TEXT NOT NULL ,
    destination_station_id  TEXT NOT NULL ,
    network_type            TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    travel_date             DATE NOT NULL,
    departure_time          TIME NULL,
    travelled_at            TIMESTAMPTZ NULL,
    journey_status          TEXT NOT NULL CHECK (journey_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    stops_travelled         INTEGER NULL CHECK (stops_travelled >= 0),
    allocated_amount_usd    NUMERIC(10,2) NOT NULL CHECK (allocated_amount_usd >= 0),
    -- [FK cascade behaviour: ON DELETE SET NULL] If the day pass journey this record references is deleted, the reference is set to NULL.
    day_pass_ref            TEXT NULL REFERENCES travel_journeys(journey_id) ON DELETE SET NULL,
    UNIQUE (order_id, journey_sequence_no),
    CONSTRAINT uq_journeys_id_sched_date
        UNIQUE (journey_id, schedule_id, travel_date),

    CONSTRAINT fk_journeys_order_network
        FOREIGN KEY (order_id, network_type)
        REFERENCES travel_orders(order_id, network_type)
        ON DELETE CASCADE,

    CONSTRAINT fk_journeys_schedule_network
        FOREIGN KEY (schedule_id, network_type)
        REFERENCES service_schedules(schedule_id, network_type)
        ON DELETE RESTRICT,

    CONSTRAINT fk_journeys_origin_station_network
        FOREIGN KEY (origin_station_id, network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE RESTRICT,

    CONSTRAINT fk_journeys_dest_station_network
        FOREIGN KEY (destination_station_id, network_type)
        REFERENCES stations(station_id, network_type)
        ON DELETE RESTRICT
);

CREATE TABLE rail_journey_reservations (
    -- [PK design decision: TEXT] Sharing a one-to-one primary key with travel_journeys.
    journey_id          TEXT PRIMARY KEY,
    schedule_id         TEXT NOT NULL,
    layout_id           TEXT NOT NULL,
    travel_date         DATE NOT NULL,
    fare_class_code     TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    coach_id            BIGINT NOT NULL,
    seat_pk             BIGINT NOT NULL,
    seat_reserved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reservation_status  TEXT NOT NULL CHECK (reservation_status IN ('active', 'cancelled')),
    -- [FK cascade behaviour: ON DELETE CASCADE] When the journey is deleted, the seat reservation record is automatically cascaded and deleted.
    CONSTRAINT fk_reservation_journey_sched_date
        FOREIGN KEY (journey_id, schedule_id, travel_date)
        REFERENCES travel_journeys(journey_id, schedule_id, travel_date)
        ON DELETE CASCADE,

    CONSTRAINT fk_reservation_layout_schedule
        FOREIGN KEY (layout_id, schedule_id)
        REFERENCES seat_layouts(layout_id, schedule_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_reservation_seat_layout_coach
        FOREIGN KEY (seat_pk, layout_id, coach_id)
        REFERENCES seat_layout_seats(seat_pk, layout_id, coach_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_reservation_coach_fare_class
        FOREIGN KEY (coach_id, fare_class_code)
        REFERENCES seat_layout_coaches(coach_id, fare_class_code)
        ON DELETE CASCADE
);

-- Implement the unique partial index, which means that only the active seat reservations 
-- Technical Note or learning please refer to Notion LOL
CREATE UNIQUE INDEX uq_active_seat_reservation
ON rail_journey_reservations (schedule_id, travel_date, seat_pk)
WHERE reservation_status = 'active';

-- ===========================================================================
-- Seat Locks and Time-based Locking Mechanisms
-- ===========================================================================

-- TASK 6 EXTENSION: seat_locks stores temporary 10-minute seat holds so two
-- users cannot select the same national rail seat at the same time.
-- [NEW] 新增臨時座位鎖定表 seat_locks
-- 用來記錄訂票流程中的暫時性座位佔用。
CREATE TABLE seat_locks (
    lock_id TEXT PRIMARY KEY, -- 'LK-' || 6位隨機字串
    user_id TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    schedule_id TEXT NOT NULL,
    travel_date DATE NOT NULL,
    seat_pk BIGINT NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL, -- 透過 Trigger 自動設定
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'released', 'confirmed')),
    
    CONSTRAINT fk_seat_locks_seat FOREIGN KEY (seat_pk) REFERENCES seat_layout_seats(seat_pk) ON DELETE CASCADE,
    CONSTRAINT fk_seat_locks_schedule FOREIGN KEY (schedule_id) REFERENCES service_schedules(schedule_id) ON DELETE CASCADE
);

-- TASK 6 EXTENSION: partial unique index enforces one active pending lock per
-- schedule/date/seat combination.
-- [NEW] 部分唯一索引 —— 業務排他鎖 (Exclusive Lock) 核心
-- 確保同一班次、同一日期、同一座位在狀態為 pending 時，只能被一個使用者佔用
CREATE UNIQUE INDEX uq_active_seat_lock
ON seat_locks (schedule_id, travel_date, seat_pk)
WHERE status = 'pending';

-- TASK 6 EXTENSION: trigger automatically assigns a 10-minute expiry to each
-- newly inserted temporary seat lock.
-- [NEW] 自動計算過期時間的 Trigger 函數
-- 在插入 seat_locks 時，自動將 expires_at 設定為 locked_at + 10 分鐘
CREATE OR REPLACE FUNCTION set_seat_lock_expiry()
RETURNS TRIGGER AS $$
BEGIN
    NEW.expires_at := NEW.locked_at + INTERVAL '10 minutes';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_set_seat_lock_expiry
BEFORE INSERT ON seat_locks
FOR EACH ROW
EXECUTE FUNCTION set_seat_lock_expiry();


-- ---------------------------------------------------------------------------
-- G. Payments
-- ---------------------------------------------------------------------------
CREATE TABLE payment_instruments (
    -- [PK design decision: TEXT] Natural payment instrument ID (such as 'PMI-100234-CARD').
    payment_instrument_id TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When a user profile is deleted, the secure payment token information bound to it is automatically cascaded and deleted.
    user_id               TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    method_type           TEXT NOT NULL CHECK (method_type IN ('credit_card', 'debit_card', 'ewallet')),
    provider_name         TEXT NULL,
    token_ref             TEXT NOT NULL,
    last4                 TEXT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE payment_transactions (
    -- TASK 6 EXTENSION: pending payment rows support the confirm/cancel payment
    -- workflow and timeout release for rail bookings and metro tickets.
    -- [PK design decision: TEXT] Natural payment transaction slip number (such as 'PM-9K4N2D').
    payment_id            TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When the parent order is deleted, related payment transaction records are automatically cascaded and deleted to prevent isolated transaction records (孤立交易記錄).
    order_id              TEXT NOT NULL REFERENCES travel_orders(order_id) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE SET NULL] If the bound payment method is cancelled and deleted, the payment card reference field in the historical transaction slip is set to NULL, retaining the flow amount (流水金額) to comply with accounting reporting requirements.
    payment_instrument_id TEXT NULL REFERENCES payment_instruments(payment_instrument_id) ON DELETE SET NULL,
    transaction_type      TEXT NOT NULL CHECK (transaction_type IN ('charge', 'refund')),
    amount_usd            NUMERIC(10,2) NOT NULL CHECK (amount_usd >= 0),
    currency_code         CHAR(3) NOT NULL DEFAULT 'USD',
    payment_status        TEXT NOT NULL CHECK (payment_status IN ('pending', 'paid', 'failed', 'refunded')),
    gateway_reference     TEXT NULL,
    processed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- [FK cascade behaviour: ON DELETE SET NULL] If the original transaction slip associated with a refund transaction is hard deleted, this field is retained and set to NULL.
    ref_payment_id        TEXT NULL REFERENCES payment_transactions(payment_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------------
-- H. Feedback
-- ---------------------------------------------------------------------------
CREATE TABLE journey_feedback (
    -- TASK 6 EXTENSION: journey_feedback supports owned feedback submission and
    -- prevents duplicate feedback per user journey.
    -- [PK design decision: TEXT] feedback serial number
    feedback_id    TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] When the parent travel journey or user profile is hard deleted, the corresponding feedback rating content is also cascaded and deleted.
    journey_id     TEXT NOT NULL REFERENCES travel_journeys(journey_id) ON DELETE CASCADE,
    user_id        TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    rating         INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment        TEXT NULL,
    submitted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (journey_id, user_id)
);

-- ---------------------------------------------------------------------------
-- I. Structured refund rules
-- ---------------------------------------------------------------------------
-- Because of the complexity of the system, we tend to keep these tables for further extension.
-- (There's no related queries for refund lol
-- Once we got more time, we will come back to improve it.
/*
CREATE TABLE refund_policies (
    policy_id     TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    network_type  TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    service_type  TEXT NULL CHECK (service_type IS NULL OR service_type IN ('normal', 'express')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE refund_policy_ticket_types (
    policy_id    TEXT NOT NULL REFERENCES refund_policies(policy_id) ON DELETE CASCADE,
    ticket_type  TEXT NOT NULL REFERENCES ticket_types(ticket_type) ON DELETE CASCADE,
    PRIMARY KEY (policy_id, ticket_type)
);

CREATE TABLE refund_policy_windows (
    window_id                    TEXT PRIMARY KEY,
    policy_id                    TEXT NOT NULL REFERENCES refund_policies(policy_id) ON DELETE CASCADE,
    label                        TEXT NOT NULL,
    hours_before_departure_min   NUMERIC(8,2) NOT NULL CHECK (hours_before_departure_min >= 0),
    hours_before_departure_max   NUMERIC(8,2) NULL CHECK (
        hours_before_departure_max IS NULL
        OR hours_before_departure_max >= hours_before_departure_min
    ),
    refund_percent               NUMERIC(5,2) NOT NULL CHECK (refund_percent BETWEEN 0 AND 100),
    admin_fee_usd                NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (admin_fee_usd >= 0),
    condition_text               TEXT NULL
);
*/

-- ---------------------------------------------------------------------------
-- H. Vector / RAG documents
-- ---------------------------------------------------------------------------

-- pgvector dimension is intentionally not fixed here because different LLM
-- embedding providers may return different dimensions. For a large production
-- system, set a fixed dimension and add an IVFFLAT/HNSW index.
CREATE TABLE policy_documents (
    -- TASK 6 EXTENSION: extended policy seed JSON is embedded into this pgvector
    -- table for semantic policy search.
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR NOT NULL,
    source_file  TEXT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Compatibility views for current queries.py
-- ---------------------------------------------------------------------------

CREATE VIEW metro_stations AS
SELECT
    station_id,
    station_name AS name,
    is_active
FROM stations
WHERE network_type = 'metro';

CREATE VIEW national_rail_stations AS
SELECT
    station_id,
    station_name AS name,
    is_active
FROM stations
WHERE network_type = 'national_rail';

CREATE VIEW metro_schedules AS
SELECT
    s.schedule_id,
    s.line_id AS line,
    s.direction,
    s.origin_station_id,
    s.destination_station_id,
    s.first_train_time,
    s.last_train_time,
    s.frequency_min,
    f.base_fare_usd,
    f.per_stop_rate_usd
FROM service_schedules s
JOIN schedule_fares f
  ON f.schedule_id = s.schedule_id
 AND f.fare_class_code = 'metro_single'
WHERE s.network_type = 'metro';

CREATE VIEW metro_schedule_stops AS
SELECT
    schedule_id,
    station_id,
    sequence_no AS stop_order,
    travel_time_from_origin_min
FROM schedule_stations
WHERE network_type = 'metro';

CREATE VIEW national_rail_schedules AS
SELECT
    schedule_id,
    line_id AS line,
    service_type,
    direction,
    origin_station_id,
    destination_station_id,
    first_train_time,
    last_train_time,
    frequency_min
FROM service_schedules
WHERE network_type = 'national_rail';

CREATE VIEW national_rail_schedule_stops AS
SELECT
    schedule_id,
    station_id,
    sequence_no AS stop_order,
    travel_time_from_origin_min
FROM schedule_stations
WHERE network_type = 'national_rail';

CREATE VIEW national_rail_fare_classes AS
SELECT
    schedule_id,
    fare_class_code AS fare_class,
    base_fare_usd,
    per_stop_rate_usd
FROM schedule_fares
WHERE fare_class_code IN ('standard', 'first');

CREATE VIEW national_rail_seat_layouts AS
SELECT
    layout_id,
    schedule_id,
    layout_version
FROM seat_layouts;

CREATE VIEW national_rail_seats AS
SELECT
    sls.seat_pk,
    sls.layout_id,
    slc.coach_code AS coach,
    sls.seat_code AS seat_id,
    sls.seat_row,
    sls.seat_column,
    slc.fare_class_code AS fare_class
FROM seat_layout_seats sls
JOIN seat_layout_coaches slc
  ON slc.coach_id = sls.coach_id;

CREATE OR REPLACE VIEW registered_users AS
SELECT
    up.user_id,
    COALESCE(uac.login_email, oauth.email) AS email,
    up.first_name,
    up.surname,
    up.full_name,
    up.phone,
    up.date_of_birth,
    up.registered_at,
    up.is_active
FROM user_profiles up
LEFT JOIN user_auth_credentials uac
  ON uac.user_id = up.user_id
LEFT JOIN user_oauth_accounts oauth
  ON oauth.user_id = up.user_id
 AND oauth.provider = 'google';

CREATE OR REPLACE VIEW user_credentials AS
SELECT
    uac.user_id,
    uac.password_hash,
    uac.password_algo AS hashing_algorithm,
    urf.question_text AS secret_question,
    urf.answer_hash AS secret_answer_hash,
    uac.password_changed_at AS updated_at
FROM user_auth_credentials uac
LEFT JOIN user_recovery_factors urf 
  ON urf.user_id = uac.user_id 
 AND urf.factor_type = 'security_question';

-- ---------------------------------------------------------------------------
-- Compatibility View Endpoints with INSTEAD OF triggers for Read/Write queries
-- ---------------------------------------------------------------------------
-- Implemented INSTEAD OF triggers for Read/Write queries to views, cuz I personally want to drop some burdens for revising queries.py
-- If you find that there exist more appropriate ways to deal with it(eg. revise the queries.py), just go for it and inform Chris!

-- 1. national_rail_bookings View
CREATE OR REPLACE VIEW national_rail_bookings AS
SELECT
    tj.journey_id AS booking_id,
    to_tbl.user_id,
    tj.schedule_id,
    tj.origin_station_id,
    tj.destination_station_id,
    tj.travel_date,
    tj.departure_time,
    to_tbl.product_type AS ticket_type,
    rjr.fare_class_code AS fare_class,
    rjr.layout_id,
    slc.coach_code AS coach,
    sls.seat_code AS seat_id,
    tj.stops_travelled,
    tj.allocated_amount_usd AS amount_usd,
    tj.journey_status AS status,
    to_tbl.purchased_at AS booked_at,
    tj.travelled_at
FROM travel_journeys tj
JOIN travel_orders to_tbl ON to_tbl.order_id = tj.order_id
LEFT JOIN rail_journey_reservations rjr ON rjr.journey_id = tj.journey_id
LEFT JOIN seat_layout_coaches slc ON slc.coach_id = rjr.coach_id
LEFT JOIN seat_layout_seats sls ON sls.seat_pk = rjr.seat_pk
WHERE to_tbl.network_type = 'national_rail';

-- national_rail_bookings INSTEAD OF INSERT Trigger
-- if the app writes a new order of national rail ticket, the trigger will insert values into travel_orders, travel_journeys, 
-- rail_journey_reservations, seat_layout_seats, seat_layouts in a transaction
CREATE OR REPLACE FUNCTION trg_national_rail_bookings_insert_func()
RETURNS TRIGGER AS $$
DECLARE
    v_coach_id BIGINT;
    v_seat_pk BIGINT;
    v_order_id TEXT;
BEGIN
    v_order_id := CONCAT('ORD-', NEW.booking_id);

    -- 1. Insert into travel_orders
    INSERT INTO travel_orders (
        order_id, order_code, user_id, network_type, product_type, order_status, total_amount_usd, purchased_at
    ) VALUES (
        v_order_id,
        NEW.booking_id,
        NEW.user_id,
        'national_rail',
        NEW.ticket_type,
        NEW.status,
        NEW.amount_usd,
        COALESCE(NEW.booked_at, NOW())
    ) ON CONFLICT (order_id) DO NOTHING;

    -- 2. Insert into travel_journeys
    INSERT INTO travel_journeys (
        journey_id,
        order_id,
        journey_sequence_no,
        schedule_id,
        origin_station_id,
        destination_station_id,
        network_type,
        travel_date,
        departure_time,
        travelled_at,
        journey_status,
        stops_travelled,
        allocated_amount_usd
    ) VALUES (
        NEW.booking_id,
        v_order_id,
        1,
        NEW.schedule_id,
        NEW.origin_station_id,
        NEW.destination_station_id,
        'national_rail',
        NEW.travel_date,
        NEW.departure_time,
        NEW.travelled_at,
        NEW.status,
        NEW.stops_travelled,
        NEW.amount_usd
    ) ON CONFLICT (journey_id) DO NOTHING;

    -- 3. Find coach_id and seat_pk
    SELECT coach_id INTO v_coach_id
    FROM seat_layout_coaches
    WHERE layout_id = NEW.layout_id AND coach_code = NEW.coach;

    IF v_coach_id IS NULL THEN
        RAISE EXCEPTION 'Coach not found for layout %, coach %', NEW.layout_id, NEW.coach;
    END IF;

    SELECT seat_pk INTO v_seat_pk
    FROM seat_layout_seats
    WHERE coach_id = v_coach_id AND seat_code = NEW.seat_id;

    IF v_seat_pk IS NULL THEN
        RAISE EXCEPTION 'Seat not found for coach %, seat %', NEW.coach, NEW.seat_id;
    END IF;

    -- 4. Insert into rail_journey_reservations
    INSERT INTO rail_journey_reservations (
        journey_id,
        schedule_id,
        layout_id,
        travel_date,
        fare_class_code,
        coach_id,
        seat_pk,
        seat_reserved_at,
        reservation_status
    ) VALUES (
        NEW.booking_id,
        NEW.schedule_id,
        NEW.layout_id,
        NEW.travel_date,
        NEW.fare_class,
        v_coach_id,
        v_seat_pk,
        COALESCE(NEW.booked_at, NOW()),
        CASE WHEN NEW.status = 'cancelled'
            THEN 'cancelled'::TEXT
            ELSE 'active'::TEXT
        END
    ) ON CONFLICT (journey_id) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_national_rail_bookings_insert
INSTEAD OF INSERT ON national_rail_bookings
FOR EACH ROW
EXECUTE FUNCTION trg_national_rail_bookings_insert_func();

-- national_rail_bookings INSTEAD OF UPDATE Trigger
-- Also, updating booking_id will update the order_id to keep them in sync 
CREATE OR REPLACE FUNCTION trg_national_rail_bookings_update_func()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE travel_journeys
    SET journey_status = NEW.status,
        travelled_at = NEW.travelled_at
    WHERE journey_id = OLD.booking_id;

    UPDATE travel_orders
    SET order_status = NEW.status
    WHERE order_id = CONCAT('ORD-', OLD.booking_id);

    IF NEW.status = 'cancelled' THEN
        UPDATE rail_journey_reservations
        SET reservation_status = 'cancelled'
        WHERE journey_id = OLD.booking_id;
    ELSIF NEW.status = 'confirmed' THEN
        UPDATE rail_journey_reservations
        SET reservation_status = 'active'
        WHERE journey_id = OLD.booking_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_national_rail_bookings_update
INSTEAD OF UPDATE ON national_rail_bookings
FOR EACH ROW
EXECUTE FUNCTION trg_national_rail_bookings_update_func();


-- 2. metro_travel_history View
-- Similar to national_rail_bookings view
CREATE OR REPLACE VIEW metro_travel_history AS
SELECT
    tj.journey_id AS trip_id,
    to_tbl.user_id,
    tj.schedule_id,
    tj.origin_station_id,
    tj.destination_station_id,
    tj.travel_date,
    to_tbl.product_type AS ticket_type,
    tj.day_pass_ref,
    tj.stops_travelled,
    tj.allocated_amount_usd AS amount_usd,
    tj.journey_status AS status,
    to_tbl.purchased_at AS purchased_at,
    tj.travelled_at
FROM travel_journeys tj
JOIN travel_orders to_tbl ON to_tbl.order_id = tj.order_id
WHERE to_tbl.network_type = 'metro';

-- metro_travel_history INSTEAD OF INSERT Trigger
CREATE OR REPLACE FUNCTION trg_metro_travel_history_insert_func()
RETURNS TRIGGER AS $$
DECLARE
    v_order_id TEXT;
BEGIN
    v_order_id := CONCAT('ORD-', NEW.trip_id);

    -- 1. Insert into travel_orders
    INSERT INTO travel_orders (
        order_id, order_code, user_id, network_type, product_type, order_status, total_amount_usd, purchased_at
    ) VALUES (
        v_order_id,
        NEW.trip_id,
        NEW.user_id,
        'metro',
        NEW.ticket_type,
        NEW.status,
        NEW.amount_usd,
        COALESCE(NEW.purchased_at, NOW())
    ) ON CONFLICT (order_id) DO NOTHING;

    -- 2. Insert into travel_journeys
    INSERT INTO travel_journeys (
        journey_id,
        order_id,
        journey_sequence_no,
        schedule_id,
        origin_station_id,
        destination_station_id,
        network_type,
        travel_date,
        departure_time,
        travelled_at,
        journey_status,
        stops_travelled,
        allocated_amount_usd,
        day_pass_ref
    ) VALUES (
        NEW.trip_id,
        v_order_id,
        1,
        NEW.schedule_id,
        NEW.origin_station_id,
        NEW.destination_station_id,
        'metro',
        NEW.travel_date,
        NULL,
        NEW.travelled_at,
        NEW.status,
        NEW.stops_travelled,
        NEW.amount_usd,
        NEW.day_pass_ref
    )
    ON CONFLICT (journey_id) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_metro_travel_history_insert
INSTEAD OF INSERT ON metro_travel_history
FOR EACH ROW
EXECUTE FUNCTION trg_metro_travel_history_insert_func();

-- metro_travel_history INSTEAD OF UPDATE Trigger
CREATE OR REPLACE FUNCTION trg_metro_travel_history_update_func()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE travel_journeys
    SET day_pass_ref = NEW.day_pass_ref,
        journey_status = NEW.status,
        travelled_at = NEW.travelled_at
    WHERE journey_id = OLD.trip_id;

    UPDATE travel_orders
    SET order_status = NEW.status
    WHERE order_id = CONCAT('ORD-', OLD.trip_id);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_metro_travel_history_update
INSTEAD OF UPDATE ON metro_travel_history
FOR EACH ROW
EXECUTE FUNCTION trg_metro_travel_history_update_func();


-- 3. payments View
CREATE OR REPLACE VIEW payments AS
SELECT
    pt.payment_id,
    CASE WHEN to_tbl.network_type = 'national_rail' THEN SUBSTRING(pt.order_id FROM 5) ELSE NULL END AS booking_id,
    CASE WHEN to_tbl.network_type = 'metro' THEN SUBSTRING(pt.order_id FROM 5) ELSE NULL END AS metro_trip_id,
    pt.amount_usd,
    COALESCE(pi.method_type, 'unspecified') AS method,
    pt.payment_status AS status,
    pt.processed_at AS paid_at
FROM payment_transactions pt
JOIN travel_orders to_tbl ON to_tbl.order_id = pt.order_id
LEFT JOIN payment_instruments pi ON pi.payment_instrument_id = pt.payment_instrument_id;

-- payments INSTEAD OF INSERT Trigger
-- distinguishes between national rail and metro bookings by checking if booking_id or metro_trip_id is not null
-- Then inserts the payment transaction into the payment_transactions table 
CREATE OR REPLACE FUNCTION trg_payments_insert_func()
RETURNS TRIGGER AS $$
DECLARE
    v_order_id TEXT;
    v_user_id TEXT;
    v_method_type TEXT;
    v_payment_instrument_id TEXT;
BEGIN
    IF NEW.booking_id IS NULL AND NEW.metro_trip_id IS NULL THEN
        RAISE EXCEPTION 'Either booking_id or metro_trip_id must be provided for payment %', NEW.payment_id;
    END IF;

    v_order_id := CONCAT('ORD-', COALESCE(NEW.booking_id, NEW.metro_trip_id));

    SELECT user_id
    INTO v_user_id
    FROM travel_orders
    WHERE order_id = v_order_id;

    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'No travel order found for payment % and order %', NEW.payment_id, v_order_id;
    END IF;

    v_method_type := COALESCE(NULLIF(NEW.method, ''), 'credit_card');
    v_payment_instrument_id := CONCAT('PMI-', v_user_id, '-', v_method_type);

    -- Store the mock payment method as a reusable seeded instrument for the user.
    INSERT INTO payment_instruments (
        payment_instrument_id, user_id, method_type, provider_name,
        token_ref, last4, is_active, created_at
    ) VALUES (
        v_payment_instrument_id,
        v_user_id,
        v_method_type,
        'mock',
        CONCAT('mock-token-', v_user_id, '-', v_method_type),
        CASE WHEN v_method_type IN ('credit_card', 'debit_card') THEN '0000' ELSE NULL END,
        TRUE,
        NOW()
    ) ON CONFLICT (payment_instrument_id) DO NOTHING;

    INSERT INTO payment_transactions (
        payment_id, order_id, payment_instrument_id, transaction_type,
        amount_usd, currency_code, payment_status, gateway_reference, processed_at
    ) VALUES (
        NEW.payment_id,
        v_order_id,
        v_payment_instrument_id,
        CASE WHEN NEW.status = 'refunded' THEN 'refund'::TEXT ELSE 'charge'::TEXT END,
        NEW.amount_usd,
        'USD',
        NEW.status,
        NULL,
        COALESCE(NEW.paid_at, NOW())
    ) ON CONFLICT (payment_id) DO UPDATE SET
        payment_instrument_id = EXCLUDED.payment_instrument_id,
        payment_status = EXCLUDED.payment_status,
        processed_at = EXCLUDED.processed_at;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_payments_insert
INSTEAD OF INSERT ON payments
FOR EACH ROW
EXECUTE FUNCTION trg_payments_insert_func();


-- 4. feedback View
-- Similar to the method implemented for national_rail_bookings view
CREATE OR REPLACE VIEW feedback AS
SELECT
    jf.feedback_id,
    jf.user_id,
    CASE WHEN to_tbl.network_type = 'national_rail' THEN jf.journey_id ELSE NULL END AS booking_id,
    CASE WHEN to_tbl.network_type = 'metro' THEN jf.journey_id ELSE NULL END AS metro_trip_id,
    jf.rating,
    jf.comment,
    jf.submitted_at
FROM journey_feedback jf
JOIN travel_journeys tj ON tj.journey_id = jf.journey_id
JOIN travel_orders to_tbl ON to_tbl.order_id = tj.order_id;

-- feedback INSTEAD OF INSERT Trigger
CREATE OR REPLACE FUNCTION trg_feedback_insert_func()
RETURNS TRIGGER AS $$
DECLARE
    v_journey_id TEXT;
BEGIN
    v_journey_id := COALESCE(NEW.booking_id, NEW.metro_trip_id);

    INSERT INTO journey_feedback (
        feedback_id, journey_id, user_id, rating, comment, submitted_at
    ) VALUES (
        NEW.feedback_id,
        v_journey_id,
        NEW.user_id,
        NEW.rating,
        NEW.comment,
        COALESCE(NEW.submitted_at, NOW())
    ) ON CONFLICT (feedback_id) DO UPDATE SET
        rating = EXCLUDED.rating,
        comment = EXCLUDED.comment,
        submitted_at = EXCLUDED.submitted_at;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_feedback_insert
INSTEAD OF INSERT ON feedback
FOR EACH ROW
EXECUTE FUNCTION trg_feedback_insert_func();

-- 5. Triggers for registered_users INSERT
-- Same as the last version
CREATE OR REPLACE FUNCTION trg_registered_users_insert_func()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO user_profiles (
        user_id, full_name, first_name, surname, phone, date_of_birth, is_active, registered_at
    ) VALUES (
        NEW.user_id,
        COALESCE(NEW.full_name, CONCAT(NEW.first_name, ' ', NEW.surname)),
        COALESCE(NEW.first_name, ''),
        COALESCE(NEW.surname, ''),
        NEW.phone,
        COALESCE(NEW.date_of_birth, '1970-01-01'::DATE),
        COALESCE(NEW.is_active, TRUE),
        COALESCE(NEW.registered_at, NOW())
    )
    ON CONFLICT (user_id) DO NOTHING;

    IF NEW.email IS NOT NULL THEN
        INSERT INTO user_auth_credentials (
            user_id, login_email, password_hash, password_algo, password_hash_params
        ) VALUES (
            NEW.user_id,
            NEW.email,
            '',
            'argon2id',
            'm=65536,t=3,p=4'
        )
        ON CONFLICT (user_id) DO UPDATE
        SET login_email = EXCLUDED.login_email;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_registered_users_insert
INSTEAD OF INSERT ON registered_users
FOR EACH ROW
EXECUTE FUNCTION trg_registered_users_insert_func();

-- Triggers for user_credentials INSERT
CREATE OR REPLACE FUNCTION trg_user_credentials_insert_func()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO user_auth_credentials (
        user_id, login_email, password_hash, password_algo, password_hash_params, password_changed_at
    ) VALUES (
        NEW.user_id,
        CONCAT(NEW.user_id, '@placeholder.local'),
        NEW.password_hash,
        COALESCE(NEW.hashing_algorithm, 'argon2id'),
        'm=65536,t=3,p=4',
        COALESCE(NEW.updated_at, NOW())
    )
    ON CONFLICT (user_id) DO UPDATE SET
        password_hash = EXCLUDED.password_hash,
        password_algo = COALESCE(EXCLUDED.password_algo, user_auth_credentials.password_algo),
        password_changed_at = COALESCE(EXCLUDED.password_changed_at, user_auth_credentials.password_changed_at);

    IF NEW.secret_question IS NOT NULL AND NEW.secret_answer_hash IS NOT NULL THEN
        INSERT INTO user_recovery_factors (
            recovery_factor_id, user_id, factor_type, question_text, answer_hash, created_at
        ) VALUES (
            CONCAT('RF-', NEW.user_id),
            NEW.user_id,
            'security_question',
            NEW.secret_question,
            NEW.secret_answer_hash,
            COALESCE(NEW.updated_at, NOW())
        )
        ON CONFLICT (recovery_factor_id) DO NOTHING;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_user_credentials_insert
INSTEAD OF INSERT ON user_credentials
FOR EACH ROW
EXECUTE FUNCTION trg_user_credentials_insert_func();

-- Triggers for user_credentials UPDATE
CREATE OR REPLACE FUNCTION trg_user_credentials_update_func()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE user_auth_credentials
    SET password_hash = NEW.password_hash,
        password_changed_at = COALESCE(NEW.updated_at, NOW())
    WHERE user_id = OLD.user_id;

    IF NEW.secret_question IS NOT NULL OR NEW.secret_answer_hash IS NOT NULL THEN
        INSERT INTO user_recovery_factors (
            recovery_factor_id, user_id, factor_type, question_text, answer_hash, created_at
        ) VALUES (
            CONCAT('RF-', OLD.user_id),
            OLD.user_id,
            'security_question',
            COALESCE(NEW.secret_question, ''),
            COALESCE(NEW.secret_answer_hash, ''),
            NOW()
        )
        ON CONFLICT (recovery_factor_id) DO UPDATE SET
            question_text = EXCLUDED.question_text,
            answer_hash = EXCLUDED.answer_hash;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_user_credentials_update
INSTEAD OF UPDATE ON user_credentials
FOR EACH ROW
EXECUTE FUNCTION trg_user_credentials_update_func();

-- ---------------------------------------------------------------------------
-- Indexes for query speed
-- ---------------------------------------------------------------------------

-- Network lookup
CREATE INDEX idx_stations_network_type
ON stations (network_type);

CREATE INDEX idx_station_lines_line
ON station_lines (line_id, station_id);

CREATE INDEX idx_station_adjacencies_from
ON station_adjacencies (from_station_id, line_id);

CREATE INDEX idx_station_adjacencies_to
ON station_adjacencies (to_station_id, line_id);

-- Schedule / stop lookup
CREATE INDEX idx_service_schedules_network_line
ON service_schedules (network_type, line_id);

CREATE INDEX idx_schedule_stations_station
ON schedule_stations (station_id, schedule_id, sequence_no);

CREATE INDEX idx_schedule_stations_schedule_station
ON schedule_stations (schedule_id, station_id);

-- Fare lookup
CREATE INDEX idx_schedule_fares_lookup
ON schedule_fares (schedule_id, fare_class_code);

-- Seat lookup
CREATE INDEX idx_seat_layouts_schedule
ON seat_layouts (schedule_id);

CREATE INDEX idx_seat_layout_seats_layout
ON seat_layout_seats (layout_id, seat_code);

CREATE INDEX idx_seat_layout_seats_coach_row
ON seat_layout_seats (coach_id, seat_row, seat_column);

-- Booking and history lookup (Optimized for normalized travel_orders and travel_journeys tables)
CREATE INDEX idx_travel_orders_user_purchased
ON travel_orders (user_id, purchased_at DESC);

CREATE INDEX idx_travel_journeys_sched_date_status
ON travel_journeys (schedule_id, travel_date, journey_status);

CREATE INDEX idx_travel_journeys_travel_date
ON travel_journeys (travel_date DESC);

CREATE INDEX idx_payment_transactions_order
ON payment_transactions (order_id);

CREATE INDEX idx_payment_instruments_user
ON payment_instruments (user_id);

-- Refund policy lookup
-- CREATE INDEX idx_refund_policies_lookup
-- ON refund_policies (network_type, service_type, is_active);

-- CREATE INDEX idx_refund_policy_windows_policy
-- ON refund_policy_windows (policy_id, hours_before_departure_min, hours_before_departure_max);

-- Policy vector search fallback index.
-- For small seed data, sequential scan is fine.
CREATE INDEX idx_policy_documents_category
ON policy_documents (category);
