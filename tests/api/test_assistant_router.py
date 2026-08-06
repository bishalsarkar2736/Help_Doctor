"""Classifying a question without spending a model call.

The router is a pure function, so every case here is a sentence and an
expectation. That is the point of keeping it free of the database and the
clock: the rules can be pinned exactly, and the ordering between them — which
is where this kind of code actually goes wrong — can be asserted.
"""

import pytest

from app.assistant.router import DayReference, Intent, route


# ---------------------------------------------------------------------------
# Doctor availability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Is Dr Rahman available tomorrow?",
        "is dr rahman available tomorrow",
        "When is Dr Rahman free?",
        "Dr. Rahman availability this week",
        "What time is Dr Rahman available?",
    ],
)
def test_a_named_doctor_with_an_availability_word(question):
    result = route(question)

    assert result.intent is Intent.DOCTOR_AVAILABILITY

    # Exact, not startswith. A looser assertion passed while the capture was
    # running into the question and yielding "rahman available" — a name that
    # matches no doctor, so someone who exists is reported as not found.
    assert result.doctor_name.lower() == "rahman"


def test_a_two_word_doctor_name_is_kept():
    result = route("Is Dr Rahman Khan available today?")

    assert result.doctor_name.lower() == "rahman khan"


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Is Dr Rahman available tomorrow?", "rahman"),
        ("Is Dr Rahman free today?", "rahman"),
        ("When is Dr Karim working this week?", "karim"),
        ("Dr Rahman", "rahman"),
        ("Is Dr Rahman Khan available on Friday?", "rahman khan"),
    ],
)
def test_the_name_never_swallows_the_question(question, expected):
    """The capture must stop at the question, not run into it."""
    assert route(question).doctor_name.lower() == expected


def test_tomorrow_is_recognised():
    assert route("Is Dr Rahman available tomorrow?").day is DayReference.TOMORROW


def test_today_is_recognised():
    assert route("Is Dr Rahman free today?").day is DayReference.TODAY


def test_a_weekday_is_recognised():
    result = route("Is Dr Rahman available on Friday?")

    assert result.weekday == 4


def test_no_day_mentioned_leaves_it_unset():
    assert route("When is Dr Rahman free?").day is None


# ---------------------------------------------------------------------------
# Earliest slot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "I need the earliest appointment",
        "Who can see me today?",
        "What is the soonest I can be seen?",
        "first available appointment please",
        "is anyone available",
    ],
)
def test_asking_for_the_soonest(question):
    assert route(question).intent is Intent.EARLIEST_SLOT


def test_the_soonest_today_carries_the_day():
    assert route("Who can see me today?").day is DayReference.TODAY


# ---------------------------------------------------------------------------
# Clinic information
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What are your opening hours?",
        "When do you close?",
        "Are you open now?",
        "What is your address?",
        "What is your phone number?",
        "Where are you located?",
        "Are you open on Friday?",
    ],
)
def test_questions_about_the_clinic(question):
    assert route(question).intent is Intent.CLINIC_INFORMATION


def test_a_holiday_question_carries_the_weekday():
    result = route("Are you open on Friday?")

    assert result.intent is Intent.CLINIC_INFORMATION
    assert result.weekday == 4


# ---------------------------------------------------------------------------
# Specializations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What specialists do you have?",
        "what specialties are available here",
        "What departments do you have?",
        "what kind of doctors do you have",
    ],
)
def test_asking_what_the_clinic_offers(question):
    assert route(question).intent is Intent.LIST_SPECIALIZATIONS


def test_naming_a_specialty_is_a_search_not_a_list():
    """"Do you have a cancer specialist?" is about one specialty, not all."""
    result = route("Do you have a cancer specialist?")

    assert result.intent is Intent.SEARCH_DOCTORS
    assert result.specialization_text == "cancer"


def test_the_patients_own_words_are_kept():
    """Not "Oncology".

    Whether "cancer" resolves to a specialty this clinic practises depends on
    what it actually practises, which this layer cannot see. A router that
    translated here would invent specialties for clinics without them.
    """
    assert route("I need a cancer specialist").specialization_text == "cancer"
    assert route("I need a cardiologist").specialization_text == "cardiologist"


# ---------------------------------------------------------------------------
# Doctor search
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "I need a cardiologist",
        "I am looking for a dermatologist",
        "Do you have a Dr Rahman?",
        "find me a heart doctor",
    ],
)
def test_looking_for_a_doctor(question):
    assert route(question).intent is Intent.SEARCH_DOCTORS


def test_a_bare_doctor_name_is_a_search():
    result = route("Dr Rahman")

    assert result.intent is Intent.SEARCH_DOCTORS
    assert result.doctor_name.lower() == "rahman"


# ---------------------------------------------------------------------------
# Precedence — where this kind of code actually goes wrong
# ---------------------------------------------------------------------------


def test_a_doctors_schedule_beats_the_clinics_hours():
    """"When is Dr Rahman free?" contains "when", which also opens "when do
    you close?". Reordering these rules is how the clinic's hours start being
    answered with a doctor's schedule."""
    assert route("When is Dr Rahman free?").intent is Intent.DOCTOR_AVAILABILITY


def test_clinic_hours_beat_a_doctor_search():
    """"Are you open on Friday?" mentions no doctor and is about the premises."""
    assert route("Are you open on Friday?").intent is Intent.CLINIC_INFORMATION


def test_the_soonest_beats_a_generic_search():
    assert route("I need the earliest appointment").intent is Intent.EARLIEST_SLOT


def test_a_named_specialty_beats_the_specialty_list():
    assert route("Do you have a cancer specialist?").intent is Intent.SEARCH_DOCTORS


# ---------------------------------------------------------------------------
# Declining to classify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "",
        "   ",
        "hello",
        "why does my head hurt",
        "what is the meaning of life",
        "thanks!",
    ],
)
def test_unrecognised_questions_are_unknown(question):
    """A real outcome, not a failure.

    UNKNOWN is what hands a question to a model. A rule that guessed to avoid
    it would answer something nobody asked.
    """
    result = route(question)

    assert result.intent is Intent.UNKNOWN
    assert result.is_known is False


def test_a_symptom_question_is_not_routed_to_a_specialty():
    """The assistant is explicitly not diagnostic.

    "My chest hurts" must not become a cardiology search — that is triage, and
    nothing here maps a complaint to a department.
    """
    assert route("my chest hurts").intent is Intent.UNKNOWN


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_every_route_reports_what_it_matched_on():
    """So a surprising classification can be explained without a debugger."""
    for question in (
        "Is Dr Rahman available tomorrow?",
        "Who can see me today?",
        "When do you close?",
        "What specialists do you have?",
    ):
        assert route(question).matched_on


def test_routing_is_deterministic():
    question = "Is Dr Rahman available tomorrow?"

    first, second = route(question), route(question)

    assert (first.intent, first.doctor_name, first.day) == (
        second.intent,
        second.doctor_name,
        second.day,
    )
