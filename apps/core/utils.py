def format_minutes(total):
    """90 -> '1 h 30 min', 120 -> '2 h', 15 -> '15 min'."""
    total = int(total or 0)
    if total < 60:
        return f"{total} min"
    hours, minutes = divmod(total, 60)
    return f"{hours} h" if not minutes else f"{hours} h {minutes} min"