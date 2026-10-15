/* Fluxo único: identificar → conferir → adicionar, sem voltar a campos já resolvidos. */
const entryForm = document.querySelector("#card-entry-form");
const queryInput = document.querySelector("#card-query");
const setInput = document.querySelector("#card-set");
const setOptions = document.querySelector("#set-options");
const cardLanguage = document.querySelector("#card-language");
const addButton = document.querySelector("#add-card-button");
const addBar = document.querySelector("#add-bar");
const addSummary = document.querySelector("#add-summary");
const entryFeedback = document.querySelector("#entry-feedback");
const addFeedback = document.querySelector("#add-feedback");
const confirmation = document.querySelector("#card-confirmation");
const chosenImage = document.querySelector("#chosen-image");
const chosenIdentity = document.querySelector("#chosen-identity");
const finishList = document.querySelector("#finish-list");
const ligaPanel = document.querySelector("#liga-link");
const priceDetails = document.querySelector("#price-details");
const priceSources = document.querySelector("#price-sources");
const moreButton = document.querySelector("#load-more-cards");
const conditionInputs = [...entryForm.querySelectorAll('input[name="condition"]')];
let selectedCard = null;
let selectedVariant = null;
let cardFormRevision = 0;
let isSavingCard = false;
let catalogRequest = 0;
let priceRequest = 0;
let searchTimer;
let searchController;
let lastCandidates = [];
let lastPage = 1;
let hasMore = false;
let scanLanguage = null;
let catalogSets = new Map();
const setsByLabel = new Map();

// Preferências da última carta salva: quem cataloga um fichário não repete idioma e condição.
const memory = {
    get(key) { try { return localStorage.getItem(`tcghub:${key}`); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(`tcghub:${key}`, value); } catch { /* sem armazenamento */ } }
};

/* "Pikachu 025/165", "025/165", "Mew ex 151", "Alcremie TG08/TG30" → nome e número impresso. */
function parseQuery(text) {
    const value = text.trim().replace(/\s+/g, " ");
    const match = value.match(/(?:^|\s)#?((?:[A-Za-z]{1,3})?\d{1,4}[a-z]?(?:\s*\/\s*(?:[A-Za-z]{1,3})?\d{1,4})?)$/);
    if (!match) return { name: value, number: "" };
    return { name: value.slice(0, match.index).trim(), number: match[1].replace(/\s+/g, "") };
}

function currentSetId() {
    const text = setInput.value.trim().toLocaleLowerCase("pt-BR");
    return text ? setsByLabel.get(text) || "" : "";
}

function setLanguage(value) {
    if ([...cardLanguage.options].some((option) => option.value === value)) cardLanguage.value = value;
}

function conditionValue() {
    return conditionInputs.find((input) => input.checked)?.value || "";
}

function setCondition(value) {
    for (const input of conditionInputs) input.checked = input.value === value;
}

function cardLabel(card) {
    const total = card.set_total ? `/${card.set_total}` : "";
    return `${card.set_name || "Coleção não informada"} · #${card.local_id}${total}`;
}

function updateEntryControls() {
    for (const control of entryForm.querySelectorAll("input, select, button")) control.disabled = isSavingCard;
    addBar.hidden = !selectedCard;
    addButton.disabled = isSavingCard || !selectedCard || !conditionValue();
    if (selectedCard) {
        const finish = { normal: "Normal", holo: "Holo", reverse: "Reverse" }[selectedVariant] || "Acabamento ?";
        const language = cardLanguage.value === "unknown" ? "Idioma ?" : cardLanguage.value.toUpperCase();
        addSummary.replaceChildren(element("strong", `${selectedCard.name} · #${selectedCard.local_id}${selectedCard.set_total ? `/${selectedCard.set_total}` : ""}`),
            element("span", [finish, conditionValue() || "Condição ?", language].join(" · ")));
    }
    updateScanControls();
}

function clearSelection() {
    selectedCard = null;
    selectedVariant = null;
    priceRequest += 1;
    confirmation.hidden = true;
    result.classList.remove("has-selection", "show-all");
    result.hidden = false;
    result.querySelectorAll(".candidate.is-selected").forEach((card) => card.classList.remove("is-selected"));
    addFeedback.replaceChildren();
    updateEntryControls();
}

function hasSearchCriteria() {
    const { name, number } = parseQuery(queryInput.value);
    return name.length >= 2 || Boolean(number) || Boolean(currentSetId());
}

function scheduleSearch() {
    cardFormRevision += 1;
    catalogRequest += 1;
    searchController?.abort();
    clearSelection();
    clearTimeout(searchTimer);
    if (setInput.value.trim() && !currentSetId()) {
        entryFeedback.textContent = "Escolha a coleção na lista sugerida, ou apague o filtro.";
        return;
    }
    if (hasSearchCriteria()) {
        entryFeedback.textContent = "Buscando…";
        searchTimer = setTimeout(() => searchCatalog(), 400);
    } else {
        result.replaceChildren(); moreButton.hidden = true;
        entryFeedback.textContent = "Fotografe a carta ou digite o nome em português ou inglês. O número impresso deixa a busca exata.";
    }
}

queryInput.addEventListener("input", scheduleSearch);
setInput.addEventListener("input", scheduleSearch);
queryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); clearTimeout(searchTimer); if (hasSearchCriteria()) searchCatalog(); }
});
for (const input of [cardLanguage, ...conditionInputs]) input.addEventListener("change", updateEntryControls);
moreButton.addEventListener("click", () => searchCatalog(lastPage + 1));

async function loadSets() {
    try {
        const response = await fetch("/api/sets");
        const data = await response.json();
        if (!response.ok) throw new Error(data.message);
        catalogSets = new Map(data.sets.map((set) => [set.id, set]));
        const sets = [...data.sets].sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
        for (const set of sets) {
            const names = [...new Set([set.names?.pt, set.names?.en, set.name].filter(Boolean))];
            const label = `${names.join(" / ")}${set.official ? ` · /${set.official}` : ""}`;
            const option = document.createElement("option");
            option.value = label;
            setOptions.append(option);
            // Aceita o rótulo sugerido, qualquer um dos nomes ou o código da coleção.
            for (const key of [label, ...names, set.id]) setsByLabel.set(key.toLocaleLowerCase("pt-BR"), set.id);
        }
    } catch {
        setInput.placeholder = "Coleções indisponíveis · busque pelo nome e número";
    }
}

async function searchCatalog(page = 1, scanCandidates = []) {
    if (isSavingCard) return;
    const { name, number } = parseQuery(queryInput.value);
    const setId = currentSetId();
    cardFormRevision += 1;
    const requestId = ++catalogRequest;
    searchController?.abort();
    const controller = new AbortController();
    searchController = controller;
    if (page === 1) clearSelection();
    moreButton.hidden = true;
    entryFeedback.textContent = "Buscando cartas físicas em português e inglês…";
    const params = new URLSearchParams({ name: name.length >= 2 ? name : "", collector_number: number, catalog_language: "auto", set_id: setId, page });
    try {
        const response = await fetch(`/api/cards/search?${params}`, { signal: controller.signal });
        const data = await response.json();
        if (requestId !== catalogRequest) return;
        if (!response.ok) throw new Error(data.error || "Não foi possível buscar as cartas.");
        lastPage = page;
        hasMore = Boolean(data.has_more);
        let cards = data.candidates;
        if (page === 1 && !cards.length && scanCandidates.length) cards = scanCandidates;
        showCardCandidates(cards, page > 1);
        moreButton.hidden = !hasMore;
        if (!lastCandidates.length) {
            entryFeedback.textContent = number
                ? "Nenhuma carta física com esse número. Confira o número impresso ou busque só pelo nome."
                : "Nenhuma carta física encontrada. Experimente o nome em inglês ou o número impresso.";
        } else if (page === 1 && data.total === 1 && number) {
            // Número impresso + única correspondência: a carta é essa; a imagem confirma.
            selectCard(cards[0], true);
        } else {
            entryFeedback.textContent = `${data.total || lastCandidates.length} carta(s). Toque na sua, conferindo imagem, coleção e número.`;
        }
    } catch (error) {
        if (requestId === catalogRequest && error.name !== "AbortError") {
            entryFeedback.textContent = error.message;
            moreButton.hidden = page === 1 || !hasMore;
        }
    }
}

function receiveScanResult(data, revision) {
    if (revision !== cardFormRevision || selectedCard || isSavingCard) {
        entryFeedback.textContent = "Foto lida; mantivemos a busca que você digitou.";
        return;
    }
    const detected = data.detected || {};
    if (detected.game && detected.game !== "pokemon") {
        entryFeedback.textContent = data.message || "O catálogo desse jogo ainda não está disponível.";
        return;
    }
    scanLanguage = [...cardLanguage.options].some((option) => option.value === detected.language) && detected.language !== "unknown"
        ? detected.language : null;
    const name = detected.printed_name || detected.search_name || "";
    const number = detected.collector_number || detected.local_id || "";
    if (!name && !number) {
        entryFeedback.textContent = data.message || "Não conseguimos ler a carta. Digite o nome ou o número impresso.";
        return;
    }
    queryInput.value = [name, number].filter(Boolean).join(" ");
    // A busca no catálogo filtra pelo total impresso; os candidatos do scanner são o plano B.
    searchCatalog(1, data.candidates || []);
}

function showCardCandidates(cards, append = false) {
    if (!append) { result.replaceChildren(); lastCandidates = []; }
    result.hidden = false;
    lastCandidates.push(...cards);
    let list = result.querySelector(".candidates");
    if (!list) { list = element("div", undefined, "candidates"); result.append(list); }
    for (const raw of cards) {
        const setId = raw.set_id || raw.id.slice(0, raw.id.lastIndexOf("-"));
        const set = catalogSets.get(setId);
        const card = { ...raw, set_id: setId, set_name: raw.set_name || set?.name, set_total: raw.set_total || set?.official };
        const candidate = element("button", undefined, "candidate");
        candidate.type = "button";
        candidate.dataset.cardId = card.id;
        if (card.image) {
            const image = document.createElement("img");
            image.src = `${card.image}/low.webp`; image.alt = ""; image.loading = "lazy";
            candidate.append(image);
        } else candidate.append(element("span", "Sem imagem", "image-placeholder"));
        candidate.append(element("span", card.name, "candidate-name"), element("span", cardLabel(card), "candidate-set"));
        candidate.addEventListener("click", () => {
            if (selectedCard?.id === card.id && result.classList.contains("has-selection") && !result.classList.contains("show-all")) {
                result.classList.add("show-all");
                return;
            }
            selectCard(card, false);
        });
        list.append(candidate);
    }
    let toggle = result.querySelector(".change-card");
    if (!toggle) {
        toggle = element("button", undefined, "change-card secondary-button compact-button");
        toggle.type = "button";
        toggle.addEventListener("click", () => { result.classList.toggle("show-all"); updateToggle(); });
        result.append(toggle);
    }
    updateToggle();
}

function updateToggle() {
    const toggle = result.querySelector(".change-card");
    if (!toggle) return;
    const others = lastCandidates.length - 1;
    toggle.hidden = !selectedCard || others < 1;
    // Carta escolhida e nada a trocar: o bloco de resultados não ocupa espaço.
    result.hidden = Boolean(selectedCard) && toggle.hidden;
    toggle.textContent = result.classList.contains("show-all") ? "Recolher opções" : `Não é esta? Ver ${others} outra(s)`;
    moreButton.hidden = !(hasMore && (!selectedCard || result.classList.contains("show-all")));
}

function renderChosenCard() {
    chosenImage.replaceChildren();
    if (selectedCard.image) {
        const image = document.createElement("img");
        image.src = `${selectedCard.image}/high.webp`; image.alt = selectedCard.name;
        chosenImage.append(image);
    } else chosenImage.append(element("div", "Sem imagem", "image-placeholder"));
    chosenIdentity.replaceChildren(element("h3", selectedCard.name), element("p", cardLabel(selectedCard)));
}

function selectCard(card, automatic) {
    if (isSavingCard) return;
    clearTimeout(searchTimer);
    searchController?.abort();
    catalogRequest += 1;
    selectedCard = { ...card };
    selectedVariant = null;
    result.classList.add("has-selection");
    result.classList.remove("show-all");
    result.querySelectorAll(".candidate").forEach((item) => item.classList.toggle("is-selected", item.dataset.cardId === card.id));
    updateToggle();
    // Idioma: o lido na foto; senão, o da última carta salva.
    setLanguage(scanLanguage || memory.get("language"));
    if (!conditionValue()) setCondition(memory.get("condition") || "NM");
    renderChosenCard();
    confirmation.hidden = false;
    addFeedback.replaceChildren();
    entryFeedback.textContent = automatic
        ? "Encontramos a carta pelo número impresso. Confira a imagem antes de adicionar."
        : "Confira a imagem, a coleção e o número antes de adicionar.";
    updateEntryControls();
    refreshPrices();
}

async function refreshPrices() {
    const card = selectedCard;
    const requestId = ++priceRequest;
    finishList.replaceChildren(element("p", "Consultando referências…", "price-note"));
    ligaPanel.replaceChildren();
    priceDetails.hidden = true;
    const params = new URLSearchParams({ catalog_language: card.language || "en" });
    try {
        const response = await fetch(`/api/cards/${encodeURIComponent(card.id)}/prices?${params}`);
        const data = await response.json();
        if (requestId !== priceRequest) return;
        if (data.card) {
            const metadata = data.card;
            Object.assign(selectedCard, { image: metadata.image || card.image, set_name: metadata.set_name || card.set_name,
                local_id: metadata.local_id || card.local_id, set_total: metadata.set_total || card.set_total });
            renderChosenCard();
        }
        if (data.liga) TCGPrices.liga(ligaPanel, data.liga);
        if (!response.ok && !data.card) throw new Error(data.error || data.message || "Referência indisponível.");
        const choose = (finish) => { selectedVariant = finish; updateEntryControls(); };
        const available = TCGPrices.finishOptions(finishList, data, selectedVariant, choose);
        // Um só acabamento possível: não há o que escolher.
        if (available.length === 1) {
            choose(available[0]);
            TCGPrices.finishOptions(finishList, data, selectedVariant, choose);
        }
        TCGPrices.sources(priceSources, data);
        priceDetails.hidden = !(data.quotes || []).length;
    } catch (error) {
        if (requestId === priceRequest) finishList.replaceChildren(element("p", `${error.message} Você ainda pode adicionar a carta.`, "price-note"));
    }
}

entryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isSavingCard || !selectedCard || !conditionValue()) return;
    const card = selectedCard;
    const payload = {
        game: "pokemon", provider: "tcgdex", external_id: card.id,
        catalog_language: card.language || "en", language: cardLanguage.value,
        collector_number: String(card.local_id || ""),
        condition: conditionValue(), variant: selectedVariant
    };
    isSavingCard = true; updateEntryControls();
    addButton.textContent = "Adicionando…";
    try {
        const response = await fetch("/api/portfolio/cards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Não foi possível adicionar a carta.");
        memory.set("language", payload.language);
        memory.set("condition", payload.condition);
        isSavingCard = false;
        // Pronto para a próxima carta, mantendo a coleção filtrada.
        scanLanguage = null;
        queryInput.value = "";
        result.replaceChildren(); lastCandidates = []; moreButton.hidden = true;
        clearSelection();
        const link = element("a", "Ver no portfólio");
        link.href = data.redirect_url;
        addFeedback.replaceChildren(element("strong", `✓ ${card.name} adicionada.`), " ", link);
        entryFeedback.textContent = "Próxima carta: fotografe ou digite o nome e o número.";
        queryInput.focus({ preventScroll: true });
        document.querySelector("#identify-heading").scrollIntoView({ block: "nearest" });
    } catch (error) {
        isSavingCard = false;
        addFeedback.textContent = error.message;
    } finally {
        addButton.textContent = "Adicionar ao portfólio";
        updateEntryControls();
    }
});

setLanguage(memory.get("language"));
updateEntryControls();
loadSets();