"""
Very simple, keyword-based department classifier for complaints.

The logic is intentionally minimal and deterministic so that
an RPA bot can easily rely on it.
"""


def classify_department(subject: str) -> str:
    """
    Classify a complaint into a department based on keywords in the subject.

    If no keyword matches, falls back to "General Department".
    """
    text = (subject or "").lower()

    # Public Works
    if "pothole" in text:
        return "Public Works"
    if "road" in text:
        return "Public Works"

    # Sanitation
    if "garbage" in text:
        return "Sanitation"
    if "trash" in text:
        return "Sanitation"

    # Water Department
    if "water" in text:
        return "Water Department"
    if "leak" in text:
        return "Water Department"

    # Electricity
    if "street light" in text:
        return "Electricity"

    return "General Department"

