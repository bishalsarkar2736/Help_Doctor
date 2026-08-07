# Medicine Assistant v2 — cutover and cleanup

`/medicines/assistant` serves v1 or v2 depending on one flag. The URL, the
authentication, the rate limit and the `answer` field are unchanged, so no
client needs touching either way.

## Enabling

```
USE_MEDICINE_ASSISTANT_V2=true
```

Run the migration report against the target database first. It asks both
implementations the same questions and refuses to bless the cutover if v2 loses
an answer v1 got right:

```
docker compose run --rm --no-deps api python -m scripts.medicine_assistant_migration_report
```

Last run against the seeded catalogue: **13 improvements, 10 wording changes,
0 regressions.**

## Rolling back

Set the flag to `false`. No redeploy, no migration, no data change — that is
the only reason the flag exists. v2 changes what the assistant *refuses*, and a
refusal firing too eagerly is a support problem that wants undoing in seconds
rather than in a release.

## What changes for a patient

Three kinds of difference, all deliberate:

**Substances resolve.** "What are the side effects of Cefixime?" returned
*"Sorry, I could not find information about that medicine"* under v1, because
no product is named Cefixime. v2 names the eleven products containing it and
asks which was meant — it does not pick one, because those eleven record six
different side-effect texts.

**Advice questions are refused.** v1 refused none of them. Asked *"Can I
combine Napa and Ace?"* it replied with a description of Napa, which reads as
an answer to the question that was asked. Asked *"I'm pregnant, can I use
this?"* it reported a lookup failure, which reads as an invitation to rephrase.

**Wording differs.** Same facts, different sentences, and a different
disclaimer.

## Cleanup, after one stable release cycle

Verified dependencies as of this commit. Check them again before deleting —
this list is a starting point, not a licence.

### Safe to delete once the flag goes

| Module | Only used by |
|---|---|
| `services/medicine_assistant_service.py` | the v1 branch of the route, and the migration report |
| `services/medicine_context_service.py` | `medicine_ai_service` |
| `services/medicine_prompt_service.py` | `medicine_ai_service` |

Also: the `USE_MEDICINE_ASSISTANT_V2` flag itself, `ENABLE_MEDICINE_AI`, the v1
tests, and `scripts/medicine_assistant_migration_report.py` — the report has
nothing to compare against once v1 is gone.

### Needs a decision first

**`services/medicine_ai_service.py`** is used by `api/routes/admin_medicine_ai.py`
as well as by v1. That admin route is not on the patient path and was not part
of this migration. Deleting the service breaks it. Port it to v2's tool layer
or remove the route deliberately — do not discover this during cleanup.

### Keep

| Module | Why |
|---|---|
| `services/medicine_matcher_service.py` | v2's matcher, plus generics, aliases and lookup |
| `services/medicine_ai_guardrail_service.py` | v2's second gate over model output |
| `services/medicine_ai_safety_service.py` | see below |
| `assistant/quota.py`, `integrations/openai_client.py` | shared with the scheduling assistant |

`medicine_ai_safety_service` holds the old keyword blocklist and is **called by
nothing in production**. It is referenced by one v2 test, which asserts that the
blocklist would refuse *"What dosage form is Ace?"* — a supported question —
and that v2's router does not. Deleting it removes the guard against someone
reintroducing that approach. Delete the module and the test together, or keep
both.

## What is never stored

Neither implementation can keep a question or a generated answer: the columns
do not exist. Recorded instead are the medicine matched, the intent, the
outcome, tokens and latency. A refused question records no medicine even when
one was named — otherwise the log would say which drug a pregnant patient asked
about.
