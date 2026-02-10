-- ============================================
-- Schwab MCP - Option Chain Storage
-- PostgreSQL Schema for schwab_data database
-- ============================================
--
-- Usage:
--   1. Create the database on your Cloud SQL instance:
--      CREATE DATABASE schwab_data;
--   2. Connect to it and run this file:
--      psql -d schwab_data -f sql/001_create_schwab_data.sql
--
-- The schema is also auto-applied when the server starts with
-- database configuration (--db-instance, etc.).

CREATE TABLE IF NOT EXISTS option_chain_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    fetch_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    strategy        TEXT,
    is_delayed      BOOLEAN,
    is_index        BOOLEAN,
    interest_rate   DOUBLE PRECISION,
    underlying_price DOUBLE PRECISION,
    volatility      DOUBLE PRECISION,
    days_to_expiration DOUBLE PRECISION,
    dividend_yield  DOUBLE PRECISION,
    number_of_contracts INTEGER,
    status          TEXT,
    request_params  JSONB
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_ts
    ON option_chain_snapshots (symbol, fetch_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_fetch_ts
    ON option_chain_snapshots (fetch_timestamp DESC);

CREATE TABLE IF NOT EXISTS option_contracts (
    id                  BIGSERIAL PRIMARY KEY,
    snapshot_id         BIGINT NOT NULL REFERENCES option_chain_snapshots(id) ON DELETE CASCADE,
    put_call            TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    description         TEXT,
    exchange_name       TEXT,
    underlying_symbol   TEXT NOT NULL,
    expiration_date     DATE NOT NULL,
    days_to_expiration  INTEGER,
    strike_price        DOUBLE PRECISION NOT NULL,
    bid                 DOUBLE PRECISION,
    ask                 DOUBLE PRECISION,
    last                DOUBLE PRECISION,
    mark                DOUBLE PRECISION,
    bid_size            INTEGER,
    ask_size            INTEGER,
    last_size           INTEGER,
    high_price          DOUBLE PRECISION,
    low_price           DOUBLE PRECISION,
    open_price          DOUBLE PRECISION,
    close_price         DOUBLE PRECISION,
    net_change          DOUBLE PRECISION,
    total_volume        INTEGER,
    volatility          DOUBLE PRECISION,
    delta               DOUBLE PRECISION,
    gamma               DOUBLE PRECISION,
    theta               DOUBLE PRECISION,
    vega                DOUBLE PRECISION,
    rho                 DOUBLE PRECISION,
    open_interest       INTEGER,
    time_value          DOUBLE PRECISION,
    theoretical_option_value DOUBLE PRECISION,
    theoretical_volatility   DOUBLE PRECISION,
    quote_time          TIMESTAMPTZ,
    trade_time          TIMESTAMPTZ,
    in_the_money        BOOLEAN,
    mini                BOOLEAN,
    non_standard        BOOLEAN,
    penny_pilot         BOOLEAN,
    intrinsic_value     DOUBLE PRECISION,
    expiration_type     TEXT,
    multiplier          DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_contracts_snapshot
    ON option_contracts (snapshot_id);
CREATE INDEX IF NOT EXISTS idx_contracts_underlying_exp
    ON option_contracts (underlying_symbol, expiration_date, strike_price);
CREATE INDEX IF NOT EXISTS idx_contracts_symbol
    ON option_contracts (symbol);
CREATE INDEX IF NOT EXISTS idx_contracts_put_call
    ON option_contracts (put_call);
