FORBIDDEN_PHRASES = [
    "take 2 tablets",
    "take one tablet",
    "you should take",
    "recommended dosage",
    "prescribe",
    "prescription",
    "diagnosis",
    "diagnose",
    "treatment plan",
]


def validate_ai_response(
    response: str,
) -> str:

    lower = response.lower()

    for phrase in FORBIDDEN_PHRASES:

        if phrase in lower:

            return (
                "The medicine database "
                "does not contain enough "
                "information to answer "
                "that safely."
            )

    return response