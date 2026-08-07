"""Classifying a medicine question, and refusing the ones that are not.

The router is a pure function, so every case here is a sentence and an
expectation — which is the reason it is separate from the code that answers.

Two properties matter more than the individual mappings.

Refusal runs BEFORE anything is identified or looked up. "I'm pregnant, can I
take Napa?" contains a real medicine name and a familiar question shape;
classified in the other order it routes to a lookup and gets answered.

And refusal is not a keyword blocklist. The dead blocklist this replaces
contains "dosage", and "What dosage form is Ace?" is a supported question — so
the rules match constructions (who the sentence is about) rather than
vocabulary, and both halves of that are asserted.
"""

import pytest

from app.medicine_assistant.router import (
    MedicineIntent,
    RefusalReason,
    route,
)


# ---------------------------------------------------------------------------
# The supported questions, verbatim from the specification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What is Napa Extra?", MedicineIntent.MEDICINE_OVERVIEW),
        ("Tell me about Cef-3.", MedicineIntent.MEDICINE_OVERVIEW),
        ("What is the generic of Napa?", MedicineIntent.GENERIC_NAME),
        ("What is the common use of Ace?", MedicineIntent.COMMON_USE),
        (
            "What are the common side effects of Cefixime?",
            MedicineIntent.SIDE_EFFECTS,
        ),
        ("How should I store Napa?", MedicineIntent.STORAGE),
        ("Who manufactures Napa?", MedicineIntent.MANUFACTURER),
        ("What dosage form is Ace?", MedicineIntent.DOSAGE_FORM),
    ],
)
def test_the_specified_questions_are_supported(question, expected):
    assert route(question).intent is expected


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What strength is Napa?", MedicineIntent.STRENGTH),
        ("What category is Ace?", MedicineIntent.CATEGORY),
        ("Is Napa a brand or generic?", MedicineIntent.BRAND_OR_GENERIC),
        ("What brands contain Cefixime?", MedicineIntent.BRANDS_OF_GENERIC),
    ],
)
def test_the_remaining_intents(question, expected):
    assert route(question).intent is expected


def test_the_generic_being_asked_about_is_captured():
    """Raw words, not a resolved substance — that needs the database."""
    assert route("What brands contain Cefixime?").subject_phrase == "cefixime"


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "I have HIV. Can I take Napa?",
        "I'm pregnant. Can I use this medicine?",
        "My child has fever.",
        "What antibiotic should I take?",
        "Can I combine Drug A and Drug B?",
        "My blood pressure is high.",
        "Recommend medicine.",
        "Diagnose me.",
    ],
)
def test_the_specified_refusals(question):
    """Verbatim from the specification's unsupported list."""
    assert route(question).is_refusal


@pytest.mark.parametrize(
    "question, reason",
    [
        ("I have diabetes, what should I use?", RefusalReason.PERSONAL_MEDICAL_CONTEXT),
        ("My daughter has a cough", RefusalReason.PERSONAL_MEDICAL_CONTEXT),
        ("Can I take Napa?", RefusalReason.ADVICE_SOUGHT),
        ("Should I take this medicine?", RefusalReason.ADVICE_SOUGHT),
        ("Is it safe?", RefusalReason.ADVICE_SOUGHT),
        ("How many tablets should I take?", RefusalReason.ADVICE_SOUGHT),
        ("Can Napa be mixed with Ace?", RefusalReason.DRUG_INTERACTION),
        ("Is Napa ok during pregnancy?", RefusalReason.POPULATION_SAFETY),
        ("Is this suitable for children?", RefusalReason.POPULATION_SAFETY),
    ],
)
def test_why_a_question_was_refused(question, reason):
    """The reason is recorded so the reply can say something useful rather
    than the same sentence to every refusal."""
    result = route(question)

    assert result.is_refusal
    assert result.refusal_reason is reason


def test_a_refusal_names_no_field():
    """Nothing downstream should be able to act on a refused question."""
    result = route("I'm pregnant, can I take Napa?")

    assert result.intent is MedicineIntent.REFUSE
    assert result.subject_phrase is None
    assert result.is_known is False


def test_refusal_wins_over_a_recognisable_medicine_question():
    """The load-bearing ordering.

    This sentence contains a real medicine name and the shape of a supported
    question. Checked in the other order it routes to a lookup and is answered.
    """
    assert route("I have asthma, what is the common use of Napa?").is_refusal


# ---------------------------------------------------------------------------
# Where a keyword blocklist would have failed
# ---------------------------------------------------------------------------


def test_dosage_form_is_not_refused():
    """The exact case the existing blocklist gets wrong.

    medicine_ai_safety_service.BLOCKED_KEYWORDS contains "dosage", so it
    refuses this — a question the specification lists as supported.
    """
    assert route("What dosage form is Ace?").intent is MedicineIntent.DOSAGE_FORM


def test_the_word_take_alone_does_not_refuse():
    """"take" appears in the old blocklist and in answerable sentences."""
    assert route("What is Napa Extra used to take care of?").is_refusal is False


def test_storage_questions_survive_the_word_keep():
    assert route("How should I keep it?").intent is MedicineIntent.STORAGE


def test_the_old_blocklist_would_have_refused_a_supported_question():
    """Asserted so the two approaches cannot be quietly swapped back.

    If this ever fails, the blocklist has changed and the exemption in the
    router may no longer be needed — or, worse, someone has wired the blocklist
    into the flow.
    """
    from app.services.medicine_ai_safety_service import is_blocked_question

    assert is_blocked_question("What dosage form is Ace?") is True
    assert route("What dosage form is Ace?").is_refusal is False


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_a_specific_field_beats_the_overview():
    """"What is the generic of Napa?" contains "what is", which also opens
    "What is Napa?". Reordering these is how a question about a generic name
    starts returning a product description."""
    assert route("What is the generic of Napa?").intent is MedicineIntent.GENERIC_NAME


def test_plural_brands_beats_the_brand_question():
    """"What brands contain Cefixime" must not read as "is this a brand"."""
    assert (
        route("What brands contain Cefixime?").intent
        is MedicineIntent.BRANDS_OF_GENERIC
    )


def test_side_effects_beats_the_overview():
    assert (
        route("What is the side effect of Napa?").intent
        is MedicineIntent.SIDE_EFFECTS
    )


# ---------------------------------------------------------------------------
# Declining to classify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    ["", "   ", "hello", "thanks", "good morning"],
)
def test_unrecognised_questions_are_unknown(question):
    result = route(question)

    assert result.intent is MedicineIntent.UNKNOWN
    assert result.is_known is False


def test_a_what_is_question_about_a_non_medicine_still_routes():
    """"What is the weather?" is classified as an overview, and that is right.

    The router cannot know what is a medicine without the database it
    deliberately cannot see. Deciding that is the matcher's job: the intent
    says "someone asked what X is", the lookup finds no X, and the answer is
    "I don't have a medicine by that name."

    A router that tried to judge it would need a catalogue, and the moment it
    has one it is no longer a pure function that can be tested by writing a
    sentence.
    """
    assert route("What is the weather?").intent is MedicineIntent.MEDICINE_OVERVIEW


def test_unknown_is_not_a_refusal():
    """They are different outcomes and get different replies: one says "I only
    do medicine information", the other says "I didn't understand"."""
    result = route("hello")

    assert result.intent is MedicineIntent.UNKNOWN
    assert result.is_refusal is False


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_every_classification_reports_what_it_matched():
    """So a surprising result can be explained without a debugger."""
    for question in (
        "What is Napa?",
        "Who manufactures Ace?",
        "I'm pregnant, can I take this?",
    ):
        assert route(question).matched_on


def test_routing_is_deterministic():
    question = "What are the side effects of Napa?"

    first, second = route(question), route(question)

    assert first.intent is second.intent
    assert first.matched_on == second.matched_on
