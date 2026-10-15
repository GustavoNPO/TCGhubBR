const cameraInput = document.querySelector("#card-camera");
const preview = document.querySelector("#preview");
const result = document.querySelector("#result");
let previewUrl;
let scanning = false;
let scanRequest = 0;
let scanController;

// Texto externo nunca vira HTML executável.
function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function updateScanControls() {
    const saving = typeof isSavingCard !== "undefined" && isSavingCard;
    cameraInput.disabled = saving;
    cameraInput.closest(".camera-button").classList.toggle("is-busy", scanning);
}

// A foto já é a ação: escolher a imagem inicia a identificação.
cameraInput.addEventListener("change", async () => {
    const file = cameraInput.files[0];
    const requestId = ++scanRequest;
    scanController?.abort();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (!file) { preview.hidden = true; preview.removeAttribute("src"); scanning = false; updateScanControls(); return; }
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl; preview.hidden = false;
    const formRevision = cardFormRevision;
    const controller = new AbortController();
    scanController = controller;
    // Limita a espera da interface. Não cancela a chamada Gemini no servidor.
    const timeout = setTimeout(() => controller.abort(), 20000);
    scanning = true;
    updateScanControls();
    entryFeedback.textContent = "Lendo a foto…";
    const formData = new FormData();
    formData.append("card", file);
    try {
        const response = await fetch("/scan", { method: "POST", body: formData, signal: controller.signal });
        const data = await response.json();
        if (requestId !== scanRequest) return;
        if (!response.ok) throw new Error(data.error || "A identificação falhou.");
        receiveScanResult(data, formRevision);
    } catch (error) {
        if (requestId !== scanRequest) return;
        entryFeedback.textContent = error.name === "AbortError"
            ? "A leitura da foto demorou. Digite o nome ou o número impresso na carta."
            : "Não foi possível ler a foto. Digite o nome ou o número impresso na carta.";
    } finally {
        clearTimeout(timeout);
        if (requestId === scanRequest) {
            scanning = false;
            cameraInput.value = "";
            updateScanControls();
        }
    }
});