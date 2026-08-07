from pydantic import BaseModel


class MedicineAssistantRequest(BaseModel):
    question: str
    # Optional clinic context. Required for non-clinic-bound callers
    # (e.g. patients); ignored for doctors (resolved from their profile).
    clinic_id: int | None = None


class MedicineAssistantResponse(BaseModel):
    """The answer, plus what v2 knows about it.

    `answer` is unchanged and always present, so every existing client keeps
    working without a code change — that is the whole point of adding fields
    rather than reshaping the response.

    The rest are optional and only populated by v2. They carry the structure
    the answer was built from, so a future screen can render a candidate list
    or link to a medicine without another migration, and any claim can be
    checked against its source. v1 leaves them null.
    """

    answer: str

    intent: str | None = None
    status: str | None = None
    result: dict | None = None