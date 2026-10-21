"""Analyse a TX/RX log saved with the Live tab's "Record Log" button
(a pasted terminal log with [HH:MM:SS.mmm] timestamps also works).

Usage:   python log_analyzer.py modbus_log_20261008_151630.txt
Writes the report to the screen and to <log name>_report.txt.
"""
import re
import sys
from collections import defaultdict

LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d\.\d+)\]\s+(.*)$")
TX = re.compile(r"^(Retry TX|Recovery TX|Config TX|Write TX|Write Retry \d+ TX|TX) -> \[([0-9A-F ]+)\] \(Slave (\d+) / FC (\d+)\)")
RX = re.compile(r"^RX <- \[([0-9A-F ]+)\] \(Slave (\d+) / FC (\d+)\)")
TIMEOUT = re.compile(r"^RX <- TIMEOUT \((\d+) ms\) \(Slave (\d+)\)")
ERROR = re.compile(r"^Communication error \(Slave (\d+)\): (.*)")
DEVICE = re.compile(r"^# DEVICE slave=(\d+) name=(.*?) kind=(\S*) fc=(\S+) addr=(\S+) count=(\S+) "
                    r"poll=(\d+) scan=(\d+) timeout=(\d+) retries=(\d+)")


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    k = min(len(values) - 1, max(0, int(round(p / 100.0 * (len(values) - 1)))))
    return values[k]


def fmt(v):
    return "-" if v is None else f"{v:.0f}"


def analyse(path):
    devices = {}
    events = []            # (t, type, slave, extra)
    others = []            # notable non-frame lines
    frames = []            # (t, slave, fc, bytes) of every good reply
    day = 0.0
    last_t = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            m = DEVICE.match(raw)
            if m:
                devices[int(m.group(1))] = dict(name=m.group(2).strip("'\""), kind=m.group(3), fc=m.group(4),
                                                poll=int(m.group(7)), scan=int(m.group(8)),
                                                timeout=int(m.group(9)), retries=int(m.group(10)))
                continue
            m = LINE.match(raw)
            if not m:
                continue
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) + day
            if last_t is not None and t < last_t - 3600:       # passed midnight
                day += 86400.0
                t += 86400.0
            last_t = t
            text = m.group(4)
            if (mm := TX.match(text)):
                events.append((t, "tx", int(mm.group(3)), mm.group(1)))
            elif (mm := RX.match(text)):
                events.append((t, "rx", int(mm.group(2)), len(mm.group(1).split())))
                frames.append((t, int(mm.group(2)), int(mm.group(3)), mm.group(1).split()))
            elif (mm := TIMEOUT.match(text)):
                events.append((t, "timeout", int(mm.group(2)), int(mm.group(1))))
            elif (mm := ERROR.match(text)):
                events.append((t, "error", int(mm.group(1)), mm.group(2)))
            else:
                low = text.lower()
                if any(k in low for k in ("offline", "recovered", "lost", "no longer available",
                                          "disconnected", "connected to", "error", "write", "polling")):
                    others.append((t, text))

    if not events:
        return "No TX/RX lines with [HH:MM:SS.mmm] timestamps were found in this file."

    start, end = events[0][0], events[-1][0]
    span = max(0.001, end - start)
    per = defaultdict(lambda: dict(poll_tx=[], tx=0, retry=0, recovery=0, config=0, write=0, rx=0,
                                   timeouts=[], errors=[], resp=[], gap_ok=[0, 0, 0], gap_to=[0, 0, 0]))
    busy = 0.0
    longest_idle = (0.0, None)
    prev_end = None            # time the bus became free (last RX / timeout / error)
    open_tx = None             # (t, slave, kind)

    def bucket(gap_ms):
        return 0 if gap_ms < 10 else (1 if gap_ms < 30 else 2)

    for t, typ, sid, extra in events:
        d = per[sid]
        if typ == "tx":
            d["tx"] += 1
            key = {"Retry TX": "retry", "Recovery TX": "recovery", "Config TX": "config", "Write TX": "write"}.get(extra)
            if extra.startswith("Write Retry"):
                key = "write"
            if key:
                d[key] += 1
            else:
                d["poll_tx"].append(t)
            gap = None if prev_end is None else (t - prev_end) * 1000.0
            if gap is not None and gap > longest_idle[0]:
                longest_idle = (gap, t)
            open_tx = (t, sid, gap)
        else:
            if open_tx is not None and open_tx[1] == sid:
                dur = t - open_tx[0]
                busy += dur
                gap = open_tx[2]
                if typ == "rx":
                    d["rx"] += 1
                    d["resp"].append(dur * 1000.0)
                    if gap is not None:
                        d["gap_ok"][bucket(gap)] += 1
                elif typ == "timeout":
                    d["timeouts"].append((t, gap))
                    if gap is not None:
                        d["gap_to"][bucket(gap)] += 1
                else:
                    d["errors"].append((t, extra))
            elif typ == "timeout":
                d["timeouts"].append((t, None))
            elif typ == "error":
                d["errors"].append((t, extra))
            elif typ == "rx":
                d["rx"] += 1
            open_tx = None
            prev_end = t

    def clock(t):
        t %= 86400
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"

    out = []
    w = out.append
    w(f"LOG ANALYSIS  {path}")
    w(f"Time span     {clock(start)} -> {clock(end)}   ({span / 60:.1f} min)")
    w(f"Bus busy      {100 * busy / span:.0f}%   (time between a request and its reply/timeout)")
    if longest_idle[1] is not None:
        w(f"Longest quiet {longest_idle[0]:.0f} ms (before {clock(longest_idle[1])})")
    w("")
    for sid in sorted(per):
        d = per[sid]
        cfg = devices.get(sid, {})
        poll = cfg.get("poll")
        gaps = [(b - a) * 1000.0 for a, b in zip(d["poll_tx"], d["poll_tx"][1:])]
        normal_gaps = [g for g in gaps if g < 10000]
        title = f"SLAVE {sid}"
        if cfg:
            title += f"  {cfg['name']}  ({cfg['kind']}, FC{cfg['fc']}, poll {cfg['poll']} ms, timeout {cfg['timeout']} ms, retries {cfg['retries']})"
        w(title)
        w("-" * len(title))
        tries = d["rx"] + len(d["timeouts"]) + len(d["errors"])
        w(f"  Requests      {d['tx']}  (poll {len(d['poll_tx'])}, retry {d['retry']}, recovery {d['recovery']}, "
          f"config {d['config']}, write {d['write']})")
        w(f"  Replies OK    {d['rx']}   timeouts {len(d['timeouts'])}   errors {len(d['errors'])}"
          + (f"   -> {100.0 * len(d['timeouts']) / tries:.2f}% timeouts" if tries else ""))
        if gaps:
            w(f"  Poll gap ms   min {fmt(min(gaps))}  median {fmt(pct(gaps, 50))}  avg {fmt(sum(normal_gaps) / max(1, len(normal_gaps)))}"
              f"  p95 {fmt(pct(gaps, 95))}  max {fmt(max(gaps))}")
            if poll:
                early = [g for g in gaps if g < poll - 1]
                late = [g for g in gaps if g > poll * 1.5]
                w(f"  vs set {poll} ms   earlier than set: {len(early)}   more than 1.5x late: {len(late)}")
        if d["resp"]:
            r = d["resp"]
            w(f"  Reply time ms min {fmt(min(r))}  median {fmt(pct(r, 50))}  p95 {fmt(pct(r, 95))}  max {fmt(max(r))}")
        names = ("< 10 ms", "10-30 ms", ">= 30 ms")
        rows = []
        for i, name in enumerate(names):
            ok, to = d["gap_ok"][i], d["gap_to"][i]
            if ok + to:
                rows.append(f"{name}: {to}/{ok + to} timeout ({100.0 * to / (ok + to):.1f}%)")
        if rows:
            w("  Quiet time before request -> " + "   ".join(rows))
        for t, gap in d["timeouts"][:15]:
            w(f"    timeout at {clock(t)}" + (f"  (request sent {gap:.0f} ms after previous reply)" if gap is not None else ""))
        if len(d["timeouts"]) > 15:
            w(f"    ... {len(d['timeouts']) - 15} more")
        for t, text in d["errors"][:10]:
            w(f"    error at {clock(t)}: {text}")
        w("")
    w(value_changes(frames, clock))
    if others:
        w("EVENTS")
        for t, text in others[:40]:
            w(f"  {clock(t)}  {text}")
        if len(others) > 40:
            w(f"  ... {len(others) - 40} more")
    return "\n".join(out)


def _decode(fc, data):
    """Channel values from one reply frame (address, fc, bytecount, data..., crc)."""
    try:
        raw = [int(x, 16) for x in data[3:3 + int(data[2], 16)]]
    except (ValueError, IndexError):
        return None
    if fc in (1, 2):
        return [(raw[i // 8] >> (i % 8)) & 1 for i in range(len(raw) * 8)]
    if fc in (3, 4):
        return [raw[i] << 8 | raw[i + 1] for i in range(0, len(raw) - 1, 2)]
    return None


def value_changes(frames, clock):
    """Every change of a reading, per slave and channel: shows real input
    changes, chatter (fast ON/OFF) and stuck values."""
    out = ["VALUE CHANGES"]
    by_slave = defaultdict(list)
    for t, sid, fc, data in frames:
        if fc == 3 and data[2] == "10":      # AI input-type config read, not a reading
            continue
        vals = _decode(fc, data)
        if vals is not None:
            by_slave[(sid, fc)].append((t, vals))
    if not by_slave:
        return "VALUE CHANGES\n  (no readings)"
    for (sid, fc), rows in sorted(by_slave.items()):
        name = "bit" if fc in (1, 2) else "register"
        changes = []                         # (t, channel, old, new)
        for (t0, a), (t1, b) in zip(rows, rows[1:]):
            for ch, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    changes.append((t1, ch + 1, x, y))
        out.append(f"  Slave {sid} FC{fc:02d}: {len(rows)} readings, {len(changes)} {name} changes")
        if not changes:
            out.append(f"    value never changed: {rows[0][1][:16]}")
            continue
        per_ch = defaultdict(list)
        for t, ch, x, y in changes:
            per_ch[ch].append((t, x, y))
        for ch, lst in sorted(per_ch.items()):
            # how long each state lasted (time between two changes of this channel)
            holds = [(b[0] - a[0]) * 1000.0 for a, b in zip(lst, lst[1:])]
            short = [h for h in holds if h < 1000]
            line = f"    ch {ch:2d}: {len(lst)} changes"
            if holds:
                line += f", shortest state {min(holds):.0f} ms, states < 1 s: {len(short)}"
            # isolated 1-reading glitches: A -> B -> A
            out.append(line)
        glitches = 0
        for (ta, a), (tb, b), (tc, c) in zip(rows, rows[1:], rows[2:]):
            if a == c and b != a:
                glitches += 1
        if glitches:
            out.append(f"    single-reading glitches (value flips for one poll and comes back): {glitches}")
        for t, ch, x, y in changes[:25]:
            out.append(f"      {clock(t)}  ch {ch}: {x} -> {y}")
        if len(changes) > 25:
            out.append(f"      ... {len(changes) - 25} more")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    report = analyse(sys.argv[1])
    print(report)
    target = sys.argv[1].rsplit(".", 1)[0] + "_report.txt"
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\nReport saved: {target}")