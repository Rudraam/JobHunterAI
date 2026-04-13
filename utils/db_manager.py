"""
Database Manager — SQLite CRUD operations for application tracking.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Optional


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "applications.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH):
    """Create all tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id               TEXT UNIQUE NOT NULL,
            url                  TEXT NOT NULL,
            company              TEXT NOT NULL,
            role                 TEXT NOT NULL,
            location             TEXT,
            salary_range         TEXT,
            job_type             TEXT,
            match_score          REAL,
            priority             TEXT DEFAULT 'medium',
            status               TEXT DEFAULT 'pending',
            applied_date         TEXT,
            response_date        TEXT,
            interview_dates      TEXT,
            notes                TEXT,
            tailored_resume_path TEXT,
            cover_letter_path    TEXT,
            created_at           TEXT DEFAULT (datetime('now')),
            updated_at           TEXT DEFAULT (datetime('now')),
            raw_jd               TEXT,
            parsed_jd            TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date                 TEXT PRIMARY KEY,
            jobs_scraped         INTEGER DEFAULT 0,
            jobs_tailored        INTEGER DEFAULT 0,
            jobs_applied         INTEGER DEFAULT 0,
            jobs_skipped         INTEGER DEFAULT 0,
            avg_match_score      REAL,
            high_priority_count  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS follow_ups (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id       INTEGER REFERENCES applications(id),
            follow_up_date       TEXT,
            follow_up_type       TEXT,
            message_sent         TEXT,
            response             TEXT,
            created_at           TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS error_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            url        TEXT,
            error      TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


# ─── Application CRUD ────────────────────────────────────────────────────────

def job_exists(job_id: str, db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return row is not None


def log_application(jd, output_dir: str = "", status: str = "tailored", db_path: str = DB_PATH):
    """Insert or update an application record.
    If the frontend already created a pending row for this URL, update that row
    instead of inserting a duplicate with a different job_id.
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    resume_path = os.path.join(output_dir, "resume.pdf") if output_dir else ""
    cl_path = os.path.join(output_dir, "cover_letter.pdf") if output_dir else ""

    # Reuse the existing job_id if a row already exists for this URL
    existing = conn.execute(
        "SELECT job_id FROM applications WHERE url = ?", (jd.url,)
    ).fetchone()
    job_id = existing["job_id"] if existing else jd.job_id

    conn.execute("""
        INSERT INTO applications
            (job_id, url, company, role, location, salary_range, job_type,
             match_score, priority, status, tailored_resume_path, cover_letter_path,
             created_at, updated_at, raw_jd, parsed_jd)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(job_id) DO UPDATE SET
            company              = excluded.company,
            role                 = excluded.role,
            location             = excluded.location,
            salary_range         = excluded.salary_range,
            match_score          = excluded.match_score,
            priority             = excluded.priority,
            status               = excluded.status,
            tailored_resume_path = excluded.tailored_resume_path,
            cover_letter_path    = excluded.cover_letter_path,
            updated_at           = excluded.updated_at,
            raw_jd               = excluded.raw_jd,
            parsed_jd            = excluded.parsed_jd
    """, (
        job_id, jd.url, jd.company, jd.title, jd.location,
        jd.salary_range, jd.job_type, jd.match_score,
        jd.priority, status, resume_path, cl_path,
        now, now,
        jd.raw_description,
        json.dumps({
            "responsibilities": jd.responsibilities,
            "requirements": jd.requirements,
            "required_skills": jd.required_skills,
            "tools_mentioned": jd.tools_mentioned,
            "keywords": jd.keywords,
        })
    ))
    conn.commit()
    conn.close()


def log_skip(jd, reason: str = "", db_path: str = DB_PATH):
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT job_id FROM applications WHERE url = ?", (jd.url,)
    ).fetchone()
    job_id = existing["job_id"] if existing else jd.job_id
    conn.execute("""
        INSERT INTO applications
            (job_id, url, company, role, location, salary_range, job_type,
             match_score, priority, status, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(job_id) DO UPDATE SET
            company = excluded.company, role = excluded.role,
            match_score = excluded.match_score,
            status = 'skipped', notes = excluded.notes, updated_at = excluded.updated_at
    """, (
        job_id, jd.url, jd.company, jd.title, jd.location,
        jd.salary_range, jd.job_type, jd.match_score,
        "low", "skipped", reason, now, now
    ))
    conn.commit()
    conn.close()


def log_review(jd, db_path: str = DB_PATH):
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT job_id FROM applications WHERE url = ?", (jd.url,)
    ).fetchone()
    job_id = existing["job_id"] if existing else jd.job_id
    conn.execute("""
        INSERT INTO applications
            (job_id, url, company, role, location, salary_range, job_type,
             match_score, priority, status, created_at, updated_at, raw_jd)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(job_id) DO UPDATE SET
            company = excluded.company, role = excluded.role,
            match_score = excluded.match_score,
            status = 'review', updated_at = excluded.updated_at, raw_jd = excluded.raw_jd
    """, (
        job_id, jd.url, jd.company, jd.title, jd.location,
        jd.salary_range, jd.job_type, jd.match_score,
        "medium", "review", now, now, jd.raw_description
    ))
    conn.commit()
    conn.close()


def log_error(url: str, error: str, db_path: str = DB_PATH):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO error_log (url, error) VALUES (?,?)", (url, error))
    conn.commit()
    conn.close()


def update_status(job_id: str, status: str, notes: str = "", db_path: str = DB_PATH):
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    applied_date = now if status == "applied" else None
    response_date = now if status in ("interview", "offer", "rejected") else None

    if applied_date:
        conn.execute(
            "UPDATE applications SET status=?, notes=?, applied_date=?, updated_at=? WHERE job_id=?",
            (status, notes, applied_date, now, job_id)
        )
    elif response_date:
        conn.execute(
            "UPDATE applications SET status=?, notes=?, response_date=?, updated_at=? WHERE job_id=?",
            (status, notes, response_date, now, job_id)
        )
    else:
        conn.execute(
            "UPDATE applications SET status=?, notes=?, updated_at=? WHERE job_id=?",
            (status, notes, now, job_id)
        )
    conn.commit()
    conn.close()


def get_applications(status: Optional[str] = None, priority: Optional[str] = None,
                     db_path: str = DB_PATH) -> list:
    conn = get_connection(db_path)
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    query += " ORDER BY match_score DESC, created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_followups(days: int = 5, db_path: str = DB_PATH) -> list:
    """Return applied jobs with no response after `days` days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM applications
        WHERE status = 'applied'
          AND applied_date < ?
          AND (response_date IS NULL OR response_date = '')
        ORDER BY applied_date ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Daily Stats ─────────────────────────────────────────────────────────────

def upsert_daily_stats(date: str, scraped: int = 0, tailored: int = 0,
                       applied: int = 0, skipped: int = 0,
                       avg_score: float = 0.0, high_priority: int = 0,
                       db_path: str = DB_PATH):
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO daily_stats
            (date, jobs_scraped, jobs_tailored, jobs_applied, jobs_skipped,
             avg_match_score, high_priority_count)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            jobs_scraped        = jobs_scraped + excluded.jobs_scraped,
            jobs_tailored       = jobs_tailored + excluded.jobs_tailored,
            jobs_applied        = jobs_applied + excluded.jobs_applied,
            jobs_skipped        = jobs_skipped + excluded.jobs_skipped,
            avg_match_score     = excluded.avg_match_score,
            high_priority_count = high_priority_count + excluded.high_priority_count
    """, (date, scraped, tailored, applied, skipped, avg_score, high_priority))
    conn.commit()
    conn.close()


def get_stats(date: Optional[str] = None, db_path: str = DB_PATH) -> dict:
    conn = get_connection(db_path)
    if date:
        row = conn.execute("SELECT * FROM daily_stats WHERE date = ?", (date,)).fetchone()
        result = dict(row) if row else {}
    else:
        rows = conn.execute("SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7").fetchall()
        result = [dict(r) for r in rows]
    conn.close()
    return result
