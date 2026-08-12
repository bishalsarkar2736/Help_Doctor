"""Monitoring configs are validated by the version that will run them.

THREE MEASUREMENTS THAT MOTIVATED THIS
`promtool check config` and `amtool check-config` are schema validators: they
answer for the version of the binary running them, not for the version deployed.
On this project all three of these were true at once:

    running Prometheus      3.13.1
    /usr/bin/promtool       2.45.3     -- a whole major behind
    running Alertmanager    0.33.1
    an amtool check ran     v0.28.1    -- five minors behind

and worse, docker-compose.yml declared `prom/prometheus` and `prom/alertmanager`
with NO TAG, so the deployed version was whatever Docker Hub last published. A
`compose pull`, or a fresh `up -d` on a host without the image cached, could move
the server across a major boundary without anything in the repository changing.
Prometheus 2.x -> 3.x altered PromQL and config handling; a rule file validated
under one and served by the other is a config that passes review and fails in
production.

WHAT IS PINNED HERE
That the images carry an explicit version, and that every validator invocation
derives its image from that same declaration rather than hard-coding one. The
second half is what keeps this true: bumping the tag in docker-compose.yml moves
the validators with it, automatically.

The host's own promtool is deliberately never used -- see
test_validation_does_not_use_the_host_binary.
"""

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

from tests.monitoring import monitoring_images  # noqa: E402

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"

# Services whose config is validated by a version-sensitive tool.
VALIDATED = ["prometheus", "alertmanager"]

# Every test file except this one. The literals below are parametrize DATA --
# the counter-examples the pinning rule is defined against -- not invocations,
# and a scanner that cannot tell the difference would forbid testing the rule.
TEST_FILES = [
    path
    for path in sorted((REPO / "tests").rglob("test_*.py"))
    if path.name != pathlib.Path(__file__).name
]


# ---------------------------------------------------------------------------
# The deployment declares a version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service", VALIDATED)
def test_the_image_is_pinned_to_a_version(service):
    """THE REGRESSION. A bare repository name means `:latest`, which is not a
    version -- it is a promise to run whatever was published most recently."""
    image = monitoring_images.service_image(service)

    assert monitoring_images.is_pinned(image), (
        f"{service} runs {image!r}, which resolves to :latest; the deployed "
        "version is then whatever the registry last published and no validation "
        "can be tied to it"
    )


@pytest.mark.parametrize("service", VALIDATED)
def test_the_pinned_tag_looks_like_a_version(service):
    """`:stable`, `:main` and `:v3` are moving targets wearing a tag."""
    image = monitoring_images.service_image(service)

    if "@sha256:" in image:
        return

    tag = image.rpartition(":")[2]

    assert re.fullmatch(r"v?\d+\.\d+\.\d+", tag), (
        f"{service} is tagged {tag!r}, which does not name an exact release"
    )


# ---------------------------------------------------------------------------
# Validation derives its image from that declaration
# ---------------------------------------------------------------------------


def test_the_helper_returns_the_deployed_images():
    assert monitoring_images.PROMETHEUS_IMAGE == monitoring_images.service_image(
        "prometheus"
    )
    assert monitoring_images.ALERTMANAGER_IMAGE == monitoring_images.service_image(
        "alertmanager"
    )


def test_no_test_hard_codes_a_monitoring_image():
    """The whole point: bumping the tag in compose must move the validators with
    it. A literal image string anywhere in the suite breaks that link silently --
    the tests keep passing, against the wrong version."""
    offenders = []

    for path in TEST_FILES:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]

            if re.search(r'["\']prom/(prometheus|alertmanager)[:"\']', code):
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")

    assert not offenders, (
        "these hard-code a monitoring image instead of deriving it from "
        "docker-compose.yml:\n  " + "\n  ".join(offenders)
    )


def test_the_helper_itself_hard_codes_nothing():
    """It reads compose; it must not carry a fallback image.

    Checked against the CODE, not the text: the module's docstrings quote the
    unpinned references deliberately, to record what the bug looked like. A
    grep-based check cannot tell a cautionary example from a default, and
    forbidding the explanation would be the wrong lesson to enforce.
    """
    import ast

    tree = ast.parse(pathlib.Path(monitoring_images.__file__).read_text())

    docstrings = set()

    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue

        first = node.body[0] if node.body else None

        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))

    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    # Assembled rather than written out, so this assertion does not itself
    # place the string it forbids into a scanned file.
    for repository in ("prometheus", "alertmanager"):
        needle = "prom/" + repository

        offenders = [text for text in literals if needle in text]

        assert not offenders, (
            f"the helper carries a hard-coded {needle} in code: {offenders}"
        )


def test_validation_does_not_use_the_host_binary():
    """`promtool` on PATH is whatever the distribution packaged -- 2.45.3 here,
    against a 3.13.1 server. Every invocation must go through the pinned image.
    """
    offenders = []

    for path in TEST_FILES:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]

            if re.search(r'["\'](promtool|amtool)["\']', code) and "--entrypoint" not in code:
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")

    assert not offenders, (
        "these invoke the host's promtool/amtool rather than the pinned "
        "image:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# The helper's own logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image,pinned",
    [
        ("prom/prometheus", False),
        ("prom/prometheus:latest", False),
        ("prom/prometheus:v3.13.1", True),
        ("prom/alertmanager:v0.33.1", True),
        ("prom/prometheus@sha256:" + "a" * 64, True),
        ("registry.example.com:5000/prom/prometheus", False),
        ("registry.example.com:5000/prom/prometheus:v3.13.1", True),
    ],
)
def test_pinning_detection(image, pinned):
    """A registry with a port puts a colon in the string that is not a tag --
    the case a naive `":" in image` check gets wrong."""
    assert monitoring_images.is_pinned(image) is pinned


def test_a_missing_service_is_an_error_not_a_default():
    """Falling back to :latest is the behaviour this module removes."""
    with pytest.raises(AssertionError, match="no 'nonexistent' service"):
        monitoring_images.service_image("nonexistent")


# ---------------------------------------------------------------------------
# Staging deploys the same versions
# ---------------------------------------------------------------------------


def test_staging_does_not_override_the_monitoring_images():
    """Staging exists to rehearse production. Rehearsing on a different
    Prometheus proves less than it appears to."""
    staging = yaml.safe_load(
        (REPO / "docker-compose.staging.yml").read_text().replace("!override", "")
    )["services"]

    for service in VALIDATED:
        assert "image" not in staging.get(service, {}), (
            f"staging pins a different {service} image than production"
        )
