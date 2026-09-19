"""Document text extraction stage."""


def extract_text(inbox, attachment_path):
    """Read a text attachment through the loader's stable interface."""
    return inbox.read_text(attachment_path)