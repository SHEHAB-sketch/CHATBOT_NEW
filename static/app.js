// ================================
// CONFIG
// ================================
const API_BASE = "";
let SESSION_ID = "session_" + Date.now();
let isLoadingSession = false;

// ================================
// NEW CHAT — saves current session, starts fresh
// ================================
function newChat() {
    // Just generate a new session ID — current session is already saved in DB
    SESSION_ID = "session_" + Date.now();

    // Clear UI
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

    // Mark no history item as active
    document.querySelectorAll(".history-item").forEach(el => el.classList.remove("active"));

    // Refresh sidebar history list
    loadSidebarHistory();

    document.getElementById("chat-input").focus();
}

// ================================
// LOAD A PAST SESSION INTO CHAT VIEW
// ================================
async function loadSession(sessionId) {
    try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
        const data = await res.json();
        if (data.error) return;

        SESSION_ID = sessionId;
        isLoadingSession = true;

        const container = document.getElementById("chat-messages");
        container.innerHTML = "";

        for (const msg of data.messages) {
            appendMessage(msg.content, msg.role === "user" ? "user" : "bot", msg.timestamp);
        }

        // Mark active in sidebar
        document.querySelectorAll(".history-item").forEach(el => {
            el.classList.toggle("active", el.dataset.id === sessionId);
        });

        // Switch to chat tab
        switchTab("chat");
        isLoadingSession = false;
        container.scrollTop = container.scrollHeight;
    } catch (err) {
        console.error("Failed to load session:", err);
    }
}

// ================================
// SIDEBAR HISTORY
// ================================
async function loadSidebarHistory() {
    try {
        const res = await fetch(`${API_BASE}/sessions`);
        const sessions = await res.json();

        const list = document.getElementById("sidebar-history-list");
        list.innerHTML = "";

        if (!sessions.length) {
            list.innerHTML = `<p class="no-history-msg">No saved chats yet</p>`;
            return;
        }

        sessions.forEach(s => {
            const btn = document.createElement("button");
            btn.className = "sidebar-item history-item" + (s.id === SESSION_ID ? " active" : "");
            btn.dataset.id = s.id;
            const date = new Date(s.updated_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
            btn.innerHTML = `
                <span class="history-icon">💬</span>
                <span class="history-info">
                    <span class="history-title">${escapeHtml(s.title)}</span>
                    <span class="history-meta">${date} · ${s.message_count} msgs</span>
                </span>
            `;
            btn.onclick = () => loadSession(s.id);
            list.appendChild(btn);
        });
    } catch (err) {
        console.error("Failed to load sidebar history:", err);
    }
}

// ================================
// HISTORY TAB — Full list with search & delete
// ================================
async function loadHistoryTab(searchQuery = "") {
    const list = document.getElementById("history-tab-list");
    list.innerHTML = `<div class="history-loading">⏳ Loading...</div>`;

    try {
        let url = searchQuery
            ? `${API_BASE}/sessions/search?q=${encodeURIComponent(searchQuery)}`
            : `${API_BASE}/sessions`;

        const res = await fetch(url);
        const sessions = await res.json();

        list.innerHTML = "";

        if (!sessions.length) {
            list.innerHTML = `<div class="history-empty">
                <div class="placeholder-icon">🗂️</div>
                <p>${searchQuery ? "No results found for: " + escapeHtml(searchQuery) : "No chat history yet. Start a conversation!"}</p>
            </div>`;
            return;
        }

        sessions.forEach(s => {
            const date = new Date(s.updated_at).toLocaleString("en-GB", {
                day: "2-digit", month: "short", year: "numeric",
                hour: "2-digit", minute: "2-digit"
            });
            const card = document.createElement("div");
            card.className = "history-card";
            card.innerHTML = `
                <div class="history-card-info" onclick="loadSession('${s.id}')">
                    <div class="history-card-title">💬 ${escapeHtml(s.title)}</div>
                    <div class="history-card-meta">
                        <span>🕐 ${date}</span>
                        <span>📨 ${s.message_count} messages</span>
                    </div>
                </div>
                <button class="delete-btn" onclick="deleteSession('${s.id}', this)" title="Delete">🗑️</button>
            `;
            list.appendChild(card);
        });

        // Update count
        document.getElementById("history-count").textContent = `${sessions.length} conversation${sessions.length !== 1 ? "s" : ""}`;
    } catch (err) {
        list.innerHTML = `<div class="history-empty"><p>⚠️ Failed to load history.</p></div>`;
    }
}

async function deleteSession(sessionId, btn) {
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    try {
        await fetch(`${API_BASE}/sessions/${sessionId}`, { method: "DELETE" });
        btn.closest(".history-card").remove();
        loadSidebarHistory();
        // If we deleted the current session, start a new one
        if (sessionId === SESSION_ID) newChat();
        // Recount
        const cards = document.querySelectorAll(".history-card").length;
        document.getElementById("history-count").textContent = `${cards} conversation${cards !== 1 ? "s" : ""}`;
    } catch (err) {
        alert("Failed to delete session.");
    }
}

function searchHistory() {
    const q = document.getElementById("history-search").value.trim();
    loadHistoryTab(q);
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ================================
// NAVIGATION & SIDEBAR
// ================================
function switchTab(tab) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".sidebar-item:not(.history-item)").forEach(el => el.classList.remove("active"));

    const targetContent = document.getElementById("tab-" + tab);
    if (targetContent) targetContent.classList.add("active");

    const targetBtn = document.getElementById("tab-" + tab + "-btn");
    if (targetBtn) targetBtn.classList.add("active");

    // Load history tab when switching to it
    if (tab === "history") loadHistoryTab();

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
            const dot = document.querySelector(".status-dot");
            dot.classList.add("online");
            document.getElementById("status-text").textContent = "AI Online";
        }
    } catch {
        document.getElementById("status-text").textContent = "Offline — start app.py";
    }
}

// ================================
// CHAT LOGIC
// ================================
function getTime(ts) {
    if (ts) {
        return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendMessage(text, sender, timestamp) {
    const container = document.getElementById("chat-messages");

    const row = document.createElement("div");
    row.className = "msg-row " + (sender === "user" ? "user-row" : "bot-row");

    const avatar = document.createElement("div");
    avatar.className = "avatar " + (sender === "user" ? "user-avatar" : "bot-avatar");
    avatar.textContent = sender === "user" ? "🧑" : "🤖";

    const bubble = document.createElement("div");
    bubble.className = "bubble " + (sender === "user" ? "user-bubble" : "bot-bubble");
    bubble.innerHTML = formatText(text) + `<p class="msg-time">${getTime(timestamp)}</p>`;

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
        const res = await fetch(API_BASE + "/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, session_id: SESSION_ID })
        });
        const data = await res.json();
        removeTyping();
        if (data.error) {
            appendMessage("⚠️ Error: " + data.error, "bot");
        } else {
            appendMessage(data.reply, "bot");
            // Refresh sidebar history to show new/updated session
            loadSidebarHistory();
        }
    } catch (err) {
        removeTyping();
        appendMessage("⚠️ Cannot connect to server. Make sure `app.py` is running on port 5000.", "bot");
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
        let threshold = { hours: (138 / 138), gpa: (2.0 / 4.0), attendance: (75 / 100), years: 1.0 }[type];
        const ratio = parseFloat(value) / max;
        if (type === "years") {
            bar.style.background = ratio <= 1 ? "linear-gradient(90deg, #22c55e, #16a34a)" : "linear-gradient(90deg, #ef4444, #dc2626)";
        } else {
            bar.style.background = ratio >= threshold
                ? "linear-gradient(90deg, #22c55e, #16a34a)"
                : "linear-gradient(90deg, #ef4444, #dc2626)";
        }
    }
    updateQuickStatus();
}

function updateQuickStatus() {
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa = parseFloat(document.getElementById("req-gpa").value) || 0;
    const att = parseFloat(document.getElementById("req-attendance").value) || 0;
    const years = parseFloat(document.getElementById("req-years").value) || 0;

    const set = (id, label, pass) => {
        const el = document.getElementById(id);
        el.textContent = label;
        el.className = "stat-item " + (pass ? "pass" : "fail");
    };

    if (hours > 0) set("stat-hours", `${hours >= 138 ? "✅" : "❌"} Credit Hours: ${hours}/138`, hours >= 138);
    if (gpa > 0) set("stat-gpa", `${gpa >= 2.0 ? "✅" : "❌"} GPA: ${gpa}/4.0`, gpa >= 2.0);
    if (att > 0) set("stat-att", `${att >= 75 ? "✅" : "❌"} Attendance: ${att}%`, att >= 75);
    if (years > 0) set("stat-years", `${years <= 8 ? "✅" : "❌"} Years: ${years}/8`, years <= 8);
}

async function checkRequirements() {
    const name = document.getElementById("req-name").value || "Student";
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa = parseFloat(document.getElementById("req-gpa").value) || 0;
    const att = parseFloat(document.getElementById("req-attendance").value) || 0;
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
        const res = await fetch(API_BASE + "/check-requirements", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, credit_hours: hours, gpa, attendance: att, years })
        });
        const data = await res.json();
        if (data.error) {
            document.getElementById("result-placeholder").style.display = "flex";
            document.getElementById("result-placeholder").querySelector("p").textContent = "⚠️ " + data.error;
        } else {
            const verdict = document.getElementById("verdict-badge");
            const resultText = document.getElementById("result-text");
            const resultContent = document.getElementById("result-content");
            verdict.textContent = data.can_graduate
                ? "🎓 مؤهل للتخرج — Eligible to Graduate"
                : "📚 غير مؤهل بعد — Not Eligible Yet";
            verdict.className = "verdict-badge " + (data.can_graduate ? "can-graduate" : "cannot-graduate");
            resultText.textContent = data.analysis;
            resultContent.style.display = "flex";
        }
    } catch (err) {
        document.getElementById("result-placeholder").style.display = "flex";
        document.getElementById("result-placeholder").querySelector("p").textContent =
            "⚠️ Cannot connect to server. Make sure app.py is running.";
    }

    btn.disabled = false;
    btn.innerHTML = "<span>🔍 تحليل بـ AI</span>";
}

// ================================
// INIT
// ================================
document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    setInterval(checkHealth, 10000);
    loadSidebarHistory();

    // Search on Enter in history tab
    const searchInput = document.getElementById("history-search");
    if (searchInput) {
        searchInput.addEventListener("keydown", e => {
            if (e.key === "Enter") searchHistory();
        });
    }
});
