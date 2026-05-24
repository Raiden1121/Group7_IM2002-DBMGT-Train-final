"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


ph = PasswordHasher()


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


def _gen_user_id() -> str:
    return f"RU{random.randint(100000, 999999)}"


def _to_jsonable(row):
    if row is None:
        return None
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, bool):
            out[k] = v
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# TODO: Implement the query_ and execute_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        travel_date:     e.g. "2025-06-01" — used to count bookings; omit for general info
    """
    sql = """
        WITH routes AS (
            SELECT
                s.schedule_id,
                s.line,
                s.service_type,
                s.direction,
                s.origin_station_id,
                s.destination_station_id,
                s.first_train_time,
                s.last_train_time,
                s.frequency_min,
                o.stop_order AS origin_stop_order,
                d.stop_order AS destination_stop_order,
                d.stop_order - o.stop_order AS stops_travelled
            FROM national_rail_schedules s
            JOIN national_rail_schedule_stops o
              ON o.schedule_id = s.schedule_id
            JOIN national_rail_schedule_stops d
              ON d.schedule_id = s.schedule_id
            WHERE o.station_id = %s
              AND d.station_id = %s
              AND o.stop_order < d.stop_order
        ),
        seat_counts AS (
            SELECT
                l.schedule_id,
                COUNT(*) AS total_seats
            FROM national_rail_seat_layouts l
            JOIN national_rail_seats seats
              ON seats.layout_id = l.layout_id
            GROUP BY l.schedule_id
        ),
        booked_counts AS (
            SELECT
                schedule_id,
                COUNT(*) AS booked_seats
            FROM national_rail_bookings
            WHERE travel_date = %s
              AND status IN ('confirmed', 'completed')
            GROUP BY schedule_id
        )
        SELECT
            r.*,
            COALESCE(sc.total_seats, 0) AS total_seats,
            COALESCE(bc.booked_seats, 0) AS booked_seats,
            COALESCE(sc.total_seats, 0) - COALESCE(bc.booked_seats, 0) AS available_seats
        FROM routes r
        LEFT JOIN seat_counts sc
          ON sc.schedule_id = r.schedule_id
        LEFT JOIN booked_counts bc
          ON bc.schedule_id = r.schedule_id
        ORDER BY r.schedule_id
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id, travel_date))
            return [_to_jsonable(row) for row in cur.fetchall()]


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """
    Calculate the fare for a national rail journey.

    Args:
        schedule_id:     e.g. "NR_SCH01"
        fare_class:      "standard" or "first"
        stops_travelled: number of stops between origin and destination (inclusive)

    Returns:
        dict with fare_class, base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = """
        SELECT
            schedule_id,
            fare_class,
            base_fare_usd,
            per_stop_rate_usd,
            %s AS stops_travelled,
            base_fare_usd + (per_stop_rate_usd * %s) AS total_fare_usd
        FROM national_rail_fare_classes
        WHERE schedule_id = %s
          AND fare_class = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (stops_travelled, stops_travelled, schedule_id, fare_class))
            return _to_jsonable(cur.fetchone())


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.

    Args:
        origin_id:       e.g. "MS01"
        destination_id:  e.g. "MS09"
    """
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.direction,
            s.origin_station_id,
            s.destination_station_id,
            s.first_train_time,
            s.last_train_time,
            s.frequency_min,
            o.stop_order AS origin_stop_order,
            d.stop_order AS destination_stop_order,
            d.stop_order - o.stop_order AS stops_travelled
        FROM metro_schedules s
        JOIN metro_schedule_stops o
          ON o.schedule_id = s.schedule_id
        JOIN metro_schedule_stops d
          ON d.schedule_id = s.schedule_id
        WHERE o.station_id = %s
          AND d.station_id = %s
          AND o.stop_order < d.stop_order
        ORDER BY s.schedule_id
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [_to_jsonable(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.

    Args:
        schedule_id:     e.g. "MS_SCH01"
        stops_travelled: number of stops between origin and destination

    Returns:
        dict with base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = """
        SELECT
            schedule_id,
            base_fare_usd,
            per_stop_rate_usd,
            %s AS stops_travelled,
            base_fare_usd + (per_stop_rate_usd * %s) AS total_fare_usd
        FROM metro_schedules
        WHERE schedule_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (stops_travelled, stops_travelled, schedule_id))
            return _to_jsonable(cur.fetchone())


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.

    Args:
        schedule_id:  e.g. "NR_SCH01"
        travel_date:  e.g. "2025-06-01"
        fare_class:   "standard" or "first"

    Returns:
        List of dicts: {seat_id, coach, row, column}
    """
    sql = """
        SELECT
            seats.seat_id,
            seats.coach,
            seats.seat_row AS row,
            seats.seat_column AS column,
            seats.fare_class
        FROM national_rail_seat_layouts layouts
        JOIN national_rail_seats seats
          ON seats.layout_id = layouts.layout_id
        WHERE layouts.schedule_id = %s
          AND seats.fare_class = %s
          AND NOT EXISTS (
              SELECT 1
              FROM national_rail_bookings b
              WHERE b.schedule_id = %s
                AND b.travel_date = %s
                AND b.coach = seats.coach
                AND b.seat_id = seats.seat_id
                AND b.status IN ('confirmed', 'completed')
          )
        ORDER BY seats.coach, seats.seat_row, seats.seat_column
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, fare_class, schedule_id, travel_date))
            return [_to_jsonable(row) for row in cur.fetchall()]


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.

    Args:
        available_seats: output of query_available_seats()
        count:           number of seats needed
    """
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT
            user_id,
            email,
            full_name,
            first_name,
            surname,
            phone,
            date_of_birth,
            is_active,
            registered_at
        FROM registered_users
        WHERE email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email.lower(),))
            return _to_jsonable(cur.fetchone())


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).

    Returns:
        dict with keys 'national_rail' (list) and 'metro' (list)
    """
    profile = query_user_profile(user_email)
    if not profile:
        return {"national_rail": [], "metro": []}

    user_id = profile["user_id"]
    rail_sql = """
        SELECT
            b.booking_id,
            b.schedule_id,
            b.travel_date,
            b.departure_time,
            b.ticket_type,
            b.fare_class,
            b.coach,
            b.seat_id,
            b.stops_travelled,
            b.amount_usd,
            b.status,
            b.booked_at,
            b.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name
        FROM national_rail_bookings b
        JOIN national_rail_stations orig
          ON orig.station_id = b.origin_station_id
        JOIN national_rail_stations dest
          ON dest.station_id = b.destination_station_id
        WHERE b.user_id = %s
        ORDER BY b.travel_date DESC, b.booked_at DESC NULLS LAST
    """
    metro_sql = """
        SELECT
            m.trip_id,
            m.schedule_id,
            m.travel_date,
            m.ticket_type,
            m.day_pass_ref,
            m.stops_travelled,
            m.amount_usd,
            m.status,
            m.purchased_at,
            m.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name
        FROM metro_travel_history m
        JOIN metro_stations orig
          ON orig.station_id = m.origin_station_id
        JOIN metro_stations dest
          ON dest.station_id = m.destination_station_id
        WHERE m.user_id = %s
        ORDER BY m.travel_date DESC, m.purchased_at DESC NULLS LAST
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(rail_sql, (user_id,))
            rail_rows = [_to_jsonable(row) for row in cur.fetchall()]
            cur.execute(metro_sql, (user_id,))
            metro_rows = [_to_jsonable(row) for row in cur.fetchall()]
            return {"national_rail": rail_rows, "metro": metro_rows}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    if booking_id.startswith("MT"):
        sql = """
            SELECT payment_id, booking_id, metro_trip_id, amount_usd, method, status, paid_at
            FROM payments
            WHERE metro_trip_id = %s
            ORDER BY paid_at DESC NULLS LAST
            LIMIT 1
        """
    else:
        sql = """
            SELECT payment_id, booking_id, metro_trip_id, amount_usd, method, status, paid_at
            FROM payments
            WHERE booking_id = %s
            ORDER BY paid_at DESC NULLS LAST
            LIMIT 1
        """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
            return _to_jsonable(cur.fetchone())


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.

    Args:
        user_id:                e.g. "RU01" — must match the logged-in user
        schedule_id:            e.g. "NR_SCH01"
        origin_station_id:      e.g. "NR01"
        destination_station_id: e.g. "NR05"
        travel_date:            e.g. "2025-06-01"
        fare_class:             "standard" or "first"
        seat_id:                e.g. "B05" (or "any" to auto-assign)
        ticket_type:            "single" (default) or "return"

    Returns:
        (True, booking_dict)   on success
        (False, error_message) on failure
    """
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, is_active
                FROM registered_users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                conn.rollback()
                return False, "User not found."
            if not user["is_active"]:
                conn.rollback()
                return False, "User account is inactive."

            cur.execute(
                """
                SELECT
                    s.schedule_id,
                    s.first_train_time,
                    o.stop_order AS origin_stop_order,
                    d.stop_order AS destination_stop_order,
                    d.stop_order - o.stop_order AS stops_travelled
                FROM national_rail_schedules s
                JOIN national_rail_schedule_stops o
                  ON o.schedule_id = s.schedule_id
                JOIN national_rail_schedule_stops d
                  ON d.schedule_id = s.schedule_id
                WHERE s.schedule_id = %s
                  AND o.station_id = %s
                  AND d.station_id = %s
                  AND o.stop_order < d.stop_order
                """,
                (schedule_id, origin_station_id, destination_station_id),
            )
            route = cur.fetchone()
            if not route:
                conn.rollback()
                return False, "Schedule does not serve the selected stations in that order."

            cur.execute(
                """
                SELECT layout_id
                FROM national_rail_seat_layouts
                WHERE schedule_id = %s
                """,
                (schedule_id,),
            )
            layout = cur.fetchone()
            if not layout:
                conn.rollback()
                return False, "No seat layout found for this schedule."
            layout_id = layout["layout_id"]

            selected_seat_id = seat_id
            selected_coach = None
            if seat_id.lower() == "any":
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    conn.rollback()
                    return False, "No seats available for the selected service."
                selected = available[0]
                selected_seat_id = selected["seat_id"]
                selected_coach = selected["coach"]
            else:
                cur.execute(
                    """
                    SELECT coach, seat_id, fare_class
                    FROM national_rail_seats
                    WHERE layout_id = %s
                      AND seat_id = %s
                    """,
                    (layout_id, seat_id),
                )
                seat = cur.fetchone()
                if not seat:
                    conn.rollback()
                    return False, "Selected seat does not exist for this schedule."
                if seat["fare_class"] != fare_class:
                    conn.rollback()
                    return False, "Selected seat does not match the requested fare class."
                cur.execute(
                    """
                    SELECT 1
                    FROM national_rail_bookings
                    WHERE schedule_id = %s
                      AND travel_date = %s
                      AND coach = %s
                      AND seat_id = %s
                      AND status IN ('confirmed', 'completed')
                    """,
                    (schedule_id, travel_date, seat["coach"], seat["seat_id"]),
                )
                if cur.fetchone():
                    conn.rollback()
                    return False, "Selected seat is already booked."
                selected_coach = seat["coach"]

            fare = query_national_rail_fare(schedule_id, fare_class, route["stops_travelled"])
            if not fare:
                conn.rollback()
                return False, "Fare information not found."

            booking_id = _gen_booking_id()
            payment_id = _gen_payment_id()

            cur.execute(
                """
                INSERT INTO national_rail_bookings (
                    booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                    travel_date, departure_time, ticket_type, fare_class, layout_id,
                    coach, seat_id, stops_travelled, amount_usd, status, booked_at, travelled_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NULL)
                """,
                (
                    booking_id,
                    user_id,
                    schedule_id,
                    origin_station_id,
                    destination_station_id,
                    travel_date,
                    route["first_train_time"],
                    ticket_type,
                    fare_class,
                    layout_id,
                    selected_coach,
                    selected_seat_id,
                    route["stops_travelled"],
                    fare["total_fare_usd"],
                    "confirmed",
                ),
            )
            cur.execute(
                """
                INSERT INTO payments (
                    payment_id, booking_id, metro_trip_id, amount_usd, method, status, paid_at
                )
                VALUES (%s, %s, NULL, %s, %s, %s, NOW())
                """,
                (payment_id, booking_id, fare["total_fare_usd"], "card", "paid"),
            )
            conn.commit()
            return True, {
                "booking_id": booking_id,
                "payment_id": payment_id,
                "user_id": user_id,
                "schedule_id": schedule_id,
                "origin_station_id": origin_station_id,
                "destination_station_id": destination_station_id,
                "travel_date": travel_date,
                "departure_time": route["first_train_time"].isoformat() if hasattr(route["first_train_time"], "isoformat") else route["first_train_time"],
                "ticket_type": ticket_type,
                "fare_class": fare_class,
                "layout_id": layout_id,
                "coach": selected_coach,
                "seat_id": selected_seat_id,
                "stops_travelled": route["stops_travelled"],
                "amount_usd": fare["total_fare_usd"],
                "status": "confirmed",
                "payment_status": "paid",
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.

    Calculates the refund amount according to the booking's service type:
      - Normal service: RF001 windows (100% / 75% / 50% / 0%)
      - Express service: RF002 windows (100% / 50% / 0%)

    Args:
        booking_id: e.g. "BK001"
        user_id:    must match the booking's user_id

    Returns:
        (True, result_dict)  with refund_amount_usd and policy note
        (False, error_msg)
    """
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    b.booking_id,
                    b.user_id,
                    b.travel_date,
                    b.departure_time,
                    b.amount_usd,
                    b.status,
                    s.service_type
                FROM national_rail_bookings b
                JOIN national_rail_schedules s
                  ON s.schedule_id = b.schedule_id
                WHERE b.booking_id = %s
                """,
                (booking_id,),
            )
            booking = cur.fetchone()
            if not booking:
                conn.rollback()
                return False, "Booking not found."
            if booking["user_id"] != user_id:
                conn.rollback()
                return False, "Booking does not belong to this user."
            if booking["status"] == "cancelled":
                conn.rollback()
                return False, "Booking is already cancelled."

            departure_dt = datetime.combine(
                booking["travel_date"],
                booking["departure_time"],
            ).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_until_departure = (departure_dt - now).total_seconds() / 3600

            service_type = booking["service_type"]
            if service_type == "normal":
                if hours_until_departure >= 48:
                    refund_percent = 100
                elif hours_until_departure >= 24:
                    refund_percent = 75
                elif hours_until_departure >= 2:
                    refund_percent = 50
                else:
                    refund_percent = 0
                policy_note = "Normal service cancellation policy applied."
            else:
                if hours_until_departure >= 48:
                    refund_percent = 100
                elif hours_until_departure >= 4:
                    refund_percent = 50
                else:
                    refund_percent = 0
                policy_note = "Express service cancellation policy applied."

            refund_amount = round(float(booking["amount_usd"]) * refund_percent / 100, 2)

            cur.execute(
                """
                UPDATE national_rail_bookings
                SET status = 'cancelled'
                WHERE booking_id = %s
                """,
                (booking_id,),
            )
            conn.commit()
            return True, {
                "booking_id": booking_id,
                "status": "cancelled",
                "refund_percent": refund_percent,
                "refund_amount_usd": refund_amount,
                "policy_note": policy_note,
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    Returns (True, user_id) on success or (False, error_message) on failure.

    NOTE: passwords are stored as plain text here intentionally for teaching
    purposes. In production, replace with a salted hash (e.g. bcrypt).
    """
    email = email.strip().lower()
    first_name = first_name.strip()
    surname = surname.strip()
    full_name = f"{first_name} {surname}".strip()
    date_of_birth = f"{int(year_of_birth):04d}-01-01"

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id FROM registered_users WHERE email = %s",
                (email,),
            )
            if cur.fetchone():
                conn.rollback()
                return False, "An account with this email already exists."

            user_id = _gen_user_id()
            while True:
                cur.execute(
                    "SELECT 1 FROM registered_users WHERE user_id = %s",
                    (user_id,),
                )
                if not cur.fetchone():
                    break
                user_id = _gen_user_id()

            cur.execute(
                """
                INSERT INTO registered_users (
                    user_id, first_name, surname, full_name, email,
                    phone, date_of_birth, registered_at, is_active
                )
                VALUES (%s, %s, %s, %s, %s, NULL, %s, NOW(), TRUE)
                """,
                (user_id, first_name, surname, full_name, email, date_of_birth),
            )
            cur.execute(
                """
                INSERT INTO user_credentials (
                    user_id, password_hash, hashing_algorithm, secret_question, secret_answer_hash
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    ph.hash(password),
                    "argon2id",
                    secret_question,
                    ph.hash(secret_answer),
                ),
            )
            conn.commit()
            return True, user_id
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    sql = """
        SELECT
            u.user_id,
            u.email,
            u.full_name,
            u.first_name,
            u.surname,
            u.phone,
            u.date_of_birth,
            u.is_active,
            c.password_hash
        FROM registered_users u
        JOIN user_credentials c
          ON c.user_id = u.user_id
        WHERE u.email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email.strip().lower(),))
            row = cur.fetchone()
            if not row or not row["is_active"]:
                return None
            try:
                ph.verify(row["password_hash"], password)
            except (VerifyMismatchError, VerificationError):
                return None
            data = dict(row)
            data.pop("password_hash", None)
            return _to_jsonable(data)


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    sql = """
        SELECT c.secret_question
        FROM registered_users u
        JOIN user_credentials c
          ON c.user_id = u.user_id
        WHERE u.email = %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email.strip().lower(),))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    sql = """
        SELECT c.secret_answer_hash
        FROM registered_users u
        JOIN user_credentials c
          ON c.user_id = u.user_id
        WHERE u.email = %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email.strip().lower(),))
            row = cur.fetchone()
            if not row or not row[0]:
                return False
            try:
                return ph.verify(row[0], answer)
            except (VerifyMismatchError, VerificationError):
                return False


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_credentials c
                SET password_hash = %s,
                    updated_at = NOW()
                FROM registered_users u
                WHERE u.user_id = c.user_id
                  AND u.email = %s
                """,
                (ph.hash(new_password), email.strip().lower()),
            )
            updated = cur.rowcount > 0
            conn.commit()
            return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]
