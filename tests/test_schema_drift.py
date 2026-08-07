"""Indexes the database relies on must be declared on the models.

An index created by raw SQL in a migration and never mirrored on its model is
invisible to `alembic revision --autogenerate`. Autogenerate compares models to
schema, sees an index no model asked for, and writes a DROP for it. Apply that
migration without reading it and the index is gone: no error, no failing test,
just a guarantee that quietly stopped holding.

That had already happened twice here. The worst case was

    CREATE UNIQUE INDEX one_latest_prescription_per_appointment
      ON prescriptions (appointment_id) WHERE (is_latest_revision = true)

which is the only thing making "an appointment has one current prescription"
true. Without it, two revisions can both claim to be the latest, and the code
that reads "the latest" picks one arbitrarily — a doctor is shown the wrong
medication, and nothing anywhere reports a problem.

These tests assert the model metadata, not the live database, so they run
anywhere and fail at the moment someone adds a raw-SQL index without declaring
it — which is the moment worth catching, rather than after a deploy.
"""

import pytest
from sqlalchemy import text

from app.db.base import Base
from app.models.medicine import Medicine  # noqa: F401  (registers the mapper)
from app.models.medicine_alias import MedicineAlias  # noqa: F401
from app.models.outbox_event import OutboxEvent  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.prescription import Prescription  # noqa: F401


def _indexes(table_name: str) -> dict:
    table = Base.metadata.tables[table_name]
    return {index.name: index for index in table.indexes}


# ---------------------------------------------------------------------------
# The invariants
# ---------------------------------------------------------------------------


def test_one_latest_prescription_per_appointment_is_declared():
    """The index that makes prescription revisions coherent."""
    index = _indexes("prescriptions").get("one_latest_prescription_per_appointment")

    assert index is not None, (
        "the partial unique index is missing from the model, so autogenerate "
        "will emit a DROP for it"
    )
    assert index.unique, "without unique, it enforces nothing"
    assert [c.name for c in index.columns] == ["appointment_id"]

    where = index.dialect_options["postgresql"].get("where")

    assert where is not None, (
        "without the partial WHERE this would allow only one prescription per "
        "appointment ever, superseded revisions included"
    )
    assert "is_latest_revision" in str(where)


def test_one_pending_payment_per_appointment_is_declared():
    """The money equivalent: no two pending payments for one appointment."""
    index = _indexes("payments").get("idx_unique_pending_payment")

    assert index is not None
    assert index.unique
    assert "status" in str(index.dialect_options["postgresql"].get("where"))


@pytest.mark.parametrize(
    "table, index_name",
    [
        ("outbox_events", "idx_outbox_ready_v2"),
        ("outbox_events", "ix_outbox_pending_retry"),
        ("medicine_aliases", "ix_medicine_aliases_alias"),
        ("medicine_aliases", "ix_medicine_aliases_medicine_id"),
        ("medicines", "ix_medicines_generic_name"),
        ("medicines", "ix_medicines_manufacturer"),
        ("medicines", "ix_medicines_strength"),
    ],
)
def test_performance_indexes_are_declared(table, index_name):
    """Losing these breaks nothing and slows everything.

    No test would fail, no error would be raised; the outbox poll and the
    medicine matcher would just degrade as the tables grow.
    """
    assert index_name in _indexes(table), (
        f"{index_name} exists in the database but not on the model, so "
        f"autogenerate will drop it"
    )


# ---------------------------------------------------------------------------
# Columns the database enforces and the model must not loosen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table, column",
    [
        ("medicines", "name"),
        ("medicines", "is_brand"),
    ],
)
def test_not_null_columns_are_declared_not_null(table, column):
    """Written as a bare mapped_column with no Mapped[...] annotation,
    SQLAlchemy infers nullable=True. The model then reads as looser than the
    schema and autogenerate emits DROP NOT NULL."""
    assert not Base.metadata.tables[table].columns[column].nullable, (
        f"{table}.{column} is NOT NULL in the database; leaving the model "
        f"nullable makes autogenerate weaken it"
    )


# ---------------------------------------------------------------------------
# Every model reaches the metadata alembic autogenerates against
# ---------------------------------------------------------------------------


def test_every_model_module_is_imported_in_the_package_init():
    """The defect underneath the index drift, and a much worse one.

    alembic/env.py does `from app.models import *` and hands Base.metadata to
    autogenerate. A model missing from app/models/__init__.py has no table in
    that metadata, and autogenerate does not treat that as "unknown" — it
    treats it as a table nobody wants and emits op.drop_table().

    Seven were missing. A generated migration proposed dropping audit_logs,
    activity_logs, prescription_templates, prescription_template_items,
    medicine_assistant_queries, medicine_ai_logs, medicine_ai_feedback and
    medicine_ai_error_logs. The compliance trail included, with no warning:
    the migration reads as ordinary generated output.

    Checked by import rather than by listing names, so a model added tomorrow
    is covered without anyone remembering to extend this test.
    """
    import ast
    from pathlib import Path

    models_dir = Path(__file__).parent.parent / "app" / "models"
    init_source = (models_dir / "__init__.py").read_text()

    imported = {
        node.module.lstrip(".")
        for node in ast.walk(ast.parse(init_source))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    missing = []

    for path in sorted(models_dir.glob("*.py")):
        if path.stem in {"__init__", "base"}:
            continue

        tree = ast.parse(path.read_text())

        # Only modules that actually declare a mapped class matter; several
        # files here are empty or fully commented out.
        declares_a_table = any(
            isinstance(node, ast.ClassDef) for node in tree.body
        )

        if declares_a_table and path.stem not in imported:
            missing.append(path.stem)

    assert not missing, (
        f"model module(s) not imported in app/models/__init__.py: {missing}. "
        f"Their tables are absent from Base.metadata, so `alembic revision "
        f"--autogenerate` will emit op.drop_table() for each of them."
    )


@pytest.mark.parametrize(
    "table",
    [
        "audit_logs",
        "activity_logs",
        "prescription_templates",
        "prescription_template_items",
        "medicine_assistant_queries",
        "medicine_ai_logs",
        "medicine_ai_feedback",
        "medicine_ai_error_logs",
    ],
)
def test_the_previously_orphaned_tables_are_in_the_metadata(table):
    """Named explicitly because these are the ones autogenerate offered to
    drop. Losing audit_logs is not a bug that can be fixed afterwards."""
    assert table in Base.metadata.tables


# ---------------------------------------------------------------------------
# Against the live database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_declared_indexes_actually_exist(db):
    """The other direction: declaring an index the database lacks is also
    drift, it just fails safe instead of dangerously."""
    expected = [
        ("prescriptions", "one_latest_prescription_per_appointment"),
        ("payments", "idx_unique_pending_payment"),
        ("outbox_events", "idx_outbox_ready_v2"),
        ("medicine_aliases", "ix_medicine_aliases_alias"),
        ("medicines", "ix_medicines_generic_name"),
    ]

    missing = []

    for table, name in expected:
        found = await db.scalar(
            text("select 1 from pg_indexes where tablename=:t and indexname=:n"),
            {"t": table, "n": name},
        )
        if not found:
            missing.append(f"{table}.{name}")

    assert not missing, f"declared on the model but absent from the schema: {missing}"


@pytest.mark.asyncio
async def test_the_prescription_invariant_actually_holds(db):
    """Not the declaration — the behaviour it buys.

    Asserted against the running database because a partial unique index that
    exists but does not bite would satisfy every test above.
    """
    duplicates = await db.scalar(
        text(
            "select count(*) from ("
            "  select appointment_id from prescriptions"
            "  where is_latest_revision = true"
            "  group by appointment_id having count(*) > 1"
            ") x"
        )
    )

    assert duplicates == 0, (
        f"{duplicates} appointment(s) have more than one prescription marked "
        f"as the latest revision"
    )
