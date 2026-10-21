"""Read-side MongoDB helpers for history, trends and alarms (Phase 5).

Everything here is blocking, so the GUI always calls it from a worker thread
(see ``run_async`` in history_views.py). One shared MongoDB connection is
created lazily and dropped after any error so the next call reconnects.
"""
import threading

try:
    from .db_writer import COLLECTIONS, DEFAULT_COLLECTION, _default_db_factory
except ImportError:
    from db_writer import COLLECTIONS, DEFAULT_COLLECTION, _default_db_factory

ALARM_EVENTS = "alarm_events"
ALARM_LIMITS = "alarm_limits"

_lock = threading.Lock()
_db = None
_factory = None          # tests may replace this through set_db_factory()


def set_db_factory(factory):
    global _factory, _db
    with _lock:
        _factory = factory
        _db = None


def get_shared_db():
    global _db
    with _lock:
        if _db is None:
            _db = (_factory or _default_db_factory)()
        return _db


def reset_shared_db():
    global _db
    with _lock:
        _db = None


def collection_for(kind):
    return COLLECTIONS.get(kind, DEFAULT_COLLECTION)


def _run(operation):
    try:
        return operation(get_shared_db())
    except Exception:
        reset_shared_db()
        raise


def query_readings(kind, slave_id, start, end, limit=20000):
    """Readings of one device in [start, end], oldest first (newest `limit` kept)."""
    def operation(db):
        cursor = (db.get_collection(collection_for(kind))
                  .find({"slave_id": slave_id, "timestamp": {"$gte": start, "$lte": end}},
                        {"_id": 0, "timestamp": 1, "channels": 1, "quality": 1})
                  .sort("timestamp", -1).limit(limit))
        docs = list(cursor)
        docs.reverse()
        return docs
    return _run(operation)


def query_alarm_events(start, end, limit=2000):
    """Alarm events in [start, end], newest first."""
    def operation(db):
        cursor = (db.get_collection(ALARM_EVENTS)
                  .find({"timestamp": {"$gte": start, "$lte": end}}, {"_id": 0})
                  .sort("timestamp", -1).limit(limit))
        return list(cursor)
    return _run(operation)


def load_limits():
    """{(slave_id, channel): {"enabled","low","high"}} from the database."""
    def operation(db):
        limits = {}
        for doc in db.get_collection(ALARM_LIMITS).find({}):
            limits[(int(doc["slave_id"]), doc["channel"])] = {
                "enabled": bool(doc.get("enabled", False)),
                "low": float(doc.get("low", 0.0)),
                "high": float(doc.get("high", 100.0)),
            }
        return limits
    return _run(operation)


def save_limits(limits):
    """Upsert every (slave_id, channel) limit."""
    def operation(db):
        collection = db.get_collection(ALARM_LIMITS)
        for (slave_id, channel), limit in limits.items():
            doc = {"_id": f"{slave_id}:{channel}", "slave_id": slave_id, "channel": channel,
                   "enabled": bool(limit["enabled"]), "low": float(limit["low"]),
                   "high": float(limit["high"])}
            collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return len(limits)
    return _run(operation)


def diagnose(kind, slave_id):
    """Why is a query empty? Counts and newest timestamp for this device."""
    def operation(db):
        collection = db.get_collection(collection_for(kind))
        newest = list(collection.find({"slave_id": slave_id}, {"_id": 0, "timestamp": 1})
                      .sort("timestamp", -1).limit(1))
        return {
            "collection": collection_for(kind),
            "total": collection.count_documents({}),
            "device": collection.count_documents({"slave_id": slave_id}),
            "newest": newest[0]["timestamp"] if newest else None,
        }
    return _run(operation)


def list_stored_devices():
    """[(slave_id, kind)] that have saved readings (one cheap distinct query per collection)."""
    def operation(db):
        found = []
        for kind in ("DI", "DO", "AI", "AO"):
            for slave_id in db.get_collection(collection_for(kind)).distinct("slave_id"):
                found.append((int(slave_id), kind))
        return sorted(found)
    return _run(operation)


def latest_readings(pairs):
    """{(slave_id, kind): newest document} for each (slave_id, kind)."""
    def operation(db):
        out = {}
        for slave_id, kind in pairs:
            docs = list(db.get_collection(collection_for(kind))
                        .find({"slave_id": slave_id}, {"_id": 0, "timestamp": 1, "channels": 1, "quality": 1})
                        .sort("timestamp", -1).limit(1))
            if docs:
                out[(slave_id, kind)] = docs[0]
        return out
    return _run(operation)


def dashboard_snapshot(target, start, end, now, limit=20000):
    """Everything the dashboard needs from the database in one background job.
    target = (slave_id, kind) for the trend chart, or None."""
    stored = list_stored_devices()
    return {
        "stored": stored,
        "latest": latest_readings(stored),
        "trend": query_readings(target[1], target[0], start, end, limit) if target else [],
        "events": query_alarm_events(now - __import__("datetime").timedelta(hours=24), now, 5000),
    }


ANALYSIS_LIMIT = 60000


def period_snapshot(kind, slave_id, start, end, pair=None, with_previous=True, limit=ANALYSIS_LIMIT):
    """Everything the Dashboard's period analysis needs in one background job:
    the readings of one device in [start, end], the previous period of the same length,
    alarm events of that device in the period, and (DO analysis) the readings of a DI device
    for the feedback check. pair = (slave_id, kind) or None."""
    span = end - start
    docs = query_readings(kind, slave_id, start, end, limit)
    prev = query_readings(kind, slave_id, start - span, start, limit) if with_previous else []
    events = [e for e in query_alarm_events(start, end, 5000) if e.get("slave_id") == slave_id]
    pair_docs = query_readings(pair[1], pair[0], start, end, limit) if pair else []
    return {"docs": docs, "prev": prev, "events": events, "pair_docs": pair_docs,
            "capped": len(docs) >= limit}