"""Structural guard: an ADMIN code path must know which clinic it is in.

WHY THIS EXISTS
A tenant-isolation audit found four cross-tenant defects, and all four were the
same shape — the DOCTOR path checked the clinic and the ADMIN path did not:

    prescription_service.get_prescription_by_id      elif ADMIN: pass
    prescription_service.get_appointment_prescription elif ADMIN: query without
                                                      the clinic predicate
    payment_refund_service.validate_refund_access    if ADMIN: return
    realtime_service.notify_admins                   select every ADMIN row

ADMIN is a clinic-bound role in this system: resolve_clinic_id raises "Admin not
assigned to clinic" without one, and the platform plane is SUPER_ADMIN. So an
admin branch that never mentions a clinic is, by construction, a branch that
treats one tenant's rows as another's.

The behavioural tests for each defect live next to the code they cover
(test_tenant_isolation.py, test_refund_service.py, test_admin_users_scoping.py).
This file catches the CLASS. It is deliberately structural because the bug is
structural: two of the four had no observable difference at the type level, and
one of them — the query-shaped variant — was missed by a first scan that looked
only for `pass` and bare `return`. Checking the branch's test AND its body for
any mention of a clinic catches all of these shapes at once.

WHAT WOULD MAKE THIS GUARD USELESS
A scanner that matches nothing passes forever. The last two tests here assert
that the scanners still find the code they are meant to police, so a moved
directory or a renamed enum turns into a failure rather than a silent pass.
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Where authorization decisions are made. Deliberately not `app/` entire:
#: models and schemas mention roles without deciding anything with them.
SCANNED_ROOTS = (
    "app/services",
    "app/api",
    "app/domain",
    "app/workers",
    "app/task",
)


def _python_files():
    for root in SCANNED_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def _is_exclusion_gate(test_node) -> bool:
    """Whether the branch rejects non-admins rather than admitting admins.

    `if user.role != UserRole.ADMIN: raise` and `if role not in (...): raise`
    are role gates. They grant nothing, and demanding a clinic inside them
    would be wrong: admin_doctor_service._admin_only is exactly this shape, a
    two-line role assertion whose callers each do their own clinic filtering.

    The defects this file exists for were all the positive form — the branch
    that decides an ADMIN may proceed — so that is what gets policed.
    """

    for node in ast.walk(test_node):
        if not isinstance(node, ast.Compare):
            continue

        if "UserRole.ADMIN" not in ast.unparse(node):
            continue

        for op in node.ops:
            if isinstance(op, (ast.NotEq, ast.NotIn)):
                return True

    return False


def _admin_role_branches():
    """Every if/elif that admits a principal because they are an ADMIN.

    `UserRole.SUPER_ADMIN` does not contain `UserRole.ADMIN` as a substring, so
    a branch testing only for the platform role is not matched here — that role
    is not clinic-bound and has nothing to compare against.
    """

    for path in _python_files():
        tree = ast.parse(path.read_text())

        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue

            test = ast.unparse(node.test)

            if "UserRole.ADMIN" not in test:
                continue

            if _is_exclusion_gate(node.test):
                continue

            yield path, node, test


def _admin_selecting_queries():
    """Every query filtering rows down to ADMIN users."""

    for path in _python_files():
        tree = ast.parse(path.read_text())

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if getattr(node.func, "attr", None) != "where":
                continue

            source = ast.unparse(node)

            if "User.role == UserRole.ADMIN" not in source:
                continue

            yield path, node, source


def _location(path, node):
    return f"{path.relative_to(REPO)}:{node.lineno}"


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


def test_every_admin_branch_mentions_a_clinic():
    """The branch's condition or its body must involve a clinic.

    Both spellings count, because both are used: invitation_service puts the
    comparison in the `if` test itself, while prescription_service puts it in
    the body. What is rejected is a branch that mentions no clinic anywhere,
    which is what all three read/write defects looked like.
    """

    offenders = []

    for path, node, test in _admin_role_branches():
        scope = "\n".join(
            [ast.unparse(node.test)] + [ast.unparse(s) for s in node.body]
        )

        if "clinic" not in scope.lower():
            offenders.append(f"{_location(path, node)}   if {test[:70]}")

    assert not offenders, (
        "ADMIN branch with no clinic comparison — a clinic admin would act on "
        "another tenant's rows:\n  " + "\n  ".join(offenders)
    )


def test_every_query_selecting_admins_is_clinic_filtered():
    """notify_admins selected `User.role == ADMIN` across every tenant and
    pushed a realtime event to all of them. Authorization at the endpoint
    cannot see this: the caller was correctly scoped and the fan-out was not."""

    offenders = []

    for path, node, source in _admin_selecting_queries():
        if "clinic" not in source.lower():
            offenders.append(f"{_location(path, node)}   {source[:90]}")

    assert not offenders, (
        "query selects ADMIN users without a clinic filter:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# The guards are not vacuous
# ---------------------------------------------------------------------------


def test_the_branch_scanner_still_finds_the_code_it_polices():
    found = list(_admin_role_branches())
    files = {str(path.relative_to(REPO)) for path, _, _ in found}

    assert len(found) >= 6, f"only {len(found)} admin branches found; scanner broken?"

    # The functions the audit actually fixed. If one stops matching, either it
    # was renamed and this guard no longer covers it, or the check was removed.
    for expected in (
        "app/services/prescription_service.py",
        "app/services/payment_refund_service.py",
        "app/services/invitation_service.py",
        "app/services/user_deletion_service.py",
        "app/services/tenant_resolver.py",
    ):
        assert expected in files, f"{expected} no longer matched by the scanner"


def test_the_query_scanner_still_finds_the_code_it_polices():
    found = list(_admin_selecting_queries())
    files = {str(path.relative_to(REPO)) for path, _, _ in found}

    assert "app/services/realtime_service.py" in files, (
        "the admin fan-out query is no longer matched; this guard is now "
        "watching nothing"
    )
