"""The medicine assistant's read-only view of the catalogue.

Explains medicines that already exist in the database. It is not a symptom
checker, not a diagnosis tool and not a source of treatment or dosage advice —
questions of that kind are refused before anything is looked up.

Structured like app/assistant: a pure router decides what was asked, tools
answer it from the database, and a language model, if enabled at all, only
turns the result into a sentence.
"""
