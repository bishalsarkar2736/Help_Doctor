"""Patient allergy vs. prescribed-medicine matching.

A pragmatic safety net (not a drug database): the patient's free-text allergen
list is tokenized and substring-matched against each prescribed medicine name.
It catches direct matches (allergy "Aspirin" blocks "Aspirin 75mg"); it will not
catch class relationships (e.g. "Penicillin" vs "Amoxicillin"). A future upgrade
is a coded drug/allergen dictionary.
"""

import re


def _tokens(allergies: str | None) -> list[str]:
    if not allergies:
        return []
    return [t.strip().lower() for t in re.split(r"[,\n;/]+", allergies) if t.strip()]


def find_allergy_conflicts(
    allergies: str | None,
    medicine_names: list[str],
) -> list[str]:
    """Return the prescribed medicines that match a recorded allergen."""
    tokens = _tokens(allergies)
    if not tokens:
        return []

    conflicts = []
    for name in medicine_names:
        low = (name or "").lower()
        if low and any(tok in low for tok in tokens):
            conflicts.append(name)
    return conflicts
