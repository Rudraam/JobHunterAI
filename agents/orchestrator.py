"""
Master Orchestrator

Connects all agents and drives the daily batch workflow:
  Ingest → Scrape → Score → Tailor → Cover Letter → Package → Track
"""

import os
import csv
import json
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.scraper_agent import ScraperAgent, load_urls_from_file
from agents.quality_scorer_agent import QualityScorerAgent, get_decision, THRESHOLD_AUTO, THRESHOLD_REVIEW
from agents.resume_tailor_agent import ResumeTailorAgent
from agents.cover_letter_agent import CoverLetterAgent
from utils import db_manager
from utils.latex_compiler import compile_and_validate, cleanup_aux_files, CompilationError, PageCountError


class Orchestrator:

    def __init__(self, config: Optional[dict] = None, api_key: Optional[str] = None,
                 max_workers: int = 5):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print("[Orchestrator] WARNING: ANTHROPIC_API_KEY not set — LLM tailoring will be skipped")
            print("  Set it with:  export ANTHROPIC_API_KEY=sk-ant-...")
        self.scraper = ScraperAgent(api_key=key)
        self.scorer = QualityScorerAgent()
        self.tailor = ResumeTailorAgent(api_key=key)
        self.cover_letter = CoverLetterAgent(api_key=key)
        self.config = config or {}
        self.max_workers = max_workers

        # Ensure DB is initialised
        db_manager.init_db()

    # ── Path Helpers ──────────────────────────────────────────────────────────

    def _output_dir(self, jd) -> str:
        safe_company = "".join(c if c.isalnum() else "_" for c in jd.company)[:30]
        safe_role = "".join(c if c.isalnum() else "_" for c in jd.title)[:30]
        date_str = datetime.now().strftime("%Y%m%d")
        folder = f"{safe_company}__{safe_role}__{date_str}"
        return os.path.join("outputs", folder)

    # ── Core Pipeline ─────────────────────────────────────────────────────────

    def _process_single(self, url: str, stats: dict, force: bool = False) -> str:
        """
        Full pipeline for one URL.
        Returns one of: 'tailored', 'review', 'skipped', 'error'
        force=True bypasses the score threshold and always tailors.
        """
        # 1. Scrape
        jd = self.scraper.scrape(url)
        if not jd:
            db_manager.log_error(url, "Scraping failed — no content extracted")
            stats["errors"] += 1
            return "error"

        db_manager.upsert_daily_stats(
            date=datetime.now().strftime("%Y-%m-%d"),
            scraped=1,
        )

        # 2. Score
        score = self.scorer.score(jd)
        decision = get_decision(score)

        if not force:
            if decision == "skip":
                print(f"[Orchestrator] SKIP  {jd.company} — {jd.title}  (score={score:.1f})")
                db_manager.log_skip(jd, reason=f"Low match score: {score:.1f}")
                db_manager.upsert_daily_stats(
                    date=datetime.now().strftime("%Y-%m-%d"),
                    skipped=1,
                )
                stats["skipped"] += 1
                return "skipped"

            if decision == "review":
                print(f"[Orchestrator] REVIEW {jd.company} — {jd.title}  (score={score:.1f})")
                db_manager.log_review(jd)
                stats["review"] += 1
                return "review"
        else:
            print(f"[Orchestrator] FORCE-TAILOR {jd.company} — {jd.title}  (score={score:.1f})")

        # 3. Tailor resume
        output_dir = self._output_dir(jd)
        print(f"[Orchestrator] TAILOR {jd.company} — {jd.title}  (score={score:.1f})")

        try:
            tex_path = self.tailor.tailor(jd, output_dir)
            resume_pdf = None
            try:
                resume_pdf = compile_and_validate(tex_path, output_dir, expected_pages=1)
                cleanup_aux_files(output_dir, "resume")
            except (CompilationError, PageCountError) as e:
                print(f"[Orchestrator] Resume PDF compile error: {e}")
                print("[Orchestrator] Continuing with .tex only — check pdflatex installation")
        except Exception as e:
            print(f"[Orchestrator] Tailoring failed: {e}")
            db_manager.log_error(url, f"Tailoring error: {e}")
            stats["errors"] += 1
            return "error"

        # 4. Generate cover letter
        tailored_tex_content = ""
        if os.path.isfile(tex_path):
            with open(tex_path, "r", encoding="utf-8") as f:
                tailored_tex_content = f.read()

        try:
            cl_tex_path = self.cover_letter.generate(jd, output_dir, tailored_tex_content)
            try:
                compile_and_validate(cl_tex_path, output_dir, expected_pages=1)
                cleanup_aux_files(output_dir, "cover_letter")
            except (CompilationError, PageCountError) as e:
                print(f"[Orchestrator] Cover letter PDF compile error: {e}")
        except Exception as e:
            print(f"[Orchestrator] Cover letter generation failed: {e}")

        # 5. Log to DB
        db_manager.log_application(jd, output_dir, status="tailored")
        db_manager.upsert_daily_stats(
            date=datetime.now().strftime("%Y-%m-%d"),
            tailored=1,
            high_priority=1 if jd.priority in ("high", "critical") else 0,
        )

        stats["tailored"] += 1
        print(f"[Orchestrator] Package saved: {output_dir}")
        return "tailored"

    # ── Public API ────────────────────────────────────────────────────────────

    def run_batch(self, urls_file: str = "urls.txt") -> dict:
        """
        Main daily batch: read URLs from file, process each one.
        Returns summary dict with counts.
        """
        urls = load_urls_from_file(urls_file)
        if not urls:
            print(f"[Orchestrator] No URLs found in {urls_file}")
            return {}

        # Dedup against cache
        new_urls = [u for u in urls if not self.scraper.is_cached(u)]
        cached_count = len(urls) - len(new_urls)

        print(f"\n{'='*60}")
        print(f"  JobHunter AI — Batch Run  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  Total URLs: {len(urls)}  |  New: {len(new_urls)}  |  Cached: {cached_count}")
        print(f"{'='*60}\n")

        stats = {"tailored": 0, "review": 0, "skipped": 0, "errors": 0}
        stats_lock = __import__("threading").Lock()

        def _process_with_lock(idx_url):
            idx, url = idx_url
            print(f"\n[{idx}/{len(new_urls)}] Processing: {url[:80]}")
            local_stats = {"tailored": 0, "review": 0, "skipped": 0, "errors": 0}
            self._process_single(url, local_stats)
            with stats_lock:
                for k in stats:
                    stats[k] += local_stats[k]

        workers = min(self.max_workers, len(new_urls))
        print(f"[Orchestrator] Starting parallel processing with {workers} workers")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_with_lock, (i, url)): url
                for i, url in enumerate(new_urls, 1)
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    print(f"[Orchestrator] Unhandled error for {url[:60]}: {exc}")
                    with stats_lock:
                        stats["errors"] += 1

        self._print_summary(stats, len(new_urls))
        self._write_csv_report(stats)
        return stats

    def run_single(self, url: str, force: bool = False) -> str:
        """Process a single URL. force=True tailors regardless of score."""
        stats = {"tailored": 0, "review": 0, "skipped": 0, "errors": 0}
        result = self._process_single(url, stats, force=force)
        print(f"\n[Orchestrator] Result: {result.upper()}")
        return result

    def update_status(self, job_id: str, status: str, notes: str = ""):
        """Update application status in the database."""
        db_manager.update_status(job_id, status, notes)
        print(f"[Orchestrator] Updated {job_id}: {status}")
        if notes:
            print(f"  Notes: {notes}")

    def get_followups(self, days: int = 5) -> list:
        """Return applications that need follow-up."""
        return db_manager.get_followups(days)

    def get_stats(self, week: bool = False) -> dict:
        """Return today's or last 7 days of stats."""
        today = datetime.now().strftime("%Y-%m-%d")
        if week:
            return db_manager.get_stats()  # returns last 7 days
        return db_manager.get_stats(date=today)

    def list_applications(self, status: Optional[str] = None,
                          priority: Optional[str] = None) -> list:
        return db_manager.get_applications(status=status, priority=priority)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def _print_summary(self, stats: dict, total: int):
        print(f"\n{'='*60}")
        print(f"  BATCH COMPLETE")
        print(f"  Processed : {total}")
        print(f"  Tailored  : {stats['tailored']}  (ready to apply)")
        print(f"  Review    : {stats['review']}   (manual check needed)")
        print(f"  Skipped   : {stats['skipped']}  (low match)")
        print(f"  Errors    : {stats['errors']}")
        print(f"{'='*60}\n")

    def _write_csv_report(self, stats: dict):
        """Write a CSV summary of today's tailored applications."""
        today = datetime.now().strftime("%Y-%m-%d")
        apps = db_manager.get_applications(status="tailored")
        today_apps = [
            a for a in apps
            if a.get("created_at", "").startswith(today)
        ]
        if not today_apps:
            return

        reports_dir = os.path.join("outputs", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        csv_path = os.path.join(reports_dir, f"applications_{today}.csv")

        fieldnames = ["company", "role", "location", "match_score", "priority",
                      "status", "tailored_resume_path", "cover_letter_path", "url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(today_apps)

        print(f"[Orchestrator] CSV report: {csv_path}")
