"""The image a monitoring config is validated with, derived from the deployment.

WHY THIS EXISTS
`promtool check config` and `amtool check-config` are schema validators, so they
answer for the version of the binary running them. Hard-coding an image in the
tests means validation can silently answer for a version nobody deploys.

Measured on this project, all three at once:

    running Prometheus       3.13.1
    host /usr/bin/promtool   2.45.3      -- a whole major behind
    running Alertmanager     0.33.1
    an amtool check ran      v0.28.1     -- five minors behind

and compose declared `prom/prometheus` / `prom/alertmanager` with no tag at all,
so "the deployed version" was whatever Docker Hub last published.

The fix is not to hard-code better numbers -- it is to stop hard-coding. These
helpers read the image out of docker-compose.yml, which is the same string the
deployment uses, so pinning a new version updates the validators by construction.
"""

import pathlib

import yaml

REPO = pathlib.Path(__file__).parent.parent.parent

COMPOSE = REPO / "docker-compose.yml"


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates compose's `!override` tag."""


def _passthrough(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!", lambda loader, suffix, node: _passthrough(loader, node))


def service_image(service: str) -> str:
    """The image compose deploys for `service`, tag included.

    Raises rather than defaulting: a missing service or a missing image is a
    configuration error, and quietly falling back to `:latest` is precisely the
    behaviour this module exists to remove.
    """
    services = yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]

    if service not in services:
        raise AssertionError(f"docker-compose.yml declares no {service!r} service")

    image = services[service].get("image")

    if not image:
        raise AssertionError(f"the {service!r} service declares no image")

    return image


def is_pinned(image: str) -> bool:
    """Does this reference name an exact version?

    A bare repository (`prom/prometheus`) means `:latest`, and so does an
    explicit `:latest`. Both leave the deployed version up to whoever last
    pushed to the registry. A digest (`@sha256:...`) is pinned too.
    """
    if "@sha256:" in image:
        return True

    _, separator, tag = image.rpartition(":")

    # No colon at all, or a colon that is part of a registry host:port.
    if not separator or "/" in tag:
        return False

    return tag != "latest"


PROMETHEUS_IMAGE = service_image("prometheus")
ALERTMANAGER_IMAGE = service_image("alertmanager")
