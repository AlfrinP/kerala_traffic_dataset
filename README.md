# Traffic Data Collection

Collects travel time data from Google Maps Distance Matrix API for 20 Kerala locations.
Runs as a cron job every hour, storing traffic-adjusted travel times in PostgreSQL.

## Setup on VPS

1. Copy the `data_collection/` folder and `.env` to your VPS.

2. Create a venv and install deps:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r data_collection/requirements.txt
   ```

3. Set up your `.env` in the project root:
   ```
   GOOGLE_MAPS_API_KEY=your-actual-key
   COLLECTOR_DATABASE_URL=postgresql://user:password@localhost:5432/smartmap
   ```

4. Make sure PostgreSQL is running and the database exists:
   ```bash
   createdb smartmap  # if not already created
   ```

5. Test it manually:
   ```bash
   python -m data_collection.collect
   ```
   You should see: `Collected 380 rows, 0 batch errors`

6. Set up the cron job (runs every hour):
   ```bash
   crontab -e
   ```
   Add this line (adjust paths to match your VPS):
   ```
   0 * * * * cd /path/to/smartmap && /path/to/smartmap/.venv/bin/python -m data_collection.collect >> /path/to/smartmap/data_collection/cron.log 2>&1
   ```

7. Verify cron is running:
   ```bash
   tail -f /path/to/smartmap/data_collection/cron.log
   ```

## Database table

The script auto-creates a `traffic_data` table with these columns:

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
| duration_s | INTEGER | Travel time without traffic (seconds) |
| duration_in_traffic_s | INTEGER | Travel time with traffic (seconds) |

## Expected data volume

- 20 locations = 380 route pairs per query
- 1 query per hour x 96 hours (4 days) = ~36,480 rows

## Useful queries

```sql
-- Check total rows collected
SELECT COUNT(*) FROM traffic_data;

-- See traffic patterns for a route
SELECT hour, AVG(duration_in_traffic_s) as avg_traffic_time, AVG(duration_s) as avg_base_time
FROM traffic_data
WHERE origin_name = 'Kochi_Ernakulam' AND dest_name = 'Thrissur'
GROUP BY hour ORDER BY hour;

-- Export to CSV if needed
COPY traffic_data TO '/tmp/traffic_data.csv' WITH CSV HEADER;
```
