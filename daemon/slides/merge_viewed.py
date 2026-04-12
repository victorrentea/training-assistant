"""Merge incoming slides_viewed deltas into the accumulated list."""


def merge_slides_viewed(
    existing: list[dict],
    incoming: list[dict],
) -> None:
    """Merge incoming delta entries into existing list, in place.

    For each incoming entry:
      - If (file_name, page) exists in existing, add seconds to it.
      - Otherwise, append a new entry (preserving insertion order).

    Args:
        existing: The current slides_viewed list (mutated in place).
        incoming: Delta entries with keys: fileName, page, seconds.
    """
    index: dict[tuple[str, int], int] = {}
    for i, sv in enumerate(existing):
        key = (sv["file_name"], sv["page"])
        index[key] = i

    for entry in incoming:
        file_name = entry.get("fileName", "")
        page = entry.get("page", 0)
        seconds = entry.get("seconds", 0)
        if not file_name or not page or seconds <= 0:
            continue
        key = (file_name, page)
        if key in index:
            existing[index[key]]["seconds"] += seconds
        else:
            index[key] = len(existing)
            existing.append({"file_name": file_name, "page": page, "seconds": seconds})
