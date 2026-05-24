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
    data = load("metro_stations.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    # Each item in `data` is a dict — inspect the JSON to see available fields.
    rows = [
        (
            station["station_id"],
            station["name"],
            station.get("lines", []),
            station.get("is_interchange_metro", False),
            station.get("interchange_metro_lines", []),
            station.get("is_interchange_national_rail", False),
            station.get("interchange_national_rail_station_id"),
        )
        for station in data
    ]
    n = insert_many(
        cur,
        "metro_stations",
        [
            "station_id",
            "name",
            "lines",
            "is_interchange_metro",
            "interchange_metro_lines",
            "is_interchange_national_rail",
            "interchange_national_rail_station_id",
        ],
        rows,
    )
    print(f"  metro_stations: {n} rows")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    station_rows = [
        (
            station["station_id"],
            station["name"],
            station.get("lines", []),
            station.get("is_interchange_national_rail", False),
            station.get("interchange_national_rail_lines", []),
            station.get("is_interchange_metro", False),
            station.get("interchange_metro_station_id"),
        )
        for station in data
    ]
    stations = insert_many(
        cur,
        "national_rail_stations",
        [
            "station_id",
            "name",
            "lines",
            "is_interchange_national_rail",
            "interchange_national_rail_lines",
            "is_interchange_metro",
            "interchange_metro_station_id",
        ],
        station_rows,
    )

    interchange_rows = [
        (
            station["interchange_metro_station_id"],
            station["station_id"],
            5,
        )
        for station in data
        if station.get("is_interchange_metro") and station.get("interchange_metro_station_id")
    ]
    interchanges = insert_many(
        cur,
        "station_interchanges",
        ["metro_station_id", "rail_station_id", "transfer_time_min"],
        interchange_rows,
    )
    print(f"  national_rail_stations: {stations} rows")
    print(f"  station_interchanges: {interchanges} rows")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    schedule_rows = [
        (
            schedule["schedule_id"],
            schedule["line"],
            schedule.get("direction"),
            schedule["origin_station_id"],
            schedule["destination_station_id"],
            schedule.get("first_train_time"),
            schedule.get("last_train_time"),
            schedule.get("base_fare_usd"),
            schedule.get("per_stop_rate_usd"),
            schedule.get("frequency_min"),
            schedule.get("operates_on", []),
        )
        for schedule in data
    ]
    schedules = insert_many(
        cur,
        "metro_schedules",
        [
            "schedule_id",
            "line",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "base_fare_usd",
            "per_stop_rate_usd",
            "frequency_min",
            "operates_on",
        ],
        schedule_rows,
    )

    stop_rows = []
    for schedule in data:
        for idx, station_id in enumerate(schedule["stops_in_order"], start=1):
            stop_rows.append(
                (
                    schedule["schedule_id"],
                    idx,
                    station_id,
                    schedule["travel_time_from_origin_min"].get(station_id),
                )
            )
    stops = insert_many(
        cur,
        "metro_schedule_stops",
        [
            "schedule_id",
            "stop_order",
            "station_id",
            "travel_time_from_origin_min",
        ],
        stop_rows,
    )
    print(f"  metro_schedules: {schedules} rows")
    print(f"  metro_schedule_stops: {stops} rows")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    schedule_rows = [
        (
            schedule["schedule_id"],
            schedule["line"],
            schedule.get("service_type"),
            schedule.get("direction"),
            schedule["origin_station_id"],
            schedule["destination_station_id"],
            schedule.get("first_train_time"),
            schedule.get("last_train_time"),
            schedule.get("frequency_min"),
            schedule.get("operates_on", []),
        )
        for schedule in data
    ]
    schedules = insert_many(
        cur,
        "national_rail_schedules",
        [
            "schedule_id",
            "line",
            "service_type",
            "direction",
            "origin_station_id",
            "destination_station_id",
            "first_train_time",
            "last_train_time",
            "frequency_min",
            "operates_on",
        ],
        schedule_rows,
    )

    stop_rows = []
    fare_rows = []
    for schedule in data:
        for idx, station_id in enumerate(schedule["stops_in_order"], start=1):
            stop_rows.append(
                (
                    schedule["schedule_id"],
                    idx,
                    station_id,
                    schedule["travel_time_from_origin_min"].get(station_id),
                )
            )
        for fare_class, fare in schedule.get("fare_classes", {}).items():
            fare_rows.append(
                (
                    schedule["schedule_id"],
                    fare_class,
                    fare.get("base_fare_usd"),
                    fare.get("per_stop_rate_usd"),
                )
            )
    stops = insert_many(
        cur,
        "national_rail_schedule_stops",
        [
            "schedule_id",
            "stop_order",
            "station_id",
            "travel_time_from_origin_min",
        ],
        stop_rows,
    )
    fares = insert_many(
        cur,
        "national_rail_fare_classes",
        ["schedule_id", "fare_class", "base_fare_usd", "per_stop_rate_usd"],
        fare_rows,
    )
    print(f"  national_rail_schedules: {schedules} rows")
    print(f"  national_rail_schedule_stops: {stops} rows")
    print(f"  national_rail_fare_classes: {fares} rows")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    layout_rows = [
        (
            layout["layout_id"],
            layout["schedule_id"],
        )
        for layout in data
    ]
    layouts = insert_many(
        cur,
        "national_rail_seat_layouts",
        ["layout_id", "schedule_id"],
        layout_rows,
    )

    coach_rows = []
    seat_rows = []
    for layout in data:
        for coach in layout.get("coaches", []):
            coach_rows.append(
                (
                    layout["layout_id"],
                    coach["coach"],
                    coach.get("fare_class"),
                )
            )
            for seat in coach.get("seats", []):
                seat_rows.append(
                    (
                        layout["layout_id"],
                        coach["coach"],
                        seat["seat_id"],
                        seat.get("row"),
                        seat.get("column"),
                        coach.get("fare_class"),
                    )
                )
    coaches = insert_many(
        cur,
        "national_rail_coaches",
        ["layout_id", "coach", "fare_class"],
        coach_rows,
    )
    seats = insert_many(
        cur,
        "national_rail_seats",
        ["layout_id", "coach", "seat_id", "seat_row", "seat_column", "fare_class"],
        seat_rows,
    )
    print(f"  national_rail_seat_layouts: {layouts} rows")
    print(f"  national_rail_coaches: {coaches} rows")
    print(f"  national_rail_seats: {seats} rows")


def seed_users(cur):
    data = load("registered_users.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    user_rows = []
    credential_rows = []
    for user in data:
        first_name, surname = split_full_name(user["full_name"])
        user_rows.append(
            (
                user["user_id"],
                first_name,
                surname,
                user["full_name"],
                user["email"].lower(),
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
            )
        )
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
    credentials = insert_many(
        cur,
        "user_credentials",
        [
            "user_id",
            "password_hash",
            "hashing_algorithm",
            "secret_question",
            "secret_answer_hash",
        ],
        credential_rows,
    )
    print(f"  registered_users: {users} rows")
    print(f"  user_credentials: {credentials} rows")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    rows = []
    for booking in data:
        # layout_id is not present in bookings.json, so derive it from the schedule.
        cur.execute(
            """
            SELECT layout_id
            FROM national_rail_seat_layouts
            WHERE schedule_id = %s
            """,
            (booking["schedule_id"],),
        )
        result = cur.fetchone()
        if result is None:
            raise ValueError(f"No layout_id found for schedule_id={booking['schedule_id']}")
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
    # Insert first with day_pass_ref cleared, then restore self-references afterwards.
    rows = [
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
        for trip in data
    ]
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
            update_count += cur.rowcount
    print(f"  metro_travel_history: {n} rows")
    print(f"  metro_travel_history day_pass_ref updates: {update_count} rows")


def seed_payments(cur):
    data = load("payments.json")
    # TODO: Design your table schema, then implement the INSERT logic here.
    rows = []
    for payment in data:
        # Raw JSON uses one reference field for both rail bookings and metro trips.
        booking_id, metro_trip_id = split_transaction_ref(payment.get("booking_id"))
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
    rows = []
    for item in data:
        # Feedback follows the same mixed BK/MT reference pattern as payments.
        booking_id, metro_trip_id = split_transaction_ref(item.get("booking_id"))
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
