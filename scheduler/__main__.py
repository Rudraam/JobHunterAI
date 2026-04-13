"""
JobHunter AI — Scheduler Entry Point

Usage:
  python -m scheduler          # Start scheduler daemon (keeps running)
  python -m scheduler --run-now <schedule_id>   # Execute once and exit
"""

import sys
import time
import signal
import logging
import argparse

from .scheduler_service import JobHunterScheduler

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="JobHunter AI Scheduler")
    parser.add_argument(
        "--run-now", type=int, metavar="SCHEDULE_ID",
        help="Execute a specific schedule immediately and exit"
    )
    args = parser.parse_args()

    scheduler = JobHunterScheduler()

    if args.run_now:
        print(f"[Scheduler] Running schedule #{args.run_now} immediately...")
        scheduler.run_now(args.run_now)
        print("[Scheduler] Done.")
        return

    # Daemon mode
    scheduler.start()
    status = scheduler.get_status()
    print(f"[Scheduler] Running with {len(status['jobs'])} active job(s). Press Ctrl+C to stop.")
    for job in status["jobs"]:
        print(f"  • {job['name']} — next run: {job['next_run']}")

    # Graceful shutdown on SIGTERM / SIGINT
    stop_flag = [False]

    def _shutdown(signum, frame):
        stop_flag[0] = True
        print("\n[Scheduler] Shutting down...")
        scheduler.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while not stop_flag[0]:
        time.sleep(30)


if __name__ == "__main__":
    main()
