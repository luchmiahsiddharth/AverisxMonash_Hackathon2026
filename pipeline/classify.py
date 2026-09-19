"""Email classification stage."""

CATEGORIES = {
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM",
}


def classify(email):
    """Return the category for an email, defaulting to GENERAL."""
    return "GENERAL"