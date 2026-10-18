-- Tiger Data (TimescaleDB 2.30) copy of the event log. Applied by app/eventdb.py on every connect,
-- one statement at a time (continuous aggregates can't be created inside a transaction), so every
-- statement must be idempotent. Statements are separated by a semicolon at the end of a line.

CREATE TABLE IF NOT EXISTS fs_events (
    time      timestamptz NOT NULL,
    boot      text        NOT NULL,  -- one id per backend process: seq restarts at 1 on every boot
    seq       integer     NOT NULL,
    type      text        NOT NULL,
    task      text,
    table_id  text,
    staff     text,                  -- data.staff, else data.assignee
    payload   jsonb       NOT NULL
);

SELECT create_hypertable('fs_events', by_range('time', INTERVAL '1 day'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS fs_events_type_time ON fs_events (type, time DESC);

CREATE INDEX IF NOT EXISTS fs_events_task_time ON fs_events (task, time DESC) WHERE task IS NOT NULL;

-- Accept latency: the card went down the socket (task.sent) to the server's tap (task.accepted).
-- tasks.py puts acceptSec on task.accepted, so this needs no join. Real-time (materialized_only
-- false): GET /stats sees the last minute too, before the refresh policy has run.
CREATE MATERIALIZED VIEW IF NOT EXISTS fs_accept_latency
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '5 minutes', time) AS bucket,
       staff,
       payload->>'kind' AS kind,
       count(*) AS n,
       sum((payload->>'acceptSec')::double precision) AS total_sec,
       max((payload->>'acceptSec')::double precision) AS max_sec,
       percentile_agg((payload->>'acceptSec')::double precision) AS pct
FROM fs_events
WHERE type = 'task.accepted' AND payload ? 'acceptSec'
GROUP BY bucket, staff, kind
WITH NO DATA;

-- Ticket time: accepted to done (from assignment when done straight from sent), as in GET /stats.
CREATE MATERIALIZED VIEW IF NOT EXISTS fs_ticket_time
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '5 minutes', time) AS bucket,
       staff,
       payload->>'kind' AS kind,
       count(*) AS n,
       sum((payload->>'ticketSec')::double precision) AS total_sec,
       max((payload->>'ticketSec')::double precision) AS max_sec,
       percentile_agg((payload->>'ticketSec')::double precision) AS pct
FROM fs_events
WHERE type = 'task.done' AND payload ? 'ticketSec'
GROUP BY bucket, staff, kind
WITH NO DATA;

SELECT add_continuous_aggregate_policy('fs_accept_latency',
    start_offset => INTERVAL '2 days', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('fs_ticket_time',
    start_offset => INTERVAL '2 days', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);
