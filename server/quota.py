"""Per-tenant quotas and usage reporting.

Three limits, each chosen because it bounds a resource this system can
actually exhaust: runs started per day (compute), datasets stored, and
total bytes stored (the database). Every one is counted from the durable
rows themselves, so usage cannot drift away from reality the way a
separate tally would.

What this deliberately does **not** do is put a price on anything. The
deployment has no billing relationship, no metered provider by default,
and no token accounting — a currency figure here would be invented, and
an invented cost is worse than no cost. Usage is reported in the units
the system genuinely measures, and turning those into money is a decision
for whoever owns the bill.

Limits are per owner, so one tenant cannot spend another's budget, and
they are enforced on the server before the resource is created — not
checked in the browser, where they would be a suggestion.
"""

from datetime import datetime, timedelta, timezone

# Generous by default: these exist to stop a runaway loop or an accident,
# not to ration ordinary use. An operator lowers them per deployment.
DEFAULTS = {
    "runs_per_day": 200,
    "datasets": 100,
    "dataset_bytes": 50_000_000,   # 50 MB across all of a tenant's uploads
}

ENV_KEYS = {
    "runs_per_day": "AGENTIC_OS_QUOTA_RUNS_PER_DAY",
    "datasets": "AGENTIC_OS_QUOTA_DATASETS",
    "dataset_bytes": "AGENTIC_OS_QUOTA_DATASET_BYTES",
}


class QuotaExceeded(Exception):
    """Raised before the resource is created, never after."""

    def __init__(self, limit_name, used, limit, message):
        super().__init__(message)
        self.limit_name = limit_name
        self.used = used
        self.limit = limit
        self.message = message


def load_limits(env=None):
    """Limits from the environment, falling back to the defaults.

    An unreadable or negative value falls back rather than failing
    startup: a typo in a limit must not take the deployment down.
    """
    import os

    env = os.environ if env is None else env
    limits = {}
    for name, default in DEFAULTS.items():
        raw = env.get(ENV_KEYS[name])
        try:
            value = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        limits[name] = value if value >= 0 else default
    return limits


def _day_start(now=None):
    moment = now or datetime.now(timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _next_day(now=None):
    moment = now or datetime.now(timezone.utc)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start + timedelta(days=1)).isoformat()


def usage(store, owner, limits, now=None):
    """What this tenant has used, and what is left."""
    runs_today = store.count_runs_since(owner, _day_start(now))
    datasets = store.dataset_usage(owner)
    return {
        "runs_today": {
            "used": runs_today,
            "limit": limits["runs_per_day"],
            "remaining": max(0, limits["runs_per_day"] - runs_today),
            "resets_at": _next_day(now),
        },
        "datasets": {
            "used": datasets["datasets"],
            "limit": limits["datasets"],
            "remaining": max(0, limits["datasets"] - datasets["datasets"]),
        },
        "dataset_bytes": {
            "used": datasets["bytes"],
            "limit": limits["dataset_bytes"],
            "remaining": max(0, limits["dataset_bytes"] - datasets["bytes"]),
        },
        # Stated rather than silently omitted: these are real costs the
        # system does not currently measure.
        "not_tracked": ["model tokens", "function execution time", "currency"],
    }


def check_run(store, owner, limits, now=None):
    used = store.count_runs_since(owner, _day_start(now))
    if used >= limits["runs_per_day"]:
        raise QuotaExceeded(
            "runs_per_day", used, limits["runs_per_day"],
            f"Daily run limit reached ({used}/{limits['runs_per_day']}). "
            f"It resets at {_next_day(now)[:16].replace('T', ' ')} UTC. "
            "Existing runs can still be advanced, approved, and read.")


def check_dataset(store, owner, limits, incoming_bytes):
    """Checked before the row is written, so a rejected upload stores
    nothing. Re-uploading a file the tenant already has is not counted:
    content-addressed storage means it consumes no new space."""
    current = store.dataset_usage(owner)
    if current["datasets"] >= limits["datasets"]:
        raise QuotaExceeded(
            "datasets", current["datasets"], limits["datasets"],
            f"Dataset limit reached ({current['datasets']}/{limits['datasets']}). "
            "Delete a dataset or re-run an existing one instead of uploading again.")
    projected = current["bytes"] + incoming_bytes
    if projected > limits["dataset_bytes"]:
        raise QuotaExceeded(
            "dataset_bytes", current["bytes"], limits["dataset_bytes"],
            f"Storage limit reached: this upload would take you to "
            f"{projected / 1_000_000:.1f} MB of a {limits['dataset_bytes'] / 1_000_000:.0f} MB "
            "allowance. Re-run an existing dataset, or remove one you no longer need.")
