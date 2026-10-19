from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

TIMEZONE = ZoneInfo("Europe/London")


def parse_calendar(text):
    return icalendar.Calendar.from_ical(text)


def to_local(value):
    # all-day events come through as plain dates: skip them
    if not isinstance(value, datetime):
        return None
    # floating times (no tz) are assumed to be local
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    return value.astimezone(TIMEZONE)


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def get_busy(cal, now):
    day_start = datetime.combine(now.date(), time(0, 0), TIMEZONE)
    day_end = day_start + timedelta(days=1)
    busy = []
    for event in recurring_ical_events.of(cal).between(day_start, day_end):
        if event.get("TRANSP") == "TRANSPARENT":
            continue
        if event.get("STATUS") == "CANCELLED":
            continue
        start = to_local(event.start)
        end = to_local(event.end)
        if start is None or end is None:
            continue
        busy.append((start, end))
    return merge_intervals(busy)


def free_status(busy, now):
    # until is None when nothing else is booked for the rest of the day
    for start, end in busy:
        if start <= now < end:
            return "busy", end
        if start > now:
            return "free", start
    return "free", None
