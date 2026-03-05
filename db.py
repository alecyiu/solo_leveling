"""SQLite access layer for the Solo Leveling question bank."""

import json
import sqlite3
from pathlib import Path

from models import Question

RESOURCES_DIR = Path(__file__).parent / "resources"
DB_PATH = RESOURCES_DIR / "questions.db"


def _connect() -> sqlite3.Connection:
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id         TEXT PRIMARY KEY,
                rank       TEXT NOT NULL,
                week       INTEGER,
                category   TEXT,
                question   TEXT NOT NULL,
                choices    TEXT NOT NULL,
                correct    INTEGER NOT NULL,
                exp_correct TEXT NOT NULL,
                exp_wrong   TEXT NOT NULL
            )
        """)


def _row_to_question(row: sqlite3.Row) -> Question:
    return Question(
        id=row["id"],
        rank=row["rank"],
        week=row["week"],
        category=row["category"],
        question=row["question"],
        choices=json.loads(row["choices"]),
        correct=row["correct"],
        explanation={"correct": row["exp_correct"], "wrong": json.loads(row["exp_wrong"])},
    )


def get_all_questions() -> list[Question]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    return [_row_to_question(r) for r in rows]


def get_existing_ids() -> set[str]:
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM questions").fetchall()
    return {r["id"] for r in rows}


def get_summary() -> dict:
    """Return a compact summary for dedup prompts: rank counts + category list."""
    with _connect() as conn:
        rank_rows = conn.execute(
            "SELECT rank, COUNT(*) as cnt FROM questions GROUP BY rank"
        ).fetchall()
        cat_rows = conn.execute(
            "SELECT DISTINCT category FROM questions WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
    return {
        "rank_counts": {r["rank"]: r["cnt"] for r in rank_rows},
        "categories": [r["category"] for r in cat_rows],
    }


def insert_questions(questions: list[Question]) -> int:
    """Insert questions, ignoring duplicates. Returns count of inserted rows."""
    if not questions:
        return 0
    rows = [
        (
            q.id,
            q.rank,
            q.week,
            q.category,
            q.question,
            json.dumps(q.choices),
            q.correct,
            q.explanation.correct,
            json.dumps(q.explanation.wrong),
        )
        for q in questions
    ]
    with _connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        conn.executemany(
            """INSERT OR IGNORE INTO questions
               (id, rank, week, category, question, choices, correct, exp_correct, exp_wrong)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        after = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    return after - before


def ensure_ready() -> None:
    """Initialize the DB and migrate from JSON if empty. Single entry point."""
    init_db()
    if not get_existing_ids():
        migrated = migrate_from_json()
        if migrated:
            print(f"Migrated {migrated} questions from JSON to SQLite.")


def migrate_from_json(json_path: Path | None = None) -> int:
    """One-time migration from questions.json to SQLite. Returns count migrated."""
    if json_path is None:
        json_path = RESOURCES_DIR / "questions.json"
    if not json_path.exists():
        return 0

    with open(json_path) as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        return 0

    questions = []
    for item in raw:
        try:
            questions.append(Question.model_validate(item))
        except Exception as e:
            print(f"Warning: skipping invalid question {item.get('id', '?')}: {e}")

    insert_questions(questions)
    return len(questions)
