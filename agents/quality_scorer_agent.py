"""
Agent 4: Match Quality Scorer

Scores each job-resume pair on match quality (0–100) to prioritize applications.
Uses a weighted multi-criteria scoring model.
"""

import re
import os
import yaml
from typing import Optional

from utils.skill_matcher import (
    extract_jd_skills, score_keyword_match, get_positive_signals, check_hard_exclusions
)

# Scoring weights (must sum to 1.0)
SCORING_WEIGHTS = {
    "keyword_match":       0.30,
    "experience_alignment": 0.25,
    "skill_coverage":      0.20,
    "seniority_fit":       0.10,
    "salary_alignment":    0.10,
    "location_match":      0.05,
}

# Thresholds
THRESHOLD_AUTO   = 60   # score >= 60: proceed to tailoring
THRESHOLD_REVIEW = 45   # score 45-59: manual review
# score < 45: skip

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"
)
_KEYWORDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "keywords.yaml"
)


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_keywords() -> dict:
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─── Individual Scoring Functions ────────────────────────────────────────────

def _score_keyword_match(jd) -> float:
    """
    Keyword match: % of JD keywords present in combined JD skills + raw text
    (simulating the resume having those keywords after tailoring).
    We score based on our skill pool coverage of the JD requirements.
    """
    all_approved_skills = _get_all_approved_skills()
    approved_lower = {s.lower() for s in all_approved_skills}

    jd_skills = set(s.lower() for s in jd.required_skills + jd.tools_mentioned)
    if not jd_skills:
        return 75.0  # no explicit skills listed → neutral score

    matched = jd_skills & approved_lower
    score = len(matched) / len(jd_skills) * 100
    return min(score, 100.0)


def _get_all_approved_skills() -> list[str]:
    kw = _load_keywords()
    skills = []
    pool = kw.get("approved_skills", {})
    for category in pool.values():
        skills.extend(category)
    return skills


def _score_experience_alignment(jd) -> float:
    """
    How well Rudra's 13-month AI/ML background aligns with the role's requirements.
    Checks for production ML keywords and experience year requirements.
    """
    raw = jd.raw_description.lower()
    responsibilities = " ".join(jd.responsibilities).lower()
    all_text = raw + " " + responsibilities

    # Keywords indicating alignment with Rudra's background
    alignment_keywords = [
        "machine learning", "deep learning", "NLP", "LLM", "generative AI",
        "RAG", "agentic", "AI agent", "PyTorch", "python", "fastapi",
        "model deployment", "model serving", "production ML", "MLOps",
        "fine-tuning", "embeddings", "vector", "transformer", "chatbot",
        "automation", "pipeline", "API", "cloud", "AWS", "Docker",
    ]
    matched = sum(1 for kw in alignment_keywords if kw.lower() in all_text)
    keyword_score = min(matched / len(alignment_keywords) * 100, 100.0)

    # Penalty for leadership/management-heavy roles (Rudra is IC)
    mgmt_keywords = ["director", "vp of", "vice president", "chief", "head of department"]
    if any(kw in all_text for kw in mgmt_keywords):
        keyword_score *= 0.7

    return keyword_score


def _score_skill_coverage(jd) -> float:
    """Required skills from JD that are in Rudra's approved pool."""
    all_approved = set(s.lower() for s in _get_all_approved_skills())
    required = set(s.lower() for s in jd.required_skills)

    if not required:
        return 70.0  # can't assess → neutral

    matched = required & all_approved
    return len(matched) / len(required) * 100


def _score_seniority_fit(jd) -> float:
    """
    Rudra has ~13 months professional experience (1yr+).
    Best fit: junior/mid-level roles.
    Penalty for senior (5+ yrs) and hard fail for staff+.
    """
    level = jd.experience_level.lower()
    exp_years_str = jd.experience_years.lower()

    # Extract year numbers from experience_years string
    numbers = re.findall(r"\d+", exp_years_str)
    min_years = int(numbers[0]) if numbers else 0

    if level in ("staff/principal",) or min_years >= 8:
        return 10.0
    if min_years >= 5 or level == "senior+":
        return 35.0
    if min_years >= 3 or level == "senior":
        return 60.0
    if min_years <= 2 or level in ("junior", "mid"):
        return 95.0
    return 75.0  # default


def _score_salary_alignment(jd) -> float:
    """Check if JD salary aligns with Rudra's target ($100K–$125K CAD)."""
    salary = (jd.salary_range or "").lower()
    if not salary or salary in ("not mentioned", ""):
        return 60.0  # unknown → neutral

    # Extract numbers from salary string
    nums = re.findall(r"\d[\d,]*", salary.replace(",", ""))
    if not nums:
        return 60.0

    values = [int(n) for n in nums]

    # Handle hourly rates (e.g., $50-$70/hr)
    if "hour" in salary or "/hr" in salary or "hourly" in salary:
        # Convert to annual (2080 hrs/year)
        annual_values = [v * 2080 for v in values]
    elif max(values) < 500:
        # Likely hourly
        annual_values = [v * 2080 for v in values]
    else:
        annual_values = values

    max_offer = max(annual_values)
    min_offer = min(annual_values)

    target_min = 100_000
    target_max = 130_000

    if max_offer < target_min * 0.85:
        return 20.0  # significantly below target
    if max_offer < target_min:
        return 50.0  # slightly below target
    if min_offer > target_max * 1.3:
        return 70.0  # above target but not a dealbreaker
    return 95.0  # within range


def _score_location_match(jd) -> float:
    """Check if the role is remote-friendly or Ontario-based."""
    remote_policy = (jd.remote_policy or "").lower()
    location = (jd.location or "").lower()
    raw = jd.raw_description.lower()

    positive = ["remote", "canada", "ontario", "toronto", "gta", "waterloo", "ottawa"]
    negative = ["must be located in", "on-site only", "in-person required",
                "us only", "united states only", "no remote"]

    if any(neg in raw for neg in negative):
        return 10.0
    if remote_policy == "remote" or "remote" in location:
        return 100.0
    if any(pos in location for pos in ["canada", "ontario", "toronto"]):
        return 90.0
    if remote_policy == "hybrid":
        return 70.0
    if any(pos in raw for pos in positive):
        return 75.0
    return 40.0  # unclear / onsite in unknown location


# ─── Main Scorer ──────────────────────────────────────────────────────────────

class QualityScorerAgent:

    def score(self, jd) -> float:
        """
        Score a JobDescription and set jd.match_score and jd.priority.
        Returns the score (0.0–100.0).
        """
        # Hard exclusion check
        exclusion = check_hard_exclusions(jd.raw_description)
        if exclusion:
            print(f"[Scorer] Hard exclusion matched: '{exclusion}' — score=0")
            jd.match_score = 0.0
            jd.priority = "skip"
            return 0.0

        component_scores = {
            "keyword_match":        _score_keyword_match(jd),
            "experience_alignment": _score_experience_alignment(jd),
            "skill_coverage":       _score_skill_coverage(jd),
            "seniority_fit":        _score_seniority_fit(jd),
            "salary_alignment":     _score_salary_alignment(jd),
            "location_match":       _score_location_match(jd),
        }

        # Bonus for positive signals
        signals = get_positive_signals(jd.raw_description)
        bonus = min(len(signals) * 2, 8)  # up to +8 points

        weighted = sum(
            component_scores[k] * SCORING_WEIGHTS[k]
            for k in SCORING_WEIGHTS
        )
        final_score = min(weighted + bonus, 100.0)
        final_score = round(final_score, 1)

        jd.match_score = final_score
        jd.priority = _assign_priority(final_score, component_scores, jd)

        self._print_score_breakdown(jd, component_scores, bonus, final_score)
        return final_score

    def _print_score_breakdown(self, jd, components: dict,
                                bonus: float, final: float):
        print(f"\n[Scorer] {jd.company} — {jd.title}")
        print(f"  {'Component':<25} {'Raw':>6}   {'Weighted':>8}")
        print(f"  {'-'*45}")
        for k, v in components.items():
            w = SCORING_WEIGHTS[k]
            print(f"  {k:<25} {v:>5.1f}%   {v*w:>7.1f}")
        print(f"  Positive signal bonus:         +{bonus:.1f}")
        print(f"  {'FINAL SCORE':<25} {final:>5.1f}  → {jd.priority.upper()}")


def _assign_priority(score: float, components: dict, jd) -> str:
    if score >= 80:
        return "critical"
    if score >= THRESHOLD_AUTO:
        return "high"
    if score >= THRESHOLD_REVIEW:
        return "medium"
    return "low"


def get_decision(score: float) -> str:
    """Return 'proceed', 'review', or 'skip' based on score."""
    if score >= THRESHOLD_AUTO:
        return "proceed"
    if score >= THRESHOLD_REVIEW:
        return "review"
    return "skip"
