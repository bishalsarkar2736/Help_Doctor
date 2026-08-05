"""add generics and link medicines to them

Revision ID: f1d3b8a52c94
Revises: e4a1c62b8f37

Brands are what a prescriber types; generics are what a patient reacts to. The
catalogue holds 11 brands of Cefixime and 7 of Metformin, so allergy checking
against brand-name strings alone misses the case that matters: a patient
recorded as allergic to "Cefixime" prescribed "Cefim".

Unlike the consent migration, this one DOES backfill. It is deriving a relation
from data already present in the same table rather than inventing a fact, so
running it is not a claim about anything that did not happen.

Normalisation here is deliberately duplicated from
medicine_matcher_service.normalize() rather than imported. A migration must
keep producing the same result years from now; importing application code that
will keep changing is how a migration silently starts doing something else.
"""

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1d3b8a52c94"
down_revision: Union[str, Sequence[str], None] = "e4a1c62b8f37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_NON_ALNUM.sub(" ", (text or "").lower()).split())


def upgrade() -> None:
    op.create_table(
        "generics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_generics_name", "generics", ["name"])
    op.create_index("ix_generics_normalized_name", "generics", ["normalized_name"])

    op.add_column(
        "medicines", sa.Column("generic_id", sa.Integer(), nullable=True)
    )
    op.create_index("ix_medicines_generic_id", "medicines", ["generic_id"])
    op.create_foreign_key(
        "fk_medicines_generic_id",
        "medicines",
        "generics",
        ["generic_id"],
        ["id"],
        # RESTRICT: deleting a generic that brands still point at would
        # silently disable allergy matching for that whole family.
        ondelete="RESTRICT",
    )

    # --- backfill -----------------------------------------------------------
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT generic_name FROM medicines "
            "WHERE generic_name IS NOT NULL AND generic_name <> ''"
        )
    ).fetchall()

    # Group by NORMALISED name so "Amoxicillin + Clavulanic Acid" and
    # "amoxicillin clavulanic acid" become one generic rather than two, which
    # would split a brand family and defeat the point of the table.
    by_normalized: dict[str, str] = {}
    for (generic_name,) in rows:
        key = _normalize(generic_name)
        if key and key not in by_normalized:
            by_normalized[key] = generic_name.strip()

    for normalized, display in by_normalized.items():
        conn.execute(
            sa.text(
                "INSERT INTO generics (name, normalized_name) "
                "VALUES (:name, :normalized) ON CONFLICT (name) DO NOTHING"
            ),
            {"name": display, "normalized": normalized},
        )

    # Link every medicine to its generic by the normalised form, so rows whose
    # spacing or punctuation differs still land on the right family.
    #
    # btrim runs AFTER the substitution, not before: "Cholecalciferol (Vitamin
    # D3)" ends in a bracket, which becomes a trailing space that the Python
    # normaliser above strips. Trimming first leaves the two disagreeing and the
    # join silently misses those rows.
    conn.execute(
        sa.text(
            """
            UPDATE medicines m
            SET generic_id = g.id
            FROM generics g
            WHERE g.normalized_name = btrim(
                    regexp_replace(lower(m.generic_name), '[^a-z0-9]+', ' ', 'g'),
                    ' '
                  )
              AND m.generic_id IS NULL
            """
        )
    )

    # A brand left unlinked is invisible to substance-level allergy checking —
    # exactly the failure this migration exists to remove. Fail loudly and roll
    # back rather than deploy a catalogue that is quietly half-covered.
    orphans = conn.execute(
        sa.text(
            "SELECT name FROM medicines "
            "WHERE generic_id IS NULL "
            "  AND generic_name IS NOT NULL AND generic_name <> '' "
            "LIMIT 10"
        )
    ).fetchall()

    if orphans:
        names = ", ".join(name for (name,) in orphans)
        raise RuntimeError(
            f"generic backfill left medicines unlinked: {names}. "
            "Their generic_name did not normalise to any generics row."
        )


def downgrade() -> None:
    op.drop_constraint("fk_medicines_generic_id", "medicines", type_="foreignkey")
    op.drop_index("ix_medicines_generic_id", table_name="medicines")
    op.drop_column("medicines", "generic_id")

    op.drop_index("ix_generics_normalized_name", table_name="generics")
    op.drop_index("ix_generics_name", table_name="generics")
    op.drop_table("generics")
