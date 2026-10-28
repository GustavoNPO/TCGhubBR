/* Conversas em tempo real.
 *
 * O navegador entra no Firestore com um token emitido pelo servidor para o
 * mesmo uid da sessão e só escuta: conversas e mensagens chegam por onSnapshot.
 * Enviar e marcar como lida passam pelo Flask, que confere quem participa.
 */
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
    getAuth, inMemoryPersistence, setPersistence, signInWithCustomToken
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
    getFirestore, collection, query, where, orderBy, limitToLast, onSnapshot
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";

const config = JSON.parse(document.querySelector("#firebase-config").textContent);
const context = JSON.parse(document.querySelector("#chat-context").textContent);
const me = context.uid;
const app = initializeApp(config, "chat");
const auth = getAuth(app);
const db = getFirestore(app);

const layout = document.querySelector(".chat-layout");
const status = document.querySelector("#chat-status");
const list = document.querySelector("#conversation-list");
const thread = document.querySelector("#thread");
const threadEmpty = document.querySelector("#thread-empty");
const messages = document.querySelector("#message-list");
const form = document.querySelector("#message-form");
const textInput = document.querySelector("#message-text");
const sendButton = document.querySelector("#message-send");
const feedback = document.querySelector("#message-feedback");
const baseTitle = document.title;

let conversations = new Map();
let loaded = false;
let selected = /^[0-9a-f]{32}$/.test(context.selected) ? context.selected : null;
let stopMessages = null;
let markingRead = null;

const errors = {
    "permission-denied": "Sem permissão para ler as conversas. Confira se as regras do Firestore foram publicadas.",
    "unavailable": "Sem conexão com o servidor de conversas. Tentando de novo…",
    "auth/network-request-failed": "Sem conexão. Verifique a internet e recarregue a página."
};
const explain = (error) => errors[error?.code] || error?.message || "Não foi possível carregar as conversas.";

const millis = (value) => value?.toMillis?.() ?? 0;
const other = (conversation) => {
    const uid = conversation.participants.find((id) => id !== me) || me;
    return conversation.people?.[uid] || {};
};
const isUnread = (conversation) => {
    const last = conversation.last_message;
    return Boolean(last && last.sender !== me && millis(last.at) > millis(conversation.read_at?.[me]));
};

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function avatar(person, node = element("span", "avatar")) {
    node.replaceChildren();
    node.setAttribute("aria-hidden", "true");
    if (person.avatar_url) {
        const image = element("img");
        image.src = person.avatar_url; image.alt = ""; image.referrerPolicy = "no-referrer";
        node.append(image);
    } else {
        node.textContent = (person.display_name || person.handle || "?").trim().slice(0, 1).toUpperCase();
    }
    return node;
}

function formatTime(value) {
    if (!value) return "";
    const date = value.toDate();
    const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === new Date().toDateString()) return time;
    return `${date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${time}`;
}

async function post(url, body) {
    const response = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Não foi possível concluir a operação.");
    return data;
}

function renderList() {
    const sorted = [...conversations.values()].sort((a, b) => millis(b.updated_at) - millis(a.updated_at));
    const unread = sorted.filter(isUnread).length;
    document.title = unread ? `(${unread}) ${baseTitle}` : baseTitle;
    status.textContent = sorted.length ? "" : "Nenhuma conversa ainda. Abra o perfil público de um colecionador e toque em Conversar.";
    list.replaceChildren(...sorted.map((conversation) => {
        const person = other(conversation);
        const item = element("li");
        const button = element("button", "conversation-item");
        button.type = "button";
        button.dataset.id = conversation.id;
        if (conversation.id === selected) button.setAttribute("aria-current", "true");
        if (isUnread(conversation)) button.classList.add("unread");
        const text = element("span", "conversation-text");
        const last = conversation.last_message;
        text.append(
            element("strong", "", person.display_name || `@${person.handle}`),
            element("span", "conversation-preview", last ? `${last.sender === me ? "Você: " : ""}${last.text}` : "Sem mensagens ainda")
        );
        button.append(avatar(person), text, element("time", "conversation-time", formatTime(last?.at)));
        item.append(button);
        return item;
    }));
}

function renderHeader() {
    const conversation = conversations.get(selected);
    if (!conversation) return;
    const person = other(conversation);
    avatar(person, document.querySelector("#thread-avatar"));
    document.querySelector("#thread-name").textContent = person.display_name || `@${person.handle}`;
    const handle = document.querySelector("#thread-handle");
    handle.textContent = `@${person.handle}`;
    handle.href = `/u/${encodeURIComponent(person.handle)}`;
}

function renderMessages(snapshot) {
    const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
    const items = snapshot.docs.map((doc) => {
        const message = doc.data({ serverTimestamps: "estimate" });
        const mine = message.sender === me;
        const item = element("li", mine ? "message mine" : "message");
        item.append(element("p", "", message.text), element("time", "", formatTime(message.created_at)));
        return item;
    });
    if (!items.length) items.push(element("li", "message-empty", "Diga olá! As mensagens aparecem aqui assim que são enviadas."));
    const lastMine = snapshot.docs.at(-1)?.data().sender === me;
    messages.replaceChildren(...items);
    // Rola para o fim ao abrir, ao enviar e quando já se estava no fim; quem lê o histórico fica onde está.
    if (!messages.dataset.loaded || nearBottom || lastMine) {
        messages.scrollTop = messages.scrollHeight;
    }
    messages.dataset.loaded = "1";
}

function markReadIfNeeded() {
    const conversation = conversations.get(selected);
    if (!conversation || !isUnread(conversation) || document.visibilityState !== "visible" || markingRead === selected) return;
    markingRead = selected;
    post(`/api/chat/conversations/${selected}/read`)
        .catch(() => {})
        .finally(() => { markingRead = null; });
}

function select(id, { push = true } = {}) {
    if (stopMessages) stopMessages();
    stopMessages = null;
    selected = id;
    feedback.textContent = "";
    layout.dataset.view = id ? "thread" : "list";
    if (push) {
        const url = id ? `/conversas?c=${id}` : "/conversas";
        history.pushState({ id }, "", url);
    }
    if (!id) {
        thread.hidden = true;
        threadEmpty.hidden = false;
        threadEmpty.firstElementChild.textContent = "Escolha uma conversa para ler as mensagens.";
        renderList();
        return;
    }
    if (loaded && !conversations.has(id)) {
        thread.hidden = true;
        threadEmpty.hidden = false;
        threadEmpty.firstElementChild.textContent = "Conversa não encontrada.";
        return;
    }
    thread.hidden = false;
    threadEmpty.hidden = true;
    messages.replaceChildren();
    delete messages.dataset.loaded;
    renderHeader();
    renderList();
    const recent = query(collection(db, "conversations", id, "messages"), orderBy("created_at"), limitToLast(100));
    stopMessages = onSnapshot(recent, renderMessages, (error) => { feedback.textContent = explain(error); });
    markReadIfNeeded();
    if (window.matchMedia("(min-width: 720px)").matches) textInput.focus();
}

list.addEventListener("click", (event) => {
    const button = event.target.closest(".conversation-item");
    if (button) select(button.dataset.id);
});
document.querySelector("#thread-back").addEventListener("click", () => select(null));
window.addEventListener("popstate", (event) => select(event.state?.id || null, { push: false }));
document.addEventListener("visibilitychange", markReadIfNeeded);

// Enter envia; Shift+Enter quebra a linha. A caixa cresce até umas 6 linhas.
textInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
    }
});
textInput.addEventListener("input", () => {
    textInput.style.height = "auto";
    const height = textInput.scrollHeight + textInput.offsetHeight - textInput.clientHeight;
    textInput.style.height = `${Math.min(height, 160)}px`;
    textInput.style.overflowY = height > 160 ? "auto" : "hidden";
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = textInput.value.trim();
    if (!text || !selected || sendButton.disabled) return;
    sendButton.disabled = true;
    feedback.textContent = "";
    try {
        await post(`/api/chat/conversations/${selected}/messages`, { text });
        textInput.value = "";
        textInput.dispatchEvent(new Event("input"));
    } catch (error) {
        feedback.textContent = error.message;
    } finally {
        sendButton.disabled = false;
        textInput.focus();
    }
});

async function connect() {
    try {
        await setPersistence(auth, inMemoryPersistence);
        const { token } = await post("/api/auth/client-token");
        await signInWithCustomToken(auth, token);
    } catch (error) {
        status.textContent = explain(error);
        return;
    }
    const mine = query(collection(db, "conversations"), where("participants", "array-contains", me));
    onSnapshot(mine, (snapshot) => {
        conversations = new Map(snapshot.docs.map((doc) => [doc.id, { ...doc.data({ serverTimestamps: "estimate" }), id: doc.id }]));
        const first = !loaded;
        loaded = true;
        renderList();
        if (first) {
            history.replaceState({ id: selected }, "", selected ? `/conversas?c=${selected}` : "/conversas");
            select(selected, { push: false });
        } else if (selected) {
            renderHeader();
            markReadIfNeeded();
        }
    }, (error) => { status.textContent = explain(error); });
}

connect();