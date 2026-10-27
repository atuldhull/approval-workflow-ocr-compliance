# Working-day calendars (Person 2)

Calendars are finalized, versioned records in the `dl.calendar_version` and
`dl.holiday` tables. `calendar_id` identifies one exact version (for example,
`RO-SOUTH@2026-27-r1`). A verified version must retain a source reference. When
a rule uses `working_days`, it must name that version and state whether the
anchor date counts with `count_anchor_day`.

Create each version and its complete holiday list in one transaction through
`register_calendar_version`. Migration `dl_0003` installs PostgreSQL triggers
intended to reject edits after finalization; integration tests in
`backend/tests/test_deadline_calendar_postgres.py` cover those guards. Run those
tests against PostgreSQL before treating the enforcement as verified. To change
weekdays or holidays, register a new `calendar_id`; existing deadlines continue
to use the version they pinned. Existing calendar-management APIs do not exist
yet.

`working_weekdays` uses Python's weekday numbering: Monday is `0`, Sunday is
`6`. Calendar records must be loaded only from an approved schedule and retain
its source reference. No national, regional, or weekly holiday defaults are
bundled here because the work plan does not identify an authoritative calendar.

Until an approved calendar is loaded, a `working_days` rule fails closed. The
current APH rules continue using their existing units and are not changed by
this capability.
