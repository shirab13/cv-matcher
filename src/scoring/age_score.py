from typing import Optional, Tuple, Dict

AGE_PENALTY_FACTOR = 0.90  # הורדה של 10%

def apply_age_penalty(base_score: float, age: Optional[int]) -> Tuple[float, Dict]:
    detail = {
        "age_found": age is not None,
        "age_value": age,
        "penalized": False,
        "factor": 1.0,
        "delta": 0.0,
    }
    if age is None:
        return base_score, detail

    if age > 50:
        new_score = base_score * AGE_PENALTY_FACTOR
        detail.update({
            "penalized": True,
            "factor": AGE_PENALTY_FACTOR,
            "delta": new_score - base_score
        })
        return new_score, detail

    return base_score, detail
