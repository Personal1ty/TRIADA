from typing import Union


def clamp(value: int, lower: int, upper: int) -> int:
    if lower > upper:
        raise ValueError(f"lower bound ({lower}) cannot be greater than upper bound ({upper})")
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
