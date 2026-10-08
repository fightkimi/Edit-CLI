from __future__ import annotations


def progress(time_us: int, duration_us: int, enter_us: int, exit_us: int) -> float:
    enter = 1.0 if not enter_us else 1 - (1 - max(0.0, min(1.0, time_us / enter_us))) ** 3
    leave = 1.0 if not exit_us else max(0.0, min(1.0, (duration_us - time_us) / exit_us)) ** 3
    return min(enter, leave)
