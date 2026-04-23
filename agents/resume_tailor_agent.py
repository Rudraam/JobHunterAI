"""
Agent 2: Resume Tailor Agent

Two-pass architecture:
  Pass 1 — Strategic Analysis: extract primary hiring signal, keyword priorities
  Pass 2 — Strategy-Informed Generation: write tailored LaTeX using the strategy
  Pass 3 — LaTeX Validation: catch escaping/brace errors before compilation
  Pass 4 — Quality Scoring: LLM rates the output against the JD
  Pass 5 — Refinement: fix specific issues if quality score < 80
"""

import re
import os
import json
import anthropic
from typing import Optional

from utils.skill_matcher import prioritize_skills_for_jd, get_skills_to_inject
from utils.latex_compiler import compile_and_validate, cleanup_aux_files, PageCountError

BASE_RESUME_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "base_resume.tex"
)

# ── Pass 1: Strategic Analysis ────────────────────────────────────────────────

STRATEGY_PROMPT = """You are a senior technical recruiter analyzing a job description to identify
EXACTLY what would make an AI/ML Engineer candidate stand out for THIS specific role.

JOB DESCRIPTION:
Company: {company}
Title: {title}
Description:
{description}

Analyze and return ONLY valid JSON with this exact structure (no markdown fences, no extra text):

{{
  "primary_signal": "The ONE thing this role is really hiring for (e.g., 'production LLM systems at scale', 'research-to-production ML pipeline', 'MLOps and infrastructure depth')",

  "must_have_keywords": ["8-12 keywords that MUST appear in the resume for ATS — use JD's exact wording"],

  "should_have_keywords": ["8-12 secondary keywords that strengthen the match"],

  "experience_emphasis": "Which of Rudra's experiences should lead? Options: mesons_compliance, mesons_ats_pipeline, mesons_recommendation_engine, mesons_mlops, aisera_qa_framework, aisera_chatbot_testing, aisera_gpu_management, veldrix_rag, veldrix_saas, voyagera_agents",

  "narrative_angle": "What story should this resume tell? E.g., 'builder of production AI systems that ship', 'researcher who closes the loop to deployment', 'startup operator with MLOps depth'",

  "tone_signals": "What tone does this company use? E.g., 'fast-paced startup', 'enterprise corporate', 'research lab', 'consultancy'",

  "red_flags_to_avoid": ["things that would hurt — e.g., 'too much chatbot/QA focus for an infra role'"],

  "metrics_to_emphasize": ["which quantified achievements matter most for THIS role"],

  "skill_priorities": {{
    "languages": ["ordered list — most JD-relevant first"],
    "ml_frameworks": ["ordered list"],
    "cloud_devops": ["ordered list"],
    "tools": ["ordered list"]
  }},

  "company_intelligence": "Anything about this company's tech stack, mission, or culture that should subtly shape the resume",

  "competitive_positioning": "What kind of candidates is Rudra competing against? How can he differentiate?"
}}
"""

# ── Pass 2: Strategy-Informed Generation ─────────────────────────────────────

GENERATION_PROMPT = """You are an elite resume writer crafting a tailored resume for an AI/ML Engineer.
You have a complete strategic analysis of the role and full creative latitude within truthfulness.

═══════════════════════════════════════════════════════════════
CANDIDATE PROFILE — Rudramani Dhiman (Canadian, Toronto, ON)
═══════════════════════════════════════════════════════════════

CURRENT ROLE: Team Lead AI Engineer at Mesons Technologies Inc. (Dec 2025 – Present)
Real accomplishments (reframe freely; do NOT invent):
- Architected AI-powered compliance service integrated into core product suite
- Built end-to-end ATS pipeline: resume parsing, candidate ranking, job matching with NLP
- Engineered job recommendation engine using collaborative filtering + LLM embeddings (40%+ relevance lift)
- Established MLOps practices: model versioning, eval pipelines, CI/CD for model deployment
- Led cross-functional collaboration with product/backend on AI feature roadmap
- Mentored junior engineers on ML best practices
- Production deployment of LLM-powered features handling real customer traffic

PREVIOUS ROLE: AI Automation Engineer at Aisera AI (Feb 2024 – Oct 2025)
Real accomplishments:
- Built automated testing scripts for AI chatbots: conversation flow, intent detection, edge cases
- Created comprehensive QA automation framework in Python (60% reduction in manual testing)
- Managed GPU-backed inference pods on cloud (high availability, autoscaling for peak traffic)
- Analyzed conversation logs to identify failure patterns; collaborated with ML team on retraining (25% accuracy improvement)
- Wrote documentation enabling faster engineer onboarding
- Worked with production LLM serving infrastructure (RunPod Serverless)

PROJECTS:
1. Veldrix AI (Founder, 2024–Present): AI startup deployed on DigitalOcean with auto-scaling and CI/CD.
   Multi-tenant SaaS, RAG pipelines, AI workflow automation, conversational AI interface,
   role-based access, usage analytics. Vector DBs: Pinecone/FAISS. Backend: FastAPI. Frontend: React.

2. Voyagera (2024): Agentic AI travel assistant. End-to-end trip planning with LLM function
   calling and tool use. Live API integrations (weather, maps, booking). Memory-augmented
   conversation system. Multi-step reasoning and planning.

EDUCATION:
- Advanced Diploma in Computer Programming and Analysis, George Brown College -- Casa Loma Campus, Toronto, ON (Sep 2023 – Apr 2026)
- Bachelor of Computer Applications (BCA) in Data Science, Chandigarh University, India (Jul 2025 – Present, online)

APPROVED SKILL POOL (inject ONLY from this list — never add skills not listed here):
Languages: Python, TypeScript, JavaScript, Java, Go, SQL, Bash, C++
AI/ML: PyTorch, TensorFlow, scikit-learn, Hugging Face Transformers, LangChain, LlamaIndex,
       OpenAI API, Anthropic API, NLP, LLMs, Agentic AI, Generative AI, Deep Learning, RAG,
       Embeddings, Fine-tuning, Prompt Engineering, Vector Databases (Pinecone, Chroma, Weaviate, FAISS),
       MLflow, Weights & Biases, Computer Vision, ONNX, Model Quantization, Reranking
Cloud/DevOps: AWS (EC2, S3, Lambda, SageMaker, Secrets Manager, ECR, CloudWatch),
              DigitalOcean, GCP basics, Docker, Kubernetes, CI/CD (Jenkins, GitHub Actions),
              RunPod Serverless, Terraform basics, Linux, Nginx
Backend/Tools: FastAPI, Flask, Django, Next.js, React, PostgreSQL, MongoDB, Redis,
               Celery, RabbitMQ, REST APIs, GraphQL basics, Git, pytest

═══════════════════════════════════════════════════════════════
STRATEGIC ANALYSIS FOR THIS ROLE
═══════════════════════════════════════════════════════════════
{strategy_json}

═══════════════════════════════════════════════════════════════
JOB DESCRIPTION
═══════════════════════════════════════════════════════════════
Company: {company}
Title: {title}
Location: {location}
Remote Policy: {remote_policy}
Experience Required: {experience_years}

Key Responsibilities:
{responsibilities}

Required Skills:
{required_skills}

ATS Keywords:
{keywords}

═══════════════════════════════════════════════════════════════
CURRENT RESUME SECTIONS (for reference)
═══════════════════════════════════════════════════════════════
{current_resume_sections}

ADDITIONAL SKILLS TO INJECT (approved pool, not currently listed):
{skills_to_inject}

═══════════════════════════════════════════════════════════════
GENERATION INSTRUCTIONS
═══════════════════════════════════════════════════════════════

Return ONLY a valid JSON object — no markdown fences, no explanation, no extra text.

SKILLS SECTION RULES:
- Use strategy's skill_priorities to reorder — front-load must_have_keywords
- Inject skills_to_inject where relevant
- Keep 4-category format: Languages | AI/ML | Cloud & DevOps | Tools & Frameworks
- Format: \\textbf{{Languages:}} Python, TypeScript, ...

EXPERIENCE RULES:
- 4-5 bullets per role (Mesons + Aisera)
- Lead with the bullet that maps to primary_signal
- Every bullet starts with strong action verb: Architected, Engineered, Deployed, Optimized,
  Built, Led, Designed, Reduced, Increased, Automated, Implemented, Developed
- Every bullet has a quantified outcome where truthful (%, time saved, scale, accuracy delta)
- Mirror JD language naturally — if JD says "production ML", say "production ML"
- Bold key technical terms with \\textbf{{}}
- Max 30 words per bullet after stripping LaTeX commands
- Each bullet maps to a REAL accomplishment listed above — no invention

PROJECTS RULES:
- Choose the 2 projects most relevant to primary_signal
- Put most relevant first
- 3-4 bullets each
- Same rules as experience bullets

ATS OPTIMIZATION:
- Cover 90%+ of must_have_keywords
- Use both long and short forms: "Large Language Models (LLMs)", "Continuous Integration (CI)"
- Match JD's exact tool names

ONE-PAGE CONSTRAINT:
Skills (4 lines) + Mesons (4-5 bullets ≤30 words each) + Aisera (4-5 bullets ≤30 words each)
+ 2 projects (3 bullets each) must fit on one US Letter page.

CRITICAL: Escape ALL LaTeX special characters: & → \\&, % → \\%, $ → \\$, # → \\#

Return this exact JSON structure:
{{
  "skills_section": "...full \\\\section{{SKILLS}} block content...",
  "experience_mesons": "...\\\\resumeItemListStart...\\\\resumeItemListEnd block...",
  "experience_aisera": "...\\\\resumeItemListStart...\\\\resumeItemListEnd block...",
  "projects_section": "...full LaTeX for 2 project entries...",
  "reasoning": "1-2 sentences on the strategic choices made"
}}

Use the EXACT same custom LaTeX commands as the original:
\\resumeItem, \\resumeSubheading, \\resumeProjectHeading,
\\resumeItemListStart, \\resumeItemListEnd,
\\resumeSubHeadingListStart, \\resumeSubHeadingListEnd
"""

# ── Pass 4: Quality Scoring ───────────────────────────────────────────────────

QUALITY_PROMPT = """You are a brutal resume reviewer. Score this tailored resume against
the job description. Be harsh — a score of 70 means real problems exist.

JOB DESCRIPTION:
Company: {company}
Title: {title}
Key Requirements: {requirements}
Must-Have Keywords: {must_have_keywords}

GENERATED RESUME CONTENT:
Skills Section:
{skills_section}

Mesons Bullets:
{mesons_bullets}

Aisera Bullets:
{aisera_bullets}

Projects:
{projects_section}

Return ONLY valid JSON:
{{
  "ats_keyword_score": 0-100,
  "experience_alignment_score": 0-100,
  "specificity_score": 0-100,
  "overall_score": 0-100,
  "missing_keywords": ["important JD keywords missing from resume"],
  "weak_bullets": ["vague, generic, or low-impact bullets that should be replaced"],
  "strong_bullets": ["bullets that clearly nail the JD requirements"],
  "issues": ["specific problems to fix — be concrete"],
  "verdict": "ship_it | needs_refinement | regenerate"
}}
"""

# ── Pass 5: Refinement ────────────────────────────────────────────────────────

REFINEMENT_PROMPT = """The following resume content needs TARGETED improvements.
Do NOT regenerate from scratch — fix ONLY the specific issues listed. Preserve strong bullets.

CURRENT CONTENT:
{current_content}

ISSUES TO FIX:
{issues}

MISSING KEYWORDS TO ADD:
{missing_keywords}

JOB CONTEXT:
Company: {company}, Title: {title}
Primary Signal: {primary_signal}

Return the full updated JSON in the SAME structure as before, with only problematic content changed.
No markdown fences, no explanation.
"""


class ResumeTailorAgent:

    def __init__(self, api_key: Optional[str] = None,
                 base_resume_path: str = BASE_RESUME_PATH,
                 quality_threshold: int = 80):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_resume_path = base_resume_path
        self.quality_threshold = quality_threshold
        self._base_tex = self._load_base_resume()

    def _load_base_resume(self) -> str:
        if not os.path.isfile(self.base_resume_path):
            raise FileNotFoundError(
                f"Base resume not found: {self.base_resume_path}\n"
                "Place your resume LaTeX at data/base_resume.tex"
            )
        with open(self.base_resume_path, "r", encoding="utf-8") as f:
            return f.read()

    def _make_client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=self.api_key)

    def _get_model(self) -> str:
        """Read model from config/settings.yaml, fall back to env var, then default."""
        env_model = os.environ.get("CLAUDE_MODEL", "")
        if env_model:
            return env_model
        try:
            import yaml
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
            return cfg.get("api", {}).get("claude_model", "claude-sonnet-4-6")
        except Exception:
            return "claude-sonnet-4-6"

    # ── Section Extraction ─────────────────────────────────────────────────

    def _extract_section(self, tex: str, section_name: str) -> str:
        pattern = rf"\\section\{{{re.escape(section_name)}\}}(.*?)(?=\\section\{{|\\end\{{document\}})"
        match = re.search(pattern, tex, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_all_modifiable_sections(self, tex: str) -> str:
        skills = self._extract_section(tex, "Technical Skills")
        experience = self._extract_section(tex, "Experience")
        projects = self._extract_section(tex, "Projects")
        return f"=== SKILLS ===\n{skills}\n\n=== EXPERIENCE ===\n{experience}\n\n=== PROJECTS ===\n{projects}"

    def _extract_current_skills_list(self, tex: str) -> list[str]:
        skills_section = self._extract_section(tex, "Technical Skills")
        cleaned = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", skills_section)
        cleaned = re.sub(r"\\[a-zA-Z]+", "", cleaned)
        cleaned = re.sub(r"[{}]", "", cleaned)
        skills = [s.strip() for s in re.split(r"[,\n]", cleaned) if s.strip()]
        return [s for s in skills if len(s) > 1]

    # ── LaTeX Section Replacement ──────────────────────────────────────────

    def _replace_section(self, tex: str, section_name: str, new_content: str) -> str:
        pattern = rf"(\\section\{{{re.escape(section_name)}\}})(.*?)(?=\\section\{{|\\end\{{document\}})"

        def replacer(m):
            return m.group(1) + "\n" + new_content + "\n"

        new_tex, count = re.subn(pattern, replacer, tex, flags=re.DOTALL | re.IGNORECASE)
        if count == 0:
            print(f"[Tailor] Warning: section '{section_name}' not found in template")
        return new_tex

    def _replace_company_bullets(self, tex: str, company_keyword: str,
                                  new_bullets_latex: str) -> str:
        pattern = (
            rf"(\\resumeSubheading\s*\{{[^}}]*{re.escape(company_keyword)}[^}}]*\}}"
            rf"(?:\s*\{{[^}}]*\}})*\s*)"
            rf"(\\resumeItemListStart.*?\\resumeItemListEnd)"
        )

        def replacer(m):
            return m.group(1) + new_bullets_latex

        new_tex, count = re.subn(
            pattern, replacer, tex, flags=re.DOTALL | re.IGNORECASE
        )
        if count == 0:
            print(f"[Tailor] Warning: company block '{company_keyword}' not found")
        return new_tex

    # ── LaTeX Validation ───────────────────────────────────────────────────

    def _validate_latex(self, content: dict) -> list[str]:
        """Catch LaTeX errors before pdflatex sees them."""
        errors = []

        def check_str(key: str, value: str):
            # Unescaped special characters (not already preceded by backslash)
            unescaped = re.findall(r'(?<!\\)([&%$#])', value)
            if unescaped:
                errors.append(f"{key}: unescaped chars {unescaped}")
            # Unbalanced braces
            open_b = value.count('{') - value.count('\\{')
            close_b = value.count('}') - value.count('\\}')
            if open_b != close_b:
                errors.append(f"{key}: unbalanced braces (open={open_b}, close={close_b})")

        for key, value in content.items():
            if isinstance(value, str):
                check_str(key, value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        check_str(f"{key}[{i}]", item)

        return errors

    # ── LLM Calls ─────────────────────────────────────────────────────────

    def _restore_latex_backslashes(self, obj):
        """
        Fix LaTeX commands corrupted by JSON escape sequence parsing.

        When the LLM emits single backslashes in JSON, json.loads() interprets
        certain sequences as control characters, eating the letter:
          \r → CR (0x0D)  — destroys \resumeItem, \renewcommand
          \t → TAB (0x09) — destroys \textbf, \textit, \textasciitilde
          \b → BS (0x08)  — destroys \begin, \bfseries
          \f → FF (0x0C)  — destroys \fill
          \n → LF (0x0A)  — destroys \newcommand, \noindent
          \v → VT (0x0B)  — destroys \vspace, \vcenter

        We detect control-char + known suffix and restore the full command.
        """
        if isinstance(obj, str):
            # CR (\r=0x0D) ate 'r': restore \r + esum → \resum, etc.
            obj = obj.replace('\x0Desum', '\\resum')
            obj = obj.replace('\x0Denew', '\\renew')
            # TAB (\t=0x09) ate 't': restore
            obj = obj.replace('\x09ext', '\\text')
            obj = obj.replace('\x09it', '\\tit')
            obj = obj.replace('\x09ab', '\\tab')
            # BS (\b=0x08) ate 'b': restore
            obj = obj.replace('\x08egin', '\\begin')
            obj = obj.replace('\x08f', '\\bf')
            # FF (\f=0x0C) ate 'f': restore
            obj = obj.replace('\x0Cill', '\\fill')
            obj = obj.replace('\x0Canc', '\\fanc')
            # LF (\n=0x0A) ate 'n': restore
            obj = obj.replace('\x0Aoindent', '\\noindent')
            obj = obj.replace('\x0Aewc', '\\newc')
            obj = obj.replace('\x0Aewl', '\\newl')
            # VT (\v=0x0B) ate 'v': restore
            obj = obj.replace('\x0Bspace', '\\vspace')
            obj = obj.replace('\x0Bcenter', '\\vcenter')
            # Also catch any remaining control chars before letters
            # (won't recover the eaten letter, but prevents garbage in output)
            obj = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F](?=[a-zA-Z])', r'\\', obj)
            return obj
        if isinstance(obj, dict):
            return {k: self._restore_latex_backslashes(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._restore_latex_backslashes(v) for v in obj]
        return obj

    def _call_llm(self, prompt: str, purpose: str) -> Optional[dict]:
        """Generic LLM call that returns parsed JSON or None on failure."""
        if not self.api_key:
            print(f"[Tailor] No API key — skipping {purpose}")
            return None
        try:
            client = self._make_client()
            message = client.messages.create(
                model=self._get_model(),
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            content = message.content[0].text.strip()
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            parsed = json.loads(content)
            return self._restore_latex_backslashes(parsed)
        except json.JSONDecodeError as e:
            print(f"[Tailor] JSON parse error in {purpose}: {e}")
            return None
        except Exception as e:
            print(f"[Tailor] LLM call failed ({purpose}): {e}")
            return None

    def _pass1_strategy(self, jd) -> Optional[dict]:
        """Pass 1: Analyze what this role is really hiring for."""
        print(f"[Tailor] Pass 1 — Strategic analysis for {jd.company}")
        description = jd.raw_description[:3000] if hasattr(jd, 'raw_description') else str(jd)
        prompt = STRATEGY_PROMPT.format(
            company=jd.company,
            title=jd.title,
            description=description,
        )
        strategy = self._call_llm(prompt, "strategy analysis")
        if strategy:
            print(f"[Tailor]   Primary signal: {strategy.get('primary_signal', 'N/A')}")
            print(f"[Tailor]   Must-have keywords: {len(strategy.get('must_have_keywords', []))} found")
        return strategy

    def _pass2_generate(self, jd, strategy: Optional[dict],
                        current_sections: str, skills_to_inject: list[str]) -> Optional[dict]:
        """Pass 2: Generate tailored content using strategy guidance."""
        print(f"[Tailor] Pass 2 — Strategy-informed generation")
        responsibilities_text = "\n".join(f"- {r}" for r in jd.responsibilities[:8])
        required_skills_text = ", ".join(jd.required_skills[:15])
        keywords_text = ", ".join(jd.keywords[:20])
        inject_text = ", ".join(skills_to_inject[:10]) if skills_to_inject else "None"
        strategy_json = json.dumps(strategy, indent=2) if strategy else '{"note": "No strategy available"}'

        prompt = GENERATION_PROMPT.format(
            strategy_json=strategy_json,
            company=jd.company,
            title=jd.title,
            location=jd.location,
            remote_policy=jd.remote_policy,
            experience_years=jd.experience_years,
            responsibilities=responsibilities_text or "Not specified",
            required_skills=required_skills_text or "Not specified",
            keywords=keywords_text or "Not specified",
            current_resume_sections=current_sections,
            skills_to_inject=inject_text,
        )
        return self._call_llm(prompt, "generation")

    def _pass4_score(self, jd, content: dict, strategy: Optional[dict]) -> Optional[dict]:
        """Pass 4: Quality score the generated content against the JD."""
        print(f"[Tailor] Pass 4 — Quality scoring")
        must_have = strategy.get("must_have_keywords", []) if strategy else []
        requirements = ", ".join(jd.required_skills[:15]) if hasattr(jd, 'required_skills') else ""

        mesons_text = content.get("experience_mesons", "")
        aisera_text = content.get("experience_aisera", "")

        prompt = QUALITY_PROMPT.format(
            company=jd.company,
            title=jd.title,
            requirements=requirements,
            must_have_keywords=", ".join(must_have),
            skills_section=content.get("skills_section", ""),
            mesons_bullets=mesons_text,
            aisera_bullets=aisera_text,
            projects_section=content.get("projects_section", ""),
        )
        return self._call_llm(prompt, "quality scoring")

    def _pass5_refine(self, jd, content: dict, quality: dict,
                      strategy: Optional[dict]) -> Optional[dict]:
        """Pass 5: Targeted refinement addressing specific issues."""
        print(f"[Tailor] Pass 5 — Refinement (score was {quality.get('overall_score', '?')})")
        issues = quality.get("issues", [])
        missing_keywords = quality.get("missing_keywords", [])
        primary_signal = strategy.get("primary_signal", "") if strategy else ""

        prompt = REFINEMENT_PROMPT.format(
            current_content=json.dumps(content, indent=2),
            issues=json.dumps(issues, indent=2),
            missing_keywords=json.dumps(missing_keywords, indent=2),
            company=jd.company,
            title=jd.title,
            primary_signal=primary_signal,
        )
        refined = self._call_llm(prompt, "refinement")
        return refined if refined else content

    # ── Main Tailoring Entry Point ─────────────────────────────────────────

    def tailor(self, jd, output_dir: str) -> str:
        """
        Two-pass tailoring with quality validation.

        Args:
            jd:         JobDescription object
            output_dir: Directory to write resume.tex

        Returns:
            Path to the tailored .tex file.
        """
        print(f"[Tailor] Tailoring resume for: {jd.company} — {jd.title}")

        tex = self._base_tex
        current_sections = self._extract_all_modifiable_sections(tex)
        current_skills_list = self._extract_current_skills_list(tex)
        skills_to_inject = get_skills_to_inject(jd.raw_description, current_skills_list)
        if skills_to_inject:
            print(f"[Tailor] Skills to inject: {', '.join(skills_to_inject)}")

        # Pass 1: Strategy
        strategy = self._pass1_strategy(jd) if self.api_key else None

        # Pass 2: Generate
        tailored = self._pass2_generate(jd, strategy, current_sections, skills_to_inject)

        if tailored:
            # Pass 3: Validate LaTeX before compiling
            errors = self._validate_latex(tailored)
            if errors:
                print(f"[Tailor] LaTeX validation warnings ({len(errors)}):")
                for e in errors[:5]:
                    print(f"  - {e}")

            # Pass 4: Quality score
            quality = self._pass4_score(jd, tailored, strategy)
            if quality:
                score = quality.get("overall_score", 0)
                verdict = quality.get("verdict", "unknown")
                print(f"[Tailor] Quality score: {score}/100 — {verdict}")

                # Pass 5: Refine if below threshold
                if score < self.quality_threshold and verdict != "ship_it":
                    tailored = self._pass5_refine(jd, tailored, quality, strategy) or tailored
                    print(f"[Tailor] Refinement complete")

            # Apply to LaTeX template
            tex = self._apply_content(tex, tailored)
        else:
            print("[Tailor] LLM unavailable — applying lightweight keyword reordering only")
            tex = self._lightweight_reorder(tex, jd)

        # Write tailored .tex
        os.makedirs(output_dir, exist_ok=True)
        tex_path = os.path.join(output_dir, "resume.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)

        print(f"[Tailor] Wrote: {tex_path}")
        return tex_path

    def _apply_content(self, tex: str, tailored: dict) -> str:
        """Apply LLM-generated content sections to the LaTeX template."""
        if tailored.get("skills_section"):
            new_skills = self._build_skills_latex(tailored["skills_section"])
            tex = self._replace_section(tex, "Technical Skills", new_skills)
        if tailored.get("experience_mesons"):
            tex = self._replace_company_bullets(tex, "Mesons", tailored["experience_mesons"])
        if tailored.get("experience_aisera"):
            tex = self._replace_company_bullets(tex, "Aisera", tailored["experience_aisera"])
        if tailored.get("projects_section"):
            tex = self._replace_section(tex, "Projects", tailored["projects_section"])
        return tex

    def _build_skills_latex(self, skills_content: str) -> str:
        if "\\begin{itemize}" in skills_content or "\\resumeSubHeadingListStart" in skills_content:
            return skills_content
        return (
            "\\begin{itemize}[leftmargin=0.15in, label={}]\n"
            "    \\small{\\item{\n"
            f"    {skills_content}\n"
            "    }}\n"
            "\\end{itemize}"
        )

    def _lightweight_reorder(self, tex: str, jd) -> str:
        """No-LLM fallback: reorder skills to front-load JD keywords."""
        skills_section = self._extract_section(tex, "Technical Skills")
        if not skills_section:
            return tex
        current_skills = self._extract_current_skills_list(tex)
        prioritize_skills_for_jd(current_skills, jd.raw_description)
        return tex  # Preserve template if no LLM available

    def compile(self, tex_path: str, output_dir: str) -> str:
        """Compile .tex → .pdf, validate 1 page. Returns pdf_path."""
        print(f"[Tailor] Compiling LaTeX...")
        try:
            pdf_path = compile_and_validate(tex_path, output_dir, expected_pages=1)
            cleanup_aux_files(output_dir, "resume")
            print(f"[Tailor] PDF compiled: {pdf_path}")
            return pdf_path
        except PageCountError as e:
            print(f"[Tailor] Page overflow: {e} — flagging for review")
            raise
        except Exception as e:
            print(f"[Tailor] Compilation error: {e}")
            raise
