"""
Skill Matcher — Keyword matching engine between JD requirements and Rudra's skill pool.
"""

import re
import os
import yaml
from typing import Optional

_KEYWORDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "keywords.yaml"
)


def _load_keywords() -> dict:
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_all_approved_skills(kw: dict) -> list[str]:
    skills = []
    pool = kw.get("approved_skills", {})
    for category in pool.values():
        skills.extend(category)
    return skills


def normalize_skill(skill: str, aliases: dict) -> str:
    """Normalize a skill name using the alias map (case-insensitive lookup)."""
    lower = skill.lower().strip()
    for alias, canonical in aliases.items():
        if alias.lower() == lower:
            return canonical
    return skill


def extract_jd_skills(jd_text: str) -> list[str]:
    """
    Find skills from the approved pool that appear in the JD text.
    Uses word-boundary matching to avoid partial matches.
    """
    kw = _load_keywords()
    approved = _get_all_approved_skills(kw)
    aliases = kw.get("skill_aliases", {})
    found = set()

    text_lower = jd_text.lower()

    for skill in approved:
        pattern = re.escape(skill.lower())
        if re.search(r"\b" + pattern + r"\b", text_lower):
            found.add(skill)

    # Also check alias keys → if JD has "sklearn" we map to "scikit-learn"
    for alias, canonical in aliases.items():
        if re.search(r"\b" + re.escape(alias.lower()) + r"\b", text_lower):
            found.add(canonical)

    return sorted(found)


def match_skills(jd_skills: list[str], resume_skills: list[str]) -> dict:
    """
    Compare JD-required skills to what's on the resume.
    Returns match stats used by the scorer.
    """
    jd_set = {s.lower() for s in jd_skills}
    resume_set = {s.lower() for s in resume_skills}
    matched = jd_set & resume_set
    missing = jd_set - resume_set

    coverage = len(matched) / len(jd_set) if jd_set else 1.0

    return {
        "matched": sorted(matched),
        "missing": sorted(missing),
        "coverage": round(coverage * 100, 1),
        "matched_count": len(matched),
        "total_jd_skills": len(jd_set),
    }


def get_skills_to_inject(jd_text: str, current_resume_skills: list[str]) -> list[str]:
    """
    Return skills from the approved pool that:
    1. Appear in the JD
    2. Are NOT already on the resume
    These are safe to inject (Rudra has them, just not listed).
    """
    jd_skills = extract_jd_skills(jd_text)
    resume_lower = {s.lower() for s in current_resume_skills}
    to_inject = [s for s in jd_skills if s.lower() not in resume_lower]
    return to_inject


def prioritize_skills_for_jd(all_resume_skills: list[str], jd_text: str) -> list[str]:
    """
    Reorder the resume skill list so JD-mentioned skills appear first.
    Returns a new ordered list.
    """
    jd_mentioned = {s.lower() for s in extract_jd_skills(jd_text)}
    prioritized = []
    rest = []
    for skill in all_resume_skills:
        if skill.lower() in jd_mentioned:
            prioritized.append(skill)
        else:
            rest.append(skill)
    return prioritized + rest


def check_hard_exclusions(jd_text: str) -> Optional[str]:
    """
    Check if JD contains any hard-exclusion phrases.
    Returns the matched phrase if excluded, None if safe.
    """
    kw = _load_keywords()
    exclusions = kw.get("hard_exclusions", [])
    text_lower = jd_text.lower()
    for phrase in exclusions:
        if phrase.lower() in text_lower:
            return phrase
    return None


def score_keyword_match(jd_keywords: list[str], resume_text: str) -> float:
    """
    ATS keyword match score: what % of JD keywords appear in the resume text.
    Returns 0.0–100.0.
    """
    if not jd_keywords:
        return 100.0
    resume_lower = resume_text.lower()
    matched = sum(
        1 for kw in jd_keywords
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", resume_lower)
    )
    return round(matched / len(jd_keywords) * 100, 1)


def get_positive_signals(jd_text: str) -> list[str]:
    """Return which positive signals are present in the JD."""
    kw = _load_keywords()
    signals = kw.get("positive_signals", {})
    text_lower = jd_text.lower()
    found = []
    for category, phrases in signals.items():
        for phrase in phrases:
            if phrase.lower() in text_lower:
                found.append(f"{category}:{phrase}")
                break  # one match per category is enough
    return found
