-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
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


-- Station tables
CREATE TABLE IF NOT EXISTS metro_stations (
    station_id VARCHAR(20) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines TEXT[],
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_lines TEXT[],
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_station_id VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS national_rail_stations (
    station_id VARCHAR(20) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines TEXT[],
    is_interchange_national_rail BOOLEAN DEFAULT FALSE,
    interchange_national_rail_lines TEXT[],
    is_interchange_metro BOOLEAN DEFAULT FALSE,
    interchange_metro_station_id VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS station_interchanges (
    interchange_id SERIAL PRIMARY KEY,
    metro_station_id VARCHAR(20) REFERENCES metro_stations(station_id),
    rail_station_id VARCHAR(20) REFERENCES national_rail_stations(station_id),
    transfer_time_min INTEGER DEFAULT 5,
    UNIQUE (metro_station_id, rail_station_id)
);


-- Schedule tables
CREATE TABLE IF NOT EXISTS metro_schedules (
    schedule_id VARCHAR(30) PRIMARY KEY,
    line VARCHAR(20) NOT NULL,
    direction VARCHAR(30),
    origin_station_id VARCHAR(20) REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(20) REFERENCES metro_stations(station_id),
    first_train_time TIME,
    last_train_time TIME,
    base_fare_usd NUMERIC(10,2),
    per_stop_rate_usd NUMERIC(10,2),
    frequency_min INTEGER,
    operates_on TEXT[]
);

CREATE TABLE IF NOT EXISTS metro_schedule_stops (
    schedule_id VARCHAR(30) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id VARCHAR(20) REFERENCES metro_stations(station_id),
    stop_order INTEGER NOT NULL,
    travel_time_from_origin_min INTEGER,
    PRIMARY KEY (schedule_id, stop_order),
    UNIQUE (schedule_id, station_id)
);

CREATE TABLE IF NOT EXISTS national_rail_schedules (
    schedule_id VARCHAR(30) PRIMARY KEY,
    line VARCHAR(20) NOT NULL,
    service_type VARCHAR(30),
    direction VARCHAR(30),
    origin_station_id VARCHAR(20) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(20) REFERENCES national_rail_stations(station_id),
    first_train_time TIME,
    last_train_time TIME,
    frequency_min INTEGER,
    operates_on TEXT[]
);

CREATE TABLE IF NOT EXISTS national_rail_schedule_stops (
    schedule_id VARCHAR(30) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id VARCHAR(20) REFERENCES national_rail_stations(station_id),
    stop_order INTEGER NOT NULL,
    travel_time_from_origin_min INTEGER,
    PRIMARY KEY (schedule_id, stop_order),
    UNIQUE (schedule_id, station_id)
);

CREATE TABLE IF NOT EXISTS national_rail_fare_classes (
    schedule_id VARCHAR(30) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class VARCHAR(30),
    base_fare_usd NUMERIC(10,2),
    per_stop_rate_usd NUMERIC(10,2),
    PRIMARY KEY (schedule_id, fare_class)
);

-- Seat layout tables
CREATE TABLE IF NOT EXISTS national_rail_seat_layouts (
    layout_id VARCHAR(30) PRIMARY KEY,
    schedule_id VARCHAR(30) NOT NULL UNIQUE REFERENCES national_rail_schedules(schedule_id)
);

CREATE TABLE IF NOT EXISTS national_rail_coaches (
    layout_id VARCHAR(30) REFERENCES national_rail_seat_layouts(layout_id) ON DELETE CASCADE,
    coach VARCHAR(10),
    fare_class VARCHAR(30),
    PRIMARY KEY (layout_id, coach)
);

CREATE TABLE IF NOT EXISTS national_rail_seats (
    layout_id VARCHAR(30),
    coach VARCHAR(10),
    seat_id VARCHAR(10),
    seat_row INTEGER,
    seat_column VARCHAR(10),
    fare_class VARCHAR(30),
    PRIMARY KEY (layout_id, coach, seat_id),
    FOREIGN KEY (layout_id, coach)
        REFERENCES national_rail_coaches(layout_id, coach)
        ON DELETE CASCADE
);

-- User tables
CREATE TABLE IF NOT EXISTS registered_users (
    user_id VARCHAR(20) PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    surname VARCHAR(50) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    phone VARCHAR(30),
    date_of_birth DATE,
    registered_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS user_credentials (
    credential_id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(20) UNIQUE NOT NULL
        REFERENCES registered_users(user_id)
        ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    hashing_algorithm VARCHAR(50) DEFAULT 'argon2id',
    secret_question TEXT,
    secret_answer_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- transaction tables
CREATE TABLE IF NOT EXISTS national_rail_bookings (
    booking_id VARCHAR(30) PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL REFERENCES registered_users(user_id),
    schedule_id VARCHAR(30) NOT NULL REFERENCES national_rail_schedules(schedule_id),
    origin_station_id VARCHAR(20) NOT NULL REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(20) NOT NULL REFERENCES national_rail_stations(station_id),
    travel_date DATE NOT NULL,
    departure_time TIME NOT NULL,
    ticket_type VARCHAR(30) NOT NULL,
    fare_class VARCHAR(30) NOT NULL,
    layout_id VARCHAR(30) NOT NULL REFERENCES national_rail_seat_layouts(layout_id),
    coach VARCHAR(10) NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    stops_travelled INTEGER NOT NULL,
    amount_usd NUMERIC(10,2) NOT NULL,
    status VARCHAR(30) NOT NULL,
    booked_at TIMESTAMPTZ,
    travelled_at TIMESTAMPTZ,
    FOREIGN KEY (layout_id, coach, seat_id)
        REFERENCES national_rail_seats(layout_id, coach, seat_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_rail_seat
ON national_rail_bookings (schedule_id, travel_date, coach, seat_id)
WHERE status IN ('confirmed', 'completed');

CREATE TABLE IF NOT EXISTS metro_travel_history (
    trip_id VARCHAR(30) PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL REFERENCES registered_users(user_id),
    schedule_id VARCHAR(30) NOT NULL REFERENCES metro_schedules(schedule_id),
    origin_station_id VARCHAR(20) NOT NULL REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(20) NOT NULL REFERENCES metro_stations(station_id),
    travel_date DATE NOT NULL,
    ticket_type VARCHAR(30) NOT NULL,
    day_pass_ref VARCHAR(30) REFERENCES metro_travel_history(trip_id),
    stops_travelled INTEGER,
    amount_usd NUMERIC(10,2) NOT NULL,
    status VARCHAR(30) NOT NULL,
    purchased_at TIMESTAMPTZ,
    travelled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(30) PRIMARY KEY,
    booking_id VARCHAR(30) REFERENCES national_rail_bookings(booking_id),
    metro_trip_id VARCHAR(30) REFERENCES metro_travel_history(trip_id),
    amount_usd NUMERIC(10,2),
    method VARCHAR(50),
    status VARCHAR(30),
    paid_at TIMESTAMPTZ,
    CHECK (
        (booking_id IS NOT NULL AND metro_trip_id IS NULL)
        OR
        (booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id VARCHAR(30) PRIMARY KEY,
    user_id VARCHAR(20) REFERENCES registered_users(user_id),
    booking_id VARCHAR(30) REFERENCES national_rail_bookings(booking_id),
    metro_trip_id VARCHAR(30) REFERENCES metro_travel_history(trip_id),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    submitted_at TIMESTAMPTZ,
    CHECK (
        (booking_id IS NOT NULL AND metro_trip_id IS NULL)
        OR
        (booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);



-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,  -- 'refund', 'booking', 'conduct'
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);
