"""
Agent 1: JD Scraper Agent

Accepts job listing URLs and extracts structured job description data.
Supports LinkedIn, Indeed, and generic career pages via:
  - requests + BeautifulSoup (fast path)
  - Playwright headless browser (JS-rendered fallback)

INPUT:  URL string
OUTPUT: JobDescription dataclass
"""

import re
import json
import time
import hashlib
import os
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from utils.jd_parser import parse_jd_with_llm, extract_experience_level, extract_salary_from_text, clean_text


# ─── Data Model ──────────────────────────────────────────────────────────────

@dataclass
class JobDescription:
    url: str
    job_id: str
    title: str
    company: str
    location: str
    salary_range: Optional[str]
    job_type: str
    experience_level: str
    posted_date: Optional[str]

    # Parsed content
    raw_description: str
    responsibilities: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    nice_to_haves: list = field(default_factory=list)

    # Extracted intelligence
    required_skills: list = field(default_factory=list)
    tools_mentioned: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    soft_skills: list = field(default_factory=list)

    # Extra parsed fields
    remote_policy: str = "not mentioned"
    visa_sponsorship: str = "not mentioned"
    experience_years: str = "not mentioned"
    education_requirement: str = "not mentioned"

    # Matching metadata
    match_score: float = 0.0
    priority: str = "medium"


def make_job_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ─── Platform-Specific Selectors ─────────────────────────────────────────────

PLATFORM_SELECTORS = {
    "linkedin.com": {
        "title": [".top-card-layout__title", "h1.t-24", ".job-details-jobs-unified-top-card__job-title h1"],
        "company": [".topcard__org-name-link", ".job-details-jobs-unified-top-card__company-name a", ".t-16.t-black.t-bold"],
        "location": [".topcard__flavor--bullet", ".job-details-jobs-unified-top-card__bullet"],
        "description": [".description__text", "#job-details", ".jobs-description__content"],
    },
    "indeed.com": {
        "title": ["h1.jobsearch-JobInfoHeader-title", "h1[data-testid='jobsearch-JobInfoHeader-title']"],
        "company": ["[data-company-name]", ".icl-u-lg-mr--sm.icl-u-xs-mr--xs"],
        "location": ["[data-testid='job-location']", ".icl-u-xs-mt--xs.icl-u-textColor--secondary"],
        "description": ["#jobDescriptionText", "[data-testid='jobDescriptionText']"],
    },
    "glassdoor.com": {
        "title": ["[data-test='job-title']", "h1.heading_Heading__BqX5J"],
        "company": ["[data-test='employerName']", ".employer-overview-link"],
        "location": ["[data-test='location']"],
        "description": ["[data-test='description']", ".jobDescriptionContent"],
    },
    "workday.com": {
        "title": ["[data-automation-id='jobPostingHeader']"],
        "company": [".css-1q2dra3"],
        "location": ["[data-automation-id='locations']"],
        "description": ["[data-automation-id='job-posting-description']"],
    },
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─── Core Scraper ─────────────────────────────────────────────────────────────

class ScraperAgent:
    def __init__(self, api_key: Optional[str] = None,
                 rate_limit_seconds: float = 5.0,
                 use_playwright: bool = True,
                 cache_path: str = "data/job_cache.json"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.rate_limit = rate_limit_seconds
        self.use_playwright = use_playwright
        self.cache_path = cache_path
        self._cache = self._load_cache()

    # ── Cache ──────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict:
        if os.path.isfile(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self, job_id: str, data: dict):
        self._cache[job_id] = data
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, indent=2)

    def is_cached(self, url: str) -> bool:
        return make_job_id(url) in self._cache

    # ── Platform Detection ─────────────────────────────────────────────────

    def _detect_platform(self, url: str) -> str:
        url_lower = url.lower()
        for platform in PLATFORM_SELECTORS:
            if platform in url_lower:
                return platform
        return "generic"

    # ── Requests + BS4 ────────────────────────────────────────────────────

    def _fetch_with_requests(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            print(f"[Scraper] requests failed for {url}: {e}")
            return None

    def _extract_with_selectors(self, soup: BeautifulSoup,
                                 selectors: list[str]) -> str:
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator=" ", strip=True)
        return ""

    def _scrape_with_requests(self, url: str, platform: str) -> Optional[dict]:
        soup = self._fetch_with_requests(url)
        if not soup:
            return None

        selectors = PLATFORM_SELECTORS.get(platform, {})

        title = self._extract_with_selectors(soup, selectors.get("title", []))
        company = self._extract_with_selectors(soup, selectors.get("company", []))
        location = self._extract_with_selectors(soup, selectors.get("location", []))
        description = self._extract_with_selectors(soup, selectors.get("description", []))

        if not description:
            # Fallback: grab the largest <div> text block
            all_divs = soup.find_all("div")
            if all_divs:
                description = max(
                    (d.get_text(separator=" ", strip=True) for d in all_divs),
                    key=len, default=""
                )

        return {
            "title": title,
            "company": company,
            "location": location,
            "raw_description": clean_text(description),
        }

    # ── Playwright ────────────────────────────────────────────────────────

    def _scrape_with_playwright(self, url: str, platform: str) -> Optional[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[Scraper] Playwright not installed. Run: pip install playwright && playwright install chromium")
            return None

        selectors = PLATFORM_SELECTORS.get(platform, {})

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                    locale="en-US",
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)  # let JS settle

                def try_selectors(sels: list[str]) -> str:
                    for sel in sels:
                        try:
                            el = page.query_selector(sel)
                            if el:
                                return el.inner_text().strip()
                        except Exception:
                            pass
                    return ""

                title = try_selectors(selectors.get("title", []))
                company = try_selectors(selectors.get("company", []))
                location = try_selectors(selectors.get("location", []))
                description = try_selectors(selectors.get("description", []))

                if not description:
                    description = page.inner_text("body")

                browser.close()

            return {
                "title": title,
                "company": company,
                "location": location,
                "raw_description": clean_text(description[:10000]),
            }
        except Exception as e:
            print(f"[Scraper] Playwright failed for {url}: {e}")
            return None

    # ── Main Entry Point ───────────────────────────────────────────────────

    def scrape(self, url: str) -> Optional[JobDescription]:
        """
        Scrape a job URL and return a populated JobDescription.
        Returns None if scraping fails entirely.
        """
        job_id = make_job_id(url)
        platform = self._detect_platform(url)

        print(f"[Scraper] Processing: {url[:80]}  (platform={platform})")
        time.sleep(self.rate_limit)

        # Try requests first (fast); fall back to Playwright
        raw = self._scrape_with_requests(url, platform)
        if (not raw or not raw.get("raw_description")) and self.use_playwright:
            print(f"[Scraper] Falling back to Playwright for {url[:60]}")
            raw = self._scrape_with_playwright(url, platform)

        if not raw or not raw.get("raw_description"):
            print(f"[Scraper] Failed to extract content from {url}")
            return None

        raw_text = raw["raw_description"]

        # LLM-based structured extraction
        print(f"[Scraper] Parsing JD with LLM...")
        parsed = parse_jd_with_llm(raw_text, api_key=self.api_key)

        # Build JobDescription
        jd = JobDescription(
            url=url,
            job_id=job_id,
            title=raw.get("title") or parsed.get("title", "Unknown Role"),
            company=raw.get("company") or "Unknown Company",
            location=raw.get("location") or "Not specified",
            salary_range=extract_salary_from_text(raw_text) or parsed.get("salary_info"),
            job_type=self._infer_job_type(raw_text),
            experience_level=extract_experience_level(raw_text),
            posted_date=None,
            raw_description=raw_text,
            responsibilities=parsed.get("responsibilities", []),
            requirements=parsed.get("requirements", []),
            nice_to_haves=parsed.get("nice_to_haves", []),
            required_skills=parsed.get("required_skills", []),
            tools_mentioned=parsed.get("tools_mentioned", []),
            keywords=parsed.get("keywords", []),
            soft_skills=parsed.get("soft_skills", []),
            remote_policy=parsed.get("remote_policy", "not mentioned"),
            visa_sponsorship=parsed.get("visa_sponsorship", "not mentioned"),
            experience_years=parsed.get("experience_years", "not mentioned"),
            education_requirement=parsed.get("education_requirement", "not mentioned"),
        )

        # Cache the result
        self._save_cache(job_id, {
            "url": url,
            "title": jd.title,
            "company": jd.company,
            "job_id": job_id,
        })

        print(f"[Scraper] Done: {jd.company} — {jd.title}")
        return jd

    def _infer_job_type(self, text: str) -> str:
        text_lower = text.lower()
        if "contract" in text_lower or "contractor" in text_lower:
            return "contract"
        if "part-time" in text_lower or "part time" in text_lower:
            return "part-time"
        if "intern" in text_lower:
            return "internship"
        return "full-time"

    def scrape_batch(self, urls: list[str],
                     skip_cached: bool = True) -> list[JobDescription]:
        """Scrape multiple URLs, optionally skipping cached ones."""
        results = []
        for url in urls:
            url = url.strip()
            if not url or url.startswith("#"):
                continue
            if skip_cached and self.is_cached(url):
                print(f"[Scraper] Skipping cached: {url[:60]}")
                continue
            jd = self.scrape(url)
            if jd:
                results.append(jd)
        return results


def load_urls_from_file(path: str) -> list[str]:
    """Load URLs from a text file (one per line, # for comments)."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
