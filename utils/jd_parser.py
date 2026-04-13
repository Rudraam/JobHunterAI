"""
JD Parser — Uses Claude API to extract structured data from raw job description text.
"""

import json
import re
import os
import anthropic
from typing import Optional

EXTRACTION_PROMPT = """Analyze this job description and extract structured data.
Return ONLY valid JSON with these exact fields (no markdown, no extra text):

{
  "responsibilities": ["list of key responsibilities"],
  "requirements": ["list of required qualifications"],
  "nice_to_haves": ["list of preferred/bonus qualifications"],
  "required_skills": ["Python", "PyTorch"],
  "tools_mentioned": ["Docker", "AWS", "Kubernetes"],
  "keywords": ["machine learning", "NLP", "production ML"],
  "soft_skills": ["leadership", "cross-functional"],
  "experience_years": "2-5",
  "education_requirement": "Bachelor's in CS or related",
  "salary_info": "Not mentioned",
  "remote_policy": "remote",
  "visa_sponsorship": "not mentioned"
}

Rules:
- required_skills: only technical skills explicitly listed as required
- tools_mentioned: specific tools/frameworks named anywhere in JD
- keywords: ATS-critical terms, use exact JD phrasing
- remote_policy: one of "remote", "hybrid", "onsite", "not mentioned"
- visa_sponsorship: one of "yes", "no", "not mentioned"
- Keep lists concise (max 10 items each). Be specific, not generic.

JOB DESCRIPTION:
{raw_jd_text}
"""


def parse_jd_with_llm(raw_text: str, api_key: Optional[str] = None) -> dict:
    """
    Call Claude API to extract structured fields from raw JD text.
    Returns a dict with all structured fields, or empty fallback on failure.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("[JDParser] Warning: No API key — returning empty parse.")
        return _empty_parse()

    client = anthropic.Anthropic(api_key=key)
    prompt = EXTRACTION_PROMPT.replace("{raw_jd_text}", raw_text[:8000])

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        content = message.content[0].text.strip()
        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[JDParser] JSON decode error: {e}")
        return _empty_parse()
    except Exception as e:
        print(f"[JDParser] LLM call failed: {e}")
        return _empty_parse()


def _empty_parse() -> dict:
    return {
        "responsibilities": [],
        "requirements": [],
        "nice_to_haves": [],
        "required_skills": [],
        "tools_mentioned": [],
        "keywords": [],
        "soft_skills": [],
        "experience_years": "not mentioned",
        "education_requirement": "not mentioned",
        "salary_info": "not mentioned",
        "remote_policy": "not mentioned",
        "visa_sponsorship": "not mentioned",
    }


def extract_experience_level(raw_text: str) -> str:
    """Heuristic experience level detection from raw JD text."""
    text = raw_text.lower()
    if any(p in text for p in ["10+ years", "10 or more years", "staff engineer", "principal"]):
        return "staff/principal"
    if any(p in text for p in ["7+ years", "8+ years", "senior staff"]):
        return "senior+"
    if any(p in text for p in ["5+ years", "6+ years", "senior"]):
        return "senior"
    if any(p in text for p in ["3+ years", "4+ years", "mid-level", "intermediate"]):
        return "mid"
    if any(p in text for p in ["1+ year", "2+ years", "junior", "entry level", "new grad"]):
        return "junior"
    return "mid"  # default assumption


def extract_salary_from_text(text: str) -> Optional[str]:
    """Extract salary info using regex patterns."""
    patterns = [
        r"\$[\d,]+\s*[-–—to]+\s*\$[\d,]+\s*(?:CAD|USD)?(?:\s*(?:per year|annually|/yr|/year))?",
        r"\$[\d,]+[kK]\s*[-–—to]+\s*\$[\d,]+[kK]\s*(?:CAD|USD)?",
        r"[\d,]+\s*[-–—to]+\s*[\d,]+\s*(?:CAD|USD)\s*(?:per hour|/hr|/hour)",
        r"CAD\s*\$?[\d,]+\s*[-–—to]+\s*\$?[\d,]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def clean_text(text: str) -> str:
    """Basic text cleaning for raw scraped content."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    return text.strip()
