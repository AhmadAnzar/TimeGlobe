-- An issue whose downloaded body disagrees with MD5SUMS is downloaded once more to see whether the
-- file changed or only the index disagrees (issue_integrity.py). When the body is unchanged,
-- mismatch_confirmed_for records the listed checksum that was examined, so the issue is not
-- downloaded again for as long as the index keeps listing that same value. A new body, or a
-- different listed checksum, brings the re-download back.
alter table circular_t_issues add column mismatch_confirmed_for char(32);
