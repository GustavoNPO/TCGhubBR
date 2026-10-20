/* Login e cadastro com Firebase Authentication.
 *
 * O navegador só autentica e entrega o ID token ao servidor, que cria o cookie
 * de sessão. A persistência do SDK fica em memória: a sessão vale pelo cookie
 * HttpOnly, não por tokens guardados no navegador. (Para o chat em tempo real,
 * o servidor poderá emitir um token próprio para o SDK, sem novo login.)
 */
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
    getAuth, inMemoryPersistence, setPersistence, signInWithEmailAndPassword, createUserWithEmailAndPassword,
    updateProfile, sendEmailVerification, sendPasswordResetEmail, GoogleAuthProvider, signInWithPopup, signOut
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";

const config = JSON.parse(document.querySelector("#firebase-config").textContent);
const nextUrl = JSON.parse(document.querySelector("#auth-next").textContent);
const auth = getAuth(initializeApp(config));
auth.languageCode = "pt";
const ready = setPersistence(auth, inMemoryPersistence);

const form = document.querySelector("#auth-form");
const nameField = document.querySelector("#name-field");
const nameInput = document.querySelector("#auth-name");
const emailInput = document.querySelector("#auth-email");
const passwordInput = document.querySelector("#auth-password");
const submit = document.querySelector("#auth-submit");
const feedback = document.querySelector("#auth-feedback");
const tabs = { login: document.querySelector("#tab-login"), register: document.querySelector("#tab-register") };
let mode = "login";
let busy = false;

const messages = {
    "auth/invalid-credential": "E-mail ou senha incorretos.",
    "auth/invalid-email": "Informe um e-mail válido.",
    "auth/user-disabled": "Esta conta foi desativada.",
    "auth/email-already-in-use": "Já existe uma conta com este e-mail. Entre ou recupere a senha.",
    "auth/weak-password": "Use uma senha com pelo menos 6 caracteres.",
    "auth/too-many-requests": "Muitas tentativas. Aguarde alguns minutos e tente de novo.",
    "auth/popup-closed-by-user": "Login com Google cancelado.",
    "auth/popup-blocked": "O navegador bloqueou a janela do Google. Permita pop-ups e tente de novo.",
    "auth/network-request-failed": "Sem conexão com o Firebase. Verifique a internet.",
    "auth/account-exists-with-different-credential": "Este e-mail já usa outro método de login. Entre com e-mail e senha."
};
const explain = (error) => messages[error?.code] || error?.message || "Não foi possível entrar. Tente novamente.";

function setMode(next) {
    mode = next;
    for (const [key, tab] of Object.entries(tabs)) tab.setAttribute("aria-selected", String(key === mode));
    nameField.hidden = mode !== "register";
    submit.textContent = mode === "register" ? "Criar conta" : "Entrar";
    passwordInput.autocomplete = mode === "register" ? "new-password" : "current-password";
    feedback.textContent = "";
}
tabs.login.addEventListener("click", () => setMode("login"));
tabs.register.addEventListener("click", () => setMode("register"));

function setBusy(value, message = "") {
    busy = value;
    for (const control of document.querySelectorAll(".auth-card button, .auth-card input")) control.disabled = value;
    if (message) feedback.textContent = message;
}

// O servidor valida o token, cria a conta/perfil no primeiro acesso e grava o cookie.
async function startSession(user) {
    const response = await fetch("/api/auth/session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: await user.getIdToken(true), next: nextUrl })
    });
    const data = await response.json();
    await signOut(auth);
    if (!response.ok) throw new Error(data.error || "Não foi possível iniciar a sessão.");
    window.location.assign(data.redirect_url || "/");
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    if (!email || !password) { feedback.textContent = "Informe e-mail e senha."; return; }
    if (mode === "register" && !nameInput.value.trim()) { feedback.textContent = "Informe um nome de exibição."; return; }
    setBusy(true, mode === "register" ? "Criando sua conta…" : "Entrando…");
    try {
        await ready;
        let credential;
        if (mode === "register") {
            credential = await createUserWithEmailAndPassword(auth, email, password);
            await updateProfile(credential.user, { displayName: nameInput.value.trim() });
            // A verificação não bloqueia o uso agora; será exigida para o chat entre usuários.
            sendEmailVerification(credential.user).catch(() => {});
        } else {
            credential = await signInWithEmailAndPassword(auth, email, password);
        }
        await startSession(credential.user);
    } catch (error) {
        setBusy(false, explain(error));
    }
});

document.querySelector("#google-button").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true, "Abrindo o Google…");
    try {
        await ready;
        const credential = await signInWithPopup(auth, new GoogleAuthProvider());
        setBusy(true, "Entrando…");
        await startSession(credential.user);
    } catch (error) {
        setBusy(false, explain(error));
    }
});

document.querySelector("#reset-password").addEventListener("click", async () => {
    const email = emailInput.value.trim();
    if (!email) { feedback.textContent = "Digite seu e-mail acima para receber o link de nova senha."; emailInput.focus(); return; }
    setBusy(true, "Enviando…");
    try {
        await sendPasswordResetEmail(auth, email);
        // Mesma mensagem com ou sem conta: não revelamos quais e-mails estão cadastrados.
        setBusy(false, "Se houver uma conta com este e-mail, você receberá o link para criar uma nova senha.");
    } catch (error) {
        setBusy(false, error?.code === "auth/invalid-email" ? explain(error)
            : "Se houver uma conta com este e-mail, você receberá o link para criar uma nova senha.");
    }
});