"""
JobHunter AI — Scheduler Service

Reads cron_schedules from SQLite and executes them on schedule using APScheduler.
Persists job state so schedules survive restarts.

Run with:  python -m scheduler
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

# Allow running from project root without installing as package
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Scheduler] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "applications.db")
TIMEZONE = os.environ.get("TIMEZONE", "America/Toronto")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_cron_tables():
    """Create cron tables if they don't exist (matches frontend/lib/db.ts schema)."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cron_schedules (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            cron_expr  TEXT NOT NULL,
            action     TEXT NOT NULL,
            enabled    INTEGER DEFAULT 1,
            last_run   TEXT,
            next_run   TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cron_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id  INTEGER REFERENCES cron_schedules(id),
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            status       TEXT DEFAULT 'running',
            jobs_total   INTEGER DEFAULT 0,
            jobs_tailored INTEGER DEFAULT 0,
            jobs_skipped INTEGER DEFAULT 0,
            errors       INTEGER DEFAULT 0,
            log          TEXT
        );
    """)
    conn.commit()
    conn.close()


def _create_run_record(schedule_id: int) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO cron_runs (schedule_id, started_at, status) VALUES (?, ?, 'running')",
        (schedule_id, datetime.now(timezone.utc).isoformat()),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def _finish_run_record(run_id: int, status: str, stats: dict, log: str = ""):
    conn = _get_conn()
    conn.execute(
        """UPDATE cron_runs
           SET finished_at = ?, status = ?,
               jobs_total = ?, jobs_tailored = ?, jobs_skipped = ?, errors = ?,
               log = ?
           WHERE id = ?""",
        (
            datetime.now(timezone.utc).isoformat(), status,
            stats.get("total", 0), stats.get("tailored", 0),
            stats.get("skipped", 0), stats.get("errors", 0),
            log, run_id,
        ),
    )
    conn.commit()
    conn.close()


def _update_schedule_timestamps(schedule_id: int, next_run: Optional[str]):
    conn = _get_conn()
    conn.execute(
        "UPDATE cron_schedules SET last_run = ?, next_run = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), next_run, schedule_id),
    )
    conn.commit()
    conn.close()


def _compute_next_run(cron_expr: str) -> Optional[str]:
    try:
        it = croniter(cron_expr, datetime.now())
        return it.get_next(datetime).isoformat()
    except Exception:
        return None


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("api", {}).get("anthropic_api_key", "") or ""
    except Exception:
        return ""


# ── Action Handlers ───────────────────────────────────────────────────────────

def _action_process_url_queue() -> dict:
    """Process all pending URLs from urls.txt."""
    urls_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "urls.txt")
    if not os.path.isfile(urls_file):
        logger.warning("urls.txt not found — skipping batch")
        return {"total": 0, "tailored": 0, "skipped": 0, "errors": 0}

    from agents.orchestrator import Orchestrator
    api_key = _get_api_key()
    orch = Orchestrator(api_key=api_key)
    stats = orch.run_batch(urls_file)
    return {
        "total": sum(stats.values()),
        "tailored": stats.get("tailored", 0),
        "skipped": stats.get("skipped", 0),
        "errors": stats.get("errors", 0),
    }


def _action_followup_check() -> dict:
    """Check for applications needing follow-up and log them."""
    from agents.orchestrator import Orchestrator
    orch = Orchestrator(api_key="")  # no LLM needed for follow-up check
    followups = orch.get_followups(days=5)
    count = len(followups)
    if count:
        logger.info(f"Follow-up check: {count} application(s) need follow-up")
        for app in followups[:10]:
            logger.info(f"  → {app.get('company')} — {app.get('role')} (applied {app.get('applied_date')})")
    return {"total": count, "tailored": 0, "skipped": 0, "errors": 0}


def _action_weekly_report() -> dict:
    """Generate a weekly stats report and print it."""
    from agents.orchestrator import Orchestrator
    orch = Orchestrator(api_key="")
    stats = orch.get_stats(week=True)
    logger.info("Weekly report generated")
    if isinstance(stats, list):
        for s in stats:
            logger.info(
                f"  {s.get('date')}: scraped={s.get('jobs_scraped',0)} "
                f"tailored={s.get('jobs_tailored',0)} applied={s.get('jobs_applied',0)}"
            )
    return {"total": 0, "tailored": 0, "skipped": 0, "errors": 0}


ACTION_MAP = {
    "process_url_queue": _action_process_url_queue,
    "followup_check":    _action_followup_check,
    "weekly_report":     _action_weekly_report,
}


# ── Core Execution ────────────────────────────────────────────────────────────

def execute_schedule(schedule_id: int):
    """Called by APScheduler — wraps the action with DB logging."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM cron_schedules WHERE id = ? AND enabled = 1", (schedule_id,)
    ).fetchone()
    conn.close()

    if not row:
        logger.warning(f"Schedule {schedule_id} not found or disabled — skipping")
        return

    name = row["name"]
    action = row["action"]
    cron_expr = row["cron_expr"]

    logger.info(f"Running schedule #{schedule_id} '{name}' (action={action})")
    run_id = _create_run_record(schedule_id)
    log_lines = [f"Started at {datetime.now().isoformat()}"]

    try:
        handler = ACTION_MAP.get(action)
        if not handler:
            raise ValueError(f"Unknown action '{action}'. Available: {list(ACTION_MAP.keys())}")

        stats = handler()
        log_lines.append(f"Completed: {stats}")
        _finish_run_record(run_id, "success", stats, "\n".join(log_lines))
        logger.info(f"Schedule #{schedule_id} '{name}' completed: {stats}")

    except Exception as exc:
        log_lines.append(f"ERROR: {exc}")
        _finish_run_record(run_id, "failed", {}, "\n".join(log_lines))
        logger.error(f"Schedule #{schedule_id} '{name}' failed: {exc}", exc_info=True)

    finally:
        next_run = _compute_next_run(cron_expr)
        _update_schedule_timestamps(schedule_id, next_run)


# ── Scheduler Lifecycle ───────────────────────────────────────────────────────

class JobHunterScheduler:

    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=TIMEZONE)
        _ensure_cron_tables()

    def load_schedules(self):
        """Load all enabled schedules from DB and register with APScheduler."""
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM cron_schedules WHERE enabled = 1"
        ).fetchall()
        conn.close()

        loaded = 0
        for row in rows:
            self._register_job(row["id"], row["cron_expr"], row["name"])
            loaded += 1

        logger.info(f"Loaded {loaded} active schedule(s) from database")
        return loaded

    def _register_job(self, schedule_id: int, cron_expr: str, name: str):
        """Add or replace an APScheduler job for a cron schedule."""
        if not croniter.is_valid(cron_expr):
            logger.warning(f"Invalid cron expression for schedule #{schedule_id} '{name}': {cron_expr}")
            return

        try:
            trigger = CronTrigger.from_crontab(cron_expr, timezone=TIMEZONE)
            self.scheduler.add_job(
                func=execute_schedule,
                trigger=trigger,
                args=[schedule_id],
                id=f"schedule_{schedule_id}",
                name=name,
                replace_existing=True,
                misfire_grace_time=300,  # Run if missed by up to 5 minutes
            )
            next_run = _compute_next_run(cron_expr)
            _update_schedule_timestamps(schedule_id, next_run)
            logger.info(f"Registered schedule #{schedule_id} '{name}' ({cron_expr}) — next: {next_run}")
        except Exception as e:
            logger.error(f"Failed to register schedule #{schedule_id}: {e}")

    def run_now(self, schedule_id: int):
        """Immediately execute a schedule (for manual 'Run Now' triggers)."""
        execute_schedule(schedule_id)

    def add_schedule(self, schedule_id: int, cron_expr: str, name: str):
        """Called when a new schedule is created via the API."""
        self._register_job(schedule_id, cron_expr, name)

    def remove_schedule(self, schedule_id: int):
        """Called when a schedule is deleted via the API."""
        job_id = f"schedule_{schedule_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed schedule #{schedule_id}")

    def start(self):
        self.load_schedules()
        self.scheduler.start()
        logger.info(f"Scheduler started (timezone={TIMEZONE})")

    def shutdown(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    def get_status(self) -> dict:
        jobs = self.scheduler.get_jobs()
        return {
            "running": self.scheduler.running,
            "timezone": TIMEZONE,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                }
                for j in jobs
            ],
        }
