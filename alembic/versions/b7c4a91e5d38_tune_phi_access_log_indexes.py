"""tune phi_access_logs indexes from measured query plans

Revision ID: b7c4a91e5d38
Revises: d2e5f80a63b1

Every read of this table goes through GET /admin/phi-access, which is
clinic-scoped: clinic_id is ALWAYS filtered, created_at is ALWAYS the sort key,
and one of patient_id / actor_user_id / resource_type is optionally added.

Measured on a 500k-row clone (40 clinics, ~12.8k rows per clinic), before and
after, with EXPLAIN (ANALYZE, BUFFERS):

    shape                            before              after
    clinic + actor_user_id           1.63 ms /  146 buf  0.13 ms /  95 buf
    clinic + resource_type           1.61 ms /  661 buf  0.12 ms / 104 buf
    clinic + patient_id              0.10 ms /   17 buf  0.06 ms /  18 buf
    count(*) clinic + resource_type  9.69 ms / 6495 buf  0.23 ms /  15 buf
    count(*) clinic + patient_id     0.05 ms /   17 buf  0.02 ms /   4 buf

Without a clinic-leading composite the planner either walks the clinic's whole
created_at range discarding non-matching rows, or builds a BitmapAnd whose
clinic-side bitmap alone reads every row in the clinic. Both scale with clinic
size, so they degrade exactly as a tenant grows. With these indexes every
count(*) becomes an Index Only Scan (Heap Fetches: 0).

Two existing indexes are dropped in exchange, because this table takes a write
on every patient-record view and index maintenance is the cost that matters:

  * ix_phi_access_logs_actor_user_id -- (actor_user_id) is an exact prefix of
    ix_phi_access_actor_time (actor_user_id, created_at). It can never be
    preferred for anything the composite does not already serve.
  * ix_phi_access_logs_request_id -- at 28 MB the largest index on the table,
    on random UUIDs (worst-case B-tree insert behaviour), and nothing queries
    by request_id. Correlation runs the other way: you read a row here and go
    look the id up in the structured logs.

Net measured effect on the write path, shipped set vs this one, 100k inserts:
1757 ms -> 1867 ms (+1.1 us per row) and 148 MB -> 155 MB of index. That buys
the read gains above, on a table whose reads are compliance investigations
where a 9.7 ms count over one clinic would become seconds at real volume.

Indexes intentionally KEPT although no current query uses them:
ix_phi_access_patient_time and ix_phi_access_actor_time serve the cross-clinic
compliance questions the table exists for (a patient's right-of-access request
spanning clinics; platform-plane review by super_admin, whose clinic_id is
NULL), and ix_phi_access_logs_created_at serves a future retention purge.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7c4a91e5d38"
down_revision: Union[str, Sequence[str], None] = "d2e5f80a63b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, columns) for the clinic-leading composites the query plans justified.
NEW_INDEXES = [
    ("ix_phi_access_clinic_patient_time", ["clinic_id", "patient_id", "created_at"]),
    ("ix_phi_access_clinic_actor_time", ["clinic_id", "actor_user_id", "created_at"]),
    ("ix_phi_access_clinic_resource_time", ["clinic_id", "resource_type", "created_at"]),
]

REDUNDANT_INDEXES = [
    # (name, columns) -- columns recorded so downgrade can restore them.
    ("ix_phi_access_logs_actor_user_id", ["actor_user_id"]),
    ("ix_phi_access_logs_request_id", ["request_id"]),
]


def upgrade() -> None:
    for name, cols in NEW_INDEXES:
        op.create_index(name, "phi_access_logs", cols)

    for name, _cols in REDUNDANT_INDEXES:
        op.drop_index(name, table_name="phi_access_logs")


def downgrade() -> None:
    for name, cols in REDUNDANT_INDEXES:
        op.create_index(name, "phi_access_logs", cols)

    for name, _cols in NEW_INDEXES:
        op.drop_index(name, table_name="phi_access_logs")
