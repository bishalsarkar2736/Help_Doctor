"""The tenant's DNS identity.

A clinic's subdomain is the label in `citycare.example.com` — the part that
identifies which tenant a request is for when routing by hostname. It is
therefore three things at once, and the validation here exists because they
disagree about what is acceptable:

1. A DNS label, bound by RFC 1123: at most 63 octets, letters/digits/hyphen
   only, no leading or trailing hyphen. A value that violates this cannot be
   resolved at all, so it must be refused at the point of entry rather than
   discovered when a certificate is issued.
2. A PUBLIC identity. Once handed out it appears in URLs, in emails, and in
   whatever bookmarks and printed material a clinic produces, so it cannot be
   quietly changed later the way a display name can.
3. A HOSTNAME on a domain this deployment already uses for other things.

Point 3 is the one that is easy to miss. `api`, `grafana` and `www` are not
merely unattractive choices: if a clinic claimed one, its subdomain would
collide with infrastructure that already answers on that name — or will. The
reserved set below is deliberately broader than "names currently in use",
because a tenant identity cannot be reclaimed once issued.

Normalisation is lowercase, because DNS is case-insensitive while a database
unique constraint is not. `CityCare` and `citycare` are the same host to every
resolver on the internet, so they must not be two rows.

This module decides nothing about ROUTING. It does not read the Host header,
does not resolve a request to a tenant, and is not an authorisation check —
those belong to app/services/clinic_context.py, which is where a Host-derived
strategy would be added. This is only the rule for what a valid identity looks
like.
"""

import re

# RFC 1123 label. Lowercase only: the value is normalised before it is checked,
# so an uppercase character here means normalisation was skipped rather than
# that the caller typed one.
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# The DNS limit for a single label. Not a product decision.
MAX_LENGTH = 63

# Names that must never become a tenant, grouped by why.
#
# Reserving generously is close to free — a clinic asked to pick another label
# is mildly inconvenienced — while failing to reserve one is not recoverable:
# the tenant is already using it by the time the collision is discovered.
RESERVED = frozenset({
    # This stack publishes or will publish these. `api` in particular already
    # appears as a hostname on the compose network, and the metrics scrape path
    # documents the confusion it causes (see app/try_except/trusted_host_middleware.py).
    "api", "www", "app", "web", "admin", "auth", "static", "assets", "cdn",
    # Observability and infrastructure services in docker-compose.yml.
    "grafana", "prometheus", "alertmanager", "pushgateway", "metrics",
    "minio", "jaeger", "mailhog", "redis", "postgres", "db",
    # Mail and DNS. A tenant holding one of these can intercept or break mail
    # delivery for the whole domain.
    "mail", "smtp", "imap", "pop", "mx", "ns", "ns1", "ns2", "dns", "email",
    "autodiscover", "autoconfig",
    # Environments and operational surfaces.
    "staging", "stage", "dev", "test", "demo", "sandbox", "preview", "local",
    "status", "health", "docs", "support", "help", "blog", "billing",
    # Certificate issuance. ACME HTTP-01 uses a well-known path rather than a
    # hostname, but these are conventional and cheap to reserve.
    "acme", "letsencrypt", "_acme-challenge",
})


class InvalidSubdomain(ValueError):
    """The proposed subdomain cannot be used as a tenant identity."""


def normalize_subdomain(value: str | None) -> str | None:
    """Strip and lowercase, or None.

    An empty string becomes None rather than "": the column is nullable, and a
    clinic with no subdomain is simply not reachable by hostname. Storing ""
    would make it look configured while matching no request, and would collide
    with the next clinic that also stored "".
    """
    if value is None:
        return None

    normalized = value.strip().lower()

    return normalized or None


def validate_subdomain(value: str | None) -> str | None:
    """The normalised subdomain, or raise InvalidSubdomain.

    None passes through: not every clinic needs a hostname, and requiring one
    would mean no clinic could be created before its DNS was decided.
    """
    normalized = normalize_subdomain(value)

    if normalized is None:
        return None

    if len(normalized) > MAX_LENGTH:
        raise InvalidSubdomain(
            f"Subdomain must be at most {MAX_LENGTH} characters"
        )

    if not _LABEL.match(normalized):
        raise InvalidSubdomain(
            "Subdomain must contain only lowercase letters, digits and "
            "hyphens, and must start and end with a letter or digit"
        )

    if normalized in RESERVED:
        raise InvalidSubdomain(
            f"'{normalized}' is reserved and cannot be used as a subdomain"
        )

    return normalized
