"""Structural guard: a route that takes a patient identifier must resolve a clinic.

WHY A SECOND GUARD
test_admin_clinic_scoping.py polices things that are PRESENT — an
`if role == ADMIN` branch, or a query filtering on `User.role == ADMIN`. It
could not have caught the defect in GET /patients/{patient_user_id}, because
that defect was the absence of a branch:

    clinic_id = current_user.clinic_id
    if current_user.role == UserRole.DOCTOR:
        ... treatment-relationship check ...
    # ADMIN and RECEPTIONIST: no branch at all, straight to the return

Both unguarded roles reached the response, so any clinic's admin or
receptionist could read any patient's record — allergies, current medications,
chronic conditions, blood type — by walking sequential user ids. No rule that
inspects existing branches can see a branch nobody wrote.

So this guard inverts the question. Rather than asking whether a check is
correct, it asks whether the route resolved a tenant AT ALL. A handler that
accepts a patient identifier and never mentions a clinic in its executable
code is reading PHI without knowing which clinic is asking, and that is the
shape of the bug regardless of which role it lets through.

WHY PATIENT IDENTIFIERS SPECIFICALLY
They are the enumerable ones. A prescription id is at least a random-ish handle
into one clinic's data; a patient identifier is a sequential user id, and the
payload behind it is the densest PHI the API returns. The rule is also crisply
decidable — a parameter is named patient_id or patient_user_id or it is not —
which keeps this guard free of the judgement calls that would make developers
route around it.

WHAT COUNTS AS RESOLVING
Either the handler COMPARES a clinic — `Appointment.clinic_id == clinic_id`,
whether as a query predicate or an authorization test — or it CALLS something
that resolves one, like resolve_clinic_id or _searcher_clinic_id.

The disjunction is not laziness, and neither half is sufficient alone:

  * Comparison alone rejects patient_history, which correctly resolves the
    clinic and hands it to a service that does the filtering. The comparison is
    real, it just is not in the handler.

  * "Mentions a clinic" alone was the first version of this guard, and it did
    not work. Reverting the GET /patients/{patient_user_id} fix left
    `clinic_id = current_user.clinic_id` in place — assigned for the audit log,
    never used to decide anything — and the guard passed. A value that is only
    read to be logged is not a tenant check, so an assignment does not count.

Comments and the docstring are stripped before any of this, so a handler cannot
satisfy the guard by describing a check it does not perform.
"""

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
ROUTES = REPO / "app" / "api" / "routes"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

#: A path or query parameter naming the patient whose data is being reached.
PATIENT_PARAM = re.compile(r"^patient(_user)?_id$")


def _route_handlers():
    """Every function in app/api/routes decorated with an HTTP method."""

    for path in sorted(ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text())

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in HTTP_METHODS
                ):
                    yield path, node, decorator
                    break


def _patient_scoped_handlers():
    for path, node, decorator in _route_handlers():
        parameters = [a.arg for a in node.args.args + node.args.kwonlyargs]
        taken = [p for p in parameters if PATIENT_PARAM.match(p)]

        if taken:
            yield path, node, taken


def _executable_body(node):
    """The handler's statements, without its docstring.

    ast.unparse already drops comments. The docstring has to be removed
    explicitly — otherwise a paragraph about clinic scoping would satisfy a
    guard that exists to check the code performs it.
    """

    body = list(node.body)

    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    return body


def _executable_source(node) -> str:
    return "\n".join(ast.unparse(statement) for statement in _executable_body(node))


def _compares_a_clinic(node) -> bool:
    """A clinic appears in a comparison — a query predicate or an `if`."""

    for statement in _executable_body(node):
        for inner in ast.walk(statement):
            if isinstance(inner, ast.Compare):
                if "clinic" in ast.unparse(inner).lower():
                    return True

    return False


def _calls_a_clinic_resolver(node) -> bool:
    """The handler calls something whose name says it yields a clinic.

    A call, not an attribute read: `current_user.clinic_id` is the value the
    vulnerable handler assigned and never checked, so reading it must not
    satisfy this.
    """

    for statement in _executable_body(node):
        for inner in ast.walk(statement):
            if not isinstance(inner, ast.Call):
                continue

            name = getattr(inner.func, "id", None) or getattr(inner.func, "attr", None)

            if name and "clinic" in name.lower():
                return True

    return False


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_every_patient_scoped_route_resolves_a_clinic():
    offenders = []

    for path, node, taken in _patient_scoped_handlers():
        if _compares_a_clinic(node) or _calls_a_clinic_resolver(node):
            continue

        offenders.append(
            f"{path.relative_to(REPO)}:{node.lineno}  "
            f"{node.name}({', '.join(taken)})"
        )

    assert not offenders, (
        "route takes a patient identifier but never resolves a clinic — it "
        "reads PHI without establishing who is asking:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# The guard is not vacuous
# ---------------------------------------------------------------------------


def test_the_scanner_finds_the_routes_it_polices():
    """A scanner matching nothing passes forever. These three are the current
    population; the assertion is a floor, not a ceiling, so adding a route does
    not fail the build — removing the guard's reach does."""

    found = list(_patient_scoped_handlers())
    names = {f"{path.name}::{node.name}" for path, node, _ in found}

    assert len(found) >= 3, f"only {len(found)} patient-scoped routes found"

    for expected in (
        "patients.py::get_patient_record",
        "patient_history.py::patient_history",
        "admin_phi_access.py::list_phi_access",
    ):
        assert expected in names, f"{expected} is no longer being policed"


def _handler(source: str):
    return ast.parse(source).body[0]


def test_prose_about_a_clinic_does_not_satisfy_the_guard():
    """Verified against synthetic handlers rather than by reading the
    implementation, since a guard that quietly accepts prose is exactly the
    failure this file depends on not having."""

    prose_only = _handler(
        'async def handler(patient_id: int):\n'
        '    """Scoped to the caller\'s clinic."""\n'
        '    # resolves the clinic from the principal\n'
        '    return await db.get(Patient, patient_id)\n'
    )

    assert not _compares_a_clinic(prose_only)
    assert not _calls_a_clinic_resolver(prose_only)
    assert "clinic" not in _executable_source(prose_only).lower()


def test_assigning_a_clinic_without_using_it_does_not_satisfy_the_guard():
    """THE CASE THAT BROKE THE FIRST VERSION OF THIS GUARD.

    This is the shape of the real defect: the clinic is read off the principal
    so the PHI access log has something to record, and no decision is ever made
    with it. An earlier rule of "mentions a clinic" passed this.
    """

    logged_only = _handler(
        "async def handler(patient_user_id: int):\n"
        "    clinic_id = current_user.clinic_id\n"
        "    await log_phi_access(clinic_id=clinic_id)\n"
        "    return patient\n"
    )

    assert "clinic" in _executable_source(logged_only).lower()

    assert not _compares_a_clinic(logged_only)
    assert not _calls_a_clinic_resolver(logged_only)


def test_either_a_comparison_or_a_resolver_call_satisfies_the_guard():
    """Both halves are needed: patient_history resolves and delegates without
    comparing, while a handler may equally filter inline without calling a
    helper."""

    resolves = _handler(
        "async def handler(patient_id: int):\n"
        "    clinic_id = await _searcher_clinic_id(db, user)\n"
        "    return clinic_id\n"
    )

    assert _calls_a_clinic_resolver(resolves)

    compares = _handler(
        "async def handler(patient_id: int):\n"
        "    return await db.scalar(\n"
        "        select(Appointment.id).where(Appointment.clinic_id == scope)\n"
        "    )\n"
    )

    assert _compares_a_clinic(compares)
