"""
Agent 3: Cover Letter Generator

Generates a compelling, personalized cover letter (LaTeX) for each job.
Complements the tailored resume — never repeats it verbatim.

INPUT:  JobDescription + tailored resume highlights
OUTPUT: .tex cover letter file
"""

import os
import re
import json
import anthropic
from datetime import date
from typing import Optional

COVER_LETTER_PROMPT = """You are an expert career consultant writing a cover letter for an AI/ML Engineer applying to a specific role.

CANDIDATE: Rudramani Dhiman
- Team Lead AI Engineer at Mesons Technologies Inc. (current, 2025–present)
- Built AI compliance service, ATS pipeline with ML-powered job recommendation engine
- Led small cross-functional team; drove MLOps practices (versioning, monitoring, deployment)
- Previous: AI Automation Engineer at Aisera AI (Feb 2024–Oct 2025)
  - Built QA automation framework for AI chatbots, integrated into CI/CD
  - Managed GPU inference pods (RunPod Serverless) for production model serving
  - Reduced chatbot failure rate through systematic failure pattern analysis
- Founded Veldrix AI startup: multi-tenant SaaS with RAG pipelines, vector DBs (Pinecone/FAISS),
  production FastAPI backend, React frontend, deployed on DigitalOcean + AWS, CI/CD via GitHub Actions
- Built Voyagera: agentic AI travel assistant with LLM tool-use, memory systems, multi-step planning
- Canadian status, based in Canada
- Advanced Diploma in Computer Programming (Canada), BCA in Data Science

JOB DETAILS:
Company: {company}
Role: {title}
Location: {location}
Remote Policy: {remote_policy}

Key Requirements:
{requirements}

Top Keywords / Culture Signals:
{keywords}

Soft Skills Emphasized:
{soft_skills}

RESUME HIGHLIGHTS (complement these — do NOT repeat verbatim):
{resume_highlights}

COVER LETTER RULES:

Paragraph 1 — OPENING HOOK (3–4 sentences):
- Do NOT start with "I am writing to apply for..." — this is forbidden
- Open with a specific, genuine reason for interest in THIS company/role
- Reference something concrete about the company (product, mission, tech stack, recent news, or what their AI work solves)
- End by connecting your background to why you're the right fit

Paragraph 2 — STRONGEST PROOF POINT (4–5 sentences):
- Connect your MOST relevant experience to their TOP requirement
- Include a specific accomplishment with a metric or concrete outcome
- Show you understand their problem space and have solved similar challenges
- Use language that mirrors the JD

Paragraph 3 — SECOND PROOF POINT / DEPTH (4–5 sentences):
- Bring in a second, distinct area of experience
- Reference Veldrix AI or Voyagera if relevant to the JD focus
- Demonstrate technical depth — be specific about what you built and how

Paragraph 4 — CLOSING (2–3 sentences):
- Express genuine enthusiasm for this specific role
- State what you'd bring in the first 90 days (concrete, confident)
- End with a professional call to action (no begging, just confidence)

STYLE REQUIREMENTS:
- Professional but with personality — not stiff or generic
- Confident, not arrogant
- Every sentence earns its place — no filler
- 350–450 words total
- Never use: "passionate", "team player", "hard worker", "detail-oriented" as standalone descriptors

LaTeX ESCAPING (apply to all special characters in output):
- & → \\&
- % → \\%
- $ → \\$
- # → \\#
- _ → \\_
- ^ → \\^{{}}
- ~ → \\textasciitilde{{}}

OUTPUT: Return ONLY the 4 paragraphs as plain text (no LaTeX formatting, just the paragraph text).
Each paragraph separated by a blank line.
Do NOT include salutation, closing, or signature — those come from the template.
"""


class CoverLetterAgent:

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._template = self._load_template()

    def _load_template(self) -> str:
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates", "cover_letter_template.tex"
        )
        if os.path.isfile(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _call_llm(self, jd, resume_highlights: str) -> Optional[str]:
        if not self.api_key:
            print("[CoverLetter] No API key — cannot generate cover letter")
            return None

        client = anthropic.Anthropic(api_key=self.api_key)

        requirements_text = "\n".join(f"- {r}" for r in jd.requirements[:8])
        keywords_text = ", ".join(jd.keywords[:15])
        soft_skills_text = ", ".join(jd.soft_skills[:8]) if jd.soft_skills else "Not specified"

        prompt = COVER_LETTER_PROMPT.format(
            company=jd.company,
            title=jd.title,
            location=jd.location,
            remote_policy=jd.remote_policy,
            requirements=requirements_text or "Not explicitly listed",
            keywords=keywords_text or "AI/ML engineering",
            soft_skills=soft_skills_text,
            resume_highlights=resume_highlights[:2000],
        )

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text.strip()
        except Exception as e:
            print(f"[CoverLetter] LLM call failed: {e}")
            return None

    def _build_latex(self, jd, body_text: str) -> str:
        """Fill the LaTeX template with generated content."""
        if not self._template:
            return self._build_fallback_latex(jd, body_text)

        today = date.today().strftime("%B %d, %Y")

        # Format body paragraphs as LaTeX paragraphs
        paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
        latex_body = "\n\n".join(paragraphs)

        tex = self._template
        tex = tex.replace("<<DATE>>", today)
        tex = tex.replace("<<HIRING_MANAGER_LINE>>", "Hiring Manager")
        tex = tex.replace("<<COMPANY_NAME>>", self._escape_latex(jd.company))
        tex = tex.replace("<<COMPANY_LOCATION>>", self._escape_latex(jd.location or "Canada"))
        tex = tex.replace("<<JOB_TITLE>>", self._escape_latex(jd.title))
        tex = tex.replace("<<JOB_ID_IF_AVAILABLE>>", "")
        tex = tex.replace("<<SALUTATION>>", "Dear Hiring Manager")
        tex = tex.replace("<<BODY>>", latex_body)

        return tex

    def _build_fallback_latex(self, jd, body_text: str) -> str:
        """Standalone LaTeX document when template file is unavailable."""
        today = date.today().strftime("%B %d, %Y")
        paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
        latex_body = "\n\n".join(paragraphs)
        company_escaped = self._escape_latex(jd.company)
        title_escaped = self._escape_latex(jd.title)
        location_escaped = self._escape_latex(jd.location or "Canada")

        return rf"""\documentclass[11pt]{{article}}
\usepackage[margin=1in]{{geometry}}
\usepackage[T1]{{fontenc}}
\usepackage[hidelinks]{{hyperref}}
\usepackage{{fontawesome5}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{8pt}}

\begin{{document}}

\begin{{center}}
    \textbf{{\Large Rudramani Dhiman}} \\[4pt]
    \small
    \faPhone*~+1 (437) 450-0315 \quad|\quad
    \faEnvelope~rudramanidhiman@gmail.com \quad|\quad
    \faLinkedin~rudramani-dhiman \quad|\quad
    \faMapMarker*~Canadian
\end{{center}}

\vspace{{12pt}}
{today}

\vspace{{8pt}}
Hiring Manager \\
{company_escaped} \\
{location_escaped}

\vspace{{8pt}}
\textbf{{Re: {title_escaped}}}

\vspace{{8pt}}
Dear Hiring Manager,

\vspace{{6pt}}
{latex_body}

\vspace{{8pt}}
Sincerely,\\[6pt]
Rudramani Dhiman

\end{{document}}
"""

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape special LaTeX characters in user-supplied strings."""
        replacements = [
            ("&", r"\&"),
            ("%", r"\%"),
            ("$", r"\$"),
            ("#", r"\#"),
            ("_", r"\_"),
        ]
        for char, escaped in replacements:
            text = text.replace(char, escaped)
        return text

    def _extract_resume_highlights(self, tailored_tex: str) -> str:
        """Pull key bullet points from tailored resume for the LLM context."""
        if not tailored_tex:
            return "Resume not yet generated."
        # Extract text from \resumeItem{...} commands
        items = re.findall(r"\\resumeItem\{([^}]+)\}", tailored_tex)
        if items:
            return "\n".join(f"- {item}" for item in items[:10])
        # Fallback: grab first 1500 chars of tex
        return tailored_tex[:1500]

    def generate(self, jd, output_dir: str,
                 tailored_tex: str = "") -> str:
        """
        Generate a cover letter .tex file for the given job.

        Args:
            jd:          JobDescription object
            output_dir:  Directory to write cover_letter.tex
            tailored_tex: Content of the tailored resume (for context)

        Returns:
            Path to the written .tex file.
        """
        print(f"[CoverLetter] Generating for: {jd.company} — {jd.title}")

        resume_highlights = self._extract_resume_highlights(tailored_tex)
        body_text = self._call_llm(jd, resume_highlights)

        if not body_text:
            body_text = self._generic_body(jd)

        latex = self._build_latex(jd, body_text)

        os.makedirs(output_dir, exist_ok=True)
        tex_path = os.path.join(output_dir, "cover_letter.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex)

        print(f"[CoverLetter] Wrote: {tex_path}")
        return tex_path

    def _generic_body(self, jd) -> str:
        """Minimal fallback body when LLM is unavailable."""
        return (
            f"I am excited to apply for the {jd.title} position at {jd.company}. "
            "With 13+ months of hands-on AI/ML engineering experience, I bring "
            "a strong foundation in production machine learning, LLM integration, "
            "and full-stack AI system development.\n\n"
            "In my current role as Team Lead AI Engineer at Mesons Technologies Inc., "
            "I have built AI compliance services, ML-powered ATS pipelines, and "
            "job recommendation engines that operate at production scale. "
            "I also manage MLOps practices including model versioning, monitoring, "
            "and deployment pipelines.\n\n"
            "As the founder of Veldrix AI, I independently architected and deployed "
            "a multi-tenant SaaS platform featuring RAG pipelines, vector database "
            "integration, and a production FastAPI backend. This experience gave me "
            "deep hands-on knowledge of end-to-end ML system design.\n\n"
            f"I would welcome the opportunity to bring this experience to {jd.company}. "
            "I am confident I can contribute meaningfully from day one and look forward "
            "to discussing how my background aligns with your team's goals."
        )
