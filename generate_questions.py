"""Auto-generate ML quiz questions using the claude CLI.

Uses parallel single-question generation with summary-based dedup.

Usage:
    uv run generate_questions.py                        # 10 mixed-rank questions
    uv run generate_questions.py -n 5 -r S -f "transformers"
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import db
from models import Question

RANK_PREFIXES = {
    "E": "e",
    "D": "d",
    "C": "c",
    "B": "b",
    "A": "a",
    "S": "s",
}

RANK_ORDER = ["E", "D", "C", "B", "A", "S"]

QUESTION_ANGLES = [
    "conceptual — test understanding of what a concept means and why it matters",
    "computational — require working through a formula, calculation, or numeric reasoning",
    "misconception — present a common mistake or trap and ask the student to identify the error",
    "comparison — compare or contrast two related techniques",
    "application — describe a real-world scenario and ask which method to apply",
    "edge-case — focus on boundary conditions, failure modes, or unusual inputs",
    "intuition — test geometric or visual intuition behind an algorithm",
    "debugging — present a broken ML pipeline or result and ask what went wrong",
]

RANK_DESCRIPTIONS = {
    "E": "E-Rank: ML fundamentals (bias/variance, overfitting, linear models, metrics)",
    "D": "D-Rank: Core techniques (regularization, gradient descent, SVMs, trees, cross-validation)",
    "C": "C-Rank: Deep learning (CNNs, RNNs/LSTMs, backprop, batch norm, dropout)",
    "B": "B-Rank: Advanced (transformers, attention, VAEs, GANs, RL)",
    "A": "A-Rank: Expert (optimization theory, information theory, diffusion models, NLP)",
    "S": "S-Rank: Master (cutting-edge research, theoretical traps, adversarial robustness, scaling laws)",
}

QUESTION_SCHEMA = """\
{
  "id": "string — rank-prefixed unique ID, e.g. e001, b003, s012",
  "rank": "string — one of E, D, C, B, A, S",
  "question": "string — the question text",
  "choices": ["choice text without letter prefix", "choice text", "choice text"],
  "correct": 0,
  "explanation": {
    "correct": "string — why the correct answer is right",
    "wrong": [
      "string — why the first wrong choice is wrong",
      "string — why the second wrong choice is wrong"
    ]
  }
}"""


def _distribute_ranks(rank: str | None, count: int) -> list[str]:
    """Distribute ranks across a batch of questions.

    - rank=None: round-robin across all 6 ranks.
    - rank specified: ~20% at current rank, ~40% at +1, ~40% at +2 (clamped to S).
    """
    if rank is None:
        return [RANK_ORDER[i % len(RANK_ORDER)] for i in range(count)]

    idx = RANK_ORDER.index(rank)
    r0 = rank
    r1 = RANK_ORDER[min(idx + 1, len(RANK_ORDER) - 1)]
    r2 = RANK_ORDER[min(idx + 2, len(RANK_ORDER) - 1)]

    # Build distribution: 20% current, 40% +1, 40% +2
    n_r0 = max(1, round(count * 0.2))
    remaining = count - n_r0
    n_r1 = remaining // 2
    n_r2 = remaining - n_r1

    result = [r0] * n_r0 + [r1] * n_r1 + [r2] * n_r2
    return result[:count]


def _next_id(prefix: str, existing: set[str]) -> str:
    num = 1
    while True:
        candidate = f"{prefix}{num:03d}"
        if candidate not in existing:
            return candidate
        num += 1


def _build_single_prompt(
    summary: dict,
    rank: str | None = None,
    focus_area: str | None = None,
    question_index: int = 0,
    total_count: int = 1,
) -> str:
    rank_block = "\n".join(f"  - {v}" for v in RANK_DESCRIPTIONS.values())

    rank_instruction = ""
    if rank:
        rank_instruction = (
            f"\nGenerate the question at rank {rank} "
            f"({RANK_DESCRIPTIONS.get(rank, rank)})."
        )

    focus_instruction = ""
    if focus_area:
        focus_instruction = f"\nFocus on the topic area: {focus_area}."

    # Compact dedup info instead of full question texts
    dedup_block = ""
    if summary.get("rank_counts") or summary.get("categories"):
        dedup_block = "\n\n--- EXISTING QUESTION BANK SUMMARY (avoid duplicating these topics) ---"
        if summary.get("rank_counts"):
            counts = ", ".join(f"{r}: {c}" for r, c in sorted(summary["rank_counts"].items()))
            dedup_block += f"\nExisting question counts by rank: {counts}"
        if summary.get("categories"):
            dedup_block += f"\nExisting categories: {', '.join(summary['categories'])}"
        dedup_block += "\n--- END SUMMARY ---"

    return f"""\
You are an expert machine learning quiz question generator.

Generate exactly 1 multiple-choice quiz question for an ML learning app.
The question MUST have exactly 3 choices, one correct answer, and detailed explanations.

IMPORTANT: Do NOT include letter prefixes like "A) ", "B) ", "C) " in the choice text.
Just provide the plain choice text.

RANK SYSTEM (difficulty tiers):
{rank_block}
{rank_instruction}{focus_instruction}

If no specific rank is requested, pick a rank that provides good coverage.

JSON SCHEMA for the question:
{QUESTION_SCHEMA}
{dedup_block}

VARIATION INSTRUCTIONS:
- This is question {question_index + 1} of {total_count}.
- Use this question angle: {QUESTION_ANGLES[question_index % len(QUESTION_ANGLES)]}
- Pick a DIFFERENT subtopic than the obvious choice for this topic.

RULES:
1. Return ONLY a single JSON object (not an array) — no commentary, no markdown.
2. The question must have exactly 3 choices.
3. The "correct" field must be an integer index (0, 1, or 2).
4. The "explanation.wrong" array must have exactly 2 entries (one per wrong choice).
5. Make the question challenging and educational, not trivial.
6. Use a placeholder ID — it will be reassigned.
7. Do NOT include letter prefixes (A), B), C)) in choice strings.
8. Wrap ALL math expressions in LaTeX delimiters: use $...$ for inline math. Use proper LaTeX commands (e.g. $\\nabla_\\theta \\log \\pi(a|s)$, $\\mathbb{{E}}$, $\\sigma$). Never write raw plain-text math.

Return the JSON object now."""


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def _generate_one(
    summary: dict,
    rank: str | None,
    focus_area: str | None,
    index: int,
    total_count: int = 1,
) -> Question | None:
    """Generate a single question via claude CLI. Returns None on failure."""
    prompt = _build_single_prompt(
        summary, rank=rank, focus_area=focus_area,
        question_index=index, total_count=total_count,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        print(f"[{index}] Error: 'claude' CLI not found.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"[{index}] Error: claude CLI timed out after 60s.", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"[{index}] Error: claude CLI exited with code {result.returncode}", file=sys.stderr)
        return None

    raw = result.stdout.strip()
    if not raw:
        print(f"[{index}] Error: empty output.", file=sys.stderr)
        return None

    cleaned = _strip_markdown_fences(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"[{index}] Error: bad JSON: {exc}", file=sys.stderr)
        return None

    # Handle case where model returns an array with one element
    if isinstance(data, list):
        if len(data) == 1:
            data = data[0]
        else:
            print(f"[{index}] Error: expected object, got array of {len(data)}", file=sys.stderr)
            return None

    try:
        return Question.model_validate(data)
    except Exception as exc:
        print(f"[{index}] Validation error: {exc}", file=sys.stderr)
        return None


def generate_questions(
    focus_area: str | None = None,
    rank: str | None = None,
    count: int = 10,
) -> list[Question]:
    """Generate new ML quiz questions via parallel claude CLI calls.

    Returns list of validated, ID-assigned Question objects.
    """
    summary = db.get_summary()
    per_question_ranks = _distribute_ranks(rank, count)

    # Launch parallel generation
    results: list[Question | None] = [None] * count
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = {
            pool.submit(_generate_one, summary, per_question_ranks[i], focus_area, i, count): i
            for i in range(count)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                print(f"[{idx}] Unexpected error: {exc}", file=sys.stderr)

    # Assign IDs serially (no race conditions)
    existing_ids = db.get_existing_ids()
    valid_questions: list[Question] = []

    for q in results:
        if q is None:
            continue
        prefix = RANK_PREFIXES[q.rank]
        new_id = _next_id(prefix, existing_ids)
        q.id = new_id
        existing_ids.add(new_id)
        valid_questions.append(q)

    if valid_questions:
        db.insert_questions(valid_questions)
        print(f"Successfully generated {len(valid_questions)} question(s).")
    else:
        print("No valid questions were generated.", file=sys.stderr)

    return valid_questions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ML quiz questions using the claude CLI."
    )
    parser.add_argument("-n", type=int, default=10, help="Number of questions (default: 10)")
    parser.add_argument("-r", type=str, default=None, choices=list(RANK_PREFIXES.keys()),
                        help="Rank/difficulty (E/D/C/B/A/S). Default: mixed.")
    parser.add_argument("-f", type=str, default=None, help="Focus area / topic.")
    args = parser.parse_args()

    db.ensure_ready()
    questions = generate_questions(focus_area=args.f, rank=args.r, count=args.n)

    if questions:
        print(f"\nGenerated {len(questions)} question(s):")
        for q in questions:
            print(f"  [{q.id}] ({q.rank}-Rank) {q.question}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
