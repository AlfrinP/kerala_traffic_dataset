"""
TomTom Matrix Routing data collector for Kerala traffic patterns.

Queries all pairs of Kerala locations via the TomTom Matrix Routing v2 API
and records travel distances and durations (with live traffic) into a
PostgreSQL database. Designed to run as a cron job every hour.

Usage:
    python collect.py

Requires in .env:
    TOMTOM_API_KEY         (free at developer.tomtom.com — 2,500 req/day)
    COLLECTOR_DATABASE_URL (e.g. postgresql://user:pass@localhost:5432/smartmap)
"""

import os
import sys
import time
from datetime import datetime, timezone

import httpx
import psycopg2
from dotenv import load_dotenv

from locations import KERALA_LOCATIONS

load_dotenv()

API_KEY = os.getenv("TOMTOM_API_KEY", "")
DATABASE_URL = os.getenv("COLLECTOR_DATABASE_URL", "")
MATRIX_URL = "https://api.tomtom.com/routing/matrix/2"
# Free tier max matrix size is 100 cells; 5 origins x 20 destinations = 100
BATCH_SIZE = 5


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traffic_data (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    day_of_week VARCHAR(10) NOT NULL,
    hour INTEGER NOT NULL,
    origin_name VARCHAR(100) NOT NULL,
    origin_lat DOUBLE PRECISION NOT NULL,
    origin_lng DOUBLE PRECISION NOT NULL,
    dest_name VARCHAR(100) NOT NULL,
    dest_lat DOUBLE PRECISION NOT NULL,
    dest_lng DOUBLE PRECISION NOT NULL,
    distance_m INTEGER NOT NULL,
    duration_s INTEGER NOT NULL,
    duration_in_traffic_s INTEGER NOT NULL
);
"""

INSERT_SQL = """
INSERT INTO traffic_data
    (timestamp, day_of_week, hour, origin_name, origin_lat, origin_lng,
     dest_name, dest_lat, dest_lng, distance_m, duration_s, duration_in_traffic_s)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def query_batch(origins: list[dict], destinations: list[dict]) -> dict:
    body = {
        "origins": [
            {"point": {"latitude": loc["lat"], "longitude": loc["lng"]}}
            for loc in origins
        ],
        "destinations": [
            {"point": {"latitude": loc["lat"], "longitude": loc["lng"]}}
            for loc in destinations
        ],
        "options": {
            "departAt": "now",
            "traffic": "live",
            "travelMode": "car",
            "routeType": "fastest",
        },
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            MATRIX_URL,
            json=body,
            params={"key": API_KEY},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def parse_response(data: dict, origins: list[dict], destinations: list[dict]) -> list[tuple]:
    """
    TomTom v2 returns a flat 'data' array. Each element has:
      - originIndex / destinationIndex
      - routeSummary.lengthInMeters
      - routeSummary.travelTimeInSeconds     (includes live traffic)
      - routeSummary.trafficDelayInSeconds    (extra delay from traffic)
    """
    now = datetime.now(timezone.utc)
    day_of_week = now.strftime("%A")
    hour = now.hour

    rows = []
    for cell in data.get("data", []):
        if "routeSummary" not in cell:
            continue

        oi = cell["originIndex"]
        di = cell["destinationIndex"]
        origin = origins[oi]
        dest = destinations[di]

        if origin["name"] == dest["name"]:
            continue

        summary = cell["routeSummary"]
        distance_m = summary["lengthInMeters"]
        travel_time_s = summary["travelTimeInSeconds"]
        traffic_delay_s = summary.get("trafficDelayInSeconds", 0)
        base_duration_s = travel_time_s - traffic_delay_s

        rows.append((
            now, day_of_week, hour,
            origin["name"], origin["lat"], origin["lng"],
            dest["name"], dest["lat"], dest["lng"],
            distance_m, base_duration_s, travel_time_s,
        ))
    return rows


def collect():
    if not API_KEY:
        print("ERROR: TOMTOM_API_KEY not set in .env")
        sys.exit(1)
    if not DATABASE_URL:
        print("ERROR: COLLECTOR_DATABASE_URL not set in .env")
        sys.exit(1)

    conn = get_db()
    ensure_table(conn)

    locations = KERALA_LOCATIONS
    total_rows = 0
    errors = 0

    for batch_start in range(0, len(locations), BATCH_SIZE):
        origins = locations[batch_start:batch_start + BATCH_SIZE]

        try:
            data = query_batch(origins, locations)
        except httpx.HTTPStatusError as e:
            print(f"ERROR batch {batch_start}: {e.response.status_code} {e.response.text[:300]}")
            errors += 1
            continue
        except Exception as e:
            print(f"ERROR batch {batch_start}: {e}")
            errors += 1
            continue

        if "detailedError" in data:
            print(f"API error: {data['detailedError']}")
            errors += 1
            continue

        rows = parse_response(data, origins, locations)

        try:
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, rows)
            conn.commit()
            total_rows += len(rows)
        except Exception as e:
            conn.rollback()
            print(f"ERROR writing to DB: {e}")
            errors += 1

        time.sleep(1)

    conn.close()
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Collected {total_rows} rows, {errors} batch errors")


if __name__ == "__main__":
    collect()
