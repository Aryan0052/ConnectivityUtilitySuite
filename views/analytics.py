"""Analytics engine for the neon Dashboard (no Qt in this file).

Everything the Dashboard shows is computed here from plain readings:

  * analog (AI) statistics, anomaly tags, limit breaches, forecast / ETA,
  * digital (DI / DO) toggle, duty-cycle, chatter and feedback analysis,
  * communication analytics (latency percentiles, success heat-map, bus load),
  * automatic insight / report text,
  * CSV import and export of a time period.

A "doc" is the same shape as a MongoDB reading document, so live data, database
history and imported CSV files all go through exactly the same analysis:

    {"timestamp": datetime, "channels": {"AI1": {"value": 4.2, "unit": "mA"}}, "quality": "GOOD"}

All adjustable thresholds are in THRESHOLDS (one place).
"""
import csv
import math
import re
from bisect import bisect_left
from collections import deque
from datetime import datetime, timedelta

# --------------------------------------------------------------------------- thresholds
THRESHOLDS = {
    "stuck_eps": 1e-3,            # AI: max-min below this (over >= stuck_min_samples) = STUCK
    "stuck_min_samples": 20,
    "stuck_min_s": 60,            # ...and flat for at least this many seconds
    "spike_k": 6.0,               # AI: |residual| > k * robust sigma = spike
    "spike_min_frac": 0.02,       # ...and at least this fraction of the value range
    "drift_sigma": 4.0,           # AI: fitted change > k * residual sigma = drift
    "drift_min_pct": 2.0,         # ...and at least this % of |mean|
    "noise_ratio": 2.0,           # AI: noise(2nd half) / noise(1st half) = NOISY
    "noise_pct": 3.0,             # AI: noise sigma above this % of |mean| = NOISY
    "chatter_per_min": 30,        # DI: toggles inside any 60 s window = CHATTER
    "hunt_per_10min": 20,         # DO: switches inside any 10 min window = HUNTING
    "idle_min_s": 600,            # DI/DO: no change for this long (whole period) = STUCK / IDLE
    "gap_factor": 5.0,            # a sample gap longer than this x median interval is a gap
    "feedback_window_s": 3.0,     # DO -> DI feedback must follow within this time
    "forecast_tail_s": 300,       # regression window used for the limit forecast
    "forecast_max_s": 86400,      # ignore forecasts further away than this
    "comm_bucket_s": 300,         # reliability heat-map bucket size
    "bus_window_s": 10.0,         # bus-load averaging window
}

TAG_ORDER = ("STUCK", "SPIKE", "DRIFT", "NOISY", "STABLE")
MAX_SEGMENTS = 4000


# --------------------------------------------------------------------------- small helpers
def median(values):
    s = sorted(values)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mean_std(values):
    n = len(values)
    if not n:
        return 0.0, 0.0
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    return m, math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def percentile(values, p):
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def linreg(ts, vals):
    """(slope per second, intercept at ts[0], residual std). Needs >= 2 points."""
    n = len(ts)
    if n < 2:
        return 0.0, vals[0] if vals else 0.0, 0.0
    t0 = ts[0]
    x = [t - t0 for t in ts]
    mx, my = sum(x) / n, sum(vals) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return 0.0, my, 0.0
    slope = sum((a - mx) * (b - my) for a, b in zip(x, vals)) / sxx
    intercept = my - slope * mx
    res = [b - (intercept + slope * a) for a, b in zip(x, vals)]
    return slope, intercept, math.sqrt(sum(r * r for r in res) / max(1, n - 2))


def fmt_duration(seconds):
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        m, r = divmod(s, 60)
        return f"{m} min {r} s" if r else f"{m} min"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h} h {m:02d} m" if m else f"{h} h"


def fmt_short_duration(seconds):
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} m {s % 60:02d} s" if s % 60 else f"{s // 60} m"
    return f"{s // 3600} h {s % 3600 // 60:02d} m"


def fmt_num(value, digits=2):
    return "--" if value is None else f"{value:.{digits}f}"


def fmt_rate(per_min):
    """'+0.80/min' or '+1.2/h' depending on size."""
    if per_min is None:
        return "--"
    if abs(per_min) >= 0.05:
        return f"{per_min:+.2f}/min"
    per_h = per_min * 60
    if abs(per_h) < 0.005:
        return "0.0/h"
    return f"{per_h:+.2f}/h"


def channel_number(name):
    m = re.search(r"(\d+)\s*$", str(name))
    return int(m.group(1)) if m else 0


def sort_channels(names):
    return sorted(names, key=lambda n: (re.sub(r"\d+\s*$", "", n), channel_number(n), n))


def to_epoch(dt):
    return dt.timestamp() if isinstance(dt, datetime) else float(dt)


# --------------------------------------------------------------------------- docs -> series
def docs_to_series(docs):
    """{channel: (ts[], vals[], unit)} from reading documents (None values skipped)."""
    out = {}
    units = {}
    for doc in docs:
        t = to_epoch(doc["timestamp"])
        for name, entry in doc.get("channels", {}).items():
            v = entry.get("value") if isinstance(entry, dict) else entry
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v != v or v in (math.inf, -math.inf):
                continue
            ts, vals = out.setdefault(name, ([], []))
            ts.append(t)
            vals.append(v)
            if isinstance(entry, dict) and entry.get("unit"):
                units[name] = entry["unit"]
    return {name: (ts, vals, units.get(name, "")) for name, (ts, vals) in
            ((n, out[n]) for n in sort_channels(out))}


def sample_info(docs):
    """(n, start, end, median interval s, coverage %, missed polls)."""
    n = len(docs)
    if not n:
        return 0, None, None, 0.0, 0.0, 0
    ts = [to_epoch(d["timestamp"]) for d in docs]
    start, end = docs[0]["timestamp"], docs[-1]["timestamp"]
    if n < 3:
        return n, start, end, 0.0, 100.0, 0
    dts = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    dt = median(dts) if dts else 0.0
    if dt <= 0:
        return n, start, end, 0.0, 100.0, 0
    expected = (ts[-1] - ts[0]) / dt + 1
    coverage = min(100.0, 100.0 * n / expected)
    return n, start, end, dt, coverage, max(0, int(round(expected - n)))


# --------------------------------------------------------------------------- analog analysis
def analyze_channel(name, ts, vals, unit="", limit=None, th=None, recent_s=None):
    th = th or THRESHOLDS
    n = len(vals)
    stat = {"name": name, "unit": unit, "n": n, "tag": "NO DATA", "score": 0, "last": None, "min": None,
            "max": None, "mean": None, "std": 0.0, "noise": 0.0, "slope_min": 0.0, "change": 0.0,
            "spikes": 0, "spike_t": None, "spike_v": None, "breaches": 0, "alarm_s": 0.0, "ttl_s": None,
            "ttl_kind": "", "ttl_slope_min": 0.0, "limit": limit if (limit and limit.get("enabled")) else None, "in_alarm": False,
            "drift_since": None, "noise_ratio": 1.0, "span_s": 0.0}
    if n == 0:
        return stat
    mean, std = mean_std(vals)
    lo, hi = min(vals), max(vals)
    stat.update(last=vals[-1], min=lo, max=hi, mean=mean, std=std, span_s=ts[-1] - ts[0])
    if n < 3:
        stat["tag"], stat["score"] = "WAIT", 100
        return stat
    dts = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    gap_max = (median(dts) if dts else 1.0) * th["gap_factor"]

    # trend over the whole window
    slope, _, res_std = linreg(ts, vals)
    stat["slope_min"] = slope * 60.0
    stat["change"] = slope * (ts[-1] - ts[0])

    # noise: std of first differences / sqrt(2), compared between window halves
    dv = [b - a for a, b in zip(vals, vals[1:])]
    half = len(dv) // 2
    stat["noise"] = mean_std(dv)[1] / math.sqrt(2)
    n1 = mean_std(dv[:half])[1] / math.sqrt(2) if half >= 4 else 0.0
    n2 = mean_std(dv[half:])[1] / math.sqrt(2) if len(dv) - half >= 4 else 0.0
    stat["noise_ratio"] = (n2 / n1) if n1 > 1e-12 else (1.0 if n2 <= 1e-12 else 99.0)

    # spikes: residual against the average of both neighbours, isolated local maxima only
    spikes = 0
    rng = hi - lo
    if n >= 7 and rng > 0:
        e = [vals[i] - (vals[i - 1] + vals[i + 1]) / 2.0 for i in range(1, n - 1)]
        chunks = max(1, min(4, len(e) // 25))          # judge each point against its own part of the window
        size = int(math.ceil(len(e) / chunks))
        cuts = []
        for c in range(chunks):
            part = e[c * size:(c + 1) * size]
            med = median(part)
            sigma = max(1.4826 * median([abs(x - med) for x in part]), 1e-12)
            cuts.append((med, max(th["spike_k"] * sigma, th["spike_min_frac"] * rng)))
        t_cut = (ts[-1] - recent_s) if recent_s else None
        for i, x in enumerate(e):
            med, cut = cuts[min(chunks - 1, i // size)]
            a = abs(x - med)
            if a <= cut:
                continue
            if (i > 0 and abs(e[i - 1] - med) > a) or (i + 1 < len(e) and abs(e[i + 1] - med) > a):
                continue
            # a real spike is isolated: several large residuals around it mean a noise burst instead
            far = sum(1 for j in (i - 3, i - 2, i + 2, i + 3)
                      if 0 <= j < len(e) and abs(e[j] - med) > 0.5 * cut)
            if far >= 2:
                continue
            if t_cut is not None and ts[i + 1] < t_cut:
                continue
            spikes += 1
            stat["spike_t"], stat["spike_v"] = ts[i + 1], vals[i + 1]
    stat["spikes"] = spikes

    # limits
    if stat["limit"]:
        high, low = stat["limit"]["high"], stat["limit"]["low"]
        out_prev = False
        for i, v in enumerate(vals):
            out = v > high or v < low
            if out and not out_prev:
                stat["breaches"] += 1
            if out and i + 1 < n:
                stat["alarm_s"] += min(ts[i + 1] - ts[i], gap_max)
            out_prev = out
        stat["in_alarm"] = out_prev
        # time to limit from the tail regression
        tail_from = ts[-1] - th["forecast_tail_s"]
        k = bisect_left(ts, tail_from)
        if len(ts) - k >= 8:
            ts_slope = linreg(ts[k:], vals[k:])[0]
            last = vals[-1]
            stat["ttl_slope_min"] = ts_slope * 60.0
            if ts_slope > 1e-12 and last < high:
                stat["ttl_s"], stat["ttl_kind"] = (high - last) / ts_slope, "HIGH"
            elif ts_slope < -1e-12 and last > low:
                stat["ttl_s"], stat["ttl_kind"] = (last - low) / -ts_slope, "LOW"
            if stat["ttl_s"] is not None and stat["ttl_s"] > th["forecast_max_s"]:
                stat["ttl_s"], stat["ttl_kind"] = None, ""

    # tag
    mean_abs = max(abs(mean), 1e-9)
    if n >= th["stuck_min_samples"] and rng <= th["stuck_eps"] and (ts[-1] - ts[0]) >= th["stuck_min_s"]:
        tag = "STUCK"
    elif spikes >= 1:
        tag = "SPIKE"
    elif (abs(stat["change"]) > th["drift_sigma"] * max(res_std, 1e-12)
          and abs(stat["change"]) > th["drift_min_pct"] / 100.0 * mean_abs):
        tag = "DRIFT"
        stat["drift_since"] = ts[0]
    elif (stat["noise_ratio"] >= th["noise_ratio"] and stat["noise"] > 0.002 * mean_abs) or \
            (stat["noise"] / mean_abs * 100.0 >= th["noise_pct"]):
        tag = "NOISY"
    else:
        tag = "STABLE"
    stat["tag"] = tag
    score = 100 - {"STUCK": 70, "SPIKE": 35, "DRIFT": 20, "NOISY": 30}.get(tag, 0)
    if stat["in_alarm"]:
        score -= 25
    if stat["ttl_s"] is not None and stat["ttl_s"] < 600:
        score -= 15
    stat["score"] = max(0, min(100, int(score)))
    return stat


def analyze_analog(docs, limit_for=None, th=None, recent_s=None):
    """Statistics for every channel of an analog device over `docs`."""
    th = th or THRESHOLDS
    n, start, end, dt, coverage, missed = sample_info(docs)
    series = docs_to_series(docs)
    channels = []
    for name, (ts, vals, unit) in series.items():
        limit = limit_for(name) if limit_for else None
        channels.append(analyze_channel(name, ts, vals, unit, limit, th, recent_s))
    good = sum(1 for d in docs if str(d.get("quality", "GOOD")).upper() == "GOOD")
    scores = [c["score"] for c in channels if c["tag"] not in ("NO DATA", "WAIT")]
    return {
        "kind": "AI", "n": n, "start": start, "end": end, "dt": dt, "coverage": coverage, "missed": missed,
        "duration_s": (to_epoch(end) - to_epoch(start)) if n else 0.0, "channels": channels, "series": series,
        "quality_pct": (100.0 * good / n) if n else 100.0,
        "signal_score": int(round(sum(scores) / len(scores))) if scores else 100,
        "anomalies": sum(1 for c in channels if c["tag"] in TAG_ORDER[:4]),
        "breaches": sum(c["breaches"] for c in channels),
        "alarm_s": sum(c["alarm_s"] for c in channels),
    }


def histogram(values, bins=15):
    """(edges, counts, mean, std) for a list of values."""
    if not values:
        return [], [], 0.0, 0.0
    lo, hi = min(values), max(values)
    mean, std = mean_std(values)
    if hi - lo < 1e-12:
        return [lo - 0.5, lo + 0.5], [len(values)], mean, std
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / width))] += 1
    return [lo + i * width for i in range(bins + 1)], counts, mean, std


def forecast_line(ts, vals, tail_s, horizon_s, points=40):
    """[(t, v)] regression-line projection over the next horizon_s seconds, or []."""
    if len(ts) < 8:
        return []
    k = bisect_left(ts, ts[-1] - tail_s)
    if len(ts) - k < 8:
        k = max(0, len(ts) - 8)
    slope, intercept, _ = linreg(ts[k:], vals[k:])
    base_t = ts[k]
    return [(ts[-1] + horizon_s * i / points,
             intercept + slope * (ts[-1] + horizon_s * i / points - base_t)) for i in range(points + 1)]


def moving_average(vals, k):
    out, acc = [], 0.0
    q = deque()
    for v in vals:
        q.append(v)
        acc += v
        if len(q) > k:
            acc -= q.popleft()
        out.append(acc / len(q))
    return out


# --------------------------------------------------------------------------- digital analysis
def _runs(ts, vals, gap_max):
    """Lists of (t_start, t_end, state) from samples, holding each state until the next sample."""
    segs = []
    if not ts:
        return segs
    cur_state, cur_start = vals[0], ts[0]
    for i in range(1, len(ts)):
        gap = ts[i] - ts[i - 1] > gap_max
        if vals[i] != cur_state or gap:
            end = ts[i - 1] if gap else ts[i]
            segs.append((cur_start, end, cur_state))
            cur_state, cur_start = vals[i], ts[i]
    segs.append((cur_start, ts[-1], cur_state))
    return segs


def _max_in_window(times, window):
    best, j = 0, 0
    for i, t in enumerate(times):
        while t - times[j] > window:
            j += 1
        best = max(best, i - j + 1)
    return best


def analyze_digital(docs, kind="DI", th=None):
    th = th or THRESHOLDS
    n, start, end, dt, coverage, missed = sample_info(docs)
    series = docs_to_series(docs)
    gap_max = max(dt * th["gap_factor"], 1.0) if dt else 1.0
    channels = []
    for name, (ts, raw, _unit) in series.items():
        vals = [1 if v else 0 for v in raw]
        changes = [(ts[i], vals[i]) for i in range(1, len(vals)) if vals[i] != vals[i - 1]]
        segs = _runs(ts, vals, gap_max)
        covered = sum(b - a for a, b, _ in segs)
        on_time = sum(b - a for a, b, s in segs if s)
        # a held state lasts until the next change sample, so bridge segment ends
        longest_on = longest_off = 0.0
        run_start, run_state = ts[0], vals[0]
        for t, v in changes:
            span = t - run_start
            if run_state:
                longest_on = max(longest_on, span)
            else:
                longest_off = max(longest_off, span)
            run_start, run_state = t, v
        span = ts[-1] - run_start
        if run_state:
            longest_on = max(longest_on, span)
        else:
            longest_off = max(longest_off, span)
        toggles = len(changes)
        times = [t for t, _ in changes]
        max_min = _max_in_window(times, 60.0)
        max_10 = _max_in_window(times, 600.0)
        span_total = ts[-1] - ts[0]
        if kind == "DI" and max_min >= th["chatter_per_min"]:
            tag = "CHATTER"
        elif kind == "DO" and max_10 >= th["hunt_per_10min"]:
            tag = "HUNTING"
        elif toggles == 0 and span_total >= th["idle_min_s"]:
            tag = "STUCK" if kind == "DI" else "IDLE"
        else:
            tag = "STABLE"
        channels.append({
            "name": name, "n": len(ts), "state": vals[-1], "toggles": toggles, "on_time": on_time,
            "duty": (100.0 * on_time / covered) if covered > 0 else (100.0 if vals[-1] else 0.0),
            "longest_on": longest_on, "longest_off": longest_off,
            "last_change": datetime.fromtimestamp(times[-1]) if times else None,
            "max_per_min": max_min, "max_per_10min": max_10, "tag": tag,
            "segments": segs[-MAX_SEGMENTS:], "changes": changes,
        })
    total = sum(c["toggles"] for c in channels)
    busiest = max(channels, key=lambda c: c["toggles"]) if channels else None
    longest = max(channels, key=lambda c: c["longest_on"]) if channels else None
    return {
        "kind": kind, "n": n, "start": start, "end": end, "dt": dt, "coverage": coverage, "missed": missed,
        "duration_s": (to_epoch(end) - to_epoch(start)) if n else 0.0, "channels": channels,
        "total_toggles": total,
        "busiest": (busiest["name"], busiest["toggles"], (100.0 * busiest["toggles"] / total) if total else 0.0)
        if busiest and busiest["toggles"] else None,
        "longest_on": (longest["name"], longest["longest_on"]) if longest and longest["longest_on"] > 0 else None,
        "chatter": sum(1 for c in channels if c["tag"] in ("CHATTER", "HUNTING")),
        "idle": sum(1 for c in channels if c["tag"] in ("STUCK", "IDLE")),
        "cycles": sum(c["toggles"] // 2 for c in channels),
        "anomalies": sum(1 for c in channels if c["tag"] != "STABLE"),
        "breaches": 0, "alarm_s": 0.0,
    }


def feedback_check(do_result, di_result, th=None):
    """DO -> DI feedback: did DIn follow DOn within the window? Rows per DO channel that switched."""
    th = th or THRESHOLDS
    di_by_num = {channel_number(c["name"]): c for c in di_result["channels"]}
    rows = []
    for ch in do_result["channels"]:
        if not ch["changes"]:
            continue
        di = di_by_num.get(channel_number(ch["name"]))
        if di is None:
            continue
        di_times = [t for t, _ in di["changes"]]
        sent = confirmed = 0
        delays = []
        for t, state in ch["changes"]:
            sent += 1
            i = bisect_left(di_times, t - 0.5)
            while i < len(di_times) and di_times[i] <= t + th["feedback_window_s"]:
                if di["changes"][i][1] == state:
                    confirmed += 1
                    delays.append(max(0.0, di_times[i] - t))
                    break
                i += 1
        rows.append({"do": ch["name"], "di": di["name"], "sent": sent, "confirmed": confirmed,
                     "delay_ms": (1000.0 * sum(delays) / len(delays)) if delays else None})
    return rows


# --------------------------------------------------------------------------- insights / report
SEV_COLORS = {"red": "#FF3D6E", "amber": "#FFB020", "violet": "#B26BFF", "blue": "#22D3FF", "green": "#39FF88"}


def _insight(sev, color, icon, text, ts=None):
    return {"sev": sev, "color": color, "icon": icon, "text": text, "ts": ts}


def analog_insights(result, live=False, name=""):
    out = []
    for c in result["channels"]:
        n, u = c["name"], (" " + c["unit"] if c["unit"] else "")
        lim = c["limit"]
        if c["ttl_s"] is not None and c["ttl_s"] <= (1800 if live else 7200):
            edge = lim["high"] if c["ttl_kind"] == "HIGH" else lim["low"]
            out.append(_insight("FORECAST", "red", "!",
                                f"{n} will reach {c['ttl_kind']} limit {edge:g}{u} in about "
                                f"<b>{fmt_duration(c['ttl_s'])}</b> (slope {fmt_rate(c['ttl_slope_min'])})"))
        if c["breaches"]:
            out.append(_insight("LIMIT", "red", "▲",
                                f"{n} breached its limit <b>{c['breaches']} time{'s' if c['breaches'] != 1 else ''}</b>, "
                                f"{fmt_duration(c['alarm_s'])} outside {lim['low']:g}–{lim['high']:g}{u}"))
        if c["tag"] == "STUCK":
            out.append(_insight("STUCK", "red", "=",
                                f"{n} has been flat at {c['last']:.3g}{u} for <b>{fmt_duration(c['span_s'])}</b> "
                                f"(stuck or disconnected input?)"))
        elif c["tag"] == "SPIKE" and c["spike_t"]:
            out.append(_insight("SPIKE", "red", "⚡",
                                f"{n} spike to {c['spike_v']:.3g}{u} at "
                                f"{datetime.fromtimestamp(c['spike_t']):%H:%M:%S} ({c['spikes']} in window)"))
        elif c["tag"] == "NOISY":
            out.append(_insight("NOISE", "amber", "~",
                                f"{n} noise is σ {c['noise']:.3g}{u} ({c['noise_ratio']:.1f}× the first half of the "
                                f"window). Check wiring or shielding"))
        elif c["tag"] == "DRIFT":
            per_h = c["slope_min"] * 60
            out.append(_insight("DRIFT", "violet", "↗",
                                f"{n} is drifting <b>{per_h:+.2f}{u}/h</b> since "
                                f"{datetime.fromtimestamp(c['drift_since']):%H:%M}"))
    if result["n"] and result["coverage"] < 98.0 and result["missed"] > 0:
        out.append(_insight("COMMS", "blue", "⚡",
                            f"{result['missed']} missed polls in this period (coverage {result['coverage']:.1f} %)"))
    if not out:
        out.append(_insight("OK", "green", "✓", "All channels are stable. No anomalies detected in this period."))
    order = {"red": 0, "amber": 1, "violet": 2, "blue": 3, "green": 4}
    out.sort(key=lambda i: order[i["color"]])
    return out


def digital_insights(result, feedback=None, live=False):
    out = []
    kind = result["kind"]
    span = max(result["duration_s"], 1.0)
    for c in result["channels"]:
        if c["tag"] == "CHATTER":
            out.append(_insight("CHATTER", "amber", "~",
                                f"{c['name']} toggled <b>{c['toggles']} times</b> (up to {c['max_per_min']} per minute). "
                                f"Possible contact bounce or noisy wiring"))
        elif c["tag"] == "HUNTING":
            out.append(_insight("HUNTING", "amber", "↻",
                                f"{c['name']} switched <b>{c['toggles']} times</b> in {fmt_duration(span)} (hunting). "
                                f"Check the control loop and relay wear"))
        elif c["tag"] == "STUCK":
            out.append(_insight("STUCK", "red", "=",
                                f"{c['name']} did not change in the whole period (stuck or disconnected sensor?)"))
        elif c["tag"] == "IDLE":
            out.append(_insight("IDLE", "blue", "·", f"{c['name']} never switched in this period"))
    for row in feedback or []:
        if row["confirmed"] == 0:
            out.append(_insight("FEEDBACK", "red", "!",
                                f"{row['do']} sent {row['sent']} command{'s' if row['sent'] != 1 else ''}, "
                                f"<b>0 confirmed</b> by {row['di']} (output or feedback wiring fault)"))
        elif row["confirmed"] < row["sent"]:
            out.append(_insight("FEEDBACK", "amber", "!",
                                f"{row['do']}: {row['sent'] - row['confirmed']} of {row['sent']} commands not confirmed by {row['di']}"))
    if result["n"] and result["coverage"] < 98.0 and result["missed"] > 0:
        out.append(_insight("COMMS", "blue", "⚡", f"{result['missed']} missed polls (coverage {result['coverage']:.1f} %)"))
    if not out:
        out.append(_insight("OK", "green", "✓", f"All {kind} channels behaved normally in this period."))
    order = {"red": 0, "amber": 1, "violet": 2, "blue": 3, "green": 4}
    out.sort(key=lambda i: order[i["color"]])
    return out


def period_report(result, name, source, compare=None):
    """Auto-generated report as [(heading, html)] for the Period Report card."""
    if not result["n"]:
        return [("SUMMARY", "No readings in the selected period.")]
    start, end = result["start"], result["end"]
    head = f"{start:%d %b %H:%M} → {end:%d %b %H:%M}"
    kind = result["kind"]
    parts = [("SUMMARY · " + head.upper(),
              f"{name} returned <b>{result['n']:,}</b> readings with <b>{result['coverage']:.1f} %</b> coverage "
              f"({result['missed']} missed poll{'s' if result['missed'] != 1 else ''}) over "
              f"<b>{fmt_duration(result['duration_s'])}</b>.")]
    finds = []
    if kind == "AI":
        parts[0] = (parts[0][0], parts[0][1] + f" Overall signal quality was <b>{result['signal_score']} / 100</b>.")
        for c in result["channels"]:
            u = " " + c["unit"] if c["unit"] else ""
            if c["breaches"]:
                finds.append(f"<b>{c['name']}</b> breached its limit <b>{c['breaches']}×</b> "
                             f"({fmt_duration(c['alarm_s'])} outside); mean {c['mean']:.2f}{u}, peak {c['max']:.2f}{u}.")
            if c["tag"] == "DRIFT":
                pct = 100.0 * c["change"] / max(abs(c["mean"]), 1e-9)
                finds.append(f"<b>{c['name']}</b> drifted <b>{pct:+.1f} %</b> over the period.")
            if c["tag"] == "NOISY":
                finds.append(f"<b>{c['name']}</b> noise σ {c['noise']:.3g}{u}, <b>{c['noise_ratio']:.1f}×</b> higher in the second half.")
            if c["tag"] == "STUCK":
                finds.append(f"<b>{c['name']}</b> is <b>flat</b> for the whole period (likely a disconnected input).")
            if c["tag"] == "SPIKE":
                finds.append(f"<b>{c['name']}</b> had {c['spikes']} spike{'s' if c['spikes'] != 1 else ''}.")
    else:
        parts[0] = (parts[0][0], parts[0][1] + f" <b>{result['total_toggles']}</b> state changes in total.")
        if result["busiest"]:
            n_, cnt, share = result["busiest"]
            finds.append(f"Most active: <b>{n_}</b> with {cnt} changes ({share:.0f} % of all).")
        if result["longest_on"]:
            finds.append(f"Longest ON: <b>{result['longest_on'][0]}</b> for {fmt_short_duration(result['longest_on'][1])}.")
        for c in result["channels"]:
            if c["tag"] in ("CHATTER", "HUNTING"):
                finds.append(f"<b>{c['name']}</b> {c['tag'].lower()}: {c['toggles']} changes.")
            elif c["tag"] == "STUCK":
                finds.append(f"<b>{c['name']}</b> never changed (stuck / idle input).")
    if finds:
        parts.append(("KEY FINDINGS", "<br>".join(finds[:8])))
    else:
        parts.append(("KEY FINDINGS", "No anomalies detected."))
    parts.append(("SOURCE", source))
    return parts


def compare_results(cur, prev):
    """[(label, text, good)] deltas against the previous period of the same length."""
    if not prev or not prev["n"]:
        return []
    rows = []
    if cur["kind"] == "AI":
        d = cur["breaches"] - prev["breaches"]
        rows.append(("breaches", f"{d:+d}", d <= 0))
    else:
        d = cur["total_toggles"] - prev["total_toggles"]
        rows.append(("changes", f"{d:+d}", d <= 0))
    dc = cur["coverage"] - prev["coverage"]
    rows.append(("coverage", f"{dc:+.1f} pt", dc >= 0))
    if cur["kind"] == "AI" and cur["channels"] and prev["channels"]:
        worst = max(cur["channels"], key=lambda c: c["breaches"] or 0)
        p = next((c for c in prev["channels"] if c["name"] == worst["name"]), None)
        if p and worst["mean"] is not None and p["mean"] is not None:
            u = (" " + worst["unit"]) if worst["unit"] else ""
            rows.append((f"{worst['name']} mean", f"{worst['mean'] - p['mean']:+.2f}{u}", True))
    else:
        rows.append(("anomalies", f"{cur['anomalies'] - prev['anomalies']:+d}", cur["anomalies"] <= prev["anomalies"]))
    return rows


def analyze(kind, docs, limit_for=None, th=None, recent_s=None):
    """Kind-aware entry point used by the Dashboard."""
    if kind in ("DI", "DO"):
        return analyze_digital(docs, kind, th)
    return analyze_analog(docs, limit_for, th, recent_s)


def health_score(success_pct, signal_scores, active_alarms, offline_devices, bad_quality_pct):
    """Plant health 0-100 with its four sub-scores (communication, signal, alarms, integrity)."""
    comm = max(0.0, min(100.0, success_pct if success_pct is not None else 100.0)) - 25.0 * offline_devices
    comm = max(0.0, comm)
    signal = sum(signal_scores) / len(signal_scores) if signal_scores else 100.0
    alarms = max(0.0, 100.0 - 12.0 * active_alarms)
    integrity = max(0.0, 100.0 - 4.0 * bad_quality_pct)
    total = 0.35 * comm + 0.25 * signal + 0.25 * alarms + 0.15 * integrity
    return {"total": int(round(total)), "comm": int(round(comm)), "signal": int(round(signal)),
            "alarms": int(round(alarms)), "integrity": int(round(integrity))}


# --------------------------------------------------------------------------- live session data
class SessionData:
    """Rolling live data for the Dashboard (GUI thread only; no locks needed)."""

    def __init__(self, max_readings=20000, max_resp=1200):
        self.max_readings = max_readings
        self.readings = {}      # sid -> deque of docs
        self.kinds = {}         # sid -> kind
        self.resp = {}          # sid -> deque of (t, ms)
        self.comm = {}          # sid -> {bucket: [ok, fail]}
        self.bus = deque()      # (t, ms)
        self.rate = deque(maxlen=400)   # response times for throughput
        self.max_resp = max_resp
        self.revision = 0
        self.bad = 0
        self.total = 0

    def clear(self):
        self.readings.clear()
        self.kinds.clear()
        self.resp.clear()
        self.comm.clear()
        self.bus.clear()
        self.rate.clear()
        self.bad = self.total = 0
        self.revision += 1

    def add_reading(self, sid, kind, ts, channels, units=None, quality="GOOD"):
        self.kinds[sid] = kind
        units = units or []
        doc = {"timestamp": ts, "quality": quality,
               "channels": {name: {"value": value, "unit": units[i] if i < len(units) else ""}
                            for i, (name, value) in enumerate(channels)}}
        self.readings.setdefault(sid, deque(maxlen=self.max_readings)).append(doc)
        self.total += 1
        if str(quality).upper() != "GOOD":
            self.bad += 1
        self.revision += 1

    def docs(self, sid, window_s=None, now=None):
        data = self.readings.get(sid)
        if not data:
            return []
        if not window_s:
            return list(data)
        cutoff = (now or datetime.now()) - timedelta(seconds=window_s)
        out = []
        for doc in reversed(data):
            if doc["timestamp"] < cutoff:
                break
            out.append(doc)
        out.reverse()
        return out

    def _bucket(self, t):
        size = THRESHOLDS["comm_bucket_s"]
        return int(t // size)

    def add_response(self, sid, ms, t):
        self.resp.setdefault(sid, deque(maxlen=self.max_resp)).append((t, float(ms)))
        self.comm.setdefault(sid, {}).setdefault(self._bucket(t), [0, 0])[0] += 1
        self.bus.append((t, float(ms)))
        self.rate.append(t)
        self._trim_bus(t)

    def add_failure(self, sid, ms, t):
        self.comm.setdefault(sid, {}).setdefault(self._bucket(t), [0, 0])[1] += 1
        self.bus.append((t, float(ms or 0)))
        self._trim_bus(t)

    def _trim_bus(self, t):
        w = THRESHOLDS["bus_window_s"]
        while self.bus and t - self.bus[0][0] > w:
            self.bus.popleft()

    def bus_util(self, t):
        self._trim_bus(t)
        w = THRESHOLDS["bus_window_s"]
        return min(100.0, 100.0 * sum(ms for _, ms in self.bus) / (w * 1000.0))

    def throughput(self, t, window=10.0):
        return sum(1 for x in self.rate if t - x <= window) / window

    def all_response_ms(self):
        return [ms for d in self.resp.values() for _, ms in d]

    def heatmap(self, sids, t, columns=24):
        """{sid: [success% or None per bucket]}, oldest first, `columns` buckets ending now."""
        size = THRESHOLDS["comm_bucket_s"]
        last = int(t // size)
        out = {}
        for sid in sids:
            row = []
            for b in range(last - columns + 1, last + 1):
                ok, fail = self.comm.get(sid, {}).get(b, (0, 0))
                row.append(100.0 * ok / (ok + fail) if ok + fail else None)
            out[sid] = row
        return out


# --------------------------------------------------------------------------- CSV import / export
_TIME_NAMES = ("time", "timestamp", "datetime", "date", "date_time", "date time", "ts")
_SKIP_NAMES = ("quality", "slave", "slave_id", "slaveid", "device", "device_id", "device_type", "type", "raw",
               "raw_rx", "id", "index", "no", "sr", "sr.no")
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                 "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S.%f",
                 "%m/%d/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M")
MAX_IMPORT_ROWS = 600000


class CsvImportError(Exception):
    pass


def _make_time_parser(sample):
    text = sample.strip()
    for fmt in _TIME_FORMATS:
        try:
            datetime.strptime(text, fmt)
            return lambda s, f=fmt: datetime.strptime(s.strip(), f)
        except ValueError:
            continue
    try:
        datetime.fromisoformat(text)
        return lambda s: datetime.fromisoformat(s.strip()).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        float(text)
        value = float(text)
        div = 1000.0 if value > 1e11 else 1.0
        return lambda s: datetime.fromtimestamp(float(s) / div)
    except ValueError:
        raise CsvImportError(f"Unrecognised time format: '{sample}'. Use e.g. 2026-10-08 09:30:00")


def _parse_value(text):
    t = str(text).strip()
    if not t:
        return None
    u = t.upper()
    if u in ("ON", "TRUE", "HIGH", "CLOSED"):
        return 1.0
    if u in ("OFF", "FALSE", "LOW", "OPEN"):
        return 0.0
    try:
        v = float(t.replace(",", "")) if re.fullmatch(r"-?[\d,]*\.?\d+(e-?\d+)?", t, re.I) else float(t)
    except ValueError:
        return None
    return v if v == v and abs(v) != math.inf else None


def _split_header(name):
    """'AI1 (mA)' -> ('AI1', 'mA')."""
    m = re.match(r"^\s*(.*?)\s*\((.*?)\)\s*$", name)
    return (m.group(1), m.group(2)) if m else (name.strip(), "")


def _guess_kind(names, binary):
    prefixes = {re.sub(r"[^A-Za-z]", "", n).upper()[:2] for n in names}
    for k in ("AI", "DI", "DO", "AO"):
        if k in prefixes:
            return k
    return "DI" if binary else "AI"


def load_csv(path):
    """Read a History-export style CSV (wide) or a long CSV (timestamp, channel, value[, unit, slave_id])
    into reading docs. Returns {"name","kind","docs","channels","units","rows","skipped","slaves"}."""
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise CsvImportError(f"Cannot open the file: {exc}")
    with handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect)
        try:
            header = next(reader)
        except StopIteration:
            raise CsvImportError("The file is empty.")
        header = [h.strip() for h in header]
        lower = [h.lower() for h in header]
        tcol = next((i for i, h in enumerate(lower) if h in _TIME_NAMES or "time" in h), None)
        if tcol is None:
            raise CsvImportError("No time column found. The first column should be 'Time' or 'timestamp'.")
        long_form = ("channel" in lower and "value" in lower)
        value_cols = []
        if not long_form:
            for i, h in enumerate(header):
                if i == tcol or lower[i] in _SKIP_NAMES or not h:
                    continue
                name, unit = _split_header(h)
                value_cols.append((i, name, unit))
            if not value_cols:
                raise CsvImportError("No data columns found next to the time column.")
        ccol = lower.index("channel") if long_form else None
        vcol = lower.index("value") if long_form else None
        ucol = lower.index("unit") if long_form and "unit" in lower else None
        scol = next((i for i, h in enumerate(lower) if h in ("slave_id", "slave", "slaveid")), None)

        parse_time = None
        rows = skipped = 0
        slaves = set()
        buckets = {}                         # timestamp -> {channel: {...}}  (long form groups by time)
        docs = []
        units = {}
        binary = True
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            rows += 1
            if rows > MAX_IMPORT_ROWS:
                skipped += 1
                continue
            try:
                if parse_time is None:
                    parse_time = _make_time_parser(row[tcol])
                ts = parse_time(row[tcol])
            except CsvImportError:
                raise
            except (ValueError, IndexError):
                skipped += 1
                continue
            if scol is not None and scol < len(row) and row[scol].strip():
                slaves.add(row[scol].strip())
            if long_form:
                try:
                    name = row[ccol].strip()
                    v = _parse_value(row[vcol])
                except IndexError:
                    skipped += 1
                    continue
                if v is None or not name:
                    skipped += 1
                    continue
                unit = row[ucol].strip() if ucol is not None and ucol < len(row) else ""
                if unit:
                    units[name] = unit
                if v not in (0.0, 1.0):
                    binary = False
                buckets.setdefault(ts, {})[name] = {"value": v, "unit": unit}
            else:
                channels = {}
                for i, name, unit in value_cols:
                    if i >= len(row):
                        continue
                    v = _parse_value(row[i])
                    if v is None:
                        continue
                    if v not in (0.0, 1.0):
                        binary = False
                    channels[name] = {"value": v, "unit": unit}
                    if unit:
                        units[name] = unit
                if not channels:
                    skipped += 1
                    continue
                docs.append({"timestamp": ts, "channels": channels, "quality": "GOOD"})
        if long_form:
            docs = [{"timestamp": ts, "channels": ch, "quality": "GOOD"} for ts, ch in buckets.items()]
    if not docs:
        raise CsvImportError("No readable rows. Check the time and value columns.")
    docs.sort(key=lambda d: d["timestamp"])
    names = sort_channels({n for d in docs for n in d["channels"]})
    kind = _guess_kind(names, binary)
    import os
    return {"name": os.path.basename(path), "kind": kind, "docs": docs, "channels": names, "units": units,
            "rows": rows, "skipped": skipped, "slaves": sorted(slaves), "binary": binary}


def write_csv(path, docs, kind):
    """Write docs in the same layout as the History tab export (round-trips through load_csv)."""
    names, units = [], {}
    for d in docs:
        for n, e in d.get("channels", {}).items():
            if n not in names:
                names.append(n)
            if isinstance(e, dict) and e.get("unit") and n not in units:
                units[n] = e["unit"]
    names = sort_channels(names)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        w = csv.writer(handle)
        w.writerow(["Time"] + [f"{n} ({units[n]})" if n in units else n for n in names] + ["Quality"])
        for d in docs:
            ts = d["timestamp"]
            ch = d.get("channels", {})
            w.writerow([ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] if isinstance(ts, datetime) else ts]
                       + [(ch.get(n, {}) or {}).get("value", "") for n in names] + [d.get("quality", "")])
    return len(docs)


def slice_docs(docs, start, end):
    """docs (sorted by time) inside [start, end]."""
    keys = [d["timestamp"] for d in docs]
    from bisect import bisect_right
    return docs[bisect_left(keys, start):bisect_right(keys, end)]