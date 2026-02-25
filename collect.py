"""
Google Maps Distance Matrix data collector for Kerala traffic patterns.

Queries all pairs of Kerala locations and records travel times with traffic
into a PostgreSQL database. Designed to run as a cron job every hour.

Usage:
    python -m data_collection.collect

Requires in .env:
    GOOGLE_MAPS_API_KEY
    COLLECTOR_DATABASE_URL  (e.g. postgresql://user:pass@localhost:5432/smartmap)
"""

import os
import sys
import time
from datetime import datetime, timezone

import httpx
import psycopg2
from dotenv import load_dotenv

from data_collection.locations import KERALA_LOCATIONS

load_dotenv()

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
DATABASE_URL = os.getenv("COLLECTOR_DATABASE_URL", "")
BASE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
BATCH_SIZE = 10


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
    origin_str = "|".join(f"{loc['lat']},{loc['lng']}" for loc in origins)
    dest_str = "|".join(f"{loc['lat']},{loc['lng']}" for loc in destinations)

    params = {
        "origins": origin_str,
        "destinations": dest_str,
        "key": API_KEY,
        "departure_time": "now",
        "traffic_model": "best_guess",
    }

    with httpx.Client(timeout=30) as client:
        resp = client.get(BASE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def collect():
    if not API_KEY:
        print("ERROR: GOOGLE_MAPS_API_KEY not set in .env")
        sys.exit(1)
    if not DATABASE_URL:
        print("ERROR: COLLECTOR_DATABASE_URL not set in .env")
        sys.exit(1)

    conn = get_db()
    ensure_table(conn)

    now = datetime.now(timezone.utc)
    timestamp = now
    day_of_week = now.strftime("%A")
    hour = now.hour

    locations = KERALA_LOCATIONS
    total_rows = 0
    errors = 0

    for batch_start in range(0, len(locations), BATCH_SIZE):
        origins = locations[batch_start:batch_start + BATCH_SIZE]

        try:
            data = query_batch(origins, locations)
        except Exception as e:
            print(f"ERROR querying batch starting at {batch_start}: {e}")
            errors += 1
            continue

        if data.get("status") != "OK":
            print(f"API error: {data.get('status')} — {data.get('error_message', '')}")
            errors += 1
            continue

        rows = []
        for i, row in enumerate(data["rows"]):
            origin = origins[i]
            for j, element in enumerate(row["elements"]):
                dest = locations[j]

                if origin["name"] == dest["name"]:
                    continue
                if element.get("status") != "OK":
                    continue

                distance_m = element["distance"]["value"]
                duration_s = element["duration"]["value"]
                duration_traffic_s = element.get("duration_in_traffic", {}).get(
                    "value", duration_s
                )

                rows.append((
                    timestamp, day_of_week, hour,
                    origin["name"], origin["lat"], origin["lng"],
                    dest["name"], dest["lat"], dest["lng"],
                    distance_m, duration_s, duration_traffic_s,
                ))

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
    print(f"[{now.isoformat()}] Collected {total_rows} rows, {errors} batch errors")


if __name__ == "__main__":
    collect()
