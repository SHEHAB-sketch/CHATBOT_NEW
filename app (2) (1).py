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

db_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
CORS(app, supports_credentials=True)

db = SQLAlchemy(app)

# --------------------------
# 🔹 Database Models
# --------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    chats = db.relationship('Chat', backref='user', lazy=True)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_id = db.Column(db.String(100), default="default", nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_reply = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

class Exam(db.Model):
    """Dynamic exam schedule managed by Admin"""
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(200), nullable=False)
    course_code = db.Column(db.String(50), nullable=True)
    exam_date = db.Column(db.String(100), nullable=False)   # e.g. "5 June 2025"
    exam_time = db.Column(db.String(50), nullable=True)     # e.g. "10:00 AM"
    exam_location = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "course_name": self.course_name,
            "course_code": self.course_code,
            "exam_date": self.exam_date,
            "exam_time": self.exam_time,
            "exam_location": self.exam_location,
            "notes": self.notes,
        }

class Announcement(db.Model):
    """Dynamic announcements managed by Admin"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), default="general")  # general, deadline, event, etc.
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "is_active": self.is_active,
            "created_at": str(self.created_at),
        }

# --------------------------
# 🔹 Gemini Setup
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
# 🔹 Load Static Knowledge Base (chatbot.txt)
# --------------------------
CHATBOT_CONTEXT = ""
base_dir = os.path.dirname(__file__)
file_path = os.path.join(base_dir, "chatbot.txt")

try:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        CHATBOT_CONTEXT = f.read()
except Exception as e:
    print(f"Warning: Could not read chatbot.txt: {e}")

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
- Students on academic probation must achieve GPA >= 2.0 next semester
- A student fails a course if attendance drops below 75%
- Failed courses can be retaken (counted toward max duration)
"""

# --------------------------
# 🔹 Dynamic DB Context Builder
# --------------------------
def build_dynamic_context():
    """Reads live data from DB and returns a formatted string for the AI prompt."""
    context_parts = []

    # Load active exams
    exams = Exam.query.all()
    if exams:
        exam_lines = ["=== EXAM SCHEDULE (Live from Admin) ==="]
        for e in exams:
            line = f"- {e.course_name}"
            if e.course_code:
                line += f" ({e.course_code})"
            line += f": {e.exam_date}"
            if e.exam_time:
                line += f" at {e.exam_time}"
            if e.exam_location:
                line += f", Location: {e.exam_location}"
            if e.notes:
                line += f". Note: {e.notes}"
            exam_lines.append(line)
        context_parts.append("\n".join(exam_lines))

    # Load active announcements
    announcements = Announcement.query.filter_by(is_active=True).all()
    if announcements:
        ann_lines = ["=== ACTIVE ANNOUNCEMENTS (Live from Admin) ==="]
        for a in announcements:
            ann_lines.append(f"[{a.category.upper()}] {a.title}: {a.content}")
        context_parts.append("\n".join(ann_lines))

    return "\n\n".join(context_parts)


def build_system_instruction():
    """Builds the full system prompt with live DB data."""
    dynamic_context = build_dynamic_context()

    return f"""You are a friendly human academic advisor for Sphinx University.
You have access to the following university knowledge base, rules, and LIVE data.

=== UNIVERSITY KNOWLEDGE BASE ===
{CHATBOT_CONTEXT}

=== GRADUATION RULES ===
{UNIVERSITY_RULES}

{dynamic_context}

=== YOUR BEHAVIOR ===
1. ALWAYS check the UNIVERSITY KNOWLEDGE BASE, GRADUATION RULES, EXAM SCHEDULE, and ANNOUNCEMENTS first.
2. If the answer comes from the university rules or live data (exams, announcements): start reply with "📚 (من اللائحة): "
3. If the answer is NOT in any provided data: start reply with "🤖 (AI): " and answer from general knowledge.
4. DO NOT use markdown formatting (no asterisks **, no hash #). DO NOT use bullet points or numbered lists.
5. DO NOT output any code or JSON. Speak like a normal person chatting on WhatsApp.
6. If the student shares academic data (credit hours, GPA, attendance), analyze eligibility naturally and prefix with "📊 (تحليل البيانات): ".
7. Respond in the same language the student uses (Arabic or English), and be empathetic and warm."""


# --------------------------
# 🔹 Gemini Model Init
# --------------------------
def get_next_model():
    global model_idx
    if not API_KEYS:
        raise ValueError("No API keys configured.")
    k_idx = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)
    m_idx = model_idx % len(MODEL_VERSIONS)
    genai.configure(api_key=API_KEYS[k_idx])
    model_name = MODEL_VERSIONS[m_idx]
    return genai.GenerativeModel(model_name, system_instruction=build_system_instruction())

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
chat_sessions = {}

import difflib

def find_local_match(user_query):
    if not CHATBOT_CONTEXT:
        return None
    lines = [line.strip() for line in CHATBOT_CONTEXT.split("\n") if line.strip()]
    matches = difflib.get_close_matches(user_query, lines, n=1, cutoff=0.3)
    if matches:
        return "📚 (من اللائحة): " + matches[0]
    return None

# --------------------------
# 🔹 Admin Auth Decorator
# --------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "يجب تسجيل الدخول"}), 401
        user = User.query.get(session["user_id"])
        if not user or not user.is_admin:
            return jsonify({"error": "غير مصرح لك. هذه الصفحة للأدمن فقط."}), 403
        return f(*args, **kwargs)
    return decorated

# --------------------------
# 🔹 Auth Routes
# --------------------------
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return jsonify({"error": "اسم المستخدم موجود مسبقاً"}), 400

    hashed_password = generate_password_hash(password)
    new_user = User(username=username, password_hash=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    session["user_id"] = new_user.id
    session["username"] = new_user.username
    session["is_admin"] = new_user.is_admin

    return jsonify({"success": True, "message": "تم التسجيل بنجاح", "username": new_user.username})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        session["user_id"] = user.id
        session["username"] = user.username
        session["is_admin"] = user.is_admin
        return jsonify({"success": True, "message": "تم تسجيل الدخول بنجاح", "username": user.username, "is_admin": user.is_admin})
    else:
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "تم تسجيل الخروج"})

@app.route("/check_auth", methods=["GET"])
def check_auth():
    if "user_id" in session:
        return jsonify({"logged_in": True, "username": session["username"], "is_admin": session.get("is_admin", False)})
    return jsonify({"logged_in": False})

# --------------------------
# 🔹 Admin: Create Admin User
# --------------------------
@app.route("/admin/create_admin", methods=["POST"])
def create_admin():
    """One-time endpoint to promote a user to admin. Protect this with a secret key."""
    data = request.get_json() or {}
    secret = data.get("secret", "")
    username = data.get("username", "").strip()
    admin_secret = os.environ.get("ADMIN_SECRET", "sphinx_admin_2025")

    if secret != admin_secret:
        return jsonify({"error": "Invalid secret"}), 403

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.is_admin = True
    db.session.commit()
    return jsonify({"success": True, "message": f"{username} is now an admin"})

# --------------------------
# 🔹 Admin: Exam CRUD
# --------------------------
@app.route("/admin/exams", methods=["GET"])
@admin_required
def admin_get_exams():
    exams = Exam.query.order_by(Exam.created_at.desc()).all()
    return jsonify({"success": True, "exams": [e.to_dict() for e in exams]})

@app.route("/admin/exams", methods=["POST"])
@admin_required
def admin_add_exam():
    data = request.get_json() or {}
    course_name = data.get("course_name", "").strip()
    exam_date = data.get("exam_date", "").strip()

    if not course_name or not exam_date:
        return jsonify({"error": "اسم المادة والتاريخ مطلوبان"}), 400

    exam = Exam(
        course_name=course_name,
        course_code=data.get("course_code", "").strip() or None,
        exam_date=exam_date,
        exam_time=data.get("exam_time", "").strip() or None,
        exam_location=data.get("exam_location", "").strip() or None,
        notes=data.get("notes", "").strip() or None,
    )
    db.session.add(exam)
    db.session.commit()

    # Invalidate cache so bot picks up new data
    response_cache.clear()

    return jsonify({"success": True, "message": "تم إضافة الامتحان", "exam": exam.to_dict()})

@app.route("/admin/exams/<int:exam_id>", methods=["PUT"])
@admin_required
def admin_update_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    data = request.get_json() or {}

    exam.course_name = data.get("course_name", exam.course_name)
    exam.course_code = data.get("course_code", exam.course_code)
    exam.exam_date = data.get("exam_date", exam.exam_date)
    exam.exam_time = data.get("exam_time", exam.exam_time)
    exam.exam_location = data.get("exam_location", exam.exam_location)
    exam.notes = data.get("notes", exam.notes)
    db.session.commit()

    response_cache.clear()
    return jsonify({"success": True, "message": "تم تحديث الامتحان", "exam": exam.to_dict()})

@app.route("/admin/exams/<int:exam_id>", methods=["DELETE"])
@admin_required
def admin_delete_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    db.session.delete(exam)
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True, "message": "تم حذف الامتحان"})

# --------------------------
# 🔹 Admin: Announcement CRUD
# --------------------------
@app.route("/admin/announcements", methods=["GET"])
@admin_required
def admin_get_announcements():
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return jsonify({"success": True, "announcements": [a.to_dict() for a in announcements]})

@app.route("/admin/announcements", methods=["POST"])
@admin_required
def admin_add_announcement():
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()

    if not title or not content:
        return jsonify({"error": "العنوان والمحتوى مطلوبان"}), 400

    ann = Announcement(
        title=title,
        content=content,
        category=data.get("category", "general"),
        is_active=data.get("is_active", True),
    )
    db.session.add(ann)
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True, "message": "تم إضافة الإعلان", "announcement": ann.to_dict()})

@app.route("/admin/announcements/<int:ann_id>", methods=["PUT"])
@admin_required
def admin_update_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    data = request.get_json() or {}

    ann.title = data.get("title", ann.title)
    ann.content = data.get("content", ann.content)
    ann.category = data.get("category", ann.category)
    ann.is_active = data.get("is_active", ann.is_active)
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True, "message": "تم تحديث الإعلان", "announcement": ann.to_dict()})

@app.route("/admin/announcements/<int:ann_id>", methods=["DELETE"])
@admin_required
def admin_delete_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    db.session.delete(ann)
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True, "message": "تم حذف الإعلان"})

# --------------------------
# 🔹 Admin: Dashboard Stats
# --------------------------
@app.route("/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    total_users = User.query.filter_by(is_admin=False).count()
    total_chats = Chat.query.count()
    total_exams = Exam.query.count()
    total_announcements = Announcement.query.filter_by(is_active=True).count()
    return jsonify({
        "success": True,
        "stats": {
            "total_users": total_users,
            "total_chats": total_chats,
            "total_exams": total_exams,
            "active_announcements": total_announcements,
        }
    })

# --------------------------
# 🔹 Chat Routes
# --------------------------
@app.route("/get_chats", methods=["GET"])
def get_chats():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح لك"}), 401

    user_id = session["user_id"]
    chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.timestamp.asc()).all()

    sessions_dict = {}
    for chat in chats:
        s_id = chat.session_id
        if s_id not in sessions_dict:
            title = chat.user_message[:30] + "..." if len(chat.user_message) > 30 else chat.user_message
            sessions_dict[s_id] = {"session_id": s_id, "title": title, "messages": []}
        sessions_dict[s_id]["messages"].append({"sender": "user", "text": chat.user_message})
        sessions_dict[s_id]["messages"].append({"sender": "bot", "text": chat.bot_reply})

    sessions_list = list(sessions_dict.values())
    sessions_list.reverse()
    return jsonify({"success": True, "sessions": sessions_list, "username": session["username"]})

@app.route("/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
    data = request.get_json() or {}
    return _handle_chat(data)

def _handle_chat(data):
    global model, model_idx
    try:
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        # 1️⃣ Try Local Static Match
        local_reply = find_local_match(user_message)
        if local_reply:
            return jsonify({"reply": local_reply, "session_id": session_id, "source": "local"})

        # 2️⃣ Check Cache
        cache_key = user_message.lower()
        if cache_key in response_cache:
            return jsonify({"reply": response_cache[cache_key], "session_id": session_id, "source": "cache"})

        # 3️⃣ Rebuild model with fresh DB context each time
        fresh_model = genai.GenerativeModel(
            MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)],
            system_instruction=build_system_instruction()
        )

        if session_id not in chat_sessions:
            chat_sessions[session_id] = []

        history = chat_sessions[session_id]
        gemini_history = []
        for turn in history[-5:]:
            gemini_history.append({"role": "user", "parts": [turn["user"]]})
            gemini_history.append({"role": "model", "parts": [turn["bot"]]})

        chat_obj = fresh_model.start_chat(history=gemini_history)
        response = chat_obj.send_message(user_message)
        bot_reply = response.text.strip()

        if not bot_reply.startswith("🤖") and not bot_reply.startswith("📚") and not bot_reply.startswith("📊"):
            bot_reply = "🤖 (AI): " + bot_reply

        # Save to DB
        user_id = session.get("user_id")
        if user_id:
            new_chat = Chat(user_id=user_id, session_id=session_id, user_message=user_message, bot_reply=bot_reply)
            db.session.add(new_chat)
            db.session.commit()

        response_cache[cache_key] = bot_reply
        history.append({"user": user_message, "bot": bot_reply})

        return jsonify({"reply": bot_reply, "session_id": session_id, "source": "ai"})

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg or "404" in error_msg:
            retries = data.get("retries", 0)
            if retries >= len(MODEL_VERSIONS) * max(len(API_KEYS), 1):
                return jsonify({"error": "عذراً، ضغط الأسئلة كبير حالياً. يرجى الانتظار 30 ثانية ⏱️"}), 429
            model_idx += 1
            model = get_next_model()
            data["retries"] = retries + 1
            return _handle_chat(data)
        return jsonify({"error": f"AI Error: {error_msg}"}), 500


# --------------------------
# 🔹 Check Requirements
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

        fresh_model = genai.GenerativeModel(
            MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)],
            system_instruction=build_system_instruction()
        )
        response = fresh_model.generate_content(prompt)
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
            return jsonify({"error": "عذراً، لقد استنفدت الحد المسموح للذكاء الاصطناعي حالياً. يرجى الانتظار دقيقة."}), 429
        return jsonify({"error": f"AI Error: {error_msg}"}), 500


# --------------------------
# 🔹 Static Routes
# --------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/admin", methods=["GET"])
def admin_page():
    return render_template("admin.html")

@app.route("/<path:path>", methods=["GET"])
def serve_static(path):
    return send_from_directory("static", path)

# --------------------------
# 🔹 Init DB & Run
# --------------------------
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
