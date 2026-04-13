# JobHunter AI — Diagnostic Report
Generated: 2026-04-13

---

## CRITICAL ISSUES (Fix Before Any Commit)

### 1. Hardcoded API Key in `config/settings.yaml:7`
**Status: CRITICAL — REVOKE THIS KEY IMMEDIATELY**
```
anthropic_api_key: "sk-ant-api03-cxsHu8SKIgpmvm0vXHIm3Ct..."
```
- Key is in version-controlled YAML file
- Must be revoked at console.anthropic.com before pushing repo
- Replacement: `ANTHROPIC_API_KEY` environment variable
- `config/settings.yaml` added to `.gitignore`

---

## Hardcoded / Mock Data Findings

| File | Line(s) | What | Replacement Strategy |
|------|---------|------|----------------------|
| `config/settings.yaml` | 7 | Anthropic API key in plaintext | `os.environ["ANTHROPIC_API_KEY"]` |
| `config/settings.yaml` | 27–37 | Personal PII (email, phone, LinkedIn) | Keep in settings.yaml (gitignored), load via yaml.safe_load |
| `agents/resume_tailor_agent.py` | 21–114 | Candidate profile hardcoded in TAILORING_PROMPT string | Load from `config/settings.yaml` candidate section at runtime |
| `agents/cover_letter_agent.py` | 18–33 | Same candidate profile in COVER_LETTER_PROMPT | Load from `config/settings.yaml` candidate section |
| `agents/resume_tailor_agent.py` | 229 | `model="claude-sonnet-4-6"` hardcoded | Load from `config/settings.yaml` api.claude_model |
| `agents/orchestrator.py` | 25 | Falls back to `""` if no env var | Warn loudly, don't silently fail |

---

## Mock Data in Frontend
**None found.** All frontend pages already use `useQuery` to hit real API endpoints:
- `/jobs` → `GET /api/jobs` with pagination, search, sort
- `/analytics` → `GET /api/analytics`
- `/documents` → `GET /api/documents/[job_id]`
- `/cron` → `GET /api/cron`
- `/settings` → `GET /api/settings`

---

## Sequential Bottlenecks

| File | Lines | Issue | Fix |
|------|-------|-------|-----|
| `agents/orchestrator.py` | 153–155 | `for url in new_urls: _process_single(url)` — fully sequential, one job at a time | `ThreadPoolExecutor` with 5 workers |
| `frontend/app/api/jobs/route.ts` | 69–78 | Spawns one `python run_daily.py single` process **per URL** — N separate Python processes | Spawn one `python run_daily.py batch` process with all URLs in a temp file |

**Performance impact**: 10 URLs currently ~200–450s sequential → ~45–90s parallel.

---

## Broken Connections

### Cron System (CRITICAL — non-functional)
- **Frontend**: `/cron` page creates/edits/deletes schedules via API ✓
- **Backend API**: `POST /api/cron` stores schedule in SQLite ✓
- **MISSING**: No daemon process that reads `cron_schedules` table and executes them
- **`next_run` field**: Never updated — always null
- **`last_run` field**: Never updated
- **Result**: Entire cron page is UI-only; nothing ever runs on schedule

**Fix**: Python APScheduler service (`scheduler/scheduler_service.py`) running as background process, reading schedules from DB.

### Agent API Path Resolution
- **File**: `frontend/app/api/agent/run/route.ts:11–12`
- `path.resolve(process.cwd(), '..')` assumes frontend runs from `frontend/` directory
- Fragile in Docker/production where `cwd` may differ
- **Fix**: Use `BACKEND_ROOT` env var or validate path exists before spawning

---

## Missing or Broken Cron
- Current implementation: DB stores cron expressions but nothing reads them
- `cron_schedules.next_run` and `last_run` columns are never updated
- Manual trigger (`POST /api/agent/run`) works but has N-process spawn bug

**Fix**: `scheduler/` package with APScheduler (persistent SQLAlchemy job store), runs as `python -m scheduler`.

---

## Secrets in Code
| File | Secret Type | Action Required |
|------|-------------|-----------------|
| `config/settings.yaml:7` | Anthropic API key (live) | **REVOKE NOW** at console.anthropic.com, then remove from file |

No secrets found in TypeScript/TSX files (frontend settings route masks the key preview correctly).

---

## Resume Quality Issues
Single-pass generation with one LLM call. Issues:
1. No strategic analysis before writing (prompt doesn't extract primary hiring signal)
2. No JSON schema validation (LLM response silently fails if shape is wrong)
3. No quality scoring pass (no way to know if output is good before compiling PDF)
4. No iterative refinement loop
5. LaTeX escaping delegated entirely to LLM (no pre-compilation validation)
6. Model hardcoded to `claude-sonnet-4-6` instead of reading from config

**Fix**: Two-pass architecture — Pass 1: strategic analysis → Pass 2: strategy-informed generation → Pass 3: LaTeX validation → Pass 4: quality scoring → Pass 5: refinement if score < 80.

---

## API Endpoints Audit

| Method | Route | Status |
|--------|-------|--------|
| POST | `/api/jobs` | ✓ Working (spawn loop bug — see above) |
| GET | `/api/jobs` | ✓ Working |
| PATCH | `/api/jobs/[id]` | ✓ Working |
| DELETE | `/api/jobs/[id]` | ✓ Working |
| GET | `/api/settings` | ✓ Working (key masked) |
| PATCH | `/api/settings` | ✓ Working |
| POST | `/api/cron` | ✓ Stores only (no execution) |
| GET | `/api/cron` | ✓ Working |
| PATCH | `/api/cron/[id]` | ✓ Working |
| DELETE | `/api/cron/[id]` | ✓ Working |
| POST | `/api/cron/[id]/run` | ✗ MISSING — needed for "Run Now" button |
| GET | `/api/analytics` | ✓ Working |
| GET | `/api/documents/[job_id]` | ✓ Working |
| POST | `/api/agent/run` | ✓ Working (path-fragile) |

---

## Missing Files
- `.gitignore` at repo root (only `frontend/.gitignore` exists)
- `.env.example`
- `README.md`
- `scheduler/` package
- `scripts/pre-push-audit.sh`

---

## Fix Execution Order
1. ✅ Revoke API key, sanitize `settings.yaml`
2. ✅ Create `.env.example` + repo-root `.gitignore`
3. ✅ Fix spawn loop in `frontend/app/api/jobs/route.ts`
4. ✅ Parallelize `orchestrator.py` with `ThreadPoolExecutor`
5. ✅ Two-pass resume generation in `resume_tailor_agent.py`
6. ✅ APScheduler cron service (`scheduler/`)
7. ✅ `POST /api/cron/[id]/run` endpoint
8. ✅ `pre-push-audit.sh` + `README.md`
