# Kerala Traffic Data Collection

Collects travel time data (with live traffic) from the TomTom Matrix Routing v2 API
for 20 Kerala locations. Runs as a cron job every hour, storing results in PostgreSQL.

## Setup

1. Get a free TomTom API key at [developer.tomtom.com](https://developer.tomtom.com) (2,500 requests/day).

2. Copy `.env.example` to `.env` and fill in your values:
   ```
   TOMTOM_API_KEY=your-tomtom-api-key
   COLLECTOR_DATABASE_URL=postgresql://user:password@localhost:5432/smartmap
   ```

3. Make sure PostgreSQL is running and the database exists:
   ```bash
   createdb smartmap  # if not already created
   ```

### Docker (recommended for VPS)

4. Build the image:
   ```bash
   docker compose build
   ```

5. Test it manually:
   ```bash
   docker compose run --rm collector
   ```
   You should see: `Collected 380 rows, 0 batch errors`

6. Set up the cron job (runs every hour):
   ```bash
   crontab -e
   ```
   Add this line (adjust path):
   ```
   0 * * * * cd /path/to/kerala_traffic_dataset && docker compose run --rm collector >> cron.log 2>&1
   ```

### Without Docker

4. Create a venv and install deps:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. Test it manually:
   ```bash
   python collect.py
   ```
   You should see: `Collected 380 rows, 0 batch errors`

6. Set up the cron job (runs every hour):
   ```bash
   crontab -e
   ```
   Add this line (adjust paths):
   ```
   0 * * * * cd /path/to/kerala_traffic_dataset && .venv/bin/python collect.py >> cron.log 2>&1
   ```

### Verify

7. Check that cron is running:
   ```bash
   tail -f cron.log
   ```

## Database table

The script auto-creates a `traffic_data` table:

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Auto-increment primary key |
| timestamp | TIMESTAMPTZ | UTC timestamp of the query |
| day_of_week | VARCHAR | Monday, Tuesday, etc. |
| hour | INTEGER | Hour (0-23) UTC |
| origin_name | VARCHAR | Origin location name |
| origin_lat/lng | DOUBLE PRECISION | Origin coordinates |
| dest_name | VARCHAR | Destination location name |
| dest_lat/lng | DOUBLE PRECISION | Destination coordinates |
| distance_m | INTEGER | Distance in meters |
| duration_s | INTEGER | Base travel time without traffic (seconds) |
| duration_in_traffic_s | INTEGER | Travel time with live traffic (seconds) |

## Expected data volume

- 20 locations = 380 route pairs per query
- 1 query per hour x 24 hours = 9,120 rows/day
- Uses only 24 of the 2,500 daily free API requests

## Useful queries

```sql
-- Check total rows collected
SELECT COUNT(*) FROM traffic_data;

-- See traffic patterns for a route
SELECT hour,
       AVG(duration_in_traffic_s) as avg_traffic_time,
       AVG(duration_s) as avg_base_time
FROM traffic_data
WHERE origin_name = 'Kochi_Ernakulam' AND dest_name = 'Thrissur'
GROUP BY hour ORDER BY hour;

-- Find most congested routes right now
SELECT origin_name, dest_name,
       duration_in_traffic_s - duration_s AS delay_s
FROM traffic_data
WHERE timestamp = (SELECT MAX(timestamp) FROM traffic_data)
ORDER BY delay_s DESC
LIMIT 10;

-- Export to CSV
COPY traffic_data TO '/tmp/traffic_data.csv' WITH CSV HEADER;
```
