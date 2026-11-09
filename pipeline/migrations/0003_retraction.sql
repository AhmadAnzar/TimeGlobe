-- A revised Circular T issue (or a corrected API series) can stop containing a value it once had.
-- Such a row is never deleted: retracted_at records when it stopped being published. Reads
-- (snapshots, the API) take only rows where retracted_at is null. If the date comes back in a
-- later revision the same row is updated in place and retracted_at is cleared again.
alter table offsets add column retracted_at timestamptz;

create index offsets_retracted_idx on offsets (lab, scale) where retracted_at is not null;
