from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import google.generativeai as genai
import os
import json
import sqlite3
import datetime

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# --------------------------
# 🔹 SQLite Database Setup
# --------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "chat_history.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --------------------------
# 🔹 Gemini Setup (Environment Variables)
# --------------------------
ENV_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
API_KEYS = [k.strip() for k in ENV_KEYS if k.strip()]

MODEL_VERSIONS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-pro-latest",
]

model_idx = 0

# --------------------------
# 🔹 Load Knowledge Base
# --------------------------
CHATBOT_CONTEXT = ""
base_dir = os.path.dirname(__file__)
target_files = ["chatbot (3).txt", "chatbot.txt", "chatbot (1).txt"]
txt_files = [f for f in os.listdir(base_dir) if f in target_files]

for filename in txt_files:
    file_path = os.path.join(base_dir, filename)
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            CHATBOT_CONTEXT += f"\n--- SOURCE: {filename} ---\n{content}\n"
    except Exception as e:
        print(f"Warning: Could not read {filename}: {e}")

if not CHATBOT_CONTEXT.strip():
    CHATBOT_CONTEXT = "University Information: Sphinx University uses a credit hour system."

# --------------------------
# 🔹 University Rules
# --------------------------
UNIVERSITY_RULES = """
Sphinx University Graduation Requirements:
- Total credit hours required: 138
- Minimum GPA: 2.0 (on a 4.0 scale)
- Minimum attendance rate: 75%
- Maximum study duration: 8 years (16 semesters)
- Students must pass all core/mandatory courses
- Students on academic probation must achieve GPA ≥ 2.0 next semester
- A student fails a course if attendance drops below 75%
- Failed courses can be retaken (counted toward max duration)
"""

# --------------------------
# 🔹 System Prompt
# --------------------------
SYSTEM_INSTRUCTION = f"""You are a friendly human academic advisor for Sphinx University.
You have access to the following university knowledge base and rules.

=== UNIVERSITY KNOWLEDGE BASE ===
{CHATBOT_CONTEXT}

=== GRADUATION RULES ===
{UNIVERSITY_RULES}

=== YOUR BEHAVIOR ===
1. You must first ALWAYS check if the answer exists in the UNIVERSITY KNOWLEDGE BASE or GRADUATION RULES.
2. IF the answer depends on the provided university rules or context, you MUST start your reply exactly with "📚 (من اللائحة): " and provide the rule directly in conversational human text.
3. IF the answer is NOT in the rules/context, you MUST start your reply exactly with "🤖 (AI): " and answer from your general knowledge.
4. DO NOT use any markdown formatting (no asterisks **, no hash #). DO NOT use bullet points or numbered lists.
5. DO NOT output any code or JSON. Speak exactly like a normal person chatting on WhatsApp.
6. If the student shares their academic data (credit hours, GPA, attendance), calculate their eligibility naturally in conversation and prefix with "📊 (تحليل البيانات): ".
7. Respond in the same language the student uses (Arabic or English), and be extremely empathetic and warm."""

# --------------------------
# 🔹 Gemini Model
# --------------------------
def get_next_model():
    global model_idx
    k_idx = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)
    m_idx = model_idx % len(MODEL_VERSIONS)
    genai.configure(api_key=API_KEYS[k_idx])
    model_name = MODEL_VERSIONS[m_idx]
    print(f"Rotation: Key[{k_idx}] | Model: {model_name}")
    return genai.GenerativeModel(model_name, system_instruction=SYSTEM_INSTRUCTION)

try:
    model = get_next_model()
except Exception as e:
    print(f"Warning: Could not initialize Gemini model: {e}")
    class MockModel:
        def generate_content(self, *args, **kwargs):
            return type('obj', (object,), {'text': 'AI Error: No API keys configured.'})
        def start_chat(self, *args, **kwargs):
            return type('obj', (object,), {'send_message': lambda msg: type('obj', (object,), {'text': 'AI Error: No API keys configured.'})})
    model = MockModel()

response_cache = {}

# --------------------------
# 🔹 Similarity Search
# --------------------------
import difflib

def find_local_match(user_query):
    if not CHATBOT_CONTEXT:
        return None
    lines = [line.strip() for line in CHATBOT_CONTEXT.split("\n") if line.strip()]
    matches = difflib.get_close_matches(user_query, lines, n=1, cutoff=0.6)
    if matches:
        return "📚 (من اللائحة): " + matches[0]
    return None

# --------------------------
# 🔹 Helper: Generate session title from first message
# --------------------------
def generate_title(message):
    words = message.strip().split()
    title = " ".join(words[:6])
    if len(words) > 6:
        title += "..."
    return title or "New Chat"

# --------------------------
# 🔹 /chat Endpoint
# --------------------------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    return _handle_chat(data)

def _handle_chat(data):
    global model, model_idx
    try:
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        now = datetime.datetime.utcnow().isoformat()

        # Ensure session exists in DB
        conn = get_db()
        cursor = conn.cursor()
        session = cursor.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            title = generate_title(user_message)
            cursor.execute(
                "INSERT INTO chat_sessions (id, title, created_at, updated_at, message_count) VALUES (?, ?, ?, ?, 0)",
                (session_id, title, now, now)
            )
            conn.commit()

        # Save user message to DB
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, "user", user_message, now)
        )
        conn.commit()

        # 1️⃣ Local match
        local_reply = find_local_match(user_message)
        if local_reply:
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, "bot", local_reply, now)
            )
            cursor.execute(
                "UPDATE chat_sessions SET updated_at = ?, message_count = message_count + 2 WHERE id = ?",
                (now, session_id)
            )
            conn.commit()
            conn.close()
            return jsonify({"reply": local_reply, "session_id": session_id, "source": "local"})

        # 2️⃣ Cache
        cache_key = user_message.lower()
        if cache_key in response_cache:
            bot_reply = response_cache[cache_key]
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, "bot", bot_reply, now)
            )
            cursor.execute(
                "UPDATE chat_sessions SET updated_at = ?, message_count = message_count + 2 WHERE id = ?",
                (now, session_id)
            )
            conn.commit()
            conn.close()
            return jsonify({"reply": bot_reply, "session_id": session_id, "source": "cache"})

        # 3️⃣ AI — load history from DB
        db_history = cursor.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT 10",
            (session_id,)
        ).fetchall()
        db_history = list(reversed(db_history))[:-1]  # exclude the message we just inserted

        gemini_history = []
        for row in db_history:
            role = "model" if row["role"] == "bot" else "user"
            gemini_history.append({"role": role, "parts": [row["content"]]})

        conn.close()

        chat_session = model.start_chat(history=gemini_history)
        response = chat_session.send_message(user_message)
        bot_reply = response.text.strip()

        if not bot_reply.startswith("🤖") and not bot_reply.startswith("📚") and not bot_reply.startswith("📊"):
            bot_reply = "🤖 (AI): " + bot_reply

        response_cache[cache_key] = bot_reply

        # Save bot reply to DB
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, "bot", bot_reply, now)
        )
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = ?, message_count = message_count + 2 WHERE id = ?",
            (now, session_id)
        )
        conn.commit()
        conn.close()

        return jsonify({"reply": bot_reply, "session_id": session_id, "source": "ai"})

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg or "404" in error_msg:
            retries = data.get("retries", 0)
            if retries >= len(MODEL_VERSIONS) * len(API_KEYS):
                friendly_err = "عذراً، ضغط الأسئلة كبير حالياً على جميع المفاتيح. يرجى الانتظار 30 ثانية والمحاولة مرة أخرى ⏱️"
                return jsonify({"error": friendly_err}), 429
            model_idx += 1
            model = get_next_model()
            data["retries"] = retries + 1
            return _handle_chat(data)
        return jsonify({"error": f"AI Error: {error_msg}"}), 500


# --------------------------
# 🔹 /sessions — Get all chat sessions
# --------------------------
@app.route("/sessions", methods=["GET"])
def get_sessions():
    conn = get_db()
    cursor = conn.cursor()
    sessions = cursor.execute(
        "SELECT id, title, created_at, updated_at, message_count FROM chat_sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(s) for s in sessions])


# --------------------------
# 🔹 /sessions/<id> — Get messages for a session
# --------------------------
@app.route("/sessions/<session_id>", methods=["GET"])
def get_session_messages(session_id):
    conn = get_db()
    cursor = conn.cursor()
    session = cursor.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        return jsonify({"error": "Session not found"}), 404
    messages = cursor.execute(
        "SELECT role, content, timestamp FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        "session": dict(session),
        "messages": [dict(m) for m in messages]
    })


# --------------------------
# 🔹 /sessions/<id> DELETE — Delete a session
# --------------------------
@app.route("/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# --------------------------
# 🔹 /sessions/search — Search sessions by keyword
# --------------------------
@app.route("/sessions/search", methods=["GET"])
def search_sessions():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    conn = get_db()
    cursor = conn.cursor()
    results = cursor.execute(
        """SELECT DISTINCT cs.id, cs.title, cs.created_at, cs.updated_at, cs.message_count
           FROM chat_sessions cs
           JOIN chat_messages cm ON cs.id = cm.session_id
           WHERE cs.title LIKE ? OR cm.content LIKE ?
           ORDER BY cs.updated_at DESC""",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in results])


# --------------------------
# 🔹 /check-requirements Endpoint
# --------------------------
@app.route("/check-requirements", methods=["POST"])
def check_requirements():
    try:
        data = request.get_json()
        credit_hours = data.get("credit_hours", 0)
        gpa = data.get("gpa", 0.0)
        attendance = data.get("attendance", 0)
        years = data.get("years", 0)
        student_name = data.get("name", "Student")

        prompt = f"""You are a strict academic advisor at Sphinx University.

{UNIVERSITY_RULES}

A student named {student_name} has submitted their academic record for graduation eligibility check:
- Completed Credit Hours: {credit_hours} / 138 required
- Current GPA: {gpa} / 4.0 (minimum required: 2.0)
- Attendance Rate: {attendance}% (minimum required: 75%)
- Years of Study: {years} / 8 maximum

Please provide:
1. ✅ or ❌ for each requirement (pass/fail)
2. An overall verdict: CAN GRADUATE or CANNOT GRADUATE YET
3. If cannot graduate: specific advice on what to improve
4. If can graduate: congratulations and graduation readiness summary
5. Estimated semesters remaining (if applicable)

Be structured, clear, and supportive. Use emojis. Respond in both Arabic and English."""

        response = model.generate_content(prompt)
        result = response.text.strip()

        can_graduate = (
            int(credit_hours) >= 138 and
            float(gpa) >= 2.0 and
            int(attendance) >= 75 and
            int(years) <= 8
        )

        return jsonify({
            "analysis": result,
            "can_graduate": can_graduate,
            "details": {
                "credit_hours": {"value": credit_hours, "required": 138, "pass": int(credit_hours) >= 138},
                "gpa": {"value": gpa, "required": 2.0, "pass": float(gpa) >= 2.0},
                "attendance": {"value": attendance, "required": 75, "pass": int(attendance) >= 75},
                "years": {"value": years, "required": 8, "pass": int(years) <= 8}
            }
        })

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "عذراً، يرجى الانتظار دقيقة والمحاولة."}), 429
        return jsonify({"error": f"AI Error: {error_msg}"}), 500


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/<path:path>", methods=["GET"])
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": "gemini-2.0-flash"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Smart Academic Advisor API running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
