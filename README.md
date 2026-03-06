# Solo Leveling: ML Hunter Exam

A self-hosted ML quiz app with a Solo Leveling RPG theme. Study machine learning disguised as a hunter ranking system.

No API keys needed for the base experience — 50 pre-built questions are included. Generate more using the `claude` CLI.

## Quick Start

```bash
cd solo_leveling
uv run server.py        # Opens browser at http://localhost:8000
```

## Generate More Questions

From the UI: type a focus area in the sidebar and click "Generate Quests".

From the CLI:

```bash
uv run generate_questions.py                     # 10 mixed questions
uv run generate_questions.py -n 5 -r S           # 5 S-rank questions
uv run generate_questions.py -f "transformers"   # focused on transformers
```

Requires `claude` CLI to be installed and authenticated.

## 8-Week Curriculum

| Weeks | Rank | Topics |
|-------|------|--------|
| 1-2 | E-Rank | ML fundamentals: bias/variance, overfitting, linear models, metrics |
| 2-3 | D-Rank | Core techniques: regularization, gradient descent, SVMs, trees |
| 3-4 | C-Rank | Deep learning: CNNs, RNNs/LSTMs, backprop, batch norm, dropout |
| 5-6 | B-Rank | Advanced: transformers, attention, VAEs, GANs, RL |
| 6-7 | A-Rank | Expert: optimization theory, information theory, diffusion models |
| 7-8 | S-Rank | Master: cutting-edge research, adversarial robustness, scaling laws |

## Game Mechanics

- **3-choice hard questions** with detailed explanations
- **XP system**: earn more XP for harder ranks (E:10 to S:100), streak bonus up to 2x
- **10 levels per rank** — rank up at level 10 with a system animation
- **Question mix**: 70% current rank, 20% harder, 10% easier
- **Progress saved** in browser localStorage

## Adding Custom Questions

Questions are stored in a SQLite database (`resources/questions.db`). On first run, the seed file `resources/questions.json` is automatically migrated into the DB.

To add questions, use the CLI or UI generate feature, or insert directly via the `db` module:

```python
import db
from models import Question

q = Question(id="e051", rank="E", question="Your question?", ...)
db.ensure_ready()
db.insert_questions([q])
```

## Project Structure

```
solo_leveling/
  pyproject.toml            # uv project config
  server.py                 # Flask server with API
  generate_questions.py     # Auto-generate questions via claude CLI
  models.py                 # Pydantic models (Question, etc.)
  db.py                     # SQLite access layer
  static/
    index.html              # Frontend (single file)
  resources/
    questions.json          # Seed question bank (auto-migrated on first run)
    questions.db            # SQLite database (generated, git-ignored)
```
