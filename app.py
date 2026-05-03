from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
import os
import jwt
import datetime
import difflib
from datetime import timedelta
from functools import wraps

# --------------------------
# 🔹 App Setup
# --------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'sphinx_university_super_secret_key_2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True, origins="*")

db = SQLAlchemy(app)

# --------------------------
# 🔹 Database Models
# --------------------------
class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    chats         = db.relationship('Chat', backref='user', lazy=True)

class Chat(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_reply    = db.Column(db.Text, nullable=False)
    timestamp    = db.Column(db.DateTime, default=db.func.current_timestamp())

# --------------------------
# 🔹 JWT Helpers
# --------------------------
def generate_token(user_id, username):
    payload = {
        'user_id':  user_id,
        'username': username,
        'exp':      datetime.datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, app.secret_key, algorithm='HS256')

def get_current_user():
    token = None
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
    if not token:
        data  = request.get_json(silent=True) or {}
        token = data.get('token', '')
    if not token:
        return None
    try:
        return jwt.decode(token, app.secret_key, algorithms=['HS256'])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
        return f(user, *args, **kwargs)
    return decorated

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
]

model_idx = 0

# --------------------------
# 🔹 Knowledge Base
# --------------------------
CHATBOT_CONTEXT = ""
base_dir    = os.path.dirname(os.path.abspath(__file__))
target_files = ["chatbot (3).txt", "chatbot.txt", "chatbot (1).txt"]

for filename in target_files:
    file_path = os.path.join(base_dir, filename)
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                CHATBOT_CONTEXT += f"\n--- SOURCE: {filename} ---\n{f.read()}\n"
        except Exception as e:
            print(f"Warning: Could not read {filename}: {e}")

if not CHATBOT_CONTEXT.strip():
    CHATBOT_CONTEXT = "University Information: Sphinx University uses a credit hour system."

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

SYSTEM_INSTRUCTION = f"""You are a friendly human academic advisor for Sphinx University.

=== UNIVERSITY KNOWLEDGE BASE ===
{CHATBOT_CONTEXT}

=== GRADUATION RULES ===
{UNIVERSITY_RULES}

=== YOUR BEHAVIOR ===
1. Always check the KNOWLEDGE BASE and RULES first.
2. If answer is in the rules/context: start reply with "📚 (من اللائحة): "
3. If NOT in rules/context: start reply with "🤖 (AI): "
4. No markdown, no asterisks, no bullet points. Talk like WhatsApp.
5. If student shares academic data (hours/GPA/attendance): analyze and prefix with "📊 (تحليل البيانات): "
6. Reply in the same language the student uses (Arabic or English). Be warm and empathetic.
"""

# --------------------------
# 🔹 Gemini Model Init
# --------------------------
def get_next_model():
    global model_idx
    if not API_KEYS:
        raise ValueError("No API keys configured. Set GEMINI_API_KEYS environment variable.")
    k_idx      = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)
    m_idx      = model_idx % len(MODEL_VERSIONS)
    model_name = MODEL_VERSIONS[m_idx]
    genai.configure(api_key=API_KEYS[k_idx])
    print(f"Using Key[{k_idx}] | Model: {model_name}")
    return genai.GenerativeModel(model_name, system_instruction=SYSTEM_INSTRUCTION)

class MockModel:
    """يُستخدم لما مفيش API keys"""
    def generate_content(self, *args, **kwargs):
        return type('R', (), {'text': '⚠️ لم يتم تكوين مفاتيح Gemini API. يرجى إضافة GEMINI_API_KEYS.'})()
    def start_chat(self, **kwargs):
        return type('C', (), {'send_message': lambda self, msg: type('R', (), {'text': '⚠️ لم يتم تكوين مفاتيح Gemini API.'})()})()

try:
    model = get_next_model() if API_KEYS else MockModel()
except Exception as e:
    print(f"Warning: Could not initialize Gemini: {e}")
    model = MockModel()

response_cache = {}
chat_sessions  = {}

def find_local_match(user_query):
    if not CHATBOT_CONTEXT:
        return None
    lines   = [l.strip() for l in CHATBOT_CONTEXT.split("\n") if l.strip()]
    matches = difflib.get_close_matches(user_query, lines, n=1, cutoff=0.3)
    return ("📚 (من اللائحة): " + matches[0]) if matches else None

# --------------------------
# 🔹 Auth Routes
# --------------------------
@app.route("/register", methods=["POST"])
def register():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400
    if len(username) < 3:
        return jsonify({"error": "اسم المستخدم يجب أن يكون 3 أحرف على الأقل"}), 400
    if len(password) < 4:
        return jsonify({"error": "كلمة المرور يجب أن تكون 4 أحرف على الأقل"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "اسم المستخدم موجود مسبقاً"}), 400

    new_user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(new_user)
    db.session.commit()

    token = generate_token(new_user.id, new_user.username)
    return jsonify({"success": True, "username": new_user.username, "token": token})

@app.route("/login", methods=["POST"])
def login():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        token = generate_token(user.id, user.username)
        return jsonify({"success": True, "username": user.username, "token": token})

    return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    return jsonify({"success": True})

@app.route("/check_auth", methods=["GET", "POST"])
def check_auth():
    user = get_current_user()
    if user:
        return jsonify({"logged_in": True, "username": user["username"]})
    return jsonify({"logged_in": False})

@app.route("/get_chats", methods=["GET", "POST"])
@require_auth
def get_chats(current_user):
    chats = Chat.query.filter_by(user_id=current_user["user_id"]).order_by(Chat.timestamp.asc()).all()
    history = []
    for c in chats:
        history.append({"sender": "user", "text": c.user_message})
        history.append({"sender": "bot",  "text": c.bot_reply})
    return jsonify({"success": True, "chats": history, "username": current_user["username"]})

# --------------------------
# 🔹 Chat Route
# --------------------------
@app.route("/chat", methods=["POST"])
@require_auth
def chat(current_user):
    data = request.get_json() or {}
    return _handle_chat(data, current_user)

def _handle_chat(data, current_user, retries=0):
    global model, model_idx
    max_retries = len(MODEL_VERSIONS) * max(len(API_KEYS), 1)

    try:
        user_message = data.get("message", "").strip()
        session_id   = data.get("session_id", "default")

        if not user_message:
            return jsonify({"error": "الرسالة فاضية"}), 400

        # 1️⃣ Local match first
        local_reply = find_local_match(user_message)
        if local_reply:
            return jsonify({"reply": local_reply, "source": "local"})

        # 2️⃣ Cache
        cache_key = user_message.lower().strip()
        if cache_key in response_cache:
            return jsonify({"reply": response_cache[cache_key], "source": "cache"})

        # 3️⃣ AI
        if not API_KEYS:
            return jsonify({"error": "لم يتم تكوين مفاتيح Gemini API في السيرفر"}), 500

        if session_id not in chat_sessions:
            chat_sessions[session_id] = []

        history        = chat_sessions[session_id]
        gemini_history = []
        for turn in history[-5:]:
            gemini_history.append({"role": "user",  "parts": [turn["user"]]})
            gemini_history.append({"role": "model", "parts": [turn["bot"]]})

        chat_obj = model.start_chat(history=gemini_history)
        response = chat_obj.send_message(user_message)
        bot_reply = response.text.strip()

        if not any(bot_reply.startswith(p) for p in ["🤖", "📚", "📊"]):
            bot_reply = "🤖 (AI): " + bot_reply

        # Save to DB
        db.session.add(Chat(
            user_id      = current_user["user_id"],
            user_message = user_message,
            bot_reply    = bot_reply
        ))
        db.session.commit()

        response_cache[cache_key] = bot_reply
        history.append({"user": user_message, "bot": bot_reply})

        return jsonify({"reply": bot_reply, "source": "ai"})

    except Exception as e:
        err = str(e)
        if any(code in err for code in ["429", "Quota", "404", "503"]):
            if retries < max_retries:
                model_idx += 1
                try:
                    model = get_next_model()
                except:
                    pass
                return _handle_chat(data, current_user, retries + 1)
            return jsonify({"error": "ضغط كبير على الـ AI حالياً، انتظر 30 ثانية وحاول تاني ⏱️"}), 429
        return jsonify({"error": f"خطأ في الـ AI: {err}"}), 500

# --------------------------
# 🔹 Graduation Checker
# --------------------------
@app.route("/check-requirements", methods=["POST"])
def check_requirements():
    try:
        data         = request.get_json() or {}
        credit_hours = int(data.get("credit_hours", 0))
        gpa          = float(data.get("gpa", 0.0))
        attendance   = int(data.get("attendance", 0))
        years        = int(data.get("years", 0))
        student_name = data.get("name", "Student")

        prompt = f"""You are a strict academic advisor at Sphinx University.

{UNIVERSITY_RULES}

Student: {student_name}
- Credit Hours: {credit_hours} / 138
- GPA: {gpa} / 4.0
- Attendance: {attendance}%
- Years of Study: {years} / 8

Give: ✅/❌ for each, overall verdict, advice if not eligible, congrats if eligible. Use emojis. Reply in Arabic and English."""

        response  = model.generate_content(prompt)
        can_grad  = (credit_hours >= 138 and gpa >= 2.0 and attendance >= 75 and years <= 8)

        return jsonify({
            "analysis":    response.text.strip(),
            "can_graduate": can_grad,
            "details": {
                "credit_hours": {"value": credit_hours, "required": 138, "pass": credit_hours >= 138},
                "gpa":          {"value": gpa,          "required": 2.0,  "pass": gpa >= 2.0},
                "attendance":   {"value": attendance,   "required": 75,   "pass": attendance >= 75},
                "years":        {"value": years,         "required": 8,    "pass": years <= 8},
            }
        })

    except Exception as e:
        err = str(e)
        if "429" in err or "Quota" in err:
            return jsonify({"error": "استنفدت الحد المسموح، انتظر دقيقة وحاول تاني."}), 429
        return jsonify({"error": f"خطأ: {err}"}), 500

# --------------------------
# 🔹 Static & Health
# --------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "api_keys": len(API_KEYS), "model": MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)]})

# --------------------------
# 🔹 Start
# --------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
