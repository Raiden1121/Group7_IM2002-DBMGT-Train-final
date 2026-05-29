-- TransitFlow relational schema.sql
-- Compatible with the current agent.py / databases/relational/queries.py table names.
-- Design goal:
--   1. Keep the Python query layer working with names such as metro_schedules,
--      national_rail_schedules, national_rail_bookings, registered_users, etc.
--   2. Still keep the core structure reasonably normalized:
--      lines / stations / service_schedules / schedule_stations / schedule_fares
--      plus seat layout tables and policy/refund support tables.
--
-- Recommended location:
--   databases/relational/schema.sql

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

DROP TABLE IF EXISTS refund_policy_windows CASCADE;
DROP TABLE IF EXISTS refund_policy_ticket_types CASCADE;
DROP TABLE IF EXISTS refund_policies CASCADE;

DROP TABLE IF EXISTS policy_documents CASCADE;

DROP TABLE IF EXISTS auth_login_audit CASCADE;
DROP TABLE IF EXISTS user_recovery_factors CASCADE;
DROP TABLE IF EXISTS user_auth_credentials CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;

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
    line_id        TEXT PRIMARY KEY,
    network_type   TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    line_name      TEXT NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE stations (
    station_id      TEXT PRIMARY KEY,
    network_type    TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    station_name    TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE station_lines (
    station_id  TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    line_id     TEXT NOT NULL REFERENCES lines(line_id) ON DELETE CASCADE,
    PRIMARY KEY (station_id, line_id)
);

-- Cross-network transfer, e.g. MS01 <-> NR01.
-- Same-system interchange does not need to be stored here; it is represented by station_lines.
CREATE TABLE station_transfers (
    from_station_id   TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    to_station_id     TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    transfer_type     TEXT NOT NULL CHECK (
        transfer_type IN ('metro_to_rail', 'rail_to_metro', 'metro_to_metro', 'rail_to_rail')
    ),
    walking_time_min  INTEGER NOT NULL DEFAULT 0 CHECK (walking_time_min >= 0),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (from_station_id, to_station_id)
);

-- Directed adjacency: A -> B and B -> A should be inserted as separate rows.
CREATE TABLE station_adjacencies (
    adjacency_id      BIGSERIAL PRIMARY KEY,
    from_station_id   TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    to_station_id     TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    line_id           TEXT NOT NULL REFERENCES lines(line_id) ON DELETE CASCADE,
    travel_time_min   INTEGER NOT NULL CHECK (travel_time_min > 0),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (from_station_id, to_station_id, line_id)
);

-- ---------------------------------------------------------------------------
-- B. Schedules and stops
-- ---------------------------------------------------------------------------

CREATE TABLE service_schedules (
    schedule_id             TEXT PRIMARY KEY,
    line_id                 TEXT NOT NULL REFERENCES lines(line_id),
    network_type            TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    service_type            TEXT NULL CHECK (service_type IS NULL OR service_type IN ('normal', 'express')),
    direction               TEXT NOT NULL,
    origin_station_id       TEXT NOT NULL REFERENCES stations(station_id),
    destination_station_id  TEXT NOT NULL REFERENCES stations(station_id),
    first_train_time        TIME NOT NULL,
    last_train_time         TIME NOT NULL,
    frequency_min           INTEGER NOT NULL CHECK (frequency_min > 0),
    is_active               BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE schedule_operating_days (
    schedule_id   TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week   TEXT NOT NULL CHECK (day_of_week IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

CREATE TABLE schedule_stations (
    schedule_id                  TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    sequence_no                  INTEGER NOT NULL CHECK (sequence_no >= 1),
    station_id                   TEXT NOT NULL REFERENCES stations(station_id),
    stops_here                   BOOLEAN NOT NULL DEFAULT TRUE,
    travel_time_from_origin_min  INTEGER NOT NULL CHECK (travel_time_from_origin_min >= 0),
    PRIMARY KEY (schedule_id, sequence_no),
    UNIQUE (schedule_id, station_id)
);

-- ---------------------------------------------------------------------------
-- C. Fares and ticket types
-- ---------------------------------------------------------------------------

CREATE TABLE ticket_types (
    ticket_type   TEXT PRIMARY KEY CHECK (ticket_type IN ('single', 'return', 'day_pass')),
    display_name  TEXT NOT NULL,
    description   TEXT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE ticket_type_network_rules (
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

-- fare_class_code:
--   national rail: 'standard', 'first'
--   metro:         'metro_single'
CREATE TABLE schedule_fares (
    schedule_id        TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    fare_class_code    TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first', 'metro_single')),
    base_fare_usd      NUMERIC(10,2) NOT NULL CHECK (base_fare_usd >= 0),
    per_stop_rate_usd  NUMERIC(10,2) NOT NULL CHECK (per_stop_rate_usd >= 0),
    currency_code      CHAR(3) NOT NULL DEFAULT 'USD',
    PRIMARY KEY (schedule_id, fare_class_code)
);

-- ---------------------------------------------------------------------------
-- D. National rail seat layouts
-- ---------------------------------------------------------------------------

CREATE TABLE seat_layouts (
    layout_id      TEXT PRIMARY KEY,
    schedule_id    TEXT NOT NULL UNIQUE REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    layout_version TEXT NOT NULL DEFAULT '1.0',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE seat_layout_coaches (
    coach_id         BIGSERIAL PRIMARY KEY,
    layout_id        TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_code       TEXT NOT NULL,
    fare_class_code  TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    UNIQUE (layout_id, coach_code),
    UNIQUE (coach_id, layout_id)
);

CREATE TABLE seat_layout_seats (
    seat_pk      BIGSERIAL PRIMARY KEY,
    layout_id    TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_id     BIGINT NOT NULL REFERENCES seat_layout_coaches(coach_id) ON DELETE CASCADE,
    seat_code    TEXT NOT NULL,
    seat_row     INTEGER NOT NULL CHECK (seat_row >= 1),
    seat_column  TEXT NOT NULL,
    UNIQUE (layout_id, seat_code),
    UNIQUE (coach_id, seat_code)
);

-- ---------------------------------------------------------------------------
-- E. Users and authentication
-- ---------------------------------------------------------------------------

CREATE TABLE user_profiles (
    user_id        TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    first_name     TEXT NOT NULL,
    surname        TEXT NOT NULL,
    phone          TEXT NULL,
    date_of_birth  DATE NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_auth_credentials (
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
    recovery_factor_id  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    factor_type         TEXT NOT NULL DEFAULT 'security_question',
    question_text       TEXT NOT NULL,
    answer_hash         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at          TIMESTAMPTZ NULL
);

CREATE TABLE auth_login_audit (
    audit_id               BIGSERIAL PRIMARY KEY,
    user_id                TEXT NULL REFERENCES user_profiles(user_id) ON DELETE SET NULL,
    login_email_attempted  TEXT NOT NULL,
    ip_hash                TEXT NULL,
    user_agent_hash        TEXT NULL,
    result                 TEXT NOT NULL CHECK (result IN ('success', 'failed', 'locked')),
    occurred_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- F. Booking / travel history
-- ---------------------------------------------------------------------------

CREATE TABLE travel_orders (
    order_id          TEXT PRIMARY KEY,
    order_code        TEXT NOT NULL UNIQUE,
    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    network_type      TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    product_type      TEXT NOT NULL REFERENCES ticket_types(ticket_type),
    order_status      TEXT NOT NULL CHECK (order_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    total_amount_usd  NUMERIC(10,2) NOT NULL CHECK (total_amount_usd >= 0),
    currency_code     CHAR(3) NOT NULL DEFAULT 'USD',
    purchased_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE travel_journeys (
    journey_id              TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES travel_orders(order_id) ON DELETE CASCADE,
    journey_sequence_no     INTEGER NOT NULL CHECK (journey_sequence_no >= 1),
    schedule_id             TEXT NOT NULL REFERENCES service_schedules(schedule_id),
    origin_station_id       TEXT NOT NULL REFERENCES stations(station_id),
    destination_station_id  TEXT NOT NULL REFERENCES stations(station_id),
    travel_date             DATE NOT NULL,
    departure_time          TIME NULL,
    travelled_at            TIMESTAMPTZ NULL,
    journey_status          TEXT NOT NULL CHECK (journey_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    stops_travelled         INTEGER NULL CHECK (stops_travelled >= 0),
    allocated_amount_usd    NUMERIC(10,2) NOT NULL CHECK (allocated_amount_usd >= 0),
    UNIQUE (order_id, journey_sequence_no)
);

CREATE TABLE rail_journey_reservations (
    journey_id          TEXT PRIMARY KEY REFERENCES travel_journeys(journey_id) ON DELETE CASCADE,
    schedule_id         TEXT NOT NULL REFERENCES service_schedules(schedule_id),
    travel_date         DATE NOT NULL,
    fare_class_code     TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    coach_id            BIGINT NOT NULL REFERENCES seat_layout_coaches(coach_id) ON DELETE CASCADE,
    seat_pk             BIGINT NOT NULL REFERENCES seat_layout_seats(seat_pk) ON DELETE CASCADE,
    seat_reserved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reservation_status  TEXT NOT NULL CHECK (reservation_status IN ('active', 'cancelled'))
);

-- Implement the unique partial index, which means that only the active seat reservations 
-- Technical Note or learning please refer to Notion LOL
CREATE UNIQUE INDEX uq_active_seat_reservation
ON rail_journey_reservations (schedule_id, travel_date, seat_pk)
WHERE reservation_status = 'active';


-- ---------------------------------------------------------------------------
-- G. Payments
-- ---------------------------------------------------------------------------
CREATE TABLE payment_instruments (
    payment_instrument_id TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    method_type           TEXT NOT NULL CHECK (method_type IN ('credit_card', 'debit_card', 'ewallet')),
    provider_name         TEXT NULL,
    token_ref             TEXT NOT NULL,
    last4                 TEXT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE payment_transactions (
    payment_id            TEXT PRIMARY KEY,
    order_id              TEXT NOT NULL REFERENCES travel_orders(order_id) ON DELETE CASCADE,
    payment_instrument_id TEXT NULL REFERENCES payment_instruments(payment_instrument_id) ON DELETE SET NULL,
    transaction_type      TEXT NOT NULL CHECK (transaction_type IN ('charge', 'refund')),
    amount_usd            NUMERIC(10,2) NOT NULL CHECK (amount_usd >= 0),
    currency_code         CHAR(3) NOT NULL DEFAULT 'USD',
    payment_status        TEXT NOT NULL CHECK (payment_status IN ('pending', 'paid', 'failed', 'refunded')),
    gateway_reference     TEXT NULL,
    processed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ref_payment_id        TEXT NULL REFERENCES payment_transactions(payment_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------------
-- H. Feedback
-- ---------------------------------------------------------------------------
CREATE TABLE journey_feedback (
    feedback_id    TEXT PRIMARY KEY,
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

-- ---------------------------------------------------------------------------
-- H. Vector / RAG documents
-- ---------------------------------------------------------------------------

-- pgvector dimension is intentionally not fixed here because different LLM
-- embedding providers may return different dimensions. For a large production
-- system, set a fixed dimension and add an IVFFLAT/HNSW index.
CREATE TABLE policy_documents (
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
FROM schedule_stations;

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
FROM schedule_stations;

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
    uac.login_email AS email,
    up.first_name,
    up.surname,
    up.full_name,
    up.phone,
    up.date_of_birth,
    up.registered_at,
    up.is_active
FROM user_profiles up
LEFT JOIN user_auth_credentials uac ON uac.user_id = up.user_id;

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

-- Triggers for registered_users INSERT
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
        '',
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

-- Booking and history lookup
CREATE INDEX idx_national_rail_bookings_user_time
ON national_rail_bookings (user_id, travel_date DESC, booked_at DESC);

CREATE INDEX idx_national_rail_bookings_schedule_date_status
ON national_rail_bookings (schedule_id, travel_date, status);

CREATE INDEX idx_metro_travel_history_user_time
ON metro_travel_history (user_id, travel_date DESC, purchased_at DESC);

CREATE INDEX idx_payment_transactions_order
ON payment_transactions (order_id);

CREATE INDEX idx_payment_instruments_user
ON payment_instruments (user_id);

-- Refund policy lookup
CREATE INDEX idx_refund_policies_lookup
ON refund_policies (network_type, service_type, is_active);

CREATE INDEX idx_refund_policy_windows_policy
ON refund_policy_windows (policy_id, hours_before_departure_min, hours_before_departure_max);

-- Policy vector search fallback index.
-- For small seed data, sequential scan is fine.
CREATE INDEX idx_policy_documents_category
ON policy_documents (category);
