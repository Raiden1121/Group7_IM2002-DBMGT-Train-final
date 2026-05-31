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
-- 0529 ver.
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

-- ===========================================================================
-- GLOBAL DATABASE DESIGN DECISIONS (教授的設計抉擇筆記)
-- ===========================================================================
--
-- 1. 主鍵設計決策 (Primary Key Choices):
--    - 採用 TEXT 作為 PK 的資料表 (如 stations, lines, service_schedules, user_profiles, travel_orders, travel_journeys, payment_instruments, payment_transactions):
--      * 理由: 這些實體的主鍵代表了「自然/業務鍵 (Natural Keys)」或來自外部整合系統定義的標準業務代碼（例如車站代碼 "MS01", 訂單號 "BK-A3F9D1"）。
--      * 優勢: 提高日誌分析與 Debug 的可讀性、方便跨系統 API 對接，且能避免數值型自增序列可能產生的業務識別斷層。
--    - 採用 BIGSERIAL / SERIAL 作為 PK 的資料表 (如 station_adjacencies, seat_layout_coaches, seat_layout_seats, auth_login_audit):
--      * 理由: 這些表為高頻寫入、系統自動生成，且通常用於記錄純內部關聯或日誌審計。
--      * 優勢: 使用數值代理主鍵 (Surrogate Keys) 可縮小索引空間 (Index Size)、大幅提升 Join 查詢速度與資料插入效能，且無須在應用程式端額外計算唯一 ID。
--
-- 2. 刪除策略設計 (Delete Strategy Decisions):
--    - 我們採用「混合式資料生命週期管理策略」(Hybrid Delete Strategy):
--      - 軟刪除 (Soft Delete - is_active BOOLEAN):
--        * 應用於: 系統的核心主資料 (Master Data) 與實體，如 lines, stations, service_schedules, ticket_types, user_profiles, payment_instruments。
--        * 理由: 即使某條線路或站點停用，其歷史訂單及行程記錄仍必須在資料庫中永久保留以供歷史對帳、退票及業務審計使用。
--      - 硬刪除與級聯刪除 (Hard Delete - ON DELETE CASCADE / RESTRICT):
--        * 應用於: 相依且無獨立生命週期的子表 (Child Tables)，如 station_lines, schedule_operating_days, schedule_stations, seat_layouts, user_auth_credentials, user_recovery_factors 等。
--        * 理由: 當父表實體被刪除時，其相依屬性便毫無業務意義，此時透過 ON DELETE CASCADE 強制將其一併清理，可維護 Referential Integrity 並防範垃圾資料殘留。
--
-- 3. 外鍵級聯行為 (Foreign Key Cascade Behaviour):
--    - 所有外鍵皆顯式聲明其級聯行為 (Explicitly Declared):
--      - ON DELETE CASCADE: 用於從屬的弱實體表，如行程座位、車廂配置等，父表消失則子表連帶消失。
--      - ON DELETE RESTRICT: 用於強實體之間的關聯表，如行程參考車站或班表。若車站已被行程所參考，則此車站禁止被刪除，防止產生懸空指針 (Dangling References)。
--      - ON DELETE SET NULL: 用於關聯性稍弱的日誌與外部交易關聯（如付款工具被刪時，交易記錄的 instrument 欄位設為 NULL），保留交易金額以供審計。
--
-- ===========================================================================

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
    -- [PK design decision: TEXT] 採用外部定義的標準路線代碼（如 'METRO_BLUE'），有利於日誌可讀性與系統對接。
    line_id        TEXT PRIMARY KEY,
    network_type   TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    line_name      TEXT NOT NULL,
    -- [Delete strategy: Soft Delete] 線路停用時設為 FALSE，確保歷史票卡與乘車記錄仍可被審計。
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_lines_id_network UNIQUE (line_id, network_type)
);

CREATE TABLE stations (
    -- [PK design decision: TEXT] 採用標準的車站自然業務編碼（如 'MS01'），易於 Debug 及路網建模。
    station_id      TEXT PRIMARY KEY,
    network_type    TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    station_name    TEXT NOT NULL,
    -- [Delete strategy: Soft Delete] 車站停用時設為 FALSE，避免破壞現存的乘車歷史記錄。
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_stations_id_network UNIQUE (station_id, network_type)
);

CREATE TABLE station_lines (
    -- [PK design decision: Composite] 複合主鍵，由車站與路線共同定義，天然唯一。
    -- [FK cascade behaviour: ON DELETE CASCADE] 當對應的車站或路線被硬刪除時，其站點與線路的隸屬關係已無業務意義，故級聯刪除。
    station_id  TEXT NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
    line_id     TEXT NOT NULL REFERENCES lines(line_id) ON DELETE CASCADE,
    PRIMARY KEY (station_id, line_id)
);

-- Cross-network transfer, e.g. MS01 <-> NR01.
-- Same-system interchange does not need to be stored here; it is represented by station_lines.
CREATE TABLE station_transfers (
    -- [PK design decision: Composite] 複合主鍵，唯一識別從 A 車站轉乘到 B 車站的轉換路徑。
    -- [FK cascade behaviour: ON DELETE CASCADE] 車站硬刪除時，相關的轉乘通道定義一併刪除。
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
    -- [PK design decision: BIGSERIAL] 內部生成的高頻路網鄰接邊，使用自增代理主鍵以提升 Join 的效能。
    adjacency_id      BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 當所屬車站或路線硬刪除時，鄰接邊隨之級聯刪除。
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
    -- [PK design decision: TEXT] 採用班表/車次自然代碼（如 'NR_SCH01'），便於營運調度與客戶查詢。
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
    -- [Delete strategy: Soft Delete] 班表停用時將 is_active 設為 FALSE，以利分析歷史班次績效。
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_schedules_id_network UNIQUE (schedule_id, network_type),
    -- [FK cascade behaviour: ON DELETE CASCADE] 所屬路線硬刪除時，其下屬班表自動隨之級聯刪除。
    CONSTRAINT fk_schedules_line_network FOREIGN KEY (line_id, network_type) REFERENCES lines(line_id, network_type) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE RESTRICT] 若某個車站是某班表的起點或終點，嚴禁直接刪除該車站，確保引用的參考完整性。
    CONSTRAINT fk_schedules_origin_station_network FOREIGN KEY (origin_station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT,
    CONSTRAINT fk_schedules_dest_station_network FOREIGN KEY (destination_station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT
);

CREATE TABLE schedule_operating_days (
    -- [PK design decision: Composite] 複合主鍵，包含班次 ID 與星期，精準表達其服務週期。
    -- [FK cascade behaviour: ON DELETE CASCADE] 班表硬刪除時，關聯的營運日定義自動隨之級聯刪除。
    schedule_id   TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week   TEXT NOT NULL CHECK (day_of_week IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')),
    PRIMARY KEY (schedule_id, day_of_week)
);

CREATE TABLE schedule_stations (
    -- [PK design decision: Composite] 複合主鍵，由班表代碼與停靠順序序列構成。
    schedule_id                  TEXT NOT NULL,
    network_type                 TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    sequence_no                  INTEGER NOT NULL CHECK (sequence_no >= 1),
    station_id                   TEXT NOT NULL,
    stops_here                   BOOLEAN NOT NULL DEFAULT TRUE,
    travel_time_from_origin_min  INTEGER NOT NULL CHECK (travel_time_from_origin_min >= 0),
    PRIMARY KEY (schedule_id, sequence_no),
    UNIQUE (schedule_id, station_id),
    -- [FK cascade behaviour: ON DELETE CASCADE] 當班表刪除時，其下的所有停靠站序定義自動級聯刪除。
    CONSTRAINT fk_schedule_stations_schedule_network FOREIGN KEY (schedule_id, network_type) REFERENCES service_schedules(schedule_id, network_type) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE RESTRICT] 車站若為某路線班表中的停靠站，嚴禁直接刪除該車站，必須先修改班表。
    CONSTRAINT fk_schedule_stations_station_network FOREIGN KEY (station_id, network_type) REFERENCES stations(station_id, network_type) ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------------
-- C. Fares and ticket types
-- ---------------------------------------------------------------------------

CREATE TABLE ticket_types (
    -- [PK design decision: TEXT] 使用票種業務唯一識別代碼（如 'single', 'return'），防止在票價策略中出現歧義。
    ticket_type   TEXT PRIMARY KEY CHECK (ticket_type IN ('single', 'return', 'day_pass')),
    display_name  TEXT NOT NULL,
    description   TEXT NULL,
    -- [Delete strategy: Soft Delete] 票種退役停售時標記為 FALSE，已售出的歷史訂單仍能追溯其票價屬性。
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO ticket_types (ticket_type, display_name, description) VALUES
('single', 'Single Ticket', 'One-way travel between two stations'),
('return', 'Return Ticket', 'Round-trip travel between two stations'),
('day_pass', 'Day Pass', 'Unlimited travel for a single calendar day')
ON CONFLICT (ticket_type) DO NOTHING;

CREATE TABLE ticket_type_network_rules (
    -- [PK design decision: Composite] 複合主鍵，由票種與鐵路網類型唯一決定某個規則集。
    -- [FK cascade behaviour: ON DELETE CASCADE] 票種刪除時，其鐵路網下的衍生票價规则也一併級聯刪除。
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
    -- [PK design decision: Composite] 複合主鍵，結合班次 ID 與艙等編碼。
    -- [FK cascade behaviour: ON DELETE CASCADE] 班表硬刪除時，關聯的艙等票價定義一併自動級聯刪除。
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

--  Debugging: making sure the search will focus on 'national_rail'
CREATE TABLE seat_layouts (
    -- [PK design decision: TEXT] 採用座位布局物理自然代碼（如 'SL_LAYOUT_A'），對應車輛配置模型。
    layout_id      TEXT PRIMARY KEY,
    schedule_id    TEXT NOT NULL UNIQUE,
    network_type   TEXT NOT NULL DEFAULT 'national_rail' CHECK (network_type = 'national_rail'),
    layout_version TEXT NOT NULL DEFAULT '1.0',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- [FK cascade behaviour: ON DELETE CASCADE] 班次刪除時，對應的座位物理布局資訊隨之級聯刪除。
    CONSTRAINT fk_seat_layouts_schedule_network FOREIGN KEY (schedule_id, network_type) REFERENCES service_schedules(schedule_id, network_type) ON DELETE CASCADE
);

CREATE TABLE seat_layout_coaches (
    -- [PK design decision: BIGSERIAL] 使用自增代理鍵以在後續關聯座位時取得最佳效能。
    coach_id         BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 座位布局配置硬刪除時，其下的所有車廂配置一併級聯刪除。
    layout_id        TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_code       TEXT NOT NULL,
    fare_class_code  TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    UNIQUE (layout_id, coach_code),
    UNIQUE (coach_id, layout_id)
);

CREATE TABLE seat_layout_seats (
    -- [PK design decision: BIGSERIAL] 單一座位代理主鍵，用於實現跨日期高頻預訂與 Lock 查詢。
    seat_pk      BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 車廂或布局被硬刪除時，下屬的具體物理座位一併級聯刪除。
    layout_id    TEXT NOT NULL REFERENCES seat_layouts(layout_id) ON DELETE CASCADE,
    coach_id     BIGINT NOT NULL REFERENCES seat_layout_coaches(coach_id) ON DELETE CASCADE,
    seat_code    TEXT NOT NULL,
    seat_row     INTEGER NOT NULL CHECK (seat_row >= 1),
    seat_column  TEXT NOT NULL,
    UNIQUE (layout_id, seat_code),
    UNIQUE (coach_id, seat_code),
    CONSTRAINT uq_seat_coach UNIQUE (seat_pk, coach_id)
);

-- ---------------------------------------------------------------------------
-- E. Users and authentication
-- ---------------------------------------------------------------------------

CREATE TABLE user_profiles (
    -- [PK design decision: TEXT] 採用固定前綴自增業務自然鍵（如 'RU100234'），方便於客服系統與使用者辨識。
    user_id        TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    first_name     TEXT NOT NULL,
    surname        TEXT NOT NULL,
    phone          TEXT NULL,
    date_of_birth  DATE NOT NULL,
    -- [Delete strategy: Soft Delete] 使用者註銷時將 is_active 設為 FALSE，確保歷史出行訂單記錄仍符合會計法律保留期限。
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_auth_credentials (
    -- [PK design decision: Shared Primary Key (TEXT)] 與 user_profiles 共享一對一主鍵，強化架構安全。
    -- [FK cascade behaviour: ON DELETE CASCADE] 使用者基本資料被永久硬刪除時，敏感的安全憑證資料一併級聯刪除，防止隱私洩漏。
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
    -- [PK design decision: TEXT] 自然恢復要素 ID（如 'RF-RU100234'）。
    recovery_factor_id  TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 用戶刪除時，其密碼找回安全問題一併級聯硬刪除。
    user_id             TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    factor_type         TEXT NOT NULL DEFAULT 'security_question',
    question_text       TEXT NOT NULL,
    answer_hash         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at          TIMESTAMPTZ NULL
);

CREATE TABLE auth_login_audit (
    -- [PK design decision: BIGSERIAL] 登入安全審計記錄，自增流水號，提供高效寫入效能。
    audit_id               BIGSERIAL PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE SET NULL] 若使用者 profile 被刪除，保留此登入安全審計行並設為 NULL，維護整體日誌分析完整性。
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
    -- [PK design decision: TEXT] 訂單唯一自然號（如 'ORD-BK-123456'），易於發票與對帳整合。
    order_id          TEXT PRIMARY KEY,
    order_code        TEXT NOT NULL UNIQUE,
    -- [FK cascade behaviour: ON DELETE CASCADE] 當會員檔案被徹底硬刪除時，其訂單資料一併刪除。
    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    network_type      TEXT NOT NULL CHECK (network_type IN ('metro', 'national_rail')),
    -- [FK cascade behaviour: ON DELETE RESTRICT] 只要此票種還有訂單關聯，嚴禁硬刪除此票種定義。
    product_type      TEXT NOT NULL REFERENCES ticket_types(ticket_type) ON DELETE RESTRICT,
    order_status      TEXT NOT NULL CHECK (order_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    total_amount_usd  NUMERIC(10,2) NOT NULL CHECK (total_amount_usd >= 0),
    currency_code     CHAR(3) NOT NULL DEFAULT 'USD',
    purchased_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE travel_journeys (
    -- [PK design decision: TEXT] 乘車行程自然識別碼（如 'BK-3J8F4A'），通常作為乘車電子憑證 (QR Code) 編碼。
    journey_id              TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 訂單被刪除時，其所包含的行程級聯硬刪除。
    order_id                TEXT NOT NULL REFERENCES travel_orders(order_id) ON DELETE CASCADE,
    journey_sequence_no     INTEGER NOT NULL CHECK (journey_sequence_no >= 1),
    -- [FK cascade behaviour: ON DELETE RESTRICT] 只要此班表有被行程所指派，嚴禁直接硬刪除該班表，必須先取消相關預訂。
    schedule_id             TEXT NOT NULL REFERENCES service_schedules(schedule_id) ON DELETE RESTRICT,
    -- [FK cascade behaviour: ON DELETE RESTRICT] 若起點或終點車站有乘車行程關聯，禁止直接刪除該車站。
    origin_station_id       TEXT NOT NULL REFERENCES stations(station_id) ON DELETE RESTRICT,
    destination_station_id  TEXT NOT NULL REFERENCES stations(station_id) ON DELETE RESTRICT,
    travel_date             DATE NOT NULL,
    departure_time          TIME NULL,
    travelled_at            TIMESTAMPTZ NULL,
    journey_status          TEXT NOT NULL CHECK (journey_status IN ('confirmed', 'completed', 'cancelled', 'refunded')),
    stops_travelled         INTEGER NULL CHECK (stops_travelled >= 0),
    allocated_amount_usd    NUMERIC(10,2) NOT NULL CHECK (allocated_amount_usd >= 0),
    -- [FK cascade behaviour: ON DELETE SET NULL] 若關聯的日票主票券行程被刪除，將此子行程參考設為 NULL。
    day_pass_ref            TEXT NULL REFERENCES travel_journeys(journey_id) ON DELETE SET NULL,
    UNIQUE (order_id, journey_sequence_no),
    CONSTRAINT uq_journeys_id_sched_date UNIQUE (journey_id, schedule_id, travel_date)
);

CREATE TABLE rail_journey_reservations (
    -- [PK design decision: TEXT] 共享 travel_journeys 的行程 ID 主鍵，一對一映射。
    journey_id          TEXT PRIMARY KEY,
    schedule_id         TEXT NOT NULL,
    travel_date         DATE NOT NULL,
    fare_class_code     TEXT NOT NULL CHECK (fare_class_code IN ('standard', 'first')),
    coach_id            BIGINT NOT NULL,
    seat_pk             BIGINT NOT NULL,
    seat_reserved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reservation_status  TEXT NOT NULL CHECK (reservation_status IN ('active', 'cancelled')),
    -- [FK cascade behaviour: ON DELETE CASCADE] 當行程被刪除時，其座位劃位預訂記錄一併級聯硬刪除。
    CONSTRAINT fk_reservation_journey_sched_date FOREIGN KEY (journey_id, schedule_id, travel_date) REFERENCES travel_journeys(journey_id, schedule_id, travel_date) ON DELETE CASCADE,
    CONSTRAINT fk_reservation_seat_coach FOREIGN KEY (seat_pk, coach_id) REFERENCES seat_layout_seats(seat_pk, coach_id) ON DELETE CASCADE
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
    -- [PK design decision: TEXT] 支付工具自然代碼（如 'PMI-100234-CARD'）。
    payment_instrument_id TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 使用者檔案刪除時，其所綁定的安全支付 Token 資訊一併級聯刪除。
    user_id               TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    method_type           TEXT NOT NULL CHECK (method_type IN ('credit_card', 'debit_card', 'ewallet')),
    provider_name         TEXT NULL,
    token_ref             TEXT NOT NULL,
    last4                 TEXT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE payment_transactions (
    -- [PK design decision: TEXT] 金融支付交易自然水單號（如 'PM-9K4N2D'）。
    payment_id            TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 當母訂單刪除時，相關金融支付記錄一併連帶級聯硬刪除以防孤立交易記錄。
    order_id              TEXT NOT NULL REFERENCES travel_orders(order_id) ON DELETE CASCADE,
    -- [FK cascade behaviour: ON DELETE SET NULL] 若綁定支付方式已註銷刪除，歷史交易單中該支付卡參照欄位設為 NULL，保留流水金額以符會計申報要求。
    payment_instrument_id TEXT NULL REFERENCES payment_instruments(payment_instrument_id) ON DELETE SET NULL,
    transaction_type      TEXT NOT NULL CHECK (transaction_type IN ('charge', 'refund')),
    amount_usd            NUMERIC(10,2) NOT NULL CHECK (amount_usd >= 0),
    currency_code         CHAR(3) NOT NULL DEFAULT 'USD',
    payment_status        TEXT NOT NULL CHECK (payment_status IN ('pending', 'paid', 'failed', 'refunded')),
    gateway_reference     TEXT NULL,
    processed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- [FK cascade behaviour: ON DELETE SET NULL] 若退款交易關聯的原交易單被硬刪，保留此欄設為 NULL。
    ref_payment_id        TEXT NULL REFERENCES payment_transactions(payment_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------------
-- H. Feedback
-- ---------------------------------------------------------------------------
CREATE TABLE journey_feedback (
    -- [PK design decision: TEXT] 反饋流水號。
    feedback_id    TEXT PRIMARY KEY,
    -- [FK cascade behaviour: ON DELETE CASCADE] 乘車歷史行程或使用者檔案硬刪除時，其反饋評分內容一併級聯硬刪除。
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
    sl.layout_id,
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
LEFT JOIN seat_layouts sl ON sl.schedule_id = tj.schedule_id
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
        journey_id, order_id, journey_sequence_no, schedule_id, origin_station_id, destination_station_id,
        travel_date, departure_time, travelled_at, journey_status, stops_travelled, allocated_amount_usd
    ) VALUES (
        NEW.booking_id,
        v_order_id,
        1,
        NEW.schedule_id,
        NEW.origin_station_id,
        NEW.destination_station_id,
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

    IF v_coach_id IS NOT NULL THEN
        SELECT seat_pk INTO v_seat_pk
        FROM seat_layout_seats
        WHERE coach_id = v_coach_id AND seat_code = NEW.seat_id;

        IF v_seat_pk IS NOT NULL THEN
            -- 4. Insert into rail_journey_reservations
            INSERT INTO rail_journey_reservations (
                journey_id, schedule_id, travel_date, fare_class_code, coach_id, seat_pk, seat_reserved_at, reservation_status
            ) VALUES (
                NEW.booking_id,
                NEW.schedule_id,
                NEW.travel_date,
                NEW.fare_class,
                v_coach_id,
                v_seat_pk,
                COALESCE(NEW.booked_at, NOW()),
                CASE WHEN NEW.status = 'cancelled' THEN 'cancelled'::TEXT ELSE 'active'::TEXT END
            ) ON CONFLICT (journey_id) DO NOTHING;
        END IF;
    END IF;

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
        journey_id, order_id, journey_sequence_no, schedule_id, origin_station_id, destination_station_id,
        travel_date, departure_time, travelled_at, journey_status, stops_travelled, allocated_amount_usd, day_pass_ref
    ) VALUES (
        NEW.trip_id,
        v_order_id,
        1,
        NEW.schedule_id,
        NEW.origin_station_id,
        NEW.destination_station_id,
        NEW.travel_date,
        NULL,
        NEW.travelled_at,
        NEW.status,
        NEW.stops_travelled,
        NEW.amount_usd,
        NEW.day_pass_ref
    ) ON CONFLICT (journey_id) DO NOTHING;

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
    COALESCE(pi.method_type, 'credit_card') AS method,
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
BEGIN
    IF NEW.booking_id IS NOT NULL AND NEW.booking_id <> '' THEN
        v_order_id := CONCAT('ORD-', NEW.booking_id);
    ELSIF NEW.metro_trip_id IS NOT NULL AND NEW.metro_trip_id <> '' THEN
        v_order_id := CONCAT('ORD-', NEW.metro_trip_id);
    ELSE
        v_order_id := NULL;
    END IF;

    INSERT INTO payment_transactions (
        payment_id, order_id, payment_instrument_id, transaction_type,
        amount_usd, currency_code, payment_status, gateway_reference, processed_at
    ) VALUES (
        NEW.payment_id,
        v_order_id,
        NULL,
        CASE WHEN NEW.status = 'refunded' THEN 'refund'::TEXT ELSE 'charge'::TEXT END,
        NEW.amount_usd,
        'USD',
        NEW.status,
        NULL,
        COALESCE(NEW.paid_at, NOW())
    ) ON CONFLICT (payment_id) DO UPDATE SET
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

-- Refund policy lookup (Commented out because base tables are commented out)
-- CREATE INDEX idx_refund_policies_lookup
-- ON refund_policies (network_type, service_type, is_active);

-- CREATE INDEX idx_refund_policy_windows_policy
-- ON refund_policy_windows (policy_id, hours_before_departure_min, hours_before_departure_max);

-- Policy vector search fallback index.
-- For small seed data, sequential scan is fine.
CREATE INDEX idx_policy_documents_category
ON policy_documents (category);
