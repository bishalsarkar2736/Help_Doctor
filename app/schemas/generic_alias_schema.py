from pydantic import BaseModel, ConfigDict, Field


class GenericAliasCreate(BaseModel):
    generic_id: int

    # An alias is a clinical claim that two names denote the same substance, so
    # it has to be a name — a one-character alias would match half the
    # catalogue's allergens on a token comparison.
    alias: str = Field(min_length=2, max_length=255)


class GenericAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generic_id: int
    alias: str

    # Echoed back so whoever registered the alias can see which substance it
    # was attached to without a second lookup.
    generic_name: str | None = None
