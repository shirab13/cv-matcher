from datetime import datetime

CUTOFF_YY = 24  # 00-24 -> 2000-2024, אחרת 1900-1999

def current_year() -> int:
    return datetime.now().year

def yy_to_yyyy(yy: str, cutoff: int = CUTOFF_YY) -> int:
    n = int(yy)
    return int(f"20{n:02d}") if n <= cutoff else int(f"19{n:02d}")
