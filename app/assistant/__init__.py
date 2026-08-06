"""The scheduling assistant's read-only view of the backend.

Everything the assistant can learn passes through this package. It contains no
prompts, no model calls and no routing — only functions that take a resolved
clinic and return structured data.

The boundary is the point. The language model never reaches a repository, a
session or a query: it is handed the output of these functions and asked to
phrase it. Anything it cannot get from here, it cannot say.
"""
