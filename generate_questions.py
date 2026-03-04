"""Auto-generate ML quiz questions using the claude CLI.

Usage:
    uv run generate_questions.py                        # 10 mixed-rank questions
    uv run generate_questions.py -n 5 -r S -f "transformers"
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"
QUESTIONS_FILE = RESOURCES_DIR / "questions.json"

RANK_PREFIXES = {
    "E": "e",
    "D": "d",
    "C": "c",
    "B": "b",
    "A": "a",
    "S": "s",
}

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
  "choices": ["string", "string", "string"],   // exactly 3 choices
  "correct": 0,                                // index into choices, 0-2
  "explanation": {
    "correct": "string — why the correct answer is right",
    "wrong": [
      "string — why the first wrong choice is wrong",
      "string — why the second wrong choice is wrong"
    ]
  }
}"""

EXAMPLE_QUESTIONS = [
    {
        "id": "e001",
        "rank": "E",
        "question": "What does a high bias in a model typically indicate?",
        "choices": [
            "The model is too simple and underfits the data",
            "The model is too complex and overfits the data",
            "The model has perfect generalization",
        ],
        "correct": 0,
        "explanation": {
            "correct": "High bias means the model makes strong assumptions about the data, leading to underfitting — it cannot capture the underlying patterns.",
            "wrong": [
                "High complexity and overfitting are symptoms of high variance, not high bias.",
                "Perfect generalization would mean both low bias and low variance, which is the ideal but rarely achieved state.",
            ],
        },
    },
    {
        "id": "b001",
        "rank": "B",
        "question": "In the Transformer architecture, what is the purpose of multi-head attention?",
        "choices": [
            "To allow the model to attend to information from different representation subspaces at different positions",
            "To reduce the computational cost of attention by splitting the input into smaller chunks",
            "To prevent the model from attending to future tokens during training",
        ],
        "correct": 0,
        "explanation": {
            "correct": "Multi-head attention runs several attention functions in parallel, each learning different relationships, then concatenates and projects the results.",
            "wrong": [
                "While the per-head dimension is smaller, multi-head attention does not primarily aim to reduce cost — it enriches representational capacity.",
                "Preventing attention to future tokens is the role of causal (masked) attention, not multi-head attention itself.",
            ],
        },
    },
]


def _load_existing_questions() -> list[dict]:
    """Load existing questions from disk, returning an empty list if the file
    does not exist or is empty."""
    if not QUESTIONS_FILE.exists():
        return []
    try:
        with open(QUESTIONS_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_questions(questions: list[dict]) -> None:
    """Persist the full question list to disk."""
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(questions, f, indent=2)
        f.write("\n")


def _existing_ids(questions: list[dict]) -> set[str]:
    return {q["id"] for q in questions}


def _next_id(prefix: str, existing: set[str]) -> str:
    """Return the next available ID for a given rank prefix, e.g. 'e003'."""
    num = 1
    while True:
        candidate = f"{prefix}{num:03d}"
        if candidate not in existing:
            return candidate
        num += 1


def _build_prompt(
    count: int,
    existing_questions: list[dict],
    rank: str | None = None,
    focus_area: str | None = None,
) -> str:
    rank_block = "\n".join(f"  - {v}" for v in RANK_DESCRIPTIONS.values())

    example_json = json.dumps(EXAMPLE_QUESTIONS, indent=2)

    # Collect existing question texts so the model can avoid duplicates.
    existing_texts = [q["question"] for q in existing_questions]
    dedup_block = ""
    if existing_texts:
        dedup_block = (
            "\n\n--- EXISTING QUESTIONS (do NOT duplicate these) ---\n"
            + "\n".join(f"- {t}" for t in existing_texts)
            + "\n--- END EXISTING QUESTIONS ---"
        )

    rank_instruction = ""
    if rank:
        rank_instruction = (
            f"\nGenerate ALL questions at rank {rank} "
            f"({RANK_DESCRIPTIONS.get(rank, rank)})."
        )

    focus_instruction = ""
    if focus_area:
        focus_instruction = (
            f"\nFocus the questions on the topic area: {focus_area}."
        )

    prompt = f"""\
You are an expert machine learning quiz question generator.

Generate exactly {count} multiple-choice quiz questions for an ML learning app.
Each question MUST have exactly 3 choices, one correct answer, and detailed explanations.

RANK SYSTEM (difficulty tiers):
{rank_block}
{rank_instruction}{focus_instruction}

If no specific rank is requested, distribute questions across multiple ranks.

JSON SCHEMA for each question:
{QUESTION_SCHEMA}

EXAMPLES:
{example_json}
{dedup_block}

RULES:
1. Return ONLY a JSON array of question objects — no commentary, no markdown.
2. Each question must have exactly 3 choices.
3. The "correct" field must be an integer index (0, 1, or 2).
4. The "explanation.wrong" array must have exactly 2 entries (one per wrong choice).
5. Do NOT duplicate any existing question listed above.
6. Make questions challenging and educational, not trivial.
7. Use the id format "<rank_prefix><3-digit-number>" (e.g. e001, b003, s012).
   Use placeholder IDs — they will be reassigned to avoid collisions.

Return the JSON array now."""

    return prompt


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```) if present."""
    stripped = text.strip()
    # Remove opening fence
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
    # Remove closing fence
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def _validate_question(q: dict) -> bool:
    """Return True if a question object passes all structural checks."""
    if not isinstance(q, dict):
        return False
    required_keys = {"id", "rank", "question", "choices", "correct", "explanation"}
    if not required_keys.issubset(q.keys()):
        return False
    if not isinstance(q["choices"], list) or len(q["choices"]) != 3:
        return False
    if q["correct"] not in (0, 1, 2):
        return False
    if not isinstance(q["explanation"], dict):
        return False
    if "correct" not in q["explanation"] or "wrong" not in q["explanation"]:
        return False
    if (
        not isinstance(q["explanation"]["wrong"], list)
        or len(q["explanation"]["wrong"]) != 2
    ):
        return False
    if q["rank"] not in RANK_PREFIXES:
        return False
    return True


def generate_questions(
    focus_area: str | None = None,
    rank: str | None = None,
    count: int = 10,
) -> list[dict]:
    """Generate new ML quiz questions via the claude CLI.

    Args:
        focus_area: Optional topic to focus questions on (e.g. "transformers").
        rank: Optional single rank letter (E/D/C/B/A/S) to constrain difficulty.
        count: Number of questions to generate.

    Returns:
        List of newly generated (and validated) question dicts.
    """
    existing = _load_existing_questions()
    prompt = _build_prompt(count, existing, rank=rank, focus_area=focus_area)

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        print("Error: 'claude' CLI not found. Please install it first.", file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        print("Error: claude CLI timed out after 120 seconds.", file=sys.stderr)
        return []

    if result.returncode != 0:
        print(f"Error: claude CLI exited with code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return []

    raw_output = result.stdout.strip()
    if not raw_output:
        print("Error: claude CLI returned empty output.", file=sys.stderr)
        return []

    cleaned = _strip_markdown_fences(raw_output)

    try:
        generated = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"Error: Failed to parse JSON from claude output: {exc}", file=sys.stderr)
        print(f"Raw output (first 500 chars): {raw_output[:500]}", file=sys.stderr)
        return []

    if not isinstance(generated, list):
        print("Error: Expected a JSON array from claude output.", file=sys.stderr)
        return []

    # Validate and assign unique IDs.
    used_ids = _existing_ids(existing)
    valid_questions: list[dict] = []

    for q in generated:
        if not _validate_question(q):
            print(f"Warning: Skipping invalid question: {q.get('question', '<no text>')!r}", file=sys.stderr)
            continue

        prefix = RANK_PREFIXES[q["rank"]]
        new_id = _next_id(prefix, used_ids)
        q["id"] = new_id
        used_ids.add(new_id)
        valid_questions.append(q)

    if valid_questions:
        all_questions = existing + valid_questions
        _save_questions(all_questions)
        print(f"Successfully generated {len(valid_questions)} question(s) and saved to {QUESTIONS_FILE}.")
    else:
        print("No valid questions were generated.", file=sys.stderr)

    return valid_questions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ML quiz questions using the claude CLI."
    )
    parser.add_argument(
        "-n",
        type=int,
        default=10,
        help="Number of questions to generate (default: 10)",
    )
    parser.add_argument(
        "-r",
        type=str,
        default=None,
        choices=list(RANK_PREFIXES.keys()),
        help="Rank/difficulty level (E/D/C/B/A/S). Default: mixed.",
    )
    parser.add_argument(
        "-f",
        type=str,
        default=None,
        help='Focus area / topic (e.g. "transformers", "regularization").',
    )
    args = parser.parse_args()

    questions = generate_questions(focus_area=args.f, rank=args.r, count=args.n)

    if questions:
        print(f"\nGenerated {len(questions)} question(s):")
        for q in questions:
            print(f"  [{q['id']}] ({q['rank']}-Rank) {q['question']}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
