"""Flask server for the Solo Leveling ML quiz app."""

import webbrowser

from flask import Flask, jsonify, request, send_from_directory

import db
from models import GenerateRequest, GenerateResponse

app = Flask(__name__, static_folder="static")

RESOURCES_DIR = db.RESOURCES_DIR


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/resources/<path:filename>")
def serve_resource(filename):
    return send_from_directory(RESOURCES_DIR, filename)


@app.get("/api/questions")
def get_questions():
    questions = db.get_all_questions()
    return jsonify([q.model_dump() for q in questions])


@app.get("/api/summary")
def get_summary():
    return jsonify(db.get_summary())


@app.post("/api/generate")
def generate():
    data = request.get_json()
    try:
        req = GenerateRequest.model_validate(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    from generate_questions import generate_questions

    questions = generate_questions(focus_area=req.focus_area, rank=req.rank, count=req.count)
    resp = GenerateResponse(generated=len(questions), questions=questions)
    return jsonify(resp.model_dump())


def main():
    db.ensure_ready()
    webbrowser.open("http://localhost:8000")
    app.run(host="localhost", port=8000, threaded=True)


if __name__ == "__main__":
    main()
