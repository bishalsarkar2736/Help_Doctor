from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar(
    "request_id", default=None
)

# Set once the request is authenticated (get_current_user) so every log line in
# the request scope carries who/which-clinic without passing it explicitly.
user_id_ctx: ContextVar[int | None] = ContextVar(
    "user_id", default=None
)

clinic_id_ctx: ContextVar[int | None] = ContextVar(
    "clinic_id", default=None
)
