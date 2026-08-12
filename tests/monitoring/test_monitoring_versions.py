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

# Every service in the monitoring stack whose version must be reproducible.
#
# prometheus and alertmanager are here because their CONFIG is validated by a
# version-sensitive tool -- promtool and amtool answer for the version running
# them. grafana and jaeger have no such validator; they are here for the other
# half of the same problem: an unpinned tag means a `compose pull` can change
# the deployed software with nothing in this repository to explain it.
#
# Measured when they were pinned: registry `:latest` for grafana had ALREADY
# moved past the image this host was running, and jaeger `:latest` was serving a
# v1 release that reached end-of-life on 2025-12-31.
VALIDATED = ["prometheus", "alertmanager", "grafana", "jaeger"]

# The two whose config a version-sensitive tool validates. Kept separate so the
# "validators derive their image" rules stay scoped to the services that have
# validators.
TOOL_VALIDATED = ["prometheus", "alertmanager"]

# Exact references, asserted literally on purpose. For these two the point is
# not "some pin" but "this specific verified image": the grafana digest was
# confirmed present in the registry as a 3-platform manifest list, and the
# jaeger tag was confirmed byte-identical to the `:latest` this host runs.
EXPECTED_REFERENCES = {
    "grafana": (
        "grafana/grafana@sha256:"
        "5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2"
    ),
    "jaeger": "jaegertracing/all-in-one:1.76.0",
}

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


# ---------------------------------------------------------------------------
# Grafana and Jaeger: pinned to specific verified images
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("service", sorted(EXPECTED_REFERENCES))
def test_the_reference_is_exactly_the_verified_one(service):
    """Not merely "pinned" -- pinned to the image that was actually checked.

    A pin to some other build would still satisfy is_pinned() while deploying
    software nobody verified. These two strings were established by inspecting
    the running containers and querying the registry, and changing either should
    be a deliberate act that updates this test alongside it.
    """
    assert monitoring_images.service_image(service) == EXPECTED_REFERENCES[service]


def test_grafana_is_pinned_by_digest():
    """A digest, not a tag, because the `13.0.2` tag has been rebuilt since this
    host pulled its image -- tag and running image are different builds of the
    same version. Only the digest reproduces what is actually running."""
    image = monitoring_images.service_image("grafana")

    assert "@sha256:" in image, image

    _, _, digest = image.partition("@sha256:")

    assert re.fullmatch(r"[0-9a-f]{64}", digest), (
        f"not a full 64-character digest: {digest!r}"
    )


def test_jaeger_is_pinned_to_a_release_tag():
    """Byte-identical to the `:latest` this host runs, so pinning changed
    nothing except who decides when it moves."""
    image = monitoring_images.service_image("jaeger")

    assert image.endswith(":1.76.0"), image
    assert "@sha256:" not in image, (
        "a digest here would be less readable than the tag, and the tag was "
        "verified to resolve to the same image"
    )


@pytest.mark.parametrize("service", sorted(EXPECTED_REFERENCES))
def test_no_fallback_to_latest(service):
    """The specific regression: reverting either of these to a floating
    reference. `grafana/grafana` with no tag means :latest just as surely as
    writing it out."""
    image = monitoring_images.service_image(service)

    assert not image.endswith(":latest"), image
    assert image != image.split(":")[0] or "@sha256:" in image, (
        f"{service} has no tag and no digest, which resolves to :latest"
    )
    assert monitoring_images.is_pinned(image)


@pytest.mark.parametrize("service", VALIDATED)
def test_the_reference_is_syntactically_valid(service):
    """Cheap parse of the reference grammar: repository[:tag][@digest]. A
    malformed reference fails at `compose up`, long after review."""
    image = monitoring_images.service_image(service)

    repository, _, digest = image.partition("@")

    if digest:
        assert digest.startswith("sha256:")
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest), digest

    name, separator, tag = repository.rpartition(":")

    if separator and "/" not in tag:
        assert re.fullmatch(r"[\w][\w.-]{0,127}", tag), f"invalid tag: {tag!r}"
        repository = name

    assert re.fullmatch(r"[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*",
                        repository), f"invalid repository: {repository!r}"


def test_the_tool_validated_services_are_still_covered():
    """Extending the list must not have quietly dropped the two whose config is
    validated by a version-sensitive binary."""
    for service in TOOL_VALIDATED:
        assert service in VALIDATED
        assert monitoring_images.is_pinned(monitoring_images.service_image(service))
