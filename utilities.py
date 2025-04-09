import random


def sample_practitioner_work_schedule(schedule_type=None):
    """Return a realistic weekly work schedule as a dict of daily time blocks."""

    full_time = {
        0: [(9 * 60, 17 * 60)],
        1: [(9 * 60, 17 * 60)],
        2: [(9 * 60, 17 * 60)],
        3: [(9 * 60, 17 * 60)],
        4: [(9 * 60, 17 * 60)],
    }

    evening_shift = {
        0: [(14 * 60, 22 * 60)],
        1: [(14 * 60, 22 * 60)],
        2: [(14 * 60, 22 * 60)],
        3: [(14 * 60, 22 * 60)],
        4: [(14 * 60, 22 * 60)],
    }

    split_shift = {
        0: [(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
        1: [(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
        2: [(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
        3: [(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
        4: [(9 * 60, 12 * 60), (14 * 60, 18 * 60)],
    }

    part_time = {
        1: [(8 * 60, 12 * 60)],  # Tuesday
        3: [(8 * 60, 12 * 60)],  # Thursday
        5: [(8 * 60, 12 * 60)],  # Saturday
    }

    weekend_only = {
        5: [(10 * 60, 16 * 60)],  # Saturday
        6: [(10 * 60, 16 * 60)],  # Sunday
    }

    rotating_24_7 = {}
    for day in range(7):
        shift = random.choice(
            [
                (0, 8 * 60),  # Midnight to 8am
                (8 * 60, 16 * 60),  # 8am to 4pm
                (16 * 60, 24 * 60),  # 4pm to Midnight
            ]
        )
        rotating_24_7[day] = [shift]

    schedules = {
        "full_time": full_time,
        "evening": evening_shift,
        "split": split_shift,
        "part_time": part_time,
        "weekend": weekend_only,
        "rotating": rotating_24_7,
    }

    if schedule_type is None:
        schedule_type = random.choice(list(schedules.keys()))

    return schedules[schedule_type]
