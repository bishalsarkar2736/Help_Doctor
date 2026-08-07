"""What changes when the medicine assistant flag is flipped.

Run this against a real database BEFORE setting USE_MEDICINE_ASSISTANT_V2=true.
It asks both implementations the same questions and classifies every difference,
so the cutover is a decision made with the diff in front of you rather than a
hope.

    python -m scripts.medicine_assistant_migration_report

WHY NOT AN EQUIVALENCE CHECK
----------------------------
Because the two are not meant to agree. v2 exists to change what the assistant
refuses and to resolve substances v1 could not find, so an equivalence gate
would flag the entire point of the work as a regression.

What matters instead is direction. A difference is only a problem when v1 was
right and v2 is worse; every other difference is either the fix landing or
wording. The classes below say which is which, and the exit code is non-zero
only for the one that matters.

    IMPROVEMENT   v1 could not answer, or answered something it should not
    INTENDED      both answer correctly, wording differs
    IDENTICAL     no change
    REGRESSION    v1 answered correctly and v2 does not   <- blocks the cutover
    MISSING       v1 supported something v2 does not      <- blocks the cutover
"""

import asyncio
import sys
from dataclasses import dataclass

from app.db.postgres import AsyncSessionLocal
from app.medicine_assistant.service import answer_medicine_question_v2
from app.services.medicine_assistant_service import answer_medicine_question

CLINIC_ID = 1
CLIENT_IP = "127.0.0.1"

# v1's answer when its matcher finds nothing. Recognising it is what lets the
# report tell "v1 could not answer" apart from "v1 answered differently".
V1_NOT_FOUND = "could not find information"


@dataclass
class Case:
    question: str
    # What the question is: a medicine-information request that must keep
    # working, or one that must be refused.
    must_answer: bool
    note: str = ""


CASES = [
    # --- the supported list, verbatim from the specification ---------------
    Case("What is Napa Extra?", True),
    Case("Tell me about Cef-3.", True),
    Case("What is the generic of Napa?", True),
    Case("What is the common use of Ace?", True),
    Case("What are the common side effects of Cefixime?", True, "generic name"),
    Case("How should I store Napa?", True),
    Case("Who manufactures Napa?", True),
    Case("What dosage form is Ace?", True),
    # --- the remaining v2 intents ------------------------------------------
    Case("What strength is Napa?", True),
    Case("What category is Ace?", True),
    Case("Is Napa a brand or generic?", True),
    Case("What brands contain Cefixime?", True, "v2 only"),
    Case("What is Paracetamol?", True, "generic name"),
    # --- the unsupported list, verbatim ------------------------------------
    Case("I have HIV. Can I take Napa?", False),
    Case("I'm pregnant. Can I use this medicine?", False),
    Case("My child has fever.", False),
    Case("What antibiotic should I take?", False),
    Case("Can I combine Napa and Ace?", False),
    Case("My blood pressure is high.", False),
    Case("Recommend medicine.", False),
    Case("Diagnose me.", False),
    Case("How many tablets of Napa should I take?", False),
    Case("Is Napa safe during pregnancy?", False),
]


def _v1_failed(answer: str) -> bool:
    return V1_NOT_FOUND in answer.lower()


def _v1_gave_medicine_info(answer: str) -> bool:
    """v1 answered with product information.

    For a question that should have been refused this is the worst outcome:
    "Can I combine Napa and Ace?" returns a description of Napa, which reads
    as an answer to the question that was asked.
    """
    return not _v1_failed(answer) and len(answer) > 40


def classify(case: Case, v1_answer: str, v2: dict) -> tuple[str, str]:
    refused = v2["result"]["status"] == "refused"
    answered = v2["result"]["status"] in ("ok", "ambiguous", "field_missing")

    if case.must_answer:
        if not answered:
            if _v1_failed(v1_answer):
                return "INTENDED", "neither implementation can answer this"

            return "REGRESSION", "v1 answered this and v2 does not"

        if _v1_failed(v1_answer):
            return "IMPROVEMENT", "v1 could not find it; v2 resolves it"

        if v1_answer.strip() == v2["message"].strip():
            return "IDENTICAL", ""

        return "INTENDED", "same facts, different wording"

    # Must be refused.
    if not refused:
        return "REGRESSION", "v2 failed to refuse"

    if _v1_gave_medicine_info(v1_answer):
        return "IMPROVEMENT", "v1 answered with medicine information"

    return "IMPROVEMENT", "v1 did not refuse; it reported a lookup failure"


async def main() -> int:
    rows = []

    async with AsyncSessionLocal() as db:
        for case in CASES:
            v1_answer = await answer_medicine_question(
                db=db, clinic_id=CLINIC_ID, question=case.question
            )
            v2 = await answer_medicine_question_v2(
                db, clinic_id=CLINIC_ID, question=case.question, client_ip=CLIENT_IP
            )

            verdict, why = classify(case, v1_answer, v2)

            rows.append((verdict, case, v1_answer, v2, why))

        # The report itself writes query rows; keep them.
        await db.commit()

    counts: dict[str, int] = {}

    for verdict, case, v1_answer, v2, why in rows:
        counts[verdict] = counts.get(verdict, 0) + 1

    print("=" * 78)
    print("MEDICINE ASSISTANT V1 -> V2 MIGRATION REPORT")
    print("=" * 78)

    for wanted in ("REGRESSION", "MISSING", "IMPROVEMENT", "INTENDED", "IDENTICAL"):
        selected = [r for r in rows if r[0] == wanted]

        if not selected:
            continue

        print(f"\n{wanted}  ({len(selected)})")
        print("-" * 78)

        for _, case, v1_answer, v2, why in selected:
            print(f"  Q: {case.question}")

            if why:
                print(f"     {why}")

            if wanted != "IDENTICAL":
                print(f"     v1: {v1_answer.strip()[:96]}")
                print(f"     v2: {v2['message'].strip()[:96]}")

    print("\n" + "=" * 78)
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    blocking = counts.get("REGRESSION", 0) + counts.get("MISSING", 0)

    if blocking:
        print(f"\n  BLOCKED: {blocking} regression(s). Do not enable v2.")
        return 1

    print("\n  No regressions. Safe to set USE_MEDICINE_ASSISTANT_V2=true.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
