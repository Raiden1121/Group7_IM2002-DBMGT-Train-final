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

import random
import string
from decimal import Decimal
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


ph = PasswordHasher()
LOCAL_TZ = ZoneInfo("Asia/Taipei")

# ── Helper functions ───────────────────────────────────────────────────────────────────
# Open a PostgreSQL connection for read-only query helpers.
def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


# Generate a candidate national rail booking ID.
def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


# Generate a candidate payment transaction ID.
def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# Generate an unused booking ID within the current transaction.
def _gen_unique_booking_id(cur) -> str:
    """Generate a booking ID that is not already used by travel_journeys."""
    booking_id = _gen_booking_id()
    while True:
        cur.execute("SELECT 1 FROM travel_journeys WHERE journey_id = %s", (booking_id,))
        if not cur.fetchone():
            return booking_id
        booking_id = _gen_booking_id()


# Generate an unused payment ID within the current transaction.
def _gen_unique_payment_id(cur) -> str:
    """Generate a payment ID that is not already used by payment_transactions."""
    payment_id = _gen_payment_id()
    while True:
        cur.execute("SELECT 1 FROM payment_transactions WHERE payment_id = %s", (payment_id,))
        if not cur.fetchone():
            return payment_id
        payment_id = _gen_payment_id()


# Generate an unused metro trip ID within the current transaction.
def _gen_unique_metro_trip_id(cur) -> str:
    """Generate a metro trip ID that is not already used by travel_journeys."""
    while True:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        trip_id = f"MT-{suffix}"
        cur.execute("SELECT 1 FROM travel_journeys WHERE journey_id = %s", (trip_id,))
        if not cur.fetchone():
            return trip_id


# Generate an unused feedback ID within the current transaction.
def _gen_unique_feedback_id(cur) -> str:
    """Generate a feedback ID that is not already used by journey_feedback."""
    while True:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        feedback_id = f"FB-{suffix}"
        cur.execute("SELECT 1 FROM journey_feedback WHERE feedback_id = %s", (feedback_id,))
        if not cur.fetchone():
            return feedback_id


# Generate a candidate local user ID.
def _gen_user_id() -> str:
    return f"RU{random.randint(100000, 999999)}"


# Convert database rows into JSON-safe Python values.
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


# Validate a registration birth year.
def _validate_birth_year(year_of_birth) -> tuple[bool, int | str]:
    """Validate and normalize a birth year used for account registration."""
    try:
        year = int(year_of_birth)
    except (TypeError, ValueError):
        return False, "Invalid year of birth."

    current_year = datetime.now(LOCAL_TZ).year
    if year < 1900 or year > current_year:
        return False, "Invalid year of birth."
    return True, year


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

# Return a simple database connectivity check.
def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# TODO: Implement the query_ and execute_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

# Find national rail services between two stations.
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
            WHERE %s IS NOT NULL
              AND travel_date = %s
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
            cur.execute(sql, (origin_id, destination_id, travel_date, travel_date))
            return [_to_jsonable(row) for row in cur.fetchall()]


# Calculate a national rail fare from schedule, class, and stop count.
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

# Find metro services between two stations.
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


# Calculate a metro fare from schedule and stop count.
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

# List currently available national rail seats.
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
            seats.fare_class,
            seats.seat_pk
        FROM national_rail_seat_layouts layouts
        JOIN national_rail_seats seats
          ON seats.layout_id = layouts.layout_id
        WHERE layouts.schedule_id = %s
          AND seats.fare_class = %s
          -- 排除已正式訂票且確認/完成的座位 (Confirmed Bookings)
          AND NOT EXISTS (
              SELECT 1
              FROM national_rail_bookings b
              WHERE b.schedule_id = %s
                AND b.travel_date = %s
                AND b.coach = seats.coach
                AND b.seat_id = seats.seat_id
                AND b.status IN ('confirmed', 'completed')
          )
          -- 排除正被他人臨時預鎖且未過期的座位 (Active seat locks)
          AND NOT EXISTS (
              SELECT 1
              FROM seat_locks l
              WHERE l.schedule_id = %s
                AND l.travel_date = %s
                AND l.seat_pk = seats.seat_pk
                AND l.status = 'pending'
                AND l.expires_at > NOW()
          )
        ORDER BY seats.coach, seats.seat_row, seats.seat_column
        -- 套用資料庫共享鎖 (S-Lock)，保護查詢期間的座位物理佈局不被修改，但允許多個用戶並行查詢
        FOR SHARE OF seats;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 傳入參數：[layouts.schedule_id, seats.fare_class, b.schedule_id, b.travel_date, l.schedule_id, l.travel_date]
            cur.execute(sql, (schedule_id, fare_class, schedule_id, travel_date, schedule_id, travel_date))
            return [_to_jsonable(row) for row in cur.fetchall()]


# Pick nearby seats from an available-seat list.
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
    groups = defaultdict(list)
    for seat in available_seats:
        groups[(seat["coach"], seat["row"])].append(seat)

    for group_seats in groups.values():
        group_seats.sort(key=lambda s: str(s["column"]))

    for _, group_seats in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        if len(group_seats) >= count:
            return [s["seat_id"] for s in group_seats[:count]]

    sorted_seats = sorted(
        available_seats,
        key=lambda s: (s["coach"], s["row"], str(s["column"])),
    )
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

# Fetch one user's profile by email.
def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    user_email = user_email.strip().lower()
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
            cur.execute(sql, (user_email,))
            return _to_jsonable(cur.fetchone())


# Fetch one user's rail and metro travel history.
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
            pay.payment_status,
            b.booked_at,
            b.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name
        FROM national_rail_bookings b
        JOIN national_rail_stations orig
          ON orig.station_id = b.origin_station_id
        JOIN national_rail_stations dest
          ON dest.station_id = b.destination_station_id
        LEFT JOIN LATERAL (
            SELECT pt.payment_status
            FROM payment_transactions pt
            WHERE pt.order_id = CONCAT('ORD-', b.booking_id)
              AND pt.transaction_type = 'charge'
            ORDER BY pt.processed_at DESC NULLS LAST
            LIMIT 1
        ) pay ON TRUE
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
            pay.payment_status,
            m.purchased_at,
            m.travelled_at,
            orig.name AS origin_name,
            dest.name AS destination_name
        FROM metro_travel_history m
        JOIN metro_stations orig
          ON orig.station_id = m.origin_station_id
        JOIN metro_stations dest
          ON dest.station_id = m.destination_station_id
        LEFT JOIN LATERAL (
            SELECT pt.payment_status
            FROM payment_transactions pt
            WHERE pt.order_id = CONCAT('ORD-', m.trip_id)
              AND pt.transaction_type = 'charge'
            ORDER BY pt.processed_at DESC NULLS LAST
            LIMIT 1
        ) pay ON TRUE
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


# Look up the latest payment transaction for one rail booking or metro trip.
def query_payment_info(booking_id: str, user_id: str | None = None) -> Optional[dict]:
    """Return the latest payment record for a single booking or metro trip."""
    booking_id = booking_id.strip().upper()
    if booking_id.startswith("ORD-"):
        booking_id = booking_id[4:]
    sql = """
        SELECT
            pt.payment_id,
            CASE WHEN to_tbl.network_type = 'national_rail' THEN SUBSTRING(pt.order_id FROM 5) ELSE NULL END AS booking_id,
            CASE WHEN to_tbl.network_type = 'metro' THEN SUBSTRING(pt.order_id FROM 5) ELSE NULL END AS metro_trip_id,
            pt.amount_usd,
            COALESCE(pi.method_type, 'unspecified') AS method,
            pt.payment_status AS status,
            pt.processed_at AS paid_at
        FROM payment_transactions pt
        JOIN travel_orders to_tbl
          ON to_tbl.order_id = pt.order_id
        LEFT JOIN payment_instruments pi
          ON pi.payment_instrument_id = pt.payment_instrument_id
        WHERE pt.order_id = %s
          AND (%s IS NULL OR to_tbl.user_id = %s)
        ORDER BY pt.processed_at DESC NULLS LAST
        LIMIT 1
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (f"ORD-{booking_id}", user_id, user_id))
            return _to_jsonable(cur.fetchone())


# ── ADDED USER ACCOUNT / METRO / FEEDBACK QUERIES ────────────────────────────

# Release expired pending orders and their reservations.
def cleanup_expired_pending_orders(user_id: str | None = None) -> int:
    """Cancel pending orders whose 10-minute payment window has expired."""
    user_id = user_id.strip() if user_id else None

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT to_tbl.order_id
                FROM travel_orders to_tbl
                JOIN payment_transactions pt
                  ON pt.order_id = to_tbl.order_id
                WHERE pt.transaction_type = 'charge'
                  AND pt.payment_status = 'pending'
                  AND pt.processed_at + INTERVAL '10 minutes' <= NOW()
                  AND (%s IS NULL OR to_tbl.user_id = %s)
                """,
                (user_id, user_id),
            )
            expired_orders = sorted({row["order_id"] for row in cur.fetchall()})

            for order_id in expired_orders:
                _release_pending_order(cur, order_id)

            conn.commit()
            return len(expired_orders)
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


# Release one pending order using existing view triggers where possible.
def _release_pending_order(cur, order_id: str) -> None:
    """Mark a pending order as cancelled/failed and release any active seat hold."""
    cur.execute(
        """
        SELECT
            to_tbl.order_id,
            to_tbl.user_id,
            to_tbl.network_type,
            tj.journey_id,
            tj.schedule_id,
            tj.travel_date,
            rjr.seat_pk
        FROM travel_orders to_tbl
        JOIN travel_journeys tj
          ON tj.order_id = to_tbl.order_id
        LEFT JOIN rail_journey_reservations rjr
          ON rjr.journey_id = tj.journey_id
        WHERE to_tbl.order_id = %s
        LIMIT 1
        """,
        (order_id,),
    )
    order = cur.fetchone()
    if not order:
        return

    if order["network_type"] == "national_rail":
        cur.execute(
            """
            UPDATE national_rail_bookings
            SET status = 'cancelled'
            WHERE booking_id = %s
            """,
            (order["journey_id"],),
        )
        if order["seat_pk"] is not None:
            cur.execute(
                """
                UPDATE seat_locks
                SET status = 'released'
                WHERE user_id = %s
                  AND schedule_id = %s
                  AND travel_date = %s
                  AND seat_pk = %s
                  AND status IN ('pending', 'confirmed')
                """,
                (
                    order["user_id"],
                    order["schedule_id"],
                    order["travel_date"],
                    order["seat_pk"],
                ),
            )
    else:
        cur.execute(
            """
            UPDATE metro_travel_history
            SET status = 'cancelled'
            WHERE trip_id = %s
            """,
            (order["journey_id"],),
        )

    cur.execute(
        """
        UPDATE payment_transactions
        SET payment_status = 'failed',
            processed_at = NOW()
        WHERE order_id = %s
          AND transaction_type = 'charge'
          AND payment_status = 'pending'
        """,
        (order_id,),
    )


# Fetch pending payment orders for one user.
def query_pending_orders(user_id: str) -> list[dict]:
    """Return pending orders that still need payment confirmation."""
    user_id = user_id.strip()
    cleanup_expired_pending_orders(user_id)

    sql = """
        SELECT
            to_tbl.order_id,
            tj.journey_id,
            to_tbl.network_type,
            origin.station_name AS origin_name,
            dest.station_name AS destination_name,
            tj.travel_date,
            pt.payment_id,
            pt.amount_usd,
            pt.payment_status,
            pt.processed_at,
            pt.processed_at + INTERVAL '10 minutes' AS expires_at,
            GREATEST(
                0,
                FLOOR(EXTRACT(EPOCH FROM (pt.processed_at + INTERVAL '10 minutes' - NOW())))
            )::INTEGER AS remaining_seconds
        FROM travel_orders to_tbl
        JOIN travel_journeys tj
          ON tj.order_id = to_tbl.order_id
        JOIN payment_transactions pt
          ON pt.order_id = to_tbl.order_id
        JOIN stations origin
          ON origin.station_id = tj.origin_station_id
         AND origin.network_type = tj.network_type
        JOIN stations dest
          ON dest.station_id = tj.destination_station_id
         AND dest.network_type = tj.network_type
        WHERE to_tbl.user_id = %s
          AND pt.transaction_type = 'charge'
          AND pt.payment_status = 'pending'
          AND pt.processed_at + INTERVAL '10 minutes' > NOW()
          AND to_tbl.order_status IN ('confirmed', 'completed')
          AND tj.journey_status IN ('confirmed', 'completed')
        ORDER BY pt.processed_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id,))
            return [_to_jsonable(row) for row in cur.fetchall()]


# Confirm payment for one pending order owned by the user.
def confirm_pending_payment(user_id: str, order_id: str) -> tuple[bool, dict | str]:
    """Mark one pending order payment as paid before the hold expires."""
    user_id = user_id.strip()
    order_id = order_id.strip().upper()

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    to_tbl.order_id,
                    pt.payment_id,
                    pt.amount_usd,
                    pt.processed_at + INTERVAL '10 minutes' AS expires_at
                FROM travel_orders to_tbl
                JOIN payment_transactions pt
                  ON pt.order_id = to_tbl.order_id
                WHERE to_tbl.order_id = %s
                  AND to_tbl.user_id = %s
                  AND pt.transaction_type = 'charge'
                  AND pt.payment_status = 'pending'
                ORDER BY pt.processed_at DESC
                LIMIT 1
                FOR UPDATE OF pt
                """,
                (order_id, user_id),
            )
            payment = cur.fetchone()
            if not payment:
                conn.rollback()
                return False, "Pending order not found."
            if payment["expires_at"] <= datetime.now(payment["expires_at"].tzinfo):
                _release_pending_order(cur, order_id)
                conn.commit()
                return False, "Payment window expired. The booking has been released."

            cur.execute(
                """
                UPDATE payment_transactions
                SET payment_status = 'paid',
                    processed_at = NOW()
                WHERE payment_id = %s
                """,
                (payment["payment_id"],),
            )
            conn.commit()
            return True, {
                "order_id": order_id,
                "payment_id": payment["payment_id"],
                "amount_usd": payment["amount_usd"],
                "payment_status": "paid",
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# Cancel one pending order owned by the user.
def cancel_pending_order(user_id: str, order_id: str) -> tuple[bool, dict | str]:
    """Cancel one pending order and release its booking or trip."""
    user_id = user_id.strip()
    order_id = order_id.strip().upper()

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT to_tbl.order_id
                FROM travel_orders to_tbl
                JOIN payment_transactions pt
                  ON pt.order_id = to_tbl.order_id
                WHERE to_tbl.order_id = %s
                  AND to_tbl.user_id = %s
                  AND pt.transaction_type = 'charge'
                  AND pt.payment_status = 'pending'
                LIMIT 1
                FOR UPDATE OF to_tbl
                """,
                (order_id, user_id),
            )
            if not cur.fetchone():
                conn.rollback()
                return False, "Pending order not found."

            _release_pending_order(cur, order_id)
            conn.commit()
            return True, {
                "order_id": order_id,
                "status": "cancelled",
                "payment_status": "failed",
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# Fetch active payment methods owned by one user without exposing token data.
def query_user_payment_methods(user_id: str) -> list[dict]:
    """Return active payment instruments for a user, excluding token_ref."""
    user_id = user_id.strip()
    sql = """
        SELECT
            payment_instrument_id,
            method_type,
            provider_name,
            last4,
            is_active,
            created_at
        FROM payment_instruments
        WHERE user_id = %s
          AND is_active = TRUE
        ORDER BY created_at DESC, payment_instrument_id
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id,))
            return [_to_jsonable(row) for row in cur.fetchall()]


# Submit one feedback record for a journey owned by the user.
def submit_feedback(
    user_id: str,
    journey_id: str,
    rating: int,
    comment: str | None,
) -> tuple[bool, dict | str]:
    """Create feedback for a user's own journey and prevent duplicate reviews."""
    user_id = user_id.strip()
    journey_id = journey_id.strip()
    comment = comment.strip() if comment else None

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return False, "Rating must be an integer between 1 and 5."
    if rating < 1 or rating > 5:
        return False, "Rating must be between 1 and 5."

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT tj.journey_id, to_tbl.user_id, to_tbl.network_type
                FROM travel_journeys tj
                JOIN travel_orders to_tbl
                  ON to_tbl.order_id = tj.order_id
                WHERE tj.journey_id = %s
                """,
                (journey_id,),
            )
            journey = cur.fetchone()
            if not journey:
                conn.rollback()
                return False, "Journey not found."
            if journey["user_id"] != user_id:
                conn.rollback()
                return False, "Journey does not belong to this user."

            cur.execute(
                """
                SELECT feedback_id
                FROM journey_feedback
                WHERE journey_id = %s
                  AND user_id = %s
                """,
                (journey_id, user_id),
            )
            if cur.fetchone():
                conn.rollback()
                return False, "Feedback has already been submitted for this journey."

            feedback_id = _gen_unique_feedback_id(cur)
            cur.execute(
                """
                INSERT INTO feedback (
                    feedback_id, user_id, booking_id, metro_trip_id, rating, comment, submitted_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    feedback_id,
                    user_id,
                    journey_id if journey["network_type"] == "national_rail" else None,
                    journey_id if journey["network_type"] == "metro" else None,
                    rating,
                    comment,
                ),
            )
            conn.commit()
            return True, {
                "feedback_id": feedback_id,
                "user_id": user_id,
                "journey_id": journey_id,
                "rating": rating,
                "comment": comment,
                "status": "submitted",
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# Fetch feedback submitted by one user, optionally for a single journey.
def query_feedback(user_id: str, journey_id: str | None = None) -> list[dict]:
    """Return feedback records owned by the user."""
    user_id = user_id.strip()
    journey_id = journey_id.strip() if journey_id else None
    sql = """
        SELECT
            jf.feedback_id,
            jf.journey_id,
            to_tbl.network_type,
            CASE WHEN to_tbl.network_type = 'national_rail' THEN jf.journey_id ELSE NULL END AS booking_id,
            CASE WHEN to_tbl.network_type = 'metro' THEN jf.journey_id ELSE NULL END AS metro_trip_id,
            jf.rating,
            jf.comment,
            jf.submitted_at
        FROM journey_feedback jf
        JOIN travel_journeys tj
          ON tj.journey_id = jf.journey_id
        JOIN travel_orders to_tbl
          ON to_tbl.order_id = tj.order_id
        WHERE jf.user_id = %s
          AND to_tbl.user_id = %s
          AND (%s IS NULL OR jf.journey_id = %s)
        ORDER BY jf.submitted_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id, user_id, journey_id, journey_id))
            return [_to_jsonable(row) for row in cur.fetchall()]


# Buy a metro ticket and create a pending payment transaction.
def buy_metro_ticket(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    ticket_type: str = "single",
    payment_instrument_id: str | None = None,
) -> tuple[bool, dict | str]:
    """Create a metro trip for an active user and defer payment completion."""
    user_id = user_id.strip()
    schedule_id = schedule_id.strip().upper()
    origin_station_id = origin_station_id.strip().upper()
    destination_station_id = destination_station_id.strip().upper()
    travel_date = travel_date.strip()
    ticket_type = ticket_type.strip().lower()
    payment_instrument_id = payment_instrument_id.strip() if payment_instrument_id else None
    if payment_instrument_id and payment_instrument_id.lower() in {"null", "none"}:
        payment_instrument_id = None

    if ticket_type not in {"single", "day_pass"}:
        return False, "Metro ticket type must be single or day_pass."

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
                    o.stop_order AS origin_stop_order,
                    d.stop_order AS destination_stop_order,
                    d.stop_order - o.stop_order AS stops_travelled
                FROM metro_schedules s
                JOIN metro_schedule_stops o
                  ON o.schedule_id = s.schedule_id
                JOIN metro_schedule_stops d
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
                return False, "Metro schedule does not serve the selected stations in that order."

            if ticket_type == "day_pass":
                amount_usd = 5.0
            else:
                cur.execute(
                    """
                    SELECT base_fare_usd + (per_stop_rate_usd * %s) AS total_fare_usd
                    FROM metro_schedules
                    WHERE schedule_id = %s
                    """,
                    (route["stops_travelled"], schedule_id),
                )
                fare = cur.fetchone()
                if not fare:
                    conn.rollback()
                    return False, "Metro fare information not found."
                amount_usd = float(fare["total_fare_usd"])

            if payment_instrument_id:
                cur.execute(
                    """
                    SELECT payment_instrument_id
                    FROM payment_instruments
                    WHERE payment_instrument_id = %s
                      AND user_id = %s
                      AND is_active = TRUE
                    """,
                    (payment_instrument_id, user_id),
                )
                if not cur.fetchone():
                    conn.rollback()
                    return False, "Payment instrument not found or inactive for this user."

            trip_id = _gen_unique_metro_trip_id(cur)
            payment_id = _gen_unique_payment_id(cur)

            cur.execute(
                """
                INSERT INTO metro_travel_history (
                    trip_id, user_id, schedule_id, origin_station_id, destination_station_id,
                    travel_date, ticket_type, day_pass_ref, stops_travelled, amount_usd,
                    status, purchased_at, travelled_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, NOW(), NOW())
                """,
                (
                    trip_id,
                    user_id,
                    schedule_id,
                    origin_station_id,
                    destination_station_id,
                    travel_date,
                    ticket_type,
                    route["stops_travelled"],
                    amount_usd,
                    "completed",
                ),
            )
            cur.execute(
                """
                INSERT INTO payment_transactions (
                    payment_id, order_id, payment_instrument_id, transaction_type,
                    amount_usd, currency_code, payment_status, gateway_reference, processed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NOW())
                """,
                (
                    payment_id,
                    f"ORD-{trip_id}",
                    payment_instrument_id,
                    "charge",
                    amount_usd,
                    "USD",
                    "pending",
                ),
            )
            conn.commit()
            return True, {
                "trip_id": trip_id,
                "payment_id": payment_id,
                "payment_instrument_id": payment_instrument_id,
                "user_id": user_id,
                "schedule_id": schedule_id,
                "origin_station_id": origin_station_id,
                "destination_station_id": destination_station_id,
                "travel_date": travel_date,
                "ticket_type": ticket_type,
                "stops_travelled": route["stops_travelled"],
                "amount_usd": amount_usd,
                "status": "completed",
                "payment_status": "pending",
            }
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        constraint_name = getattr(e.diag, "constraint_name", None)
        if constraint_name in {"travel_orders_pkey", "travel_orders_order_code_key", "travel_journeys_pkey"}:
            return False, "Generated metro trip ID already exists. Please try again."
        if constraint_name == "payment_transactions_pkey":
            return False, "Generated payment ID already exists. Please try again."
        return False, f"Metro ticket could not be completed because of a duplicate record: {constraint_name}."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# Fetch recent login audit entries for one user only.
def query_my_login_audit(user_id: str, limit: int = 10) -> list[dict]:
    """Return the user's own login audit results without IP or user-agent hashes."""
    user_id = user_id.strip()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    sql = """
        SELECT result, occurred_at
        FROM auth_login_audit
        WHERE user_id = %s
        ORDER BY occurred_at DESC
        LIMIT %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id, limit))
            return [_to_jsonable(row) for row in cur.fetchall()]


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

# Create a rail booking from route details when the user does not know schedule_id.
def execute_booking_by_route(
    user_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str = "any",
    ticket_type: str = "single",
    payment_instrument_id: str | None = None,
) -> tuple[bool, dict | str]:
    """
    Resolve a national rail route booking to a concrete schedule, then reuse execute_booking().
    """
    user_id = user_id.strip()
    origin_station_id = origin_station_id.strip().upper()
    destination_station_id = destination_station_id.strip().upper()
    travel_date = travel_date.strip()
    fare_class = fare_class.strip().lower()
    seat_id = seat_id.strip() if seat_id else "any"
    ticket_type = ticket_type.strip().lower()
    payment_instrument_id = payment_instrument_id.strip() if payment_instrument_id else None
    if payment_instrument_id and payment_instrument_id.lower() in {"null", "none"}:
        payment_instrument_id = None

    sql = """
        SELECT
            s.schedule_id,
            s.first_train_time,
            o.stop_order AS origin_stop_order,
            d.stop_order AS destination_stop_order
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops o
          ON o.schedule_id = s.schedule_id
        JOIN national_rail_schedule_stops d
          ON d.schedule_id = s.schedule_id
        JOIN national_rail_fare_classes f
          ON f.schedule_id = s.schedule_id
         AND f.fare_class = %s
        WHERE o.station_id = %s
          AND d.station_id = %s
          AND o.stop_order < d.stop_order
        ORDER BY s.first_train_time, s.schedule_id
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (fare_class, origin_station_id, destination_station_id))
            schedules = [_to_jsonable(row) for row in cur.fetchall()]

    if not schedules:
        return False, "No national rail schedule serves this route with the requested fare class."

    if seat_id.lower() != "any":
        for schedule in schedules:
            ok, data = execute_booking(
                user_id=user_id,
                schedule_id=schedule["schedule_id"],
                origin_station_id=origin_station_id,
                destination_station_id=destination_station_id,
                travel_date=travel_date,
                fare_class=fare_class,
                seat_id=seat_id,
                ticket_type=ticket_type,
                payment_instrument_id=payment_instrument_id,
            )
            if ok:
                return ok, data
        return False, "Selected seat is not available on any matching schedule."

    for schedule in schedules:
        available = query_available_seats(
            schedule_id=schedule["schedule_id"],
            travel_date=travel_date,
            fare_class=fare_class,
        )
        selected = auto_select_adjacent_seats(available, 1)
        if not selected:
            continue
        ok, data = execute_booking(
            user_id=user_id,
            schedule_id=schedule["schedule_id"],
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
            travel_date=travel_date,
            fare_class=fare_class,
            seat_id=selected[0],
            ticket_type=ticket_type,
            payment_instrument_id=payment_instrument_id,
        )
        if ok:
            return ok, data

    return False, "No available seats for this route, date, and fare class."


# [NEW] 申請預鎖座位 (業務排他鎖)
def execute_lock_seat(
    user_id: str,
    schedule_id: str,
    travel_date: str,
    seat_id: str,
) -> tuple[bool, str]:
    """
    嘗試獲取業務排他鎖 (10 分鐘座位預鎖)。
    1. 執行過期鎖清除的垃圾回收。
    2. 檢查座位是否存在，並透過 SELECT ... FOR UPDATE 獲得列級鎖防止併發衝擊。
    3. 驗證該座位當前沒有被正式預訂。
    4. 生成唯一的隨機 LK 鎖編號，嘗試 INSERT。若捕獲 UniqueViolation，說明該座位已被他人鎖定。
    """
    user_id = user_id.strip()
    schedule_id = schedule_id.strip().upper()
    travel_date = travel_date.strip()
    seat_id = seat_id.strip().upper()

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. 垃圾回收：自動清理過期的 pending 臨時鎖以保持資料表整潔
            cur.execute("DELETE FROM seat_locks WHERE expires_at <= NOW();")

            # 2. 獲取該座位的物理 seat_pk
            cur.execute(
                """
                SELECT s.seat_pk
                FROM national_rail_seat_layouts l
                JOIN national_rail_seats s ON s.layout_id = l.layout_id
                WHERE l.schedule_id = %s AND s.seat_id = %s
                """,
                (schedule_id, seat_id)
            )
            seat = cur.fetchone()
            if not seat:
                conn.rollback()
                return False, "Seat not found for the selected schedule."
            seat_pk = seat["seat_pk"]

            # 3. 獲取資料庫級排他鎖 (X-Lock)，保證高併發插入時的併發安全性
            cur.execute("SELECT 1 FROM seat_layout_seats WHERE seat_pk = %s FOR UPDATE;", (seat_pk,))

            # 4. 檢查座位是否已經被正式訂票 (Confirmed Booking)
            cur.execute(
                """
                SELECT 1
                FROM national_rail_bookings b
                JOIN national_rail_seats seats ON seats.coach = b.coach AND seats.seat_id = b.seat_id
                JOIN national_rail_seat_layouts layouts ON layouts.layout_id = seats.layout_id
                WHERE layouts.schedule_id = %s
                  AND b.travel_date = %s
                  AND seats.seat_pk = %s
                  AND b.status IN ('confirmed', 'completed')
                """,
                (schedule_id, travel_date, seat_pk)
            )
            if cur.fetchone():
                conn.rollback()
                return False, "Selected seat is already booked."

            # 5. 確保該座位沒有被其他人的有效 pending 鎖佔用
            cur.execute(
                """
                SELECT 1 FROM seat_locks
                WHERE schedule_id = %s
                  AND travel_date = %s
                  AND seat_pk = %s
                  AND status = 'pending'
                  AND expires_at > NOW()
                """,
                (schedule_id, travel_date, seat_pk)
            )
            if cur.fetchone():
                conn.rollback()
                return False, "該座位正在被其他人挑選中，請稍候"

            # 6. 生成唯一鎖編號並插入臨時鎖記錄 (自動透過 Trigger 設定 10 分鐘過期)
            while True:
                suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                lock_id = f"LK-{suffix}"
                cur.execute("SELECT 1 FROM seat_locks WHERE lock_id = %s", (lock_id,))
                if not cur.fetchone():
                    break

            cur.execute(
                """
                INSERT INTO seat_locks (lock_id, user_id, schedule_id, travel_date, seat_pk, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                """,
                (lock_id, user_id, schedule_id, travel_date, seat_pk)
            )
            conn.commit()
            return True, lock_id

    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        # 捕獲唯一性衝突，代表該座位正被其他人臨時預鎖中
        return False, "該座位正在被其他人挑選中，請稍候"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# [NEW] 手動釋放座位鎖 (使用者放棄預訂流程時主動調用)
def execute_release_seat(lock_id: str, user_id: str) -> bool:
    """
    手動釋放座位鎖。
    當用戶主動取消付款或返回上一頁時，將該臨時鎖狀態標記為 released 或直接刪除以釋放資源。
    """
    lock_id = lock_id.strip()
    user_id = user_id.strip()

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # 刪除該用戶對應的 pending 狀態臨時鎖
            cur.execute(
                """
                DELETE FROM seat_locks
                WHERE lock_id = %s AND user_id = %s AND status = 'pending'
                """,
                (lock_id, user_id)
            )
            released = cur.rowcount > 0
            conn.commit()
            return released
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# Create a rail booking and record a pending charge transaction.
def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
    payment_instrument_id: str | None = None,
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user and defer payment completion.

    Args:
        user_id:                e.g. "RU01" — must match the logged-in user
        schedule_id:            e.g. "NR_SCH01"
        origin_station_id:      e.g. "NR01"
        destination_station_id: e.g. "NR05"
        travel_date:            e.g. "2025-06-01"
        fare_class:             "standard" or "first"
        seat_id:                e.g. "B05" (or "any" to auto-assign)
        ticket_type:            "single" (default) or "return"
        payment_instrument_id:  optional saved payment method owned by the user

    Returns:
        (True, booking_dict)   on success
        (False, error_message) on failure
    """
    user_id = user_id.strip()
    schedule_id = schedule_id.strip().upper()
    origin_station_id = origin_station_id.strip().upper()
    destination_station_id = destination_station_id.strip().upper()
    travel_date = travel_date.strip()
    seat_id = seat_id.strip()
    if seat_id.lower() != "any":
        seat_id = seat_id.upper()
    fare_class = fare_class.strip().lower()
    ticket_type = ticket_type.strip().lower()
    payment_instrument_id = payment_instrument_id.strip() if payment_instrument_id else None
    if payment_instrument_id and payment_instrument_id.lower() in {"null", "none"}:
        payment_instrument_id = None

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
            selected_seat_pk = None
            if seat_id.lower() == "any":
                # query_available_seats 會帶有 FOR SHARE S-Lock，保證讀取期間不會發生配置修改
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    conn.rollback()
                    return False, "No seats available for the selected service."
                selected = available[0]
                selected_seat_id = selected["seat_id"]
                selected_coach = selected["coach"]
                selected_seat_pk = selected["seat_pk"]
            else:
                cur.execute(
                    """
                    SELECT coach, seat_id, fare_class, seat_pk
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
                selected_coach = seat["coach"]
                selected_seat_pk = seat["seat_pk"]

            # 1. 套用資料庫列級排他鎖 (X-Lock / FOR UPDATE)，阻止其他交易同時對該座位進行 booking
            cur.execute(
                "SELECT 1 FROM seat_layout_seats WHERE seat_pk = %s FOR UPDATE;",
                (selected_seat_pk,)
            )

            # 2. 驗證該座位當前沒有被正式預訂 (防禦 Race Condition)
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
                (schedule_id, travel_date, selected_coach, selected_seat_id),
            )
            if cur.fetchone():
                conn.rollback()
                return False, "Selected seat is already booked."

            # 3. 確保該座位沒有被「其他用戶」的有效 pending 臨時鎖佔用
            cur.execute(
                """
                SELECT user_id 
                FROM seat_locks 
                WHERE schedule_id = %s 
                  AND travel_date = %s 
                  AND seat_pk = %s 
                  AND status = 'pending' 
                  AND expires_at > NOW()
                """,
                (schedule_id, travel_date, selected_seat_pk)
            )
            active_lock = cur.fetchone()
            if active_lock and active_lock["user_id"] != user_id:
                conn.rollback()
                return False, "該座位已被其他使用者臨時預鎖，請選擇其他座位"

            fare = query_national_rail_fare(schedule_id, fare_class, route["stops_travelled"])
            if not fare:
                conn.rollback()
                return False, "Fare information not found."

            if payment_instrument_id:
                cur.execute(
                    """
                    SELECT payment_instrument_id
                    FROM payment_instruments
                    WHERE payment_instrument_id = %s
                      AND user_id = %s
                      AND is_active = TRUE
                    """,
                    (payment_instrument_id, user_id),
                )
                if not cur.fetchone():
                    conn.rollback()
                    return False, "Payment instrument not found or inactive for this user."

            booking_id = _gen_unique_booking_id(cur)
            payment_id = _gen_unique_payment_id(cur)

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
                INSERT INTO payment_transactions (
                    payment_id, order_id, payment_instrument_id, transaction_type,
                    amount_usd, currency_code, payment_status, gateway_reference, processed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NOW())
                """,
                (
                    payment_id,
                    f"ORD-{booking_id}",
                    payment_instrument_id,
                    "charge",
                    fare["total_fare_usd"],
                    "USD",
                    "pending",
                ),
            )

            # 4. 鎖轉移 (Lock Transfer)：若當前用戶擁有該座位的臨時鎖，將其 pending 鎖升級/更新為 confirmed
            cur.execute(
                """
                UPDATE seat_locks
                SET status = 'confirmed'
                WHERE user_id = %s
                  AND schedule_id = %s
                  AND travel_date = %s
                  AND seat_pk = %s
                  AND status = 'pending'
                """,
                (user_id, schedule_id, travel_date, selected_seat_pk)
            )

            conn.commit()
            return True, {
                "booking_id": booking_id,
                "payment_id": payment_id,
                "payment_instrument_id": payment_instrument_id,
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
                "payment_status": "pending",
            }
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        constraint_name = getattr(e.diag, "constraint_name", None)
        if constraint_name == "uq_active_seat_reservation":
            return False, "Selected seat was just booked by another user. Please choose another seat."
        if constraint_name in {"travel_orders_pkey", "travel_journeys_pkey"}:
            return False, "Generated booking ID already exists. Please try again."
        if constraint_name == "payment_transactions_pkey":
            return False, "Generated payment ID already exists. Please try again."
        return False, f"Booking could not be completed because of a duplicate record: {constraint_name}."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# Cancel a rail booking and record the matching refund transaction when applicable.
def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.

    Calculates the refund amount according to the booking's service type:
      - Normal service: RF001 windows (100% / 75% - $0.50 / 50% - $0.50 / 0%)
      - Express service: RF002 windows (100% - $1.00 / 50% - $1.00 / 0%)

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
                    b.ticket_type,
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
            if booking["status"] != "confirmed":
                conn.rollback()
                return False, f"Only confirmed bookings can be cancelled. Current status: {booking['status']}."

            departure_dt = datetime.combine(
                booking["travel_date"],
                booking["departure_time"],
                tzinfo=LOCAL_TZ,
            )
            now = datetime.now(LOCAL_TZ)
            hours_until_departure = (departure_dt - now).total_seconds() / 3600
            if hours_until_departure <= 0:
                conn.rollback()
                return False, "This booking cannot be cancelled after departure."

            service_type = booking["service_type"]
            if service_type == "normal":
                if hours_until_departure >= 48:
                    refund_percent = 100
                    admin_fee_usd = 0.0
                elif hours_until_departure >= 24:
                    refund_percent = 75
                    admin_fee_usd = 0.5
                elif hours_until_departure >= 2:
                    refund_percent = 50
                    admin_fee_usd = 0.5
                else:
                    refund_percent = 0
                    admin_fee_usd = 0.0
                policy_note = "Normal service cancellation policy applied."
            else:
                if hours_until_departure >= 48:
                    refund_percent = 100
                    admin_fee_usd = 1.0
                elif hours_until_departure >= 24:
                    refund_percent = 50
                    admin_fee_usd = 1.0
                else:
                    refund_percent = 0
                    admin_fee_usd = 0.0
                policy_note = "Express service cancellation policy applied."

            refund_amount = max(
                0,
                round(float(booking["amount_usd"]) * refund_percent / 100 - admin_fee_usd, 2),
            )

            cur.execute(
                """
                SELECT payment_id, payment_instrument_id
                FROM payment_transactions
                WHERE order_id = %s
                  AND transaction_type = 'charge'
                  AND payment_status = 'paid'
                ORDER BY processed_at DESC
                LIMIT 1
                """,
                (f"ORD-{booking_id}",),
            )
            original_payment = cur.fetchone()
            refund_payment_id = None

            cur.execute(
                """
                UPDATE national_rail_bookings
                SET status = 'cancelled'
                WHERE booking_id = %s
                """,
                (booking_id,),
            )

            if refund_amount > 0 and original_payment:
                refund_payment_id = _gen_unique_payment_id(cur)
                cur.execute(
                    """
                    INSERT INTO payment_transactions (
                        payment_id, order_id, payment_instrument_id, transaction_type,
                        amount_usd, currency_code, payment_status, gateway_reference,
                        processed_at, ref_payment_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NOW(), %s)
                    """,
                    (
                        refund_payment_id,
                        f"ORD-{booking_id}",
                        original_payment["payment_instrument_id"],
                        "refund",
                        refund_amount,
                        "USD",
                        "refunded",
                        original_payment["payment_id"],
                    ),
                )

            conn.commit()
            return True, {
                "booking_id": booking_id,
                "status": "cancelled",
                "refund_percent": refund_percent,
                "admin_fee_usd": admin_fee_usd,
                "refund_amount_usd": refund_amount,
                "refund_payment_id": refund_payment_id,
                "ref_payment_id": original_payment["payment_id"] if original_payment else None,
                "policy_note": policy_note,
            }
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

# Register a password user with Argon2-hashed credentials and recovery answer.
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

    NOTE: passwords and recovery answers are stored as Argon2 hashes.
    """
    email = email.strip().lower()
    first_name = first_name.strip()
    surname = surname.strip()
    full_name = f"{first_name} {surname}".strip()
    secret_question = secret_question.strip()
    secret_answer = secret_answer.strip()

    ok_year, year_or_error = _validate_birth_year(year_of_birth)
    if not ok_year:
        return False, year_or_error
    if not email:
        return False, "Email cannot be empty."
    if "@" not in email or "." not in email:
        return False, "Invalid email format."
    if not first_name:
        return False, "First name cannot be empty."
    if not surname:
        return False, "Surname cannot be empty."
    if not password:
        return False, "Password cannot be empty."
    if not secret_question:
        return False, "Secret question cannot be empty."
    if not secret_answer:
        return False, "Secret answer cannot be empty."

    date_of_birth = f"{year_or_error:04d}-01-01"

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


# Verify a password login and write an audit result for the attempt.
def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    email = email.strip().lower()
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
    audit_sql = """
        INSERT INTO auth_login_audit (
            user_id, login_email_attempted, ip_hash, user_agent_hash, result, occurred_at
        )
        VALUES (%s, %s, NULL, NULL, %s, NOW())
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if not row:
                cur.execute(audit_sql, (None, email, "failed"))
                return None
            if not row["is_active"]:
                cur.execute(audit_sql, (row["user_id"], email, "locked"))
                return None
            try:
                ph.verify(row["password_hash"], password)
            except (VerifyMismatchError, VerificationError):
                cur.execute(audit_sql, (row["user_id"], email, "failed"))
                return None
            cur.execute(audit_sql, (row["user_id"], email, "success"))
            data = dict(row)
            data.pop("password_hash", None)
            return _to_jsonable(data)


# Link an existing Google account or stage a new Google signup.
def login_or_create_google_user(
    provider_user_id: str,
    email: str,
    email_verified: bool,
    display_name: str | None,
    avatar_url: str | None,
) -> Optional[dict]:
    """
    Login an existing Google OAuth user or link Google to an existing email account.

    New Google-only users are not created here because user_profiles.date_of_birth
    is required. The UI stores the Google profile in session and asks for birth year
    before calling complete_google_signup().
    """
    email = email.strip().lower()
    full_name = (display_name or email.split("@")[0]).strip()

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Existing Google account
            cur.execute(
                """
                SELECT u.*
                FROM user_oauth_accounts oauth
                JOIN registered_users u
                  ON u.user_id = oauth.user_id
                WHERE oauth.provider = 'google'
                  AND oauth.provider_user_id = %s
                """,
                (provider_user_id,),
            )
            user = cur.fetchone()
            if user:
                if not user["is_active"]:
                    conn.rollback()
                    return None
                cur.execute(
                    """
                    UPDATE user_oauth_accounts
                    SET last_login_at = NOW(),
                        email = %s,
                        email_verified = %s,
                        display_name = %s,
                        avatar_url = %s
                    WHERE provider = 'google'
                      AND provider_user_id = %s
                    """,
                    (email, email_verified, full_name, avatar_url, provider_user_id),
                )
                conn.commit()
                return _to_jsonable(user)

            # 2. Existing local account with same email
            cur.execute(
                "SELECT * FROM registered_users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()
            if not user:
                conn.rollback()
                return {
                    "needs_birth_year": True,
                    "provider": "google",
                    "provider_user_id": provider_user_id,
                    "email": email,
                    "email_verified": email_verified,
                    "display_name": full_name,
                    "avatar_url": avatar_url,
                }
            if not user["is_active"]:
                conn.rollback()
                return None
            user_id = user["user_id"]

            # 3. Link Google account to the existing local user.
            cur.execute(
                """
                INSERT INTO user_oauth_accounts (
                    provider, provider_user_id, user_id, email,
                    email_verified, display_name, avatar_url,
                    created_at, last_login_at
                )
                VALUES ('google', %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (provider, provider_user_id) DO UPDATE
                SET last_login_at = NOW()
                """,
                (provider_user_id, user_id, email, email_verified, full_name, avatar_url),
            )

            cur.execute("SELECT * FROM registered_users WHERE user_id = %s", (user_id,))
            user = cur.fetchone()
            conn.commit()
            return _to_jsonable(user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Complete a pending Google signup after collecting birth year.
def complete_google_signup(
    provider_user_id: str,
    email: str,
    email_verified: bool,
    display_name: str | None,
    avatar_url: str | None,
    year_of_birth: int,
) -> Optional[dict]:
    """
    Create a local TransitFlow user after Google OAuth and required birth year.

    If the Google account or email was linked while the user was completing the
    form, the existing active account is returned instead of creating a duplicate.
    """
    email = email.strip().lower()
    full_name = (display_name or email.split("@")[0]).strip()
    parts = full_name.split(maxsplit=1)
    first_name = parts[0]
    surname = parts[1] if len(parts) > 1 else ""

    ok_year, year_or_error = _validate_birth_year(year_of_birth)
    if not ok_year:
        return None
    date_of_birth = f"{year_or_error:04d}-01-01"

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Re-check whether the Google account was created in another tab.
            cur.execute(
                """
                SELECT u.*
                FROM user_oauth_accounts oauth
                JOIN registered_users u
                  ON u.user_id = oauth.user_id
                WHERE oauth.provider = 'google'
                  AND oauth.provider_user_id = %s
                """,
                (provider_user_id,),
            )
            user = cur.fetchone()
            if user:
                if not user["is_active"]:
                    conn.rollback()
                    return None
                cur.execute(
                    """
                    UPDATE user_oauth_accounts
                    SET last_login_at = NOW()
                    WHERE provider = 'google'
                      AND provider_user_id = %s
                    """,
                    (provider_user_id,),
                )
                conn.commit()
                return _to_jsonable(user)

            # 2. Reuse an existing local account with the same email when present.
            cur.execute(
                "SELECT * FROM registered_users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()
            if user:
                if not user["is_active"]:
                    conn.rollback()
                    return None
                user_id = user["user_id"]
            else:
                user_id = _gen_user_id()
                while True:
                    cur.execute("SELECT 1 FROM user_profiles WHERE user_id = %s", (user_id,))
                    if not cur.fetchone():
                        break
                    user_id = _gen_user_id()

                cur.execute(
                    """
                    INSERT INTO user_profiles (
                        user_id, full_name, first_name, surname,
                        phone, date_of_birth, is_active, registered_at
                    )
                    VALUES (%s, %s, %s, %s, NULL, %s, TRUE, NOW())
                    """,
                    (user_id, full_name, first_name, surname, date_of_birth),
                )

            # 3. Store the Google account mapping after the local user exists.
            cur.execute(
                """
                INSERT INTO user_oauth_accounts (
                    provider, provider_user_id, user_id, email,
                    email_verified, display_name, avatar_url,
                    created_at, last_login_at
                )
                VALUES ('google', %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (provider, provider_user_id) DO UPDATE
                SET last_login_at = NOW(),
                    email = EXCLUDED.email,
                    email_verified = EXCLUDED.email_verified,
                    display_name = EXCLUDED.display_name,
                    avatar_url = EXCLUDED.avatar_url
                """,
                (provider_user_id, user_id, email, email_verified, full_name, avatar_url),
            )

            cur.execute("SELECT * FROM registered_users WHERE user_id = %s", (user_id,))
            user = cur.fetchone()
            conn.commit()
            return _to_jsonable(user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Fetch the password recovery question for an email.
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


# Verify a password recovery answer.
def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer."""
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
                return ph.verify(row[0], answer.strip())
            except (VerifyMismatchError, VerificationError):
                return False


# Replace a password credential with a new Argon2 hash.
def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    new_password = new_password.strip()
    if not new_password:
        return False

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_auth_credentials c
                SET password_hash = %s,
                    password_changed_at = NOW()
                FROM user_profiles up
                WHERE up.user_id = c.user_id
                  AND LOWER(c.login_email) = %s
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

# Search policy documents by vector similarity.
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


# Store one embedded policy document chunk.
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
