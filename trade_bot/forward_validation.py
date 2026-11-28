"""Frozen FV1 cohort protocol. Paper-only; fail closed on missing or invalid evidence."""
from __future__ import annotations
import hashlib, json, math, os, random, tempfile
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL = {
    "name": "AURELIS FV1",
    "eligible_signals": 200,
    "scored_outcomes": 100,
    "minimum_days": 30,
    "profit_factor_min": 1.25,
    "equity_drawdown_max_pct": 15.0,
    "record_integrity_min_pct": 98.0,
    "bootstrap_confidence": 0.95,
    "bootstrap_iterations": 5000,
    "paper_only": True,
}

def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp_required")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone_required")
    return dt.astimezone(timezone.utc)

def fingerprint(source_map):
    if not source_map or not all(isinstance(k, str) and isinstance(v, str) for k, v in source_map.items()):
        raise ValueError("source_map_must_contain_text")
    payload = json.dumps(source_map, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()

def cohort_eligible(signal, frozen_at, strategy_hash):
    try:
        created = parse_utc(signal.get("created_at"))
        frozen = parse_utc(frozen_at)
    except (TypeError, ValueError):
        return False, "invalid_or_missing_timestamp"
    if created <= frozen:
        return False, "pre_freeze_signal"
    if signal.get("strategy_fingerprint") != strategy_hash:
        return False, "strategy_fingerprint_mismatch"
    if signal.get("cohort_id") != "FV1":
        return False, "wrong_cohort"
    if signal.get("status") not in ("OPEN", "CLOSED"):
        return False, "invalid_status"
    return True, "eligible"

def bootstrap_daily_block_ci(daily_returns, iterations=None, seed=20261128):
    """Percentile CI for mean daily return using resampled daily blocks (days as units)."""
    values = [float(x) for x in daily_returns]
    if len(values) < 2 or not all(math.isfinite(x) for x in values):
        return None
    n = len(values)
    iterations = int(iterations or PROTOCOL["bootstrap_iterations"])
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(iterations))
    return {"lower_95_pct": means[max(0, int(0.025 * iterations) - 1)],
            "upper_95_pct": means[min(iterations - 1, int(0.975 * iterations))],
            "days": n, "iterations": iterations}

def evaluate_gates(metrics):
    required = ("signals", "scored", "days", "expectancy_pct", "profit_factor",
                "equity_drawdown_pct", "integrity_pct", "bootstrap_ci_low_pct",
                "critical_risk_breaches")
    missing = [k for k in required if k not in metrics or metrics[k] is None]
    checks = {
        "sample_signals": ("signals", lambda x: x >= PROTOCOL["eligible_signals"]),
        "scored_outcomes": ("scored", lambda x: x >= PROTOCOL["scored_outcomes"]),
        "duration_days": ("days", lambda x: x >= PROTOCOL["minimum_days"]),
        "expectancy": ("expectancy_pct", lambda x: x > 0),
        "profit_factor": ("profit_factor", lambda x: x >= PROTOCOL["profit_factor_min"]),
        "equity_drawdown": ("equity_drawdown_pct", lambda x: x <= PROTOCOL["equity_drawdown_max_pct"]),
        "record_integrity": ("integrity_pct", lambda x: x >= PROTOCOL["record_integrity_min_pct"]),
        "bootstrap_ci": ("bootstrap_ci_low_pct", lambda x: x > 0),
        "critical_risk_breaches": ("critical_risk_breaches", lambda x: x == 0),
    }
    gates = {}
    for name, (key, predicate) in checks.items():
        value = metrics.get(key)
        valid = isinstance(value, (int, float)) and math.isfinite(value)
        passed = valid and predicate(value)
        gates[name] = {"status": "PASS" if passed else ("PENDING" if key in missing or not valid else "FAIL"),
                       "value": value}
    statuses = [g["status"] for g in gates.values()]
    status = "PENDING" if "PENDING" in statuses else ("PASS" if all(s == "PASS" for s in statuses) else "FAIL")
    return {"status": status, "missing_metrics": missing, "gates": gates, "paper_only": True}

def load_state(path):
    p = Path(path)
    if not p.exists():
        return {"protocol": PROTOCOL, "cohort_id": "FV1", "frozen_at": None,
                "strategy_fingerprint": None, "signals": [], "risk_breaches": [], "watchlist_history": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("protocol") != PROTOCOL or data.get("cohort_id") != "FV1":
        raise ValueError("state_protocol_mismatch")
    return data

def save_state(path, state):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
