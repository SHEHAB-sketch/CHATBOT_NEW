from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import google.generativeai as genai
import os
import json

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# --------------------------
# 🔹 Gemini Setup (Environment Variables)
# --------------------------
# Get API keys from environment variable (comma-separated) or use defaults
ENV_KEYS = os.environ.get("GEMINI_API_KEYS", "").split(",")
API_KEYS = [k.strip() for k in ENV_KEYS if k.strip()]

# بنبدل بين الموديلات دي عشان كل واحد ليه ليميت لوحده!
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
# 🔹 Load Knowledge Base (Dynamic RAG-style)
# --------------------------
# بنجمع ملفات الداتا الأساسية بس عشان الـ AI يتعلم منها
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
# 🔹 Gemini Setup (Rotating Models & Cache)
# --------------------------
model_idx = 0

def get_next_model():
    global model_idx
    k_idx = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)
    m_idx = model_idx % len(MODEL_VERSIONS)
    
    genai.configure(api_key=API_KEYS[k_idx])
    model_name = MODEL_VERSIONS[m_idx]
    
    print(f"Rotation matching: Key[{k_idx}] | Model: {model_name}")
    # هنا بنبعت الداتا كلها مرة واحدة في الـ system_instruction
    return genai.GenerativeModel(model_name, system_instruction=SYSTEM_INSTRUCTION)

model = get_next_model()
response_cache = {}

# Logic handled via SYSTEM_INSTRUCTION above

# --------------------------
# 🔹 Chat History (per session - in-memory)
# --------------------------
chat_sessions = {}

import difflib

# --------------------------
# 🔹 Similarity Search (Local Data First)
# --------------------------
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

        # 1️⃣ FIRST: Try Local Data Match
        local_reply = find_local_match(user_message)
        if local_reply:
            return jsonify({"reply": local_reply, "session_id": session_id, "source": "local"})

        # 2️⃣ SECOND: Check Global Cache
        cache_key = user_message.lower()
        if cache_key in response_cache:
            return jsonify({"reply": response_cache[cache_key], "session_id": session_id, "source": "cache"})

        # 3️⃣ THIRD: Resort to AI
        if session_id not in chat_sessions:
            chat_sessions[session_id] = []
        
        history = chat_sessions[session_id]
        # تحويل الهيستوري لشكل يفهمه Gemini
        gemini_history = []
        for turn in history[-5:]: # آخر 5 رسايل بس عشان السرعة
            gemini_history.append({"role": "user", "parts": [turn["user"]]})
            gemini_history.append({"role": "model", "parts": [turn["bot"]]})

        # بنفتح شات سيشن بالهيستوري القديم
        chat = model.start_chat(history=gemini_history)
        
        # بنبعت الرسالة الجديدة
        # ملاحظة: الداتا كلها موجودة في الـ system_instruction اللي اتعرفت وقت إنشاء الـ model
        response = chat.send_message(user_message)
        bot_reply = response.text.strip()
        
        if not bot_reply.startswith("🤖") and not bot_reply.startswith("📚") and not bot_reply.startswith("📊"):
             bot_reply = "🤖 (AI): " + bot_reply

        # Save to cache and history
        response_cache[cache_key] = bot_reply
        history.append({"user": user_message, "bot": bot_reply})
        
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

        # Simple pass/fail logic for frontend badge
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
            friendly_err = "عذراً، لقد استنفدت الحد المسموح للذكاء الاصطناعي حالياً. يرجى الانتظار دقيقة والمحاولة."
            return jsonify({"error": friendly_err}), 429
        return jsonify({"error": f"AI Error: {error_msg}"}), 500


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/<path:path>", methods=["GET"])
def serve_static(path):
    return send_from_directory("static", path)


# --------------------------
# 🔹 /health Endpoint
# --------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": "gemini-2.0-flash"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Smart Academic Advisor API running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
