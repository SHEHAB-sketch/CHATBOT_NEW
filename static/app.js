const API_BASE = "";
let SESSION_ID = "session_" + Date.now();
let isLoginMode = true;

let allSessions = [];

// ================================
// NEW CHAT
// ================================
function newChat() {
    if (!confirm("هل تريد بدء محادثة جديدة؟ سيتم مسح الرسائل الحالية. / Start a new chat?")) return;

    SESSION_ID = "session_" + Date.now();

    const container = document.getElementById("chat-messages");
    container.innerHTML = `
        <div class="msg-row bot-row">
            <div class="avatar bot-avatar">🤖</div>
            <div class="bubble bot-bubble">
              <p>مرحباً! أنا مستشارك الأكاديمي الذكي 👋</p>
              <p>يمكنك سؤالي عن أي موضوع أكاديمي.</p>
              <p class="msg-time">Now</p>
            </div>
        </div>
    `;

    loadChats(true);
    document.getElementById("chat-input").focus();
}

// ================================
// AUTH
// ================================
async function checkAuth() {
    try {
        const res = await fetch(API_BASE + "/check_auth");
        const data = await res.json();

        if (data.logged_in) {
            document.getElementById("auth-modal").classList.remove("active");
            document.getElementById("user-info-display").textContent =
                "مرحباً، " + data.username;

            loadChats();
        } else {
            document.getElementById("auth-modal").classList.add("active");
        }
    } catch (err) {
        console.error(err);
    }
}

async function submitAuth() {
    const username = document.getElementById("auth-username").value.trim();
    const password = document.getElementById("auth-password").value.trim();
    const errorEl = document.getElementById("auth-error");

    if (!username || !password) {
        errorEl.textContent = "ادخل البيانات";
        return;
    }

    const endpoint = isLoginMode ? "/login" : "/register";

    const res = await fetch(API_BASE + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
    });

    const data = await res.json();

    if (data.error) {
        errorEl.textContent = data.error;
    } else {
        document.getElementById("auth-modal").classList.remove("active");
        document.getElementById("user-info-display").textContent =
            "مرحباً، " + data.username;

        loadChats();
    }
}

// ================================
// LOAD CHATS (SIDEBAR FIXED)
// ================================
async function loadChats(skipAutoLoad = false) {
    try {
        const res = await fetch(API_BASE + "/get_chats");
        const data = await res.json();

        if (!data.success || !data.sessions) return;

        allSessions = data.sessions;

        const list = document.getElementById("history-list");
        const section = document.getElementById("history-section");

        list.innerHTML = "";

        if (data.sessions.length > 0) {
            section.style.display = "block";
        }

        data.sessions.forEach(session => {
            const btn = document.createElement("button");
            btn.className = "sidebar-item history-item";
            btn.textContent = "💬 " + session.title;

            btn.onclick = () => loadSession(session.session_id);

            list.appendChild(btn);
        });

        // auto load latest chat
        if (!skipAutoLoad && data.sessions.length > 0) {
            loadSession(data.sessions[0].session_id);
        }

    } catch (err) {
        console.error("loadChats error", err);
    }
}

// ================================
// LOAD SESSION
// ================================
function loadSession(sessionId) {
    const session = allSessions.find(s => s.session_id === sessionId);
    if (!session) return;

    SESSION_ID = sessionId;

    const container = document.getElementById("chat-messages");

    container.innerHTML = `
        <div class="msg-row bot-row">
            <div class="avatar bot-avatar">🤖</div>
            <div class="bubble bot-bubble">
              <p>مرحباً بعودتك 👋</p>
              <p class="msg-time">Now</p>
            </div>
        </div>
    `;

    session.messages.forEach(msg => {
        appendMessage(msg.text, msg.sender);
    });

    switchTab('chat');
}

// ================================
// CHAT SEND (🔥 FIX IMPORTANT)
// ================================
async function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, "user");
    input.value = "";

    showTyping();

    try {
        const res = await fetch(API_BASE + "/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: text,
                session_id: SESSION_ID
            })
        });

        const data = await res.json();
        removeTyping();

        if (data.error) {
            appendMessage("⚠️ " + data.error, "bot");
        } else {
            appendMessage(data.reply, "bot");

            // 🔥 IMPORTANT FIX: refresh sidebar instantly
            await loadChats();
        }

    } catch (err) {
        removeTyping();
        appendMessage("⚠️ Server error", "bot");
    }
}

// ================================
// UI HELPERS
// ================================
function appendMessage(text, sender) {
    const container = document.getElementById("chat-messages");

    const row = document.createElement("div");
    row.className = "msg-row " + (sender === "user" ? "user-row" : "bot-row");

    row.innerHTML = `
        <div class="avatar">${sender === "user" ? "🧑" : "🤖"}</div>
        <div class="bubble">
            ${text}
        </div>
    `;

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function showTyping() {
    const container = document.getElementById("chat-messages");

    const div = document.createElement("div");
    div.id = "typing";
    div.className = "msg-row bot-row";
    div.innerHTML = `<div class="avatar">🤖</div><div class="bubble">typing...</div>`;

    container.appendChild(div);
}

function removeTyping() {
    const el = document.getElementById("typing");
    if (el) el.remove();
}

// ================================
// NAV
// ================================
function switchTab(tab) {
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    document.getElementById("tab-" + tab).classList.add("active");
}

// ================================
// INIT
// ================================
document.addEventListener("DOMContentLoaded", () => {
    checkAuth();
});
