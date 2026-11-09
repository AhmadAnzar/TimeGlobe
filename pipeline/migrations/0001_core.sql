-- Core tables for the drift data. The pipeline is the only writer; everything else reads.
-- Later tables (links, stations, ntp_zones) arrive with the phases that need them.

create table labs (
    code          text primary key,
    name          text not null,
    city          text not null,
    country_bipm  text not null,            -- BIPM's text, verbatim
    iso2          char(2) not null,
    lat           double precision not null check (lat between -90 and 90),
    lon           double precision not null check (lon between -180 and 180),
    year_start    integer,
    year_stop     integer,
    status        text not null check (status in ('current', 'former', 'not_in_issue')),
    check (year_stop is null or year_start is null or year_stop >= year_start)
);

-- UTC-UTC(k) (scale 'utc', every 5 days) and rapid UTCr-UTC(k) (scale 'utcr', daily).
-- A missing date is an absent row, never a zero. circular_t_no is set when a value was taken
-- from a Circular T issue instead of the API.
create table offsets (
    lab             text not null references labs (code),
    scale           text not null check (scale in ('utc', 'utcr')),
    mjd             integer not null,
    value_ns        double precision not null,
    uncertainty_ns  double precision check (uncertainty_ns is null or uncertainty_ns >= 0),
    circular_t_no   integer,
    primary key (lab, scale, mjd)
);

-- Clocks not marked stopped on the Time Database clock list, per lab, as of the first day of a month.
create table clock_counts (
    lab    text not null references labs (code),
    month  date not null check (extract(day from month) = 1),
    n      integer not null check (n >= 0),
    primary key (lab, month)
);

-- UTC minus a GNSS time scale, daily.
create table gnss_offsets (
    system          text not null check (system in ('gps', 'glonass', 'galileo', 'beidou')),
    mjd             integer not null,
    value_ns        double precision not null,
    uncertainty_ns  double precision check (uncertainty_ns is null or uncertainty_ns >= 0),
    primary key (system, mjd)
);

-- One row per pipeline run. rows_changed counts existing rows whose value was overwritten
-- (BIPM corrections); details holds the data flags (rebuilt or excluded series).
create table ingest_runs (
    id             bigint generated always as identity primary key,
    source         text not null,
    started_at     timestamptz not null default now(),
    finished_at    timestamptz,
    rows_added     integer not null default 0,
    rows_changed   integer not null default 0,
    status         text not null check (status in ('running', 'ok', 'failed')),
    error          text,
    circular_t_no  integer,
    details        jsonb not null default '{}'::jsonb
);

create index offsets_scale_mjd_idx on offsets (scale, mjd);
