"""Flask server for the Solo Leveling ML quiz app."""

import json
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

RESOURCES_DIR = Path(__file__).parent / "resources"


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/resources/<path:filename>")
def serve_resource(filename):
    return send_from_directory(RESOURCES_DIR, filename)


@app.get("/api/questions")
def get_questions():
    questions_file = RESOURCES_DIR / "questions.json"
    with open(questions_file) as f:
        questions = json.load(f)
    return jsonify(questions)


@app.post("/api/generate")
def generate():
    data = request.get_json()
    focus_area = data.get("focus_area", "transformers")
    rank = data.get("rank", "B")
    count = data.get("count", 5)

    from generate_questions import generate_questions

    questions = generate_questions(focus_area=focus_area, rank=rank, count=count)
    return jsonify(questions)


def main():
    webbrowser.open("http://localhost:8000")
    app.run(host="localhost", port=8000)


if __name__ == "__main__":
    main()
