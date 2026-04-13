# JobHunter AI

Autonomous AI-powered job application platform. Scrapes job postings, tailors resumes and cover letters per role using Claude, and tracks applications through your pipeline.

## Quick Start

```bash
git clone https://github.com/yourusername/jobhunter-ai
cd jobhunter-ai

# 1. Set up environment
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Node dependencies
cd frontend && npm install && cd ..

# 4. Start everything
cd frontend && npm run dev:all
```

Open http://localhost:3000

---

## Architecture

```
jobhunter-ai/
├── agents/              Python pipeline
│   ├── scraper_agent.py         Playwright + HTTP scraping
│   ├── quality_scorer_agent.py  Keyword scoring against candidate profile
│   ├── resume_tailor_agent.py   Two-pass LLM tailoring with quality validation
│   ├── cover_letter_agent.py    Personalized cover letter generation
│   └── orchestrator.py          Parallel batch coordinator (ThreadPoolExecutor)
├── scheduler/           APScheduler daemon
│   ├── scheduler_service.py     Cron execution engine
│   └── __main__.py              Entry point (python -m scheduler)
├── utils/               Shared utilities
│   ├── db_manager.py            SQLite CRUD
│   ├── latex_compiler.py        pdflatex wrapper + page validation
│   └── skill_matcher.py         Keyword injection from approved pool
├── frontend/            Next.js 16 + TypeScript
│   ├── app/(app)/               Pages: dashboard, jobs, documents, cron, analytics
│   └── app/api/                 API routes (proxied to Python backend)
├── config/
│   └── settings.yaml            Local config (gitignored — use .env instead)
├── data/                SQLite DB (gitignored)
└── outputs/             Generated resumes/cover letters (gitignored)
```

## Features

- **Concurrent scraping** — 5 parallel workers, per-domain rate limiting (LinkedIn: 5s, Indeed: 3s)
- **Two-pass resume tailoring** — Pass 1: strategic analysis; Pass 2: strategy-informed generation; Pass 3: LaTeX validation; Pass 4: quality scoring; Pass 5: refinement if score < 80
- **Quality gate** — Every tailored resume is scored by Claude. Resumes below 80/100 are automatically refined before compiling
- **Parallel PDF compilation** — ThreadPoolExecutor for LaTeX → PDF conversion
- **APScheduler cron** — Persistent schedule execution (survives restarts), "Run Now" button in UI
- **Real-time dashboard** — React Query with 4s polling when jobs are pending
- **Inline PDF preview** — Documents page streams PDFs from disk

## Usage

### Process jobs from CLI

```bash
# Add URLs to urls.txt (one per line), then:
python run_daily.py batch

# Single URL
python run_daily.py single --url "https://linkedin.com/jobs/view/..."

# Check status
python run_daily.py status
python run_daily.py status --week

# See what's ready to apply
python run_daily.py list --status tailored

# Mark as applied
python run_daily.py update <job_id> --status applied

# Follow-up reminders
python run_daily.py followup
```

### Scheduler (cron automation)

```bash
# Start the scheduler daemon (runs in background, executes cron schedules)
python -m scheduler

# Run a specific schedule immediately
python -m scheduler --run-now <schedule_id>

# Or from frontend directory:
npm run dev:scheduler    # scheduler only
npm run dev:all          # Next.js + scheduler together
```

## Environment Variables

See `.env.example` for all variables. Required:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `BACKEND_ROOT` | Path to project root (default: `..` from frontend/) |
| `CLAUDE_MODEL` | LLM model (default: `claude-sonnet-4-6`) |
| `TIMEZONE` | Scheduler timezone (default: `America/Toronto`) |

## Requirements

**Python:** apscheduler, croniter, anthropic, playwright, pyyaml, python-dotenv

**LaTeX:** `pdflatex` must be installed (`texlive-full` on Ubuntu, MiKTeX on Windows)

**Node:** 18+

## Before Pushing to GitHub

```bash
chmod +x scripts/pre-push-audit.sh
./scripts/pre-push-audit.sh
```

This checks for leaked API keys, staged .env files, and database files.

## License

MIT
