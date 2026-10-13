
const cameraInput = document.querySelector("#card-camera");
const preview = document.querySelector("#preview");
const previewContainer = document.querySelector("#preview-container");
const form = document.querySelector("#scan-form");
const scanButton = document.querySelector("#scan-button");
const result = document.querySelector("#result");
const scanFeedback = document.querySelector("#scan-feedback");
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
    scanButton.disabled = scanning || saving || !cameraInput.files[0];
    scanButton.textContent = scanning ? "Identificando..." : "Identificar carta";
}

cameraInput.addEventListener("change", () => {
    scanRequest += 1;
    scanController?.abort();
    scanning = false;
    scanFeedback.textContent = "";
    const file = cameraInput.files[0];
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (!file) {
        preview.removeAttribute("src");
        previewContainer.classList.remove("visible");
    } else {
        previewUrl = URL.createObjectURL(file);
        preview.src = previewUrl;
        previewContainer.classList.add("visible");
    }
    updateScanControls();
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = cameraInput.files[0];
    if (!file || scanning || isSavingCard) return;
    const requestId = ++scanRequest;
    const formRevision = cardFormRevision;
    const controller = new AbortController();
    scanController = controller;
    // Limita a espera da interface. Não cancela a chamada Gemini no servidor.
    const timeout = setTimeout(() => controller.abort(), 20000);
    scanning = true;
    updateScanControls();
    scanFeedback.textContent = "Analisando foto... Você pode continuar preenchendo os dados abaixo.";
    const formData = new FormData();
    formData.append("card", file);

    try {
        const response = await fetch("/scan", {
            method: "POST", body: formData, signal: controller.signal
        });
        const data = await response.json();
        if (requestId !== scanRequest) return;
        if (!response.ok) throw new Error(data.error || "A identificação falhou.");
        receiveScanResult(data, formRevision);
    } catch (error) {
        if (requestId !== scanRequest) return;
        scanFeedback.textContent = error.name === "AbortError"
            ? "A identificação demorou. Continue pela busca manual no catálogo."
            : "Não foi possível identificar a foto. Continue pela busca manual no catálogo.";
    } finally {
        clearTimeout(timeout);
        if (requestId === scanRequest) {
            scanning = false;
            updateScanControls();
        }
    }
});