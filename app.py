from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import timedelta
import uuid

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'sphinx_university_super_secret_key')

# --------------------------
# DB CONFIG
# --------------------------
db_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

CORS(app, supports_credentials=True)

db = SQLAlchemy(app)

# --------------------------
# MODELS
# --------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_id = db.Column(db.String(120), nullable=False)

    user_message = db.Column(db.Text, nullable=False)
    bot_reply = db.Column(db.Text, nullable=False)

    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

# --------------------------
# REGISTER
# --------------------------
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Missing data"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "User already exists"}), 400

    user = User(
        username=username,
        password_hash=generate_password_hash(password)
    )

    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    session["username"] = user.username

    return jsonify({"success": True, "username": username})

# --------------------------
# LOGIN
# --------------------------
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    user = User.query.filter_by(username=data.get("username")).first()

    if user and check_password_hash(user.password_hash, data.get("password")):
        session["user_id"] = user.id
        session["username"] = user.username
        return jsonify({"success": True, "username": user.username})

    return jsonify({"error": "Invalid credentials"}), 401

# --------------------------
# CHAT (FIXED)
# --------------------------
@app.route("/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json() or {}
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"error": "Empty message"}), 400

    # 🔥 FIX: proper session handling
    session_id = data.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())

    # fake AI response (replace Gemini here if needed)
    bot_reply = "🤖 AI: " + message[::-1]

    chat = Chat(
        user_id=session["user_id"],
        session_id=session_id,
        user_message=message,
        bot_reply=bot_reply
    )

    db.session.add(chat)
    db.session.commit()

    return jsonify({
        "reply": bot_reply,
        "session_id": session_id
    })

# --------------------------
# GET CHATS (FIXED SIDEBAR)
# --------------------------
@app.route("/get_chats", methods=["GET"])
def get_chats():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    chats = Chat.query.filter_by(user_id=session["user_id"])\
        .order_by(Chat.timestamp.desc())\
        .all()

    sessions = {}

    for c in chats:
        if c.session_id not in sessions:
            sessions[c.session_id] = {
                "session_id": c.session_id,
                "title": c.user_message[:30],
                "last_time": c.timestamp,
                "messages": []
            }

        sessions[c.session_id]["messages"].append({
            "sender": "user",
            "text": c.user_message
        })

        sessions[c.session_id]["messages"].append({
            "sender": "bot",
            "text": c.bot_reply
        })

    sessions_list = sorted(
        sessions.values(),
        key=lambda x: x["last_time"],
        reverse=True
    )

    return jsonify({
        "success": True,
        "sessions": sessions_list,
        "username": session.get("username")
    })

# --------------------------
# AUTH CHECK
# --------------------------
@app.route("/check_auth")
def check_auth():
    return jsonify({
        "logged_in": "user_id" in session,
        "username": session.get("username")
    })

# --------------------------
# LOGOUT
# --------------------------
@app.route("/logout")
def logout():
    session.clear()
    return jsonify({"success": True})

# --------------------------
# HOME
# --------------------------
@app.route("/")
def home():
    return render_template("index.html")

# --------------------------
# INIT DB
# --------------------------
with app.app_context():
    db.create_all()

# --------------------------
# RUN
# --------------------------
if __name__ == "__main__":
    app.run(debug=True)
