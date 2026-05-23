from flask import Flask, request, jsonify, send_from_directory, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
import os
import json
from datetime import timedelta
from functools import wraps

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'sphinx_university_super_secret_key')

# Use DATABASE_URL from environment if available
db_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

CORS(app, supports_credentials=True)

db = SQLAlchemy(app)

# =========================================================
# 🔹 MODELS
# =========================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False)

    password_hash = db.Column(db.String(256), nullable=False)

    # 🔥 ADMIN FLAG
    is_admin = db.Column(db.Boolean, default=False)

    chats = db.relationship('Chat', backref='user', lazy=True)


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    session_id = db.Column(db.String(100), default="default", nullable=False)

    user_message = db.Column(db.Text, nullable=False)

    bot_reply = db.Column(db.Text, nullable=False)

    timestamp = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )


# 🔥 NEW TABLE FOR EXAMS
class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    subject = db.Column(db.String(100), nullable=False)

    exam_date = db.Column(db.String(100), nullable=False)

    academic_year = db.Column(db.String(100), nullable=False)


# =========================================================
# 🔹 ADMIN DECORATOR
# =========================================================

def admin_required(f):

    @wraps(f)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return jsonify({"error": "يجب تسجيل الدخول"}), 401

        user = User.query.get(session["user_id"])

        if not user or not user.is_admin:
            return jsonify({"error": "Admins only"}), 403

        return f(*args, **kwargs)

    return wrapper


# =========================================================
# 🔹 GEMINI CONFIG
# =========================================================

ENV_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")

API_KEYS = [k.strip() for k in ENV_KEYS if k.strip()]

MODEL_VERSIONS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

model_idx = 0


# =========================================================
# 🔹 LOAD CHATBOT CONTEXT
# =========================================================

CHATBOT_CONTEXT = ""

base_dir = os.path.dirname(__file__)

file_path = os.path.join(base_dir, "chatbot.txt")

try:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        CHATBOT_CONTEXT = f.read()

except Exception as e:
    print(f"Warning: {e}")

if not CHATBOT_CONTEXT.strip():
    CHATBOT_CONTEXT = "Sphinx University Information."


# =========================================================
# 🔹 UNIVERSITY RULES
# =========================================================

UNIVERSITY_RULES = """
Sphinx University Graduation Requirements:
- Total credit hours required: 138
- Minimum GPA: 2.0
- Minimum attendance rate: 75%
- Maximum study duration: 8 years
"""


# =========================================================
# 🔹 SYSTEM PROMPT
# =========================================================

SYSTEM_INSTRUCTION = f"""
You are a friendly academic advisor for Sphinx University.

Use this knowledge:

{CHATBOT_CONTEXT}

Rules:

{UNIVERSITY_RULES}

Always respond naturally.
"""


# =========================================================
# 🔹 GEMINI MODEL
# =========================================================

def get_next_model():

    global model_idx

    if not API_KEYS:
        raise ValueError("No API Keys configured.")

    k_idx = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)

    m_idx = model_idx % len(MODEL_VERSIONS)

    genai.configure(api_key=API_KEYS[k_idx])

    return genai.GenerativeModel(
        MODEL_VERSIONS[m_idx],
        system_instruction=SYSTEM_INSTRUCTION
    )


try:
    model = get_next_model()

except Exception as e:

    print(e)

    class MockModel:

        def generate_content(self, *args, **kwargs):
            return type(
                'obj',
                (object,),
                {'text': 'AI Error'}
            )

        def start_chat(self, *args, **kwargs):
            return type(
                'obj',
                (object,),
                {
                    'send_message': lambda msg: type(
                        'obj',
                        (object,),
                        {'text': 'AI Error'}
                    )
                }
            )

    model = MockModel()


# =========================================================
# 🔹 MEMORY
# =========================================================

response_cache = {}

chat_sessions = {}

import difflib


# =========================================================
# 🔹 LOCAL SEARCH
# =========================================================

def find_local_match(user_query):

    if not CHATBOT_CONTEXT:
        return None

    lines = [
        line.strip()
        for line in CHATBOT_CONTEXT.split("\n")
        if line.strip()
    ]

    matches = difflib.get_close_matches(
        user_query,
        lines,
        n=1,
        cutoff=0.3
    )

    if matches:
        return "📚 (من اللائحة): " + matches[0]

    return None


# =========================================================
# 🔹 REGISTER
# =========================================================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json() or {}

    username = data.get("username", "").strip()

    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "بيانات ناقصة"}), 400

    existing_user = User.query.filter_by(
        username=username
    ).first()

    if existing_user:
        return jsonify({"error": "المستخدم موجود بالفعل"}), 400

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password)
    )

    db.session.add(new_user)

    db.session.commit()

    session["user_id"] = new_user.id

    session["username"] = new_user.username

    return jsonify({
        "success": True,
        "username": new_user.username
    })


# =========================================================
# 🔹 LOGIN
# =========================================================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json() or {}

    username = data.get("username", "").strip()

    password = data.get("password", "").strip()

    user = User.query.filter_by(
        username=username
    ).first()

    if user and check_password_hash(
        user.password_hash,
        password
    ):

        session["user_id"] = user.id

        session["username"] = user.username

        return jsonify({
            "success": True,
            "username": user.username
        })

    return jsonify({
        "error": "اسم المستخدم أو كلمة المرور خطأ"
    }), 401


# =========================================================
# 🔹 LOGOUT
# =========================================================

@app.route("/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "success": True
    })


# =========================================================
# 🔹 CHECK AUTH
# =========================================================

@app.route("/check_auth", methods=["GET"])
def check_auth():

    if "user_id" in session:

        return jsonify({
            "logged_in": True,
            "username": session["username"]
        })

    return jsonify({
        "logged_in": False
    })


# =========================================================
# 🔹 ADMIN ROUTES
# =========================================================

@app.route("/admin/add_exam", methods=["POST"])
@admin_required
def add_exam():

    data = request.get_json() or {}

    subject = data.get("subject")

    exam_date = data.get("exam_date")

    academic_year = data.get("academic_year")

    if not subject or not exam_date or not academic_year:
        return jsonify({"error": "بيانات ناقصة"}), 400

    exam = Exam(
        subject=subject,
        exam_date=exam_date,
        academic_year=academic_year
    )

    db.session.add(exam)

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "تم إضافة الامتحان"
    })


@app.route("/get_exams", methods=["GET"])
def get_exams():

    exams = Exam.query.all()

    result = []

    for exam in exams:

        result.append({
            "subject": exam.subject,
            "exam_date": exam.exam_date,
            "academic_year": exam.academic_year
        })

    return jsonify({
        "success": True,
        "exams": result
    })


# 🔥 TEMP ROUTE TO MAKE ADMIN
@app.route("/make_admin/<username>")
def make_admin(username):

    user = User.query.filter_by(
        username=username
    ).first()

    if not user:
        return "User not found"

    user.is_admin = True

    db.session.commit()

    return f"{username} is now admin"


# =========================================================
# 🔹 GET CHATS
# =========================================================

@app.route("/get_chats", methods=["GET"])
def get_chats():

    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    chats = Chat.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Chat.timestamp.asc()).all()

    sessions_dict = {}

    for chat in chats:

        s_id = chat.session_id

        if s_id not in sessions_dict:

            title = (
                chat.user_message[:30] + "..."
                if len(chat.user_message) > 30
                else chat.user_message
            )

            sessions_dict[s_id] = {
                "session_id": s_id,
                "title": title,
                "messages": []
            }

        sessions_dict[s_id]["messages"].append({
            "sender": "user",
            "text": chat.user_message
        })

        sessions_dict[s_id]["messages"].append({
            "sender": "bot",
            "text": chat.bot_reply
        })

    sessions_list = list(sessions_dict.values())

    sessions_list.reverse()

    return jsonify({
        "success": True,
        "sessions": sessions_list,
        "username": session["username"]
    })


# =========================================================
# 🔹 CHAT
# =========================================================

@app.route("/chat", methods=["POST"])
def chat():

    if "user_id" not in session:
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    data = request.get_json() or {}

    return _handle_chat(data)


def _handle_chat(data):

    global model, model_idx

    try:

        user_message = data.get("message", "").strip()

        session_id = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        # =================================================
        # 🔥 SEARCH EXAMS FIRST
        # =================================================

        exams = Exam.query.all()

        for exam in exams:

            if exam.subject.lower() in user_message.lower():

                reply = f"📚 امتحان مادة {exam.subject} يوم {exam.exam_date} للفرقة {exam.academic_year}"

                return jsonify({
                    "reply": reply,
                    "session_id": session_id,
                    "source": "database"
                })

        # =================================================
        # 🔥 LOCAL SEARCH
        # =================================================

        local_reply = find_local_match(user_message)

        if local_reply:

            return jsonify({
                "reply": local_reply,
                "session_id": session_id,
                "source": "local"
            })

        # =================================================
        # 🔥 CACHE
        # =================================================

        cache_key = user_message.lower()

        if cache_key in response_cache:

            return jsonify({
                "reply": response_cache[cache_key],
                "session_id": session_id,
                "source": "cache"
            })

        # =================================================
        # 🔥 AI
        # =================================================

        if session_id not in chat_sessions:
            chat_sessions[session_id] = []

        history = chat_sessions[session_id]

        gemini_history = []

        for turn in history[-5:]:

            gemini_history.append({
                "role": "user",
                "parts": [turn["user"]]
            })

            gemini_history.append({
                "role": "model",
                "parts": [turn["bot"]]
            })

        chat_ai = model.start_chat(history=gemini_history)

        response = chat_ai.send_message(user_message)

        bot_reply = response.text.strip()

        if not bot_reply.startswith("🤖"):
            bot_reply = "🤖 (AI): " + bot_reply

        # SAVE CHAT

        user_id = session.get("user_id")

        if user_id:

            new_chat = Chat(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                bot_reply=bot_reply
            )

            db.session.add(new_chat)

            db.session.commit()

        response_cache[cache_key] = bot_reply

        history.append({
            "user": user_message,
            "bot": bot_reply
        })

        return jsonify({
            "reply": bot_reply,
            "session_id": session_id,
            "source": "ai"
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# 🔹 REQUIREMENTS CHECKER
# =========================================================

@app.route("/check-requirements", methods=["POST"])
def check_requirements():

    try:

        data = request.get_json()

        credit_hours = data.get("credit_hours", 0)

        gpa = data.get("gpa", 0.0)

        attendance = data.get("attendance", 0)

        years = data.get("years", 0)

        can_graduate = (
            int(credit_hours) >= 138 and
            float(gpa) >= 2.0 and
            int(attendance) >= 75 and
            int(years) <= 8
        )

        result = (
            "🎓 مؤهل للتخرج"
            if can_graduate
            else "📚 غير مؤهل بعد"
        )

        return jsonify({
            "analysis": result,
            "can_graduate": can_graduate
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# 🔹 HOME
# =========================================================

@app.route("/", methods=["GET"])
def index():

    return render_template("index.html")


@app.route("/<path:path>", methods=["GET"])
def serve_static(path):

    return send_from_directory("static", path)


# =========================================================
# 🔹 INIT DATABASE
# =========================================================

with app.app_context():

    db.create_all()


# =========================================================
# 🔹 RUN
# =========================================================

if __name__ == "__main__":

    app.run(debug=True, port=5000)
