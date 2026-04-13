#!/usr/bin/env python3
"""
JobHunter AI — Daily CLI

Usage:
  python run_daily.py batch [--input urls.txt]
  python run_daily.py single --url "https://..."
  python run_daily.py status [--week]
  python run_daily.py list [--status applied] [--priority high]
  python run_daily.py update <job_id> --status interview [--notes "..."]
  python run_daily.py followup [--days 5]
  python run_daily.py report [--week]
"""

import os
import sys
import argparse
from datetime import datetime

# Allow running from project root without installing as package
sys.path.insert(0, os.path.dirname(__file__))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Load API key from settings.yaml if not in environment
def _load_api_key_from_config() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        import yaml
        config_path = os.path.join(os.path.dirname(__file__), "config", "settings.yaml")
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("api", {}).get("anthropic_api_key", "") or ""
    except Exception:
        return ""


def _get_orchestrator():
    from agents.orchestrator import Orchestrator
    api_key = _load_api_key_from_config()
    if not api_key:
        print("[Warning] ANTHROPIC_API_KEY not set. LLM-based tailoring will be skipped.")
        print("  Set it with:  export ANTHROPIC_API_KEY=sk-ant-...")
        print("  Or add it to config/settings.yaml under api.anthropic_api_key\n")
    return Orchestrator(api_key=api_key)


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_row(app: dict) -> str:
    score = f"{app.get('match_score', 0):.0f}" if app.get("match_score") else " -"
    return (
        f"  {app.get('job_id','')[:10]:<12}"
        f"  {app.get('company','')[:25]:<27}"
        f"  {app.get('role','')[:30]:<32}"
        f"  {score:>4}"
        f"  {app.get('priority',''):<8}"
        f"  {app.get('status','')}"
    )


def _print_table(apps: list):
    header = (
        f"  {'JOB ID':<12}  {'COMPANY':<27}  {'ROLE':<32}  {'SCR':>4}  {'PRIORITY':<8}  STATUS"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for a in apps:
        print(_fmt_row(a))
    print(f"\n  Total: {len(apps)}")


def _print_stats(stats, week: bool = False):
    if not stats:
        print("  No stats found.")
        return

    if isinstance(stats, list):
        # Week view
        print(f"\n  {'DATE':<12}  {'SCRAPED':>8}  {'TAILORED':>9}  {'APPLIED':>8}  {'SKIPPED':>8}  {'AVG SCORE':>10}")
        print("  " + "-" * 65)
        for s in stats:
            avg = f"{s.get('avg_match_score', 0):.1f}" if s.get("avg_match_score") else "  -"
            print(
                f"  {s.get('date',''):<12}"
                f"  {s.get('jobs_scraped',0):>8}"
                f"  {s.get('jobs_tailored',0):>9}"
                f"  {s.get('jobs_applied',0):>8}"
                f"  {s.get('jobs_skipped',0):>8}"
                f"  {avg:>10}"
            )
    else:
        # Single day
        s = stats
        print(f"\n  Date           : {s.get('date', datetime.now().strftime('%Y-%m-%d'))}")
        print(f"  Jobs Scraped   : {s.get('jobs_scraped', 0)}")
        print(f"  Tailored       : {s.get('jobs_tailored', 0)}  (ready to apply)")
        print(f"  Applied        : {s.get('jobs_applied', 0)}")
        print(f"  Skipped        : {s.get('jobs_skipped', 0)}")
        print(f"  High Priority  : {s.get('high_priority_count', 0)}")
        avg = s.get("avg_match_score")
        if avg:
            print(f"  Avg Match Score: {avg:.1f}")


# ── Subcommands ───────────────────────────────────────────────────────────────

def cmd_batch(args):
    """Run daily batch processing on urls.txt (or specified file)."""
    urls_file = args.input
    if not os.path.isfile(urls_file):
        print(f"[Error] URLs file not found: {urls_file}")
        print(f"  Create {urls_file} and paste job URLs (one per line).")
        sys.exit(1)

    orch = _get_orchestrator()
    results = orch.run_batch(urls_file)

    print("\nDone. Next steps:")
    print("  python run_daily.py list --status tailored   # See ready packages")
    print("  python run_daily.py followup                 # Follow-up reminders")


def cmd_single(args):
    """Process a single job URL."""
    if not args.url:
        print("[Error] --url is required")
        sys.exit(1)
    orch = _get_orchestrator()
    orch.run_single(args.url)


def cmd_status(args):
    """Show daily or weekly stats."""
    orch = _get_orchestrator()
    stats = orch.get_stats(week=args.week)
    label = "Weekly Stats (last 7 days)" if args.week else "Today's Stats"
    print(f"\n  {label}")
    print("  " + "=" * 50)
    _print_stats(stats, week=args.week)
    print()


def cmd_list(args):
    """List applications filtered by status/priority."""
    orch = _get_orchestrator()
    apps = orch.list_applications(status=args.status, priority=args.priority)

    filters = []
    if args.status:
        filters.append(f"status={args.status}")
    if args.priority:
        filters.append(f"priority={args.priority}")
    label = "Applications" + (f" [{', '.join(filters)}]" if filters else "")

    print(f"\n  {label}")
    print("  " + "=" * 90)
    if not apps:
        print("  (none found)")
    else:
        _print_table(apps)
    print()


def cmd_update(args):
    """Update status of an application."""
    if not args.job_id:
        print("[Error] job_id is required")
        sys.exit(1)
    if not args.status:
        print("[Error] --status is required")
        sys.exit(1)

    valid_statuses = [
        "pending", "tailored", "applied", "rejected",
        "screening", "interview", "offer", "declined", "ghosted"
    ]
    if args.status not in valid_statuses:
        print(f"[Error] Invalid status '{args.status}'. Valid: {', '.join(valid_statuses)}")
        sys.exit(1)

    orch = _get_orchestrator()
    orch.update_status(args.job_id, args.status, args.notes or "")
    print(f"  Updated: {args.job_id} → {args.status}")


def cmd_followup(args):
    """Show applications that need follow-up."""
    orch = _get_orchestrator()
    days = args.days
    apps = orch.get_followups(days=days)

    print(f"\n  Follow-up needed (applied {days}+ days ago, no response)")
    print("  " + "=" * 90)
    if not apps:
        print(f"  No follow-ups needed. (No applications applied {days}+ days ago without response)")
    else:
        _print_table(apps)
        print("\n  Action: Send a brief, professional follow-up email or LinkedIn message.")
        print("  Then:   python run_daily.py update <job_id> --status applied --notes 'Followed up'")
    print()


def cmd_report(args):
    """Generate a summary report."""
    orch = _get_orchestrator()
    stats = orch.get_stats(week=args.week)
    apps = orch.list_applications()

    print("\n  =" * 30)
    print("  JOBHUNTER AI — APPLICATION REPORT")
    if args.week:
        print("  Period: Last 7 days")
    print("  Generated:", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("  =" * 30)

    print("\n  STATS")
    _print_stats(stats, week=args.week)

    print("\n\n  ALL APPLICATIONS")
    print("  " + "=" * 90)
    if apps:
        _print_table(apps)
    else:
        print("  No applications tracked yet.")

    # Breakdown by status
    from collections import Counter
    status_counts = Counter(a.get("status", "unknown") for a in apps)
    print("\n\n  STATUS BREAKDOWN")
    print("  " + "-" * 30)
    for status, count in sorted(status_counts.items()):
        print(f"  {status:<15} {count:>3}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_daily.py",
        description="JobHunter AI — AI/ML Job Application Automation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_daily.py batch                             # Process urls.txt
  python run_daily.py batch --input my_jobs.txt        # Custom input file
  python run_daily.py single --url "https://..."       # Process one URL
  python run_daily.py status                           # Today's stats
  python run_daily.py status --week                    # 7-day stats
  python run_daily.py list --status tailored           # Ready-to-apply packages
  python run_daily.py list --priority high             # High-priority jobs
  python run_daily.py update abc123 --status applied   # Mark as applied
  python run_daily.py update abc123 --status interview --notes "Phone screen Mar 28"
  python run_daily.py followup                         # Follow-up reminders
  python run_daily.py report --week                    # Weekly report
        """
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # batch
    p_batch = sub.add_parser("batch", help="Run daily batch on a URLs file")
    p_batch.add_argument("--input", default="urls.txt", metavar="FILE",
                         help="Text file with job URLs, one per line (default: urls.txt)")

    # single
    p_single = sub.add_parser("single", help="Process a single job URL")
    p_single.add_argument("--url", required=True, help="Job listing URL")

    # status
    p_status = sub.add_parser("status", help="Show stats dashboard")
    p_status.add_argument("--week", action="store_true", help="Show last 7 days")

    # list
    p_list = sub.add_parser("list", help="List applications")
    p_list.add_argument("--status", help="Filter by status (e.g. applied, tailored, interview)")
    p_list.add_argument("--priority", help="Filter by priority (low, medium, high, critical)")

    # update
    p_update = sub.add_parser("update", help="Update application status")
    p_update.add_argument("job_id", help="Job ID (first 10+ chars from 'list' output)")
    p_update.add_argument("--status", required=True,
                          help="New status: pending|tailored|applied|rejected|screening|interview|offer|declined|ghosted")
    p_update.add_argument("--notes", default="", help="Optional notes")

    # followup
    p_followup = sub.add_parser("followup", help="Show applications needing follow-up")
    p_followup.add_argument("--days", type=int, default=5,
                            help="Days since application with no response (default: 5)")

    # report
    p_report = sub.add_parser("report", help="Generate full report")
    p_report.add_argument("--week", action="store_true", help="Include week stats")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "batch":   cmd_batch,
        "single":  cmd_single,
        "status":  cmd_status,
        "list":    cmd_list,
        "update":  cmd_update,
        "followup": cmd_followup,
        "report":  cmd_report,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
