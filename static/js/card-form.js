const entryForm = document.querySelector("#card-entry-form");
const nameInput = document.querySelector("#card-name");
const numberInput = document.querySelector("#card-number");
const catalogLanguage = document.querySelector("#catalog-language");
const cardLanguage = document.querySelector("#card-language");
const cardCondition = document.querySelector("#card-condition");
const cardVariant = document.querySelector("#card-variant");
const searchButton = document.querySelector("#catalog-search-button");
const addButton = document.querySelector("#add-card-button");
const entryFeedback = document.querySelector("#entry-feedback");
const chosenPreview = document.querySelector("#chosen-card");
const pricePanels = document.querySelector("#price-panels");
const ligaPanel = document.querySelector("#liga-result");
const internationalPanel = document.querySelector("#catalog-price-result");
const entryDialog = document.querySelector("#entry-dialog");
const dialogCard = document.querySelector("#entry-dialog-card");
const dialogMessage = document.querySelector("#entry-dialog-message");
const dialogContinue = document.querySelector("#entry-dialog-continue");
let selectedCard = null;
let cardFormRevision = 0;
let isSavingCard = false;
let catalogRequest = 0;
let searchTimer;

function updateEntryControls() {
    entryForm.querySelectorAll("input, select, button").forEach((control) => {
        control.disabled = isSavingCard;
    });
    addButton.disabled = isSavingCard || !selectedCard || !cardCondition.value;
    const currentStep = selectedCard ? (cardCondition.value ? 3 : 2) : 1;
    document.querySelectorAll("#entry-progress [data-step]").forEach((step) => {
        const number = Number(step.dataset.step);
        step.classList.toggle("is-complete", number < currentStep);
        if (number === currentStep) step.setAttribute("aria-current", "step");
        else step.removeAttribute("aria-current");
    });
    updateScanControls();
}

function nextEntryTarget() {
    if (cardLanguage.value === "unknown") return cardLanguage;
    if (!cardCondition.value) return cardCondition;
    return addButton;
}

function focusNextEntryTarget() {
    const target = nextEntryTarget();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "center", behavior: reducedMotion ? "auto" : "smooth" });
    target.focus({ preventScroll: true });
    target.classList.add("next-action");
    target.addEventListener("blur", () => target.classList.remove("next-action"), { once: true });
}

function showEntryGuidance() {
    dialogCard.textContent = `${selectedCard.name} · #${numberInput.value || selectedCard.local_id}`;
    const target = nextEntryTarget();
    dialogMessage.textContent = target === cardLanguage
        ? "Confira o idioma da sua carta e selecione a condição. Depois, clique em Adicionar ao portfolio."
        : target === cardCondition
            ? "Agora selecione a condição da sua carta. Depois, clique em Adicionar ao portfolio."
            : "Confira os dados. Sua carta já pode ser adicionada ao portfolio.";
    dialogContinue.textContent = target === addButton ? "Ir para Adicionar" : "Continuar cadastro";
    // O dialog nativo mantém o foco dentro do modal e permite fechar com Escape.
    if (typeof entryDialog.showModal === "function") {
        if (!entryDialog.open) entryDialog.showModal();
        document.body.classList.add("modal-open");
    } else {
        focusNextEntryTarget();
    }
}

document.querySelector("#entry-dialog-close").addEventListener("click", () => entryDialog.close());
dialogContinue.addEventListener("click", () => entryDialog.close());
entryDialog.addEventListener("close", () => {
    document.body.classList.remove("modal-open");
    focusNextEntryTarget();
});

function invalidatePrice(panel) {
    panel.dataset.requestId = String(Number(panel.dataset.requestId || 0) + 1);
    panel.replaceChildren();
}

function clearSelection() {
    selectedCard = null;
    chosenPreview.hidden = true;
    pricePanels.hidden = true;
    invalidatePrice(ligaPanel);
    invalidatePrice(internationalPanel);
    updateEntryControls();
}

// Nome/número/idioma do catálogo mudam a identidade escolhida.
for (const input of [nameInput, numberInput, catalogLanguage]) {
    input.addEventListener("input", () => {
        input.dataset.edited = "true";
        cardFormRevision += 1;
        catalogRequest += 1;
        clearSelection();
        result.replaceChildren();
        clearTimeout(searchTimer);
        if (nameInput.value.trim().length >= 2) {
            entryFeedback.textContent = "Buscando candidatos...";
            searchTimer = setTimeout(searchCatalog, 400);
        } else {
            entryFeedback.textContent = "Digite pelo menos dois caracteres para buscar.";
        }
    });
}

for (const input of [cardLanguage, cardCondition, cardVariant]) {
    input.addEventListener("input", () => {
        input.dataset.edited = "true";
        updateEntryControls();
        if (!selectedCard) return;
        refreshLigaPrice();
        if (input === cardVariant) refreshInternationalPrice();
    });
}

searchButton.addEventListener("click", () => {
    clearTimeout(searchTimer);
    searchCatalog();
});

async function searchCatalog() {
    if (isSavingCard) return;
    const name = nameInput.value.trim();
    if (name.length < 2) {
        entryFeedback.textContent = "Digite pelo menos dois caracteres para buscar.";
        return;
    }
    // Uma busca manual explícita também invalida um scan ainda pendente.
    cardFormRevision += 1;
    const requestId = ++catalogRequest;
    clearSelection();
    entryFeedback.textContent = "Buscando no catálogo... Os demais campos continuam disponíveis.";
    const params = new URLSearchParams({
        name, collector_number: numberInput.value,
        catalog_language: catalogLanguage.value
    });
    try {
        const response = await fetch(`/api/cards/search?${params}`);
        const data = await response.json();
        if (requestId !== catalogRequest) return;
        if (!response.ok) throw new Error(data.error || "Não foi possível buscar no catálogo.");
        showCardCandidates(data.candidates);
    } catch (error) {
        if (requestId === catalogRequest) entryFeedback.textContent = error.message;
    }
}

function receiveScanResult(data, revision) {
    if (revision !== cardFormRevision || selectedCard || isSavingCard) {
        scanFeedback.textContent = "Foto analisada; suas escolhas manuais foram preservadas.";
        return;
    }
    const detected = data.detected || {};
    if (detected.game && detected.game !== "pokemon") {
        scanFeedback.textContent = data.message || "O catálogo desse jogo ainda não está disponível.";
        return;
    }
    // Só preenche campos que o usuário ainda não editou.
    for (const [input, value] of [
        [nameInput, detected.printed_name || detected.search_name],
        [numberInput, detected.collector_number],
        [cardLanguage, detected.language],
        [catalogLanguage, data.candidates?.[0]?.language]
    ]) {
        if (value && input.dataset.edited !== "true") input.value = value;
    }
    if (data.status !== "ok") {
        scanFeedback.textContent = data.message || "Confira os dados e continue pela busca manual.";
        return;
    }
    scanFeedback.textContent = "Foto identificada. Escolha a carta abaixo.";
    showCardCandidates(data.candidates);
}

function showCardCandidates(cards) {
    result.replaceChildren();
    entryFeedback.textContent = cards.length
        ? "Escolha a edição correta. Confira a imagem e o número."
        : "Nenhum candidato encontrado. Confira o nome, número ou idioma do catálogo.";
    const list = element("div", undefined, "candidates");
    for (const card of cards) {
        const candidate = element("div", undefined, "candidate");
        if (card.image) {
            const image = document.createElement("img");
            image.src = `${card.image}/high.webp`;
            image.alt = card.name;
            candidate.append(image);
        }
        candidate.append(element("h3", card.name), element("p", `#${card.local_id} · ${card.id}`));
        const choose = element("button", "É esta", "confirm-card");
        choose.type = "button";
        choose.disabled = isSavingCard;
        choose.addEventListener("click", () => selectCard(card));
        candidate.append(choose);
        list.append(candidate);
    }
    result.append(list);
}

function selectCard(card) {
    if (isSavingCard) return;
    clearTimeout(searchTimer);
    catalogRequest += 1;
    cardFormRevision += 1;
    selectedCard = card;
    nameInput.value = card.name;
    // Mantém o número completo lido/digitado quando pertence à carta escolhida.
    const localNumber = (value) => String(value || "").split("/")[0].replace(/^0+/, "") || "0";
    if (!numberInput.value || localNumber(numberInput.value) !== localNumber(card.local_id)) {
        numberInput.value = card.local_id || "";
    }
    catalogLanguage.value = card.language;
    chosenPreview.replaceChildren(element("h3", card.name),
        element("p", `Carta selecionada: ${card.id} · catálogo ${card.language}`));
    chosenPreview.hidden = false;
    pricePanels.hidden = false;
    result.replaceChildren();
    entryFeedback.textContent = "Confira o idioma, a condição e a variante. O preço não precisa terminar para adicionar.";
    updateEntryControls();
    refreshInternationalPrice();
    refreshLigaPrice();
    showEntryGuidance();
}

function startPriceRequest(panel, message) {
    const requestId = String(Number(panel.dataset.requestId || 0) + 1);
    panel.dataset.requestId = requestId;
    panel.replaceChildren(element("p", message));
    return requestId;
}

async function refreshLigaPrice() {
    if (!selectedCard) return;
    const requestId = startPriceRequest(ligaPanel, "Consultando Liga Pokémon...");
    if (!cardCondition.value) {
        ligaPanel.replaceChildren(element("p", "Selecione a condição para consultar a Liga."));
        return;
    }
    const params = new URLSearchParams({
        external_id: selectedCard.id, catalog_language: selectedCard.language,
        name: nameInput.value, collector_number: numberInput.value,
        language: cardLanguage.value, condition: cardCondition.value
    });
    try {
        const response = await fetch(`/api/ligapokemon/search?${params}`);
        const data = await response.json();
        if (ligaPanel.dataset.requestId !== requestId) return;
        if (!response.ok) throw new Error(data.error || data.message || "Liga indisponível.");
        const text = data.status === "ok" && typeof data.price === "number"
            ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(data.price)
            : "Preço indisponível";
        ligaPanel.replaceChildren(element("p", text, "price-value"), element("p", data.message),
            element("p", "Referência geral: idioma, condição e variante da oferta não foram confirmados."));
        if (data.search_url) {
            const link = element("a", "Conferir na Liga", "button-link");
            link.href = data.search_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            ligaPanel.append(link);
        }
    } catch (error) {
        if (ligaPanel.dataset.requestId === requestId) ligaPanel.replaceChildren(element("p", error.message));
    }
}

async function refreshInternationalPrice() {
    if (!selectedCard) return;
    const requestId = startPriceRequest(internationalPanel, "Consultando referência internacional...");
    const language = selectedCard.language;
    const params = new URLSearchParams({ catalog_language: language, variant: cardVariant.value });
    try {
        const response = await fetch(`/api/cards/${encodeURIComponent(selectedCard.id)}/prices?${params}`);
        const data = await response.json();
        if (internationalPanel.dataset.requestId !== requestId) return;
        if (!response.ok) throw new Error(data.error || data.message || "Referência indisponível.");
        internationalPanel.replaceChildren();
        if (!data.quotes.length) internationalPanel.append(element("p", "Preço indisponível para esta carta/variante."));
        for (const quote of data.quotes) {
            const native = new Intl.NumberFormat("pt-BR", { style: "currency", currency: quote.currency }).format(quote.amount);
            internationalPanel.append(element("p", `${quote.source} · ${quote.variant}: ${native}`, "price-value"));
            if (quote.estimated_brl !== null) {
                const converted = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(quote.estimated_brl);
                internationalPanel.append(element("p", `Estimativa: ≈ ${converted}`),
                    element("p", `Câmbio ${quote.exchange_rate.source}, de ${quote.exchange_rate.date}.`));
            } else {
                internationalPanel.append(element("p", "Conversão em reais indisponível."));
            }
            if (quote.updated_at) internationalPanel.append(element("p", `Preço atualizado em ${quote.updated_at.slice(0, 10)}.`));
        }
        internationalPanel.append(element("p", `Catálogo ${language}. ${data.message}`));
    } catch (error) {
        if (internationalPanel.dataset.requestId === requestId) internationalPanel.replaceChildren(element("p", error.message));
    }
}

entryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isSavingCard || !selectedCard || !entryForm.reportValidity()) return;
    const payload = {
        game: "pokemon", provider: "tcgdex", external_id: selectedCard.id,
        catalog_language: selectedCard.language, language: cardLanguage.value,
        collector_number: numberInput.value || selectedCard.local_id,
        condition: cardCondition.value, variant: cardVariant.value || null
    };
    isSavingCard = true;
    updateEntryControls();
    result.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    addButton.textContent = "Adicionando...";
    entryFeedback.textContent = "Salvando sua carta...";
    try {
        const response = await fetch("/api/portfolio/cards", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Não foi possível adicionar a carta.");
        entryFeedback.textContent = "Carta salva! Abrindo seu portfolio...";
        window.location.assign(data.redirect_url);
    } catch (error) {
        entryFeedback.textContent = error.message;
        isSavingCard = false;
        addButton.textContent = "Adicionar ao portfolio";
        updateEntryControls();
        result.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
});

updateEntryControls();