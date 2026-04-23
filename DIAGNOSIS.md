# JobHunter AI — Pipeline Diagnosis

## Frontend → Backend Connection
- Add Job button calls: `POST /api/jobs`
- That endpoint exists: **YES** — `frontend/app/api/jobs/route.ts`
- That endpoint handler does: validates URLs, inserts into SQLite, spawns Python process
- Backend is running on: Next.js handles everything (port 3000)
- Frontend proxies to backend via: direct Next.js API routes (same process)

## Processing Pipeline
- After URL is saved to DB, processing is triggered by: `spawn('python', [scriptPath, 'batch', '--input', tmpFile])`
- The trigger mechanism works: **NO** — CRITICAL BUG

## Root Cause: Wrong Python Executable

`spawn('python', ...)` launches **Python 3.14** (default `python` on this machine).
Python 3.14 has **NO pip** and **NO packages installed** — `import anthropic` fails immediately.

All required packages (`anthropic`, `beautifulsoup4`, `requests`, `playwright`, etc.) are installed
under **Python 3.11** only, accessible via `py -3.11`.

**Evidence:**
```
C:\Python314\python.exe: No module named pip
C:\Python314\python.exe: No module named anthropic
```
vs.
```
py -3.11 -c "import anthropic; print(anthropic.__version__)"  → 0.86.0 ✓
```

The Python process spawned by the API route crashes silently on import (stdio: 'ignore'),
so no error ever surfaces. The DB job stays `pending` forever.

## Secondary Issue: pdflatex Not Installed
- pdflatex: **NOT FOUND** in PATH or common Windows locations
- Without pdflatex, PDF compilation fails at the end of the pipeline
- The orchestrator handles this gracefully (logs error, saves .tex, marks job `tailored` anyway)
- But the PDF paths in the DB will point to files that don't exist → document preview fails
- **Fix: Install MiKTeX via winget**

## Bug: newUrls filter logic is wrong
File: `frontend/app/api/jobs/route.ts` line 78
```typescript
const newUrls = urls.filter(u => u.trim() && inserted.length > 0)
```
`inserted.length > 0` is a scalar boolean — it passes ALL non-empty input URLs to the batch
runner, including duplicates. Should only pass the URLs that were actually inserted.

## Critical Missing Links Identified
1. **`spawn('python', ...)` → Python 3.14 with no packages** — processing crashes silently on start
2. **pdflatex not installed** — PDF output fails (pipeline still completes with .tex only)
3. **`newUrls` bug** — passes all URLs including duplicates to batch runner
4. **stdio: 'ignore' on spawned process** — errors are completely invisible

## Dependencies Status
- anthropic 0.86.0: ✅ installed in Python 3.11
- beautifulsoup4 4.14.3: ✅ installed in Python 3.11
- requests: ✅ installed in Python 3.11
- playwright: ✅ installed in Python 3.11 (need `playwright install chromium`)
- pdflatex: ❌ NOT INSTALLED — install MiKTeX
- ANTHROPIC_API_KEY: ✅ in config/settings.yaml (loaded by `_load_api_key_from_config()`)

## Database State
- Tables exist: YES (applications, daily_stats, cron_schedules, cron_runs, error_log)
- Schema is correct: YES
- Jobs in DB: 5 total
- Jobs with status beyond 'pending': 0 (all stuck at pending due to root cause)
- Note: 3 of 5 existing jobs have LinkedIn search-results URLs (not individual job pages)
  → These will fail scraping regardless. Test with a direct job view URL.

## What Will Work After Fixes
1. Change spawn to `py -3.11` → Python 3.11 has all packages → processing starts
2. Install MiKTeX → PDFs compile → document preview works
3. Fix newUrls → clean batch inputs
4. Add log file → errors visible in `logs/agent.log`
5. `playwright install chromium` → Playwright fallback works for JS-heavy pages
