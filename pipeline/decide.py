"""Submission decision stage."""


def decide(category, comparison=None):
    result = {"category": category}
    if comparison is not None:
        result.update(comparison)
    return result