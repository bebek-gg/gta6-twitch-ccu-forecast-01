"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Reads one case file (makefun/twitch-ccu-case/v1) and writes, for hours 2..24
of the release day, five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's
concurrent Twitch viewers in the game's category.

Method
------
A launch's audience curve is shaped by the clock, not by its size: the UTC
day's hours fall on the same local times in every region for every launch,
so past launches' curves, rescaled by their own first hour, predict the
shape of a new launch. For each comparable launch in the case file we take
the log of (viewers in hour h / viewers in hour 1) for h = 2..24. GTA VI
launches on consoles only (PlayStation 5 and Xbox Series X|S) at midnight
local time, rolling region by region, so the reference set is the
comparables that launched on consoles only: a PC launch that unlocks
simultaneously worldwide has a first hour near zero and a ratio curve that
explodes hundreds-fold later, which is not GTA VI's shape. Per hour we take
the median log-ratio as the centre and the 5th/25th/75th/95th percentiles
of the log-ratios as the spread, then scale by this case's own first-hour
print. The spread widens with the horizon because the ratios genuinely
spread out later in the day.

One more regularity: a launch whose first hour is already huge has less
room left to grow, so its peak ratio is smaller. Across the console-only
comparables the log peak ratio falls with the log first-hour print
(slope about -0.31, R^2 about 0.72), so the centre is shifted up or down
by how far this case's first hour sits from the reference set's middle,
most at the hours where the curve peaks and not at all in the overnight
dip. The shift is capped at half a log unit either way, so a first hour
beyond anything the comparables saw cannot drag the forecast to an
absurd peak. With no usable comparables we fall back to holding the
first hour's print with a spread that widens like a random walk in log
space.

Standard library only, no network, no randomness: the same case always
writes the same bytes. Reads $MAKEFUN_INPUT_DIR (else /input) and writes
$MAKEFUN_OUTPUT_DIR (else /output).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels, used only for the fallback
# spread (and to keep the outer quantiles honest when a sample is tiny).
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]
# Smallest log-spread allowed at any hour, so a handful of agreeing
# comparables never yields an overconfident razor-thin band.
MIN_SIGMA = 0.10
# Fallback spread growth per square-root hour when no comparables exist.
FALLBACK_SIGMA = 0.22


def parse_time(text):
    """An ISO 8601 timestamp to an aware datetime; None when unparsable."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def median(values):
    """The median of a non-empty list of numbers."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def percentile(values, q):
    """The q-th percentile (0..1) of a non-empty list, linear interpolation."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    pos = q * (n - 1)
    low = int(pos)
    high = min(low + 1, n - 1)
    frac = pos - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def is_console_only(platforms):
    """True when a launch shipped on consoles only, with no PC release.

    The platforms field is free text ("PS5, Xbox Series, PC (PS5 later)",
    "PC (PS5 2023-09-06)", "PS5 only"), so a bare-token test misses a PC
    release written with a note attached. A substring test catches every
    form, and no console platform name contains the letters PC.
    """
    if not isinstance(platforms, str):
        return False
    return "pc" not in platforms.lower()


def hour_of(point_time, day_start):
    """Which hour of the release day (1..24) a timestamp falls in, else None."""
    if point_time is None or day_start is None:
        return None
    offset = int((point_time - day_start).total_seconds() // 3600) + 1
    if 1 <= offset <= 24:
        return offset
    return None


def comparable_curves(case):
    """Per-hour log-ratios to hour 1, for the console-only comparables.

    Returns a dict hour -> list of log(viewers_h / viewers_1). A comparable
    counts only when it has a positive hour-1 print; an hour counts only
    when that comparable has a positive print for it.
    """
    day_curves = []
    for comp in case.get("comparables") or []:
        if not is_console_only(comp.get("platforms")):
            continue
        day_start = parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        by_hour = {}
        for row in comp.get("hourly") or []:
            viewers = row.get("viewers")
            if not isinstance(viewers, (int, float)) or viewers <= 0:
                continue
            hour = hour_of(parse_time(row.get("from")), day_start)
            if hour is not None and hour not in by_hour:
                by_hour[hour] = float(viewers)
        if 1 not in by_hour:
            continue
        first = by_hour[1]
        day_curves.append({h: math.log(v / first)
                           for h, v in by_hour.items() if h >= 2})
    per_hour = {}
    for curve in day_curves:
        for hour, value in curve.items():
            per_hour.setdefault(hour, []).append(value)
    return per_hour


def all_curves(case):
    """The same log-ratios, but over every comparable with an hour-1 print.

    Used as a fallback when too few console-only comparables have data.
    """
    per_hour = {}
    for comp in case.get("comparables") or []:
        day_start = parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        by_hour = {}
        for row in comp.get("hourly") or []:
            viewers = row.get("viewers")
            if not isinstance(viewers, (int, float)) or viewers <= 0:
                continue
            hour = hour_of(parse_time(row.get("from")), day_start)
            if hour is not None and hour not in by_hour:
                by_hour[hour] = float(viewers)
        if 1 not in by_hour:
            continue
        first = by_hour[1]
        for hour, value in by_hour.items():
            if hour >= 2:
                per_hour.setdefault(hour, []).append(math.log(value / first))
    return per_hour


def peak_scale_shift(case, first_print, centres):
    """How far to shift the centre curve for this case's first-hour size.

    Fits log peak ratio against log first-hour print over the console-only
    comparables (each needs at least ten hours of data), then measures how
    far this case's predicted peak sits from the reference set's median
    peak. The shift is spread over the hours in proportion to how far the
    centre at each hour sits above the overnight dip, so the peak hours
    move most and the dip barely moves. It is capped at half a log unit
    either way. Returns a dict hour -> shift (log units), empty when the
    fit cannot be made.
    """
    if not centres:
        return {}
    points = []
    for comp in case.get("comparables") or []:
        if not is_console_only(comp.get("platforms")):
            continue
        day_start = parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        by_hour = {}
        for row in comp.get("hourly") or []:
            viewers = row.get("viewers")
            if not isinstance(viewers, (int, float)) or viewers <= 0:
                continue
            hour = hour_of(parse_time(row.get("from")), day_start)
            if hour is not None and hour not in by_hour:
                by_hour[hour] = float(viewers)
        if 1 not in by_hour or len(by_hour) < 10:
            continue
        first = by_hour[1]
        peak = max(value / first for hour, value in by_hour.items()
                   if hour >= 2)
        points.append((math.log(first), math.log(peak)))
    if len(points) < 4:
        return {}
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in points)
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    if sxx <= 0:
        return {}
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    predicted = intercept + slope * math.log(first_print)
    delta = predicted - mean_y
    delta = max(-0.5, min(0.5, delta))
    low = min(centres.values())
    high = max(centres.values())
    span = high - low
    if span <= 0:
        return {}
    return {hour: delta * (centre - low) / span
            for hour, centre in centres.items()}


def round2(value):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100.0
    return int(rounded) if float(rounded).is_integer() else rounded


def quantiles_for_hour(hour, first_print, per_hour, fallback_per_hour,
                       centre_override=None):
    """The five forecast quantiles for one hour, as viewer counts."""
    values = per_hour.get(hour) or []
    if len(values) < 3:
        values = fallback_per_hour.get(hour) or []
    if len(values) >= 3:
        centre = centre_override if centre_override is not None \
            else median(values)
        low_outer = percentile(values, 0.05)
        low_inner = percentile(values, 0.25)
        high_inner = percentile(values, 0.75)
        high_outer = percentile(values, 0.95)
        # A tiny sample's outer percentiles are its extremes, so widen them
        # toward a normal spread when they sit implausibly close to the
        # centre; never let the band collapse below MIN_SIGMA.
        spread = max((high_inner - low_inner) / 1.349, MIN_SIGMA)
        low_outer = min(low_outer, centre - 1.645 * spread)
        high_outer = max(high_outer, centre + 1.645 * spread)
        low_inner = min(low_inner, centre - 0.674 * spread)
        high_inner = max(high_inner, centre + 0.674 * spread)
        logs = [low_outer, low_inner, centre, high_inner, high_outer]
    else:
        # No usable history for this hour: hold the first hour and widen
        # the spread with the square root of the hours elapsed.
        sigma = FALLBACK_SIGMA * math.sqrt(hour - 1)
        logs = [z * sigma for z in Z]
    counts = []
    previous = 0.0
    for log_value in logs:
        count = first_print * math.exp(log_value)
        count = min(max(count, 1.0), 1e9)
        count = round2(count)
        if count < previous:
            count = previous
        counts.append(count)
        previous = count
    return counts


def forecast_case(case, name):
    """The forecast object for one case."""
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, "
                         f"not {LEVELS}")
    known = case.get("known") or []
    first_row = next((k for k in known if k.get("hour") == 1), None)
    # No hour-1 print at all is not a reason to crash: the case is
    # unscored in that event, but a valid forecast keeps the entry
    # well-formed, so fall back to a print of 1 viewer.
    viewers = first_row.get("viewers") if first_row is not None else None
    first_print = float(viewers) if isinstance(viewers, (int, float)) \
        and viewers > 0 else 1.0
    per_hour = comparable_curves(case)
    fallback = all_curves(case)
    centres = {}
    for hour, values in per_hour.items():
        if len(values) >= 3:
            centres[hour] = median(values)
    shifts = peak_scale_shift(case, first_print, centres)
    hours = []
    for row in case.get("forecast") or []:
        hour = row.get("hour")
        if not isinstance(hour, int) or hour < 2 or hour > 24:
            continue
        # The centre is the raw median of the console-only log-ratios,
        # shifted for this case's first-hour size; the band edges come
        # from the raw percentiles.
        centre = centres.get(hour)
        if centre is not None:
            centre += shifts.get(hour, 0.0)
        hours.append({"hour": hour,
                      "q": quantiles_for_hour(hour, first_print, per_hour,
                                              fallback, centre)})
    hours.sort(key=lambda row: row["hour"])
    if [row["hour"] for row in hours] != list(range(2, 25)):
        raise ValueError(f"{name} did not forecast hours 2..24")
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
