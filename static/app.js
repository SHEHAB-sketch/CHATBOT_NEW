// ================================
// CONFIG
// ================================
const API_BASE = "";
let SESSION_ID = "session_" + Date.now();
let isLoginMode = true;

// ================================
// TOKEN MANAGEMENT (JWT في localStorage)
// ================================
function saveToken(token) {
    localStorage.setItem("auth_token", token);
}

function getToken() {
    return localStorage.getItem("auth_token");
}

function clearToken() {
    localStorage.removeItem("auth_token");
}

// ================================
// HELPER: fetch مع JWT token دايماً
// ================================
async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };
    if (token) {
        headers["Authorization"] = "Bearer " + token;
    }
    return fetch(API_BASE + url, {
        ...options,
        headers
    });
}

// ================================
// NEW CHAT
// ================================
function newChat() {
    if (!confirm("هل تريد بدء محادثة جديدة؟ / Start a new chat?")) return;
    SESSION_ID = "session_" + Date.now();
    const container = document.getElementById("chat-messages");
    container.innerHTML = `
        <div class="msg-row bot-row">
            <div class="avatar bot-avatar">🤖</div>
            <div class="bubble bot-bubble">
              <p>مرحباً! أنا مستشارك الأكاديمي الذكي في جامعة سفنكس 👋</p>
              <p>يمكنك سؤالي عن أي موضوع أكاديمي، أو أخبرني ببياناتك (ساعات، GPA، حضور) وهحللها فوراً!</p>
              <p class="msg-time">Now</p>
            </div>
        </div>
    `;
    document.getElementById("chat-input").focus();
}

// ================================
// AUTHENTICATION LOGIC
// ================================
async function checkAuth() {
    const token = getToken();
    if (!token) {
        document.getElementById("auth-modal").classList.add("active");
        return;
    }
    try {
        const res = await apiFetch("/check_auth");
        const data = await res.json();
        if (data.logged_in) {
            document.getElementById("auth-modal").classList.remove("active");
            document.getElementById("user-info-display").textContent = "مرحباً، " + data.username;
            loadChats();
        } else {
            clearToken();
            document.getElementById("auth-modal").classList.add("active");
        }
    } catch (err) {
        console.error("Auth check failed", err);
        document.getElementById("auth-modal").classList.add("active");
    }
}

function toggleAuthMode() {
    isLoginMode = !isLoginMode;
    document.getElementById("auth-error").textContent = "";
    document.getElementById("auth-username").value = "";
    document.getElementById("auth-password").value = "";

    if (isLoginMode) {
        document.getElementById("auth-title").textContent = "تسجيل الدخول";
        document.getElementById("auth-btn-text").textContent = "دخول";
        document.getElementById("auth-switch-text").textContent = "ليس لديك حساب؟";
        document.getElementById("auth-switch-link").textContent = "سجل الآن";
    } else {
        document.getElementById("auth-title").textContent = "إنشاء حساب";
        document.getElementById("auth-btn-text").textContent = "تسجيل";
        document.getElementById("auth-switch-text").textContent = "لديك حساب بالفعل؟";
        document.getElementById("auth-switch-link").textContent = "سجل الدخول";
    }
}

async function submitAuth() {
    const username = document.getElementById("auth-username").value.trim();
    const password = document.getElementById("auth-password").value.trim();
    const errorEl = document.getElementById("auth-error");
    const btnText = document.getElementById("auth-btn-text");

    if (!username || !password) {
        errorEl.textContent = "الرجاء إدخال اسم المستخدم وكلمة المرور";
        return;
    }

    errorEl.textContent = "";
    btnText.textContent = "جاري التحميل...";

    const endpoint = isLoginMode ? "/login" : "/register";

    try {
        const res = await fetch(API_BASE + endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });

        const data = await res.json();

        if (data.error) {
            errorEl.textContent = data.error;
        } else if (data.token) {
            saveToken(data.token);
            errorEl.textContent = "";
            document.getElementById("auth-modal").classList.remove("active");
            document.getElementById("user-info-display").textContent = "مرحباً، " + data.username;
            loadChats();
        } else {
            errorEl.textContent = "حدث خطأ غير متوقع، حاول تاني";
        }
    } catch (err) {
        console.error("Auth error:", err);
        errorEl.textContent = "⚠️ تأكد من اتصالك بالإنترنت وحاول تاني";
    }

    btnText.textContent = isLoginMode ? "دخول" : "تسجيل";
}

async function logout() {
    clearToken();
    document.getElementById("chat-messages").innerHTML = "";
    document.getElementById("user-info-display").textContent = "";
    document.getElementById("auth-modal").classList.add("active");
}

async function loadChats() {
    try {
        const res = await apiFetch("/get_chats");
        const data = await res.json();
        if (data.success && data.chats.length > 0) {
            const container = document.getElementById("chat-messages");
            container.innerHTML = `
                <div class="msg-row bot-row">
                    <div class="avatar bot-avatar">🤖</div>
                    <div class="bubble bot-bubble">
                      <p>مرحباً بعودتك! أنا مستشارك الأكاديمي الذكي 👋</p>
                      <p class="msg-time">Now</p>
                    </div>
                </div>
            `;
            data.chats.forEach(chat => appendMessage(chat.text, chat.sender));
        }
    } catch (err) {
        console.error("Failed to load chats", err);
    }
}

// ================================
// NAVIGATION & SIDEBAR
// ================================
function switchTab(tab) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".sidebar-item").forEach(el => el.classList.remove("active"));
    const targetContent = document.getElementById("tab-" + tab);
    if (targetContent) targetContent.classList.add("active");
    const targetBtn = document.getElementById("tab-" + tab + "-btn");
    if (targetBtn) targetBtn.classList.add("active");
    if (window.innerWidth <= 768) {
        document.getElementById("sidebar").classList.remove("open");
        const overlay = document.getElementById("sidebar-overlay");
        if (overlay) overlay.classList.remove("active");
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    sidebar.classList.toggle("open");
    const overlay = document.getElementById("sidebar-overlay");
    if (overlay) overlay.classList.toggle("active");
}

// ================================
// HEALTH CHECK
// ================================
async function checkHealth() {
    try {
        const res = await fetch(API_BASE + "/health");
        if (res.ok) {
            document.querySelector(".status-dot").classList.add("online");
            document.getElementById("status-text").textContent = "AI Online";
        }
    } catch {
        document.getElementById("status-text").textContent = "Offline";
    }
}

// ================================
// CHAT LOGIC
// ================================
function getTime() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendMessage(text, sender) {
    const container = document.getElementById("chat-messages");
    const row = document.createElement("div");
    row.className = "msg-row " + (sender === "user" ? "user-row" : "bot-row");
    const avatar = document.createElement("div");
    avatar.className = "avatar " + (sender === "user" ? "user-avatar" : "bot-avatar");
    avatar.textContent = sender === "user" ? "🧑" : "🤖";
    const bubble = document.createElement("div");
    bubble.className = "bubble " + (sender === "user" ? "user-bubble" : "bot-bubble");
    bubble.innerHTML = formatText(text) + `<p class="msg-time">${getTime()}</p>`;
    row.appendChild(avatar);
    row.appendChild(bubble);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function formatText(text) {
    return text
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/```[\s\S]*?```/g, "")
        .replace(/#{1,3}\s(.+)/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>")
        .replace(/^- (.+)/gm, "• $1");
}

function showTyping() {
    const container = document.getElementById("chat-messages");
    const row = document.createElement("div");
    row.className = "msg-row bot-row";
    row.id = "typing-row";
    const avatar = document.createElement("div");
    avatar.className = "avatar bot-avatar";
    avatar.textContent = "🤖";
    const indicator = document.createElement("div");
    indicator.className = "typing-indicator";
    indicator.innerHTML = "<span></span><span></span><span></span>";
    row.appendChild(avatar);
    row.appendChild(indicator);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function removeTyping() {
    const el = document.getElementById("typing-row");
    if (el) el.remove();
}

async function sendMessage() {
    const input = document.getElementById("chat-input");
    const btn = document.getElementById("send-btn");
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    input.value = "";
    input.style.height = "auto";
    btn.disabled = true;
    showTyping();

    try {
        const res = await apiFetch("/chat", {
            method: "POST",
            body: JSON.stringify({ message: text, session_id: SESSION_ID })
        });

        if (res.status === 401) {
            removeTyping();
            clearToken();
            document.getElementById("auth-modal").classList.add("active");
            return;
        }

        const data = await res.json();
        removeTyping();
        if (data.error) {
            appendMessage("⚠️ " + data.error, "bot");
        } else {
            appendMessage(data.reply, "bot");
        }
    } catch (err) {
        removeTyping();
        appendMessage("⚠️ حدث خطأ في الاتصال، حاول تاني.", "bot");
    }

    btn.disabled = false;
    input.focus();
}

function sendQuick(text) {
    document.getElementById("chat-input").value = text;
    sendMessage();
}

function handleKey(e) {
    const ta = document.getElementById("chat-input");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// ================================
// REQUIREMENTS CHECKER
// ================================
function updateProgress(type, value, max) {
    const pct = Math.min((parseFloat(value) / max) * 100, 100);
    const bar = document.getElementById("prog-" + type);
    if (bar) {
        bar.style.width = pct + "%";
        let threshold = { hours: (138/138), gpa: (2.0/4.0), attendance: (75/100), years: 1.0 }[type];
        const ratio = parseFloat(value) / max;
        if (type === "years") {
            bar.style.background = ratio <= 1 ? "linear-gradient(90deg,#22c55e,#16a34a)" : "linear-gradient(90deg,#ef4444,#dc2626)";
        } else {
            bar.style.background = ratio >= threshold
                ? "linear-gradient(90deg,#22c55e,#16a34a)"
                : "linear-gradient(90deg,#ef4444,#dc2626)";
        }
    }
    updateQuickStatus();
}

function updateQuickStatus() {
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa   = parseFloat(document.getElementById("req-gpa").value)   || 0;
    const att   = parseFloat(document.getElementById("req-attendance").value) || 0;
    const years = parseFloat(document.getElementById("req-years").value) || 0;
    const set = (id, label, pass) => {
        const el = document.getElementById(id);
        el.textContent = label;
        el.className = "stat-item " + (pass ? "pass" : "fail");
    };
    if (hours > 0) set("stat-hours", `${hours>=138?"✅":"❌"} Credit Hours: ${hours}/138`, hours>=138);
    if (gpa   > 0) set("stat-gpa",   `${gpa>=2.0?"✅":"❌"} GPA: ${gpa}/4.0`, gpa>=2.0);
    if (att   > 0) set("stat-att",   `${att>=75?"✅":"❌"} Attendance: ${att}%`, att>=75);
    if (years > 0) set("stat-years", `${years<=8?"✅":"❌"} Years: ${years}/8`, years<=8);
}

async function checkRequirements() {
    const name  = document.getElementById("req-name").value || "Student";
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa   = parseFloat(document.getElementById("req-gpa").value)   || 0;
    const att   = parseFloat(document.getElementById("req-attendance").value) || 0;
    const years = parseFloat(document.getElementById("req-years").value) || 0;

    if (!hours && !gpa && !att && !years) {
        alert("من فضلك أدخل بياناتك الأكاديمية أولاً");
        return;
    }

    const btn = document.getElementById("check-btn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> جاري التحليل بالـ AI...`;
    document.getElementById("result-placeholder").style.display = "none";
    document.getElementById("result-content").style.display = "none";

    try {
        const res = await apiFetch("/check-requirements", {
            method: "POST",
            body: JSON.stringify({ name, credit_hours: hours, gpa, attendance: att, years })
        });
        const data = await res.json();
        if (data.error) {
            document.getElementById("result-placeholder").style.display = "flex";
            document.getElementById("result-placeholder").querySelector("p").textContent = "⚠️ " + data.error;
        } else {
            const verdict = document.getElementById("verdict-badge");
            verdict.textContent = data.can_graduate
                ? "🎓 مؤهل للتخرج — Eligible to Graduate"
                : "📚 غير مؤهل بعد — Not Eligible Yet";
            verdict.className = "verdict-badge " + (data.can_graduate ? "can-graduate" : "cannot-graduate");
            document.getElementById("result-text").textContent = data.analysis;
            document.getElementById("result-content").style.display = "flex";
        }
    } catch (err) {
        document.getElementById("result-placeholder").style.display = "flex";
        document.getElementById("result-placeholder").querySelector("p").textContent = "⚠️ حدث خطأ في الاتصال، حاول تاني.";
    }

    btn.disabled = false;
    btn.innerHTML = "<span>🔍 تحليل بـ AI</span>";
}

// ================================
// INIT
// ================================
document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    checkAuth();
    setInterval(checkHealth, 10000);
});

// Enter في modal تسجيل الدخول
document.addEventListener("keydown", (e) => {
    const modal = document.getElementById("auth-modal");
    if (modal && modal.classList.contains("active") && e.key === "Enter") {
        submitAuth();
    }
});
