BLOCKED_KEYWORDS = {
    "dosage",
    "dose",
    "take",
    "stop",
    "replace",
    "interaction",
    "combine",
    "pregnant",
    "pregnancy",
    "breastfeeding",
    "child",
    "kid",
    "baby",
    "safe",
    "unsafe",
}


def is_blocked_question(
    question: str,
) -> bool:

    question_lower = question.lower()

    return any(
        keyword in question_lower
        for keyword in BLOCKED_KEYWORDS
    )