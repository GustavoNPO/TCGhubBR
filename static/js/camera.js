const cameraInput = document.querySelector("#card-camera");
const preview = document.querySelector("#preview");
const previewContainer = document.querySelector("#preview-container");
const form = document.querySelector("#scan-form");
const scanButton = document.querySelector("#scan-button");
const result = document.querySelector("#result");
let previewUrl;
let busy = false;

function setBusy(value) {
    busy = value;
    cameraInput.disabled = value;
    scanButton.disabled = value || !cameraInput.files[0];
    result.querySelectorAll("button").forEach((button) => {
        button.disabled = value;
    });
}

// textContent mantém nomes e mensagens externos como texto.
function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

cameraInput.addEventListener("change", () => {
    const file = cameraInput.files[0];
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    result.replaceChildren();
    if (!file) {
        preview.removeAttribute("src");
        previewContainer.classList.remove("visible");
        scanButton.disabled = true;
        return;
    }
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    previewContainer.classList.add("visible");
    scanButton.disabled = false;
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = cameraInput.files[0];
    if (!file || busy) return;

    setBusy(true);
    scanButton.textContent = "Identificando...";
    result.replaceChildren(element("p", "Analisando carta..."));
    const formData = new FormData();
    formData.append("card", file);

    try {
        const response = await fetch("/scan", { method: "POST", body: formData });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Não foi possível analisar a carta.");
        showResult(data);
    } catch (error) {
        result.replaceChildren(element("p", `Erro: ${error.message}`, "error-message"));
    } finally {
        setBusy(false);
        scanButton.textContent = "Identificar carta";
    }
});

function showResult(data) {
    result.replaceChildren();
    if (data.status === "retry" || data.status === "game_detected") {
        const message = element("div", undefined, "scan-message");
        message.append(
            element("h2", data.status === "retry" ? "Vamos tentar novamente" : "TCG identificado!"),
            element("p", data.message)
        );
        if (data.status === "game_detected") {
            message.append(element("p", `Carta: ${data.detected.printed_name ?? "Nome não identificado"}`));
        }
        result.append(message);
        return;
    }
    if (data.status !== "ok") {
        result.append(element("p", data.error || "Não foi possível identificar a carta.", "error-message"));
        return;
    }

    result.append(element("h2", "Encontramos sua carta"));
    result.append(element("p", "Confirme a carta para adicioná-la ao inventário."));
    const candidates = element("div", undefined, "candidates");
    const feedback = element("p", "", "save-feedback");
    feedback.setAttribute("role", "status");

    for (const card of data.candidates) {
        const candidate = element("div", undefined, "candidate");
        if (card.image) {
            const image = document.createElement("img");
            image.src = `${card.image}/high.webp`;
            image.alt = card.name;
            candidate.append(image);
        }
        candidate.append(element("h3", card.name), element("p", `#${card.local_id}`));
        candidate.append(element("p", `Idioma da carta: ${data.detected.language} · Catálogo: ${card.language}`));
        const confirm = element("button", "É esta", "confirm-card");
        confirm.type = "button";
        confirm.addEventListener("click", () => confirmCard(card, data.detected, confirm, feedback));
        candidate.append(confirm);
        candidates.append(candidate);
    }

    const retry = element("button", "Nenhuma dessas", "secondary-button");
    retry.type = "button";
    retry.addEventListener("click", () => {
        result.replaceChildren();
        cameraInput.value = "";
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        preview.removeAttribute("src");
        previewContainer.classList.remove("visible");
        scanButton.disabled = true;
        cameraInput.click();
    });
    result.append(candidates, feedback, retry);
}

async function confirmCard(card, detected, button, feedback) {
    if (busy) return;
    setBusy(true);
    button.textContent = "Salvando...";
    feedback.textContent = "Adicionando carta ao inventário...";
    feedback.classList.remove("error-message");

    try {
        const response = await fetch("/api/portfolio/cards", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                game: detected.game,
                provider: "tcgdex",
                external_id: card.id,
                language: detected.language,
                catalog_language: card.language,
                collector_number: detected.collector_number
            })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Não foi possível salvar a carta.");
        feedback.textContent = "Carta salva! Abrindo seu inventário...";
        window.location.assign(data.redirect_url);
    } catch (error) {
        feedback.textContent = `Erro: ${error.message}`;
        feedback.classList.add("error-message");
        button.textContent = "É esta";
        setBusy(false);
    }
}