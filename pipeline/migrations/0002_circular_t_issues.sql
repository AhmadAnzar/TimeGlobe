-- Stored Circular T issues, so the daily job can verify them against MD5SUMS and diff a revision.
-- md5 is the checksum of body as downloaded; listed_md5 is what MD5SUMS listed when last checked.
-- An issue whose md5 differs from listed_md5 is re-downloaded; if the file is unchanged the index
-- is what disagrees (see issue_integrity.py). verified = (md5 = listed_md5).
create table circular_t_issues (
    issue       integer primary key,
    md5         char(32) not null,
    listed_md5  char(32),
    body        text not null,
    fetched_at  timestamptz not null default now(),
    checked_at  timestamptz not null default now()
);

-- Offsets taken from a Circular T issue point at the stored issue.
alter table offsets
    add constraint offsets_circular_t_no_fkey
    foreign key (circular_t_no) references circular_t_issues (issue);
