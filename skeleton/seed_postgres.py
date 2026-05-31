"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys

import psycopg2
from argon2 import PasswordHasher
from psycopg2.extras import execute_values

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


ph = PasswordHasher()


def hash_secret(value):
    # Argon2 hash strings already include the algorithm parameters and salt.
    if value is None:
        return None
    return ph.hash(str(value))


def split_full_name(full_name):
    # Mock data stores a single full_name, but the schema separates first/surname.
    parts = full_name.strip().split(" ", 1)
    first_name = parts[0]
    surname = parts[1] if len(parts) > 1 else ""
    return first_name, surname


def split_transaction_ref(ref):
    """
    payments / feedback 的 raw JSON 欄位叫 booking_id，
    但裡面可能是：
    - BKxxx: national rail booking
    - MTxxx: metro trip
    """
    if not ref:
        return None, None

    ref = str(ref)

    if ref.startswith("BK"):
        return ref, None

    if ref.startswith("MT"):
        return None, ref

    return ref, None


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    # TODO: Design your table schema, then implement the INSERT logic here.
    # Each item in `data` is a dict — inspect the JSON to see available fields.
    data = load("metro_stations.json")
    
    # 1. Seed lines
    unique_lines = set()
    for station in data:
        for line in station.get("lines", []):
            unique_lines.add(line)
            
    line_rows = [(line, "metro", f"Metro {line}", True) for line in sorted(unique_lines)]
    n_lines = insert_many(cur, "lines", ["line_id", "network_type", "line_name", "is_active"], line_rows)
    
    # 2. Seed stations
    station_rows = [(station["station_id"], "metro", station["name"], True) for station in data]
    n_stations = insert_many(cur, "stations", ["station_id", "network_type", "station_name", "is_active"], station_rows)
    
    # 3. Seed station_lines
    station_line_rows = []
    for station in data:
        for line in station.get("lines", []):
            # network_type is required by the composite FK to keep metro station-line links scoped to metro.
            station_line_rows.append((station["station_id"], line, "metro"))
    n_station_lines = insert_many(cur, "station_lines", ["station_id", "line_id", "network_type"], station_line_rows)
    
    # 4. Seed station_adjacencies
    adjacency_rows = []
    for station in data:
        for adj in station.get("adjacent_stations", []):
            # network_type enforces that both stations and the line are part of the metro network.
            adjacency_rows.append((station["station_id"], adj["station_id"], adj["line"], "metro", adj["travel_time_min"]))
    n_adj = insert_many(cur, "station_adjacencies", ["from_station_id", "to_station_id", "line_id", "network_type", "travel_time_min"], adjacency_rows)
    
    print(f"  metro_stations: seeded {n_lines} lines, {n_stations} stations, {n_station_lines} station_lines, {n_adj} adjacencies")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    # TODO: Design your table schema, then implement the INSERT logic here.

    # 1. Seed lines
    unique_lines = set()
    for station in data:
        for line in station.get("lines", []):
            unique_lines.add(line)
            
    line_rows = [(line, "national_rail", f"National Rail {line}", True) for line in sorted(unique_lines)]
    n_lines = insert_many(cur, "lines", ["line_id", "network_type", "line_name", "is_active"], line_rows)
    
    # 2. Seed stations
    station_rows = [(station["station_id"], "national_rail", station["name"], True) for station in data]
    n_stations = insert_many(cur, "stations", ["station_id", "network_type", "station_name", "is_active"], station_rows)
    
    # 3. Seed station_lines
    station_line_rows = []
    for station in data:
        for line in station.get("lines", []):
            # network_type is required by the composite FK to keep rail station-line links scoped to rail.
            station_line_rows.append((station["station_id"], line, "national_rail"))
    n_station_lines = insert_many(cur, "station_lines", ["station_id", "line_id", "network_type"], station_line_rows)
    
    # 4. Seed station_transfers
    transfer_rows = []
    for station in data:
        if station.get("is_interchange_metro") and station.get("interchange_metro_station_id"):
            metro_id = station["interchange_metro_station_id"]
            rail_id = station["station_id"]
            transfer_rows.append((metro_id, rail_id, "metro_to_rail", 5, True))
            transfer_rows.append((rail_id, metro_id, "rail_to_metro", 5, True))
            
    n_transfers = insert_many(cur, "station_transfers", ["from_station_id", "to_station_id", "transfer_type", "walking_time_min", "is_active"], transfer_rows)
    
    # 5. Seed station_adjacencies
    adjacency_rows = []
    for station in data:
        for adj in station.get("adjacent_stations", []):
            # network_type enforces that both stations and the line are part of the national rail network.
            adjacency_rows.append((station["station_id"], adj["station_id"], adj["line"], "national_rail", adj["travel_time_min"]))
    n_adj = insert_many(cur, "station_adjacencies", ["from_station_id", "to_station_id", "line_id", "network_type", "travel_time_min"], adjacency_rows)
    
    print(f"  national_rail_stations: seeded {n_lines} lines, {n_stations} stations, {n_station_lines} station_lines, {n_transfers} transfers, {n_adj} adjacencies")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    
    # 1. Insert into service_schedules
    schedule_rows = [
        (
            s["schedule_id"],
            s["line"],
            "metro",
            None,
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            s["first_train_time"],
            s["last_train_time"],
            s["frequency_min"],
            True
        )
        for s in data
    ]
    n_schedules = insert_many(
        cur,
        "service_schedules",
        [
            "schedule_id",
            "line_id",
            "network_type",
            "service_type",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "frequency_min",
            "is_active"
        ],
        schedule_rows
    )
    
    # 2. Insert into schedule_operating_days
    operating_day_rows = []
    for s in data:
        for day in s.get("operates_on", []):
            operating_day_rows.append((s["schedule_id"], day))
    n_days = insert_many(cur, "schedule_operating_days", ["schedule_id", "day_of_week"], operating_day_rows)
    
    # 3. Insert into schedule_stations
    stop_rows = []
    for s in data:
        for idx, station_id in enumerate(s["stops_in_order"], start=1):
            travel_time = s["travel_time_from_origin_min"].get(station_id, 0)
            stop_rows.append((s["schedule_id"], "metro", idx, station_id, True, travel_time))
    n_stops = insert_many(
        cur,
        "schedule_stations",
        [
            "schedule_id",
            "network_type",
            "sequence_no",
            "station_id",
            "stops_here",
            "travel_time_from_origin_min"
        ],
        stop_rows
    )
    
    # 4. Insert into schedule_fares
    fare_rows = [
        # network_type is part of the fare schedule FK and restricts metro fares to metro_single.
        (s["schedule_id"], "metro", "metro_single", s["base_fare_usd"], s["per_stop_rate_usd"], "USD")
        for s in data
    ]
    n_fares = insert_many(
        cur,
        "schedule_fares",
        ["schedule_id", "network_type", "fare_class_code", "base_fare_usd", "per_stop_rate_usd", "currency_code"],
        fare_rows
    )
    
    print(f"  metro_schedules: seeded {n_schedules} schedules, {n_days} operating days, {n_stops} stops, {n_fares} fares")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    
    # 1. Insert into service_schedules
    schedule_rows = [
        (
            s["schedule_id"],
            s["line"],
            "national_rail",
            s.get("service_type"),
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            s["first_train_time"],
            s["last_train_time"],
            s["frequency_min"],
            True
        )
        for s in data
    ]
    n_schedules = insert_many(
        cur,
        "service_schedules",
        [
            "schedule_id",
            "line_id",
            "network_type",
            "service_type",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "frequency_min",
            "is_active"
        ],
        schedule_rows
    )
    
    # 2. Insert into schedule_operating_days
    operating_day_rows = []
    for s in data:
        for day in s.get("operates_on", []):
            operating_day_rows.append((s["schedule_id"], day))
    n_days = insert_many(cur, "schedule_operating_days", ["schedule_id", "day_of_week"], operating_day_rows)
    
    # 3. Insert into schedule_stations
    stop_rows = []
    for s in data:
        for idx, station_id in enumerate(s["stops_in_order"], start=1):
            travel_time = s["travel_time_from_origin_min"].get(station_id, 0)
            stop_rows.append((s["schedule_id"], "national_rail", idx, station_id, True, travel_time))
    n_stops = insert_many(
        cur,
        "schedule_stations",
        [
            "schedule_id",
            "network_type",
            "sequence_no",
            "station_id",
            "stops_here",
            "travel_time_from_origin_min"
        ],
        stop_rows
    )
    
    # 4. Insert into schedule_fares
    fare_rows = []
    for s in data:
        for fare_class, fare in s.get("fare_classes", {}).items():
            fare_rows.append(
                (
                    s["schedule_id"],
                    "national_rail",
                    fare_class,
                    fare.get("base_fare_usd"),
                    fare.get("per_stop_rate_usd"),
                    "USD"
                )
            )
    n_fares = insert_many(
        cur,
        "schedule_fares",
        ["schedule_id", "network_type", "fare_class_code", "base_fare_usd", "per_stop_rate_usd", "currency_code"],
        fare_rows
    )
    
    print(f"  national_rail_schedules: seeded {n_schedules} schedules, {n_days} operating days, {n_stops} stops, {n_fares} fares")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    
    # 1. Seed layouts
    layout_rows = [(layout["layout_id"], layout["schedule_id"]) for layout in data]
    n_layouts = insert_many(cur, "seat_layouts", ["layout_id", "schedule_id"], layout_rows)
    
    n_coaches = 0
    seat_rows = []
    
    # 2. Seed coaches and gather seats
    for layout in data:
        layout_id = layout["layout_id"]
        for coach in layout.get("coaches", []):
            coach_code = coach["coach"]
            fare_class = coach["fare_class"]
            
            # Insert coach idempotently
            cur.execute(
                """
                INSERT INTO seat_layout_coaches (layout_id, coach_code, fare_class_code)
                VALUES (%s, %s, %s)
                ON CONFLICT (layout_id, coach_code) DO NOTHING
                RETURNING coach_id;
                """,
                (layout_id, coach_code, fare_class)
            )
            res = cur.fetchone()
            if res:
                coach_id = res[0]
                n_coaches += 1
            else:
                cur.execute(
                    """
                    SELECT coach_id FROM seat_layout_coaches
                    WHERE layout_id = %s AND coach_code = %s;
                    """,
                    (layout_id, coach_code)
                )
                coach_id = cur.fetchone()[0]
                
            for seat in coach.get("seats", []):
                seat_rows.append((layout_id, coach_id, seat["seat_id"], seat["row"], seat["column"]))
                
    # 3. Seed seats
    n_seats = insert_many(
        cur,
        "seat_layout_seats",
        ["layout_id", "coach_id", "seat_code", "seat_row", "seat_column"],
        seat_rows
    )
    
    print(f"  seat_layouts: seeded {n_layouts} layouts, {n_coaches} new coaches, {n_seats} seats")


def seed_users(cur):
    data = load("registered_users.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # 1. Validate and prepare user profile / credential rows
    user_rows = []
    credential_rows = []
    seen_emails = set()
    for user in data:
        required_fields = ["user_id", "full_name", "email", "password", "date_of_birth"]
        missing_fields = [field for field in required_fields if not user.get(field)]
        if missing_fields:
            raise ValueError(
                f"registered_users.json record is missing {missing_fields}: user_id={user.get('user_id')}"
            )

        email = user["email"].lower()
        if email in seen_emails:
            raise ValueError(f"Duplicate registered user email after lower-casing: {email}")
        seen_emails.add(email)

        if bool(user.get("secret_question")) != bool(user.get("secret_answer")):
            raise ValueError(
                "Secret question and answer must be provided together for "
                f"user_id={user['user_id']}"
            )

        first_name, surname = split_full_name(user["full_name"])
        # The registered_users view splits profile data from authentication data.
        user_rows.append(
            (
                user["user_id"],
                first_name,
                surname,
                user["full_name"],
                email,
                user.get("phone"),
                user.get("date_of_birth"),
                user.get("registered_at"),
                user.get("is_active", True),
            )
        )
        credential_rows.append(
            (
                user["user_id"],
                # Passwords and recovery answers should never be stored as plain text.
                ph.hash(user["password"]),
                "argon2id",
                user.get("secret_question"),
                hash_secret(user.get("secret_answer")),
                user.get("registered_at"),
            )
        )
    # 2. Insert user profile rows through the compatibility view
    users = insert_many(
        cur,
        "registered_users",
        [
            "user_id",
            "first_name",
            "surname",
            "full_name",
            "email",
            "phone",
            "date_of_birth",
            "registered_at",
            "is_active",
        ],
        user_rows,
    )
    # 3. Insert authentication and recovery credential rows through the compatibility view
    credentials = insert_many(
        cur,
        "user_credentials",
        [
            "user_id",
            "password_hash",
            "hashing_algorithm",
            "secret_question",
            "secret_answer_hash",
            "updated_at",
        ],
        credential_rows,
    )
    print(f"  registered_users: {users} rows")
    print(f"  user_credentials: {credentials} rows")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # 1. Validate booking seat selections and prepare rows
    rows = []
    for booking in data:
        # layout_id is not present in bookings.json, so derive it from the schedule.
        # The schema also requires the selected coach, seat, and fare class to match.
        cur.execute(
            """
            SELECT nrl.layout_id
            FROM national_rail_seat_layouts nrl
            JOIN national_rail_seats nrs
              ON nrs.layout_id = nrl.layout_id
            WHERE nrl.schedule_id = %s
              AND nrs.coach = %s
              AND nrs.seat_id = %s
              AND nrs.fare_class = %s
            """,
            (
                booking["schedule_id"],
                booking["coach"],
                booking["seat_id"],
                booking["fare_class"],
            ),
        )
        result = cur.fetchone()
        if result is None:
            raise ValueError(
                "No matching rail seat found for "
                f"booking_id={booking['booking_id']}, "
                f"schedule_id={booking['schedule_id']}, "
                f"coach={booking['coach']}, "
                f"seat_id={booking['seat_id']}, "
                f"fare_class={booking['fare_class']}"
            )
        layout_id = result[0]
        rows.append(
            (
                booking["booking_id"],
                booking["user_id"],
                booking["schedule_id"],
                booking["origin_station_id"],
                booking["destination_station_id"],
                booking["travel_date"],
                booking["departure_time"],
                booking["ticket_type"],
                booking["fare_class"],
                layout_id,
                booking["coach"],
                booking["seat_id"],
                booking["stops_travelled"],
                booking["amount_usd"],
                booking["status"],
                booking.get("booked_at"),
                booking.get("travelled_at"),
            )
        )
    # 2. Insert bookings through the compatibility view
    n = insert_many(
        cur,
        "national_rail_bookings",
        [
            "booking_id",
            "user_id",
            "schedule_id",
            "origin_station_id",
            "destination_station_id",
            "travel_date",
            "departure_time",
            "ticket_type",
            "fare_class",
            "layout_id",
            "coach",
            "seat_id",
            "stops_travelled",
            "amount_usd",
            "status",
            "booked_at",
            "travelled_at",
        ],
        rows,
    )
    print(f"  national_rail_bookings: {n} rows")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # 1. Validate metro trips and prepare rows without day_pass_ref
    # Insert first with day_pass_ref cleared, then restore self-references afterwards.
    rows = []
    for trip in data:
        # The schema requires metro journeys to use a metro schedule and metro stations.
        cur.execute(
            """
            SELECT 1
            FROM metro_schedules ms
            JOIN metro_stations origin_station
              ON origin_station.station_id = %s
            JOIN metro_stations dest_station
              ON dest_station.station_id = %s
            WHERE ms.schedule_id = %s
            """,
            (
                trip["origin_station_id"],
                trip["destination_station_id"],
                trip["schedule_id"],
            ),
        )
        if cur.fetchone() is None:
            raise ValueError(
                "No matching metro schedule/stops found for "
                f"trip_id={trip['trip_id']}, "
                f"schedule_id={trip['schedule_id']}, "
                f"origin={trip['origin_station_id']}, "
                f"destination={trip['destination_station_id']}"
            )
        rows.append(
            (
                trip["trip_id"],
                trip["user_id"],
                trip["schedule_id"],
                trip["origin_station_id"],
                trip["destination_station_id"],
                trip["travel_date"],
                trip["ticket_type"],
                None,
                trip.get("stops_travelled"),
                trip["amount_usd"],
                trip["status"],
                trip.get("purchased_at"),
                trip.get("travelled_at"),
            )
        )
    # 2. Insert metro travel history rows through the compatibility view
    n = insert_many(
        cur,
        "metro_travel_history",
        [
            "trip_id",
            "user_id",
            "schedule_id",
            "origin_station_id",
            "destination_station_id",
            "travel_date",
            "ticket_type",
            "day_pass_ref",
            "stops_travelled",
            "amount_usd",
            "status",
            "purchased_at",
            "travelled_at",
        ],
        rows,
    )
    # 3. Restore day_pass_ref values after base trips exist
    update_count = 0
    for trip in data:
        if trip.get("day_pass_ref"):
            cur.execute(
                """
                UPDATE metro_travel_history
                SET day_pass_ref = %s
                WHERE trip_id = %s
                """,
                (trip["day_pass_ref"], trip["trip_id"]),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    "Failed to restore day_pass_ref for "
                    f"trip_id={trip['trip_id']}, "
                    f"day_pass_ref={trip['day_pass_ref']}"
                )
            update_count += cur.rowcount
    print(f"  metro_travel_history: {n} rows")
    print(f"  metro_travel_history day_pass_ref updates: {update_count} rows")


def seed_payments(cur):
    data = load("payments.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # 1. Validate payment references and prepare rows
    rows = []
    for payment in data:
        # Raw JSON uses one reference field for both rail bookings and metro trips.
        booking_id, metro_trip_id = split_transaction_ref(payment.get("booking_id"))
        if booking_id:
            cur.execute(
                "SELECT 1 FROM national_rail_bookings WHERE booking_id = %s",
                (booking_id,),
            )
            if cur.fetchone() is None:
                raise ValueError(
                    "No national rail booking found for "
                    f"payment_id={payment['payment_id']}, booking_id={booking_id}"
                )
        elif metro_trip_id:
            cur.execute(
                "SELECT 1 FROM metro_travel_history WHERE trip_id = %s",
                (metro_trip_id,),
            )
            if cur.fetchone() is None:
                raise ValueError(
                    "No metro trip found for "
                    f"payment_id={payment['payment_id']}, metro_trip_id={metro_trip_id}"
                )
        else:
            raise ValueError(f"Payment {payment['payment_id']} has no booking or metro trip reference")
        rows.append(
            (
                payment["payment_id"],
                booking_id,
                metro_trip_id,
                payment["amount_usd"],
                payment["method"],
                payment["status"],
                payment["paid_at"],
            )
        )
    # 2. Insert payment rows through the compatibility view
    n = insert_many(
        cur,
        "payments",
        ["payment_id", "booking_id", "metro_trip_id", "amount_usd", "method", "status", "paid_at"],
        rows,
    )
    print(f"  payments: {n} rows")


def seed_feedback(cur):
    data = load("feedback.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # 1. Validate feedback references and prepare rows
    rows = []
    for item in data:
        # Feedback follows the same mixed BK/MT reference pattern as payments.
        booking_id, metro_trip_id = split_transaction_ref(item.get("booking_id"))
        if booking_id:
            cur.execute(
                "SELECT user_id FROM national_rail_bookings WHERE booking_id = %s",
                (booking_id,),
            )
            result = cur.fetchone()
            ref_name = "booking_id"
            ref_value = booking_id
        elif metro_trip_id:
            cur.execute(
                "SELECT user_id FROM metro_travel_history WHERE trip_id = %s",
                (metro_trip_id,),
            )
            result = cur.fetchone()
            ref_name = "metro_trip_id"
            ref_value = metro_trip_id
        else:
            raise ValueError(f"Feedback {item['feedback_id']} has no booking or metro trip reference")

        if result is None:
            raise ValueError(
                "No travelled journey found for "
                f"feedback_id={item['feedback_id']}, "
                f"{ref_name}={ref_value}"
            )
        if result[0] != item["user_id"]:
            raise ValueError(
                "Feedback user does not match journey user for "
                f"feedback_id={item['feedback_id']}, "
                f"{ref_name}={ref_value}, "
                f"feedback_user={item['user_id']}, "
                f"journey_user={result[0]}"
            )
        rows.append(
            (
                item["feedback_id"],
                item["user_id"],
                booking_id,
                metro_trip_id,
                item["rating"],
                item.get("comment"),
                item.get("submitted_at"),
            )
        )
    # 2. Insert feedback rows through the compatibility view
    n = insert_many(
        cur,
        "feedback",
        ["feedback_id", "user_id", "booking_id", "metro_trip_id", "rating", "comment", "submitted_at"],
        rows,
    )
    print(f"  feedback: {n} rows")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Seeding tables (dependency order):")
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        conn.commit()
        print("\nAll done. Database seeded successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
