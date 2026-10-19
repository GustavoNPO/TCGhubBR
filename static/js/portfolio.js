(() => {
    const dataElement = document.querySelector("#portfolio-data");
    if (!dataElement) return;
    const { cards, folders } = JSON.parse(dataElement.textContent);
    const cardById = new Map(cards.map((card) => [card.id, card]));
    const grid = document.querySelector("#inventory-grid");
    const cells = new Map([...grid.querySelectorAll(".inventory-cell")].map((cell) => [cell.dataset.cardId, cell]));
    const details = document.querySelector("#selected-card");
    const folderFilter = document.querySelector("#folder-filter");
    const search = document.querySelector("#inventory-search");
    const sort = document.querySelector("#inventory-sort");
    const feedback = document.querySelector("#portfolio-feedback");
    const selectAll = document.querySelector("#select-all");
    const selection = new Set();
    const prices = new Map();
    const fetchedAt = new Map();
    const priceRequests = new Map();
    let visibleCards = [];
    let selectedId = null;
    let busy = false;
    let draggedId = null;
    let pendingDelete = null;
    let editingFolder = null;

    const text = (tag, value, className) => {
        const node = document.createElement(tag);
        node.textContent = value;
        if (className) node.className = className;
        return node;
    };
    const normalize = (value) => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");

    function rememberView() {
        const url = new URL(window.location.href);
        for (const [key, value] of [["folder", folderFilter.value], ["q", search.value], ["sort", sort.value], ["card", selectedId || ""]]) {
            if (value) url.searchParams.set(key, value);
            else url.searchParams.delete(key);
        }
        window.history.replaceState(null, "", url);
    }

    function updateSelection() {
        document.querySelector("#bulk-bar").hidden = selection.size === 0;
        document.querySelector("#selection-count").textContent = `${selection.size} selecionada(s)`;
        const checked = pageCards.filter((card) => selection.has(card.id)).length;
        selectAll.checked = pageCards.length > 0 && checked === pageCards.length;
        selectAll.indeterminate = checked > 0 && checked < pageCards.length;
        selectAll.disabled = busy || pageCards.length === 0;
    }       

    function updateOrderControls() {
        const index = visibleCards.findIndex((card) => card.id === selectedId);
        const earlier = details.querySelector('[data-action="earlier"]');
        const later = details.querySelector('[data-action="later"]');
        if (earlier) earlier.disabled = busy || sort.value !== "custom" || index <= 0;
        if (later) later.disabled = busy || sort.value !== "custom" || index < 0 || index === visibleCards.length - 1;
    }

    function renderInventory(focusId = null) {
        const query = normalize(search.value.trim());
        visibleCards = cards.filter((card) => (
            folderFilter.value === "all" || (folderFilter.value === "none" ? !card.folder_id : card.folder_id === folderFilter.value)
        ) && normalize(`${card.name} ${card.set_name || ""} ${card.collector_number || ""}`).includes(query));
        visibleCards.sort((a, b) => {
            if (sort.value === "name") return a.name.localeCompare(b.name, "pt-BR") || a.position - b.position;
            if (sort.value === "set") return (a.set_name || "").localeCompare(b.set_name || "", "pt-BR") || a.position - b.position;
            if (sort.value === "recent") return (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || b.position - a.position;
            return a.position - b.position;
        });

        grid.style.setProperty("--grid-cols", gridSize);

        const pageCount = Math.max(1, Math.ceil(visibleCards.length / pageSize));
        const focusIndex = visibleCards.findIndex((card) => card.id === focusId);
        if (focusIndex >= 0) page = Math.floor(focusIndex / pageSize);
        page = Math.min(Math.max(page, 0), pageCount - 1);
        pageCards = visibleCards.slice(page * pageSize, (page + 1) * pageSize);

        for (const cell of cells.values()) cell.hidden = true;
        for (const card of pageCards) {
            const cell = cells.get(card.id);
            cell.hidden = false;
            cell.draggable = !busy && sort.value === "custom";
            grid.append(cell);
        }
        grid.hidden = pageCards.length === 0;

        pager.hidden = pageCount <= 1;
        pageLabel.textContent = `Página ${page + 1} de ${pageCount}`;
        prevButton.disabled = busy || page === 0;
        nextButton.disabled = busy || page >= pageCount - 1;

        document.querySelector("#inventory-empty").hidden = visibleCards.length > 0;
        document.querySelector("#inventory-count").textContent = `${visibleCards.length} de ${cards.length} carta(s)`;
        document.querySelector("#order-hint").textContent = sort.value === "custom"
            ? "Arraste as cartas para organizar, ou use as setas nos detalhes."
            : "Selecione Minha ordem para reorganizar as cartas.";
        const isFolder = folders.some((folder) => folder.id === folderFilter.value);
        document.querySelector("#rename-folder").hidden = !isFolder;
        document.querySelector("#delete-folder").hidden = !isFolder;
        if (!pageCards.some((card) => card.id === selectedId)) {
            selectCard(pageCards.some((card) => card.id === focusId) ? focusId : pageCards[0]?.id || null);
        }
        updateSelection();
        updateOrderControls();
        rememberView();
    }

    const SIZE_KEY = "portfolio-grid-size";
    const readSize = () => {
        try { return localStorage.getItem(SIZE_KEY) === "4" ? 4 : 3; } catch { return 3; }
    };
    let gridSize = readSize();      // 3 ou 4
    let pageSize = gridSize ** 2;   // 9 ou 16
    let page = 0;
    let pageCards = [];

    const pager = document.createElement("nav");
    pager.className = "pagination";
    pager.setAttribute("aria-label", "Paginação do inventário");
    const prevButton = text("button", "‹ Anterior", "secondary-button compact-button");
    const nextButton = text("button", "Próxima ›", "secondary-button compact-button");
    prevButton.type = nextButton.type = "button";
    const pageLabel = text("span", "", "page-label");
    pageLabel.setAttribute("aria-live", "polite");
    pager.append(prevButton, pageLabel, nextButton);
    grid.after(pager);

    
    const sizeLabel = document.createElement("label");
    sizeLabel.className = "grid-size";
    sizeLabel.append("Tamanho do grid ");
    const sizeSelect = document.createElement("select");
    sizeSelect.setAttribute("aria-label", "Tamanho do grid");
    for (const [value, label] of [["3", "3 × 3 (9 por página)"], ["4", "4 × 4 (16 por página)"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        sizeSelect.append(option);
    }
    sizeSelect.value = String(gridSize);
    sizeLabel.append(sizeSelect);
    grid.before(sizeLabel);

    sizeSelect.addEventListener("change", () => {
        if (busy) return;
        gridSize = Number(sizeSelect.value) === 4 ? 4 : 3;
        pageSize = gridSize ** 2;
        try { localStorage.setItem(SIZE_KEY, String(gridSize)); } catch {}
        renderInventory(selectedId); // mantém a carta selecionada visível
    });

    function renderPrices(data) {
        const panel = details.querySelector(".market-content");
        if (panel) TCGPrices.snapshot(panel, data);
    }

    async function loadPrices(id, force = false) {
        const stored = prices.get(id) || cardById.get(id)?.market_prices;
        const saved = stored?.pricing_version === TCGPrices.version ? stored : null;
        if (saved && selectedId === id) renderPrices(saved);
        if (!force && saved && prices.has(id) && Date.now() - fetchedAt.get(id) < (saved.status === "ok" ? 3600000 : 60000)) return;
        if (priceRequests.has(id)) return;
        const button = details.querySelector('[data-action="refresh"]');
        if (selectedId === id && button) { button.disabled = true; button.textContent = "Consultando…"; }
        const request = (async () => {
            try {
                const response = await fetch(`/api/portfolio/cards/${encodeURIComponent(id)}/prices`, {
                    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force })
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || "Preço indisponível.");
                prices.set(id, result);
                fetchedAt.set(id, Date.now());
                if (selectedId === id) renderPrices(result);
            } catch (error) {
                if (selectedId === id) {
                    const panel = details.querySelector(".market-content");
                    if (!saved) panel.replaceChildren(text("p", error.message));
                    else panel.prepend(text("p", "Não foi possível atualizar. Exibindo a referência salva.", "price-warning"));
                }
            } finally {
                priceRequests.delete(id);
                if (selectedId === id) {
                    const refresh = details.querySelector('[data-action="refresh"]');
                    refresh.disabled = busy;
                    refresh.textContent = "Atualizar";
                }
            }
        })();
        priceRequests.set(id, request);
        await request;
    }

    function selectCard(id, scroll = false) {
        selectedId = id;
        for (const [cardId, cell] of cells) {
            const button = cell.querySelector(".inventory-item");
            button.classList.toggle("selected", cardId === id);
            button.setAttribute("aria-pressed", String(cardId === id));
        }
        details.hidden = !id;
        if (!id) { details.replaceChildren(); return; }
        const button = cells.get(id).querySelector(".inventory-item");
        details.replaceChildren(document.getElementById(button.dataset.detailsId).content.cloneNode(true));
        updateOrderControls();
        loadPrices(id);
        if (priceRequests.has(id)) {
            const refresh = details.querySelector('[data-action="refresh"]');
            refresh.disabled = true;
            refresh.textContent = "Consultando…";
        }
        rememberView();
        if (scroll && window.matchMedia("(max-width: 799px)").matches) {
            details.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        }
    }

    async function mutation(url, method, payload) {
        if (busy) return false;
        busy = true;
        feedback.textContent = "Salvando alterações…";
        document.querySelectorAll("main button, main input, main select").forEach((control) => {
            control.dataset.wasDisabled = String(control.disabled);
            control.disabled = true;
        });
        for (const cell of cells.values()) cell.draggable = false;
        try {
            const response = await fetch(url, {
                method, headers: { "Content-Type": "application/json" },
                ...(payload !== undefined ? { body: JSON.stringify(payload) } : {})
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Não foi possível salvar.");
            feedback.textContent = "Alterações salvas.";
            return true;
        } catch (error) {
            feedback.textContent = error.message;
            document.querySelector("#folder-feedback").textContent = error.message;
            document.querySelector("#confirm-feedback").textContent = error.message;
            return false;
        } finally {
            busy = false;
            document.querySelectorAll("[data-was-disabled]").forEach((control) => {
                control.disabled = control.dataset.wasDisabled === "true";
                delete control.dataset.wasDisabled;
            });
            renderInventory();
            const refresh = details.querySelector('[data-action="refresh"]');
            if (refresh) refresh.disabled = priceRequests.has(selectedId);
        }
    }

    async function reorder(ids, focusId = null) {
        if (sort.value !== "custom" || busy) return;
        if (ids.length > 450) { feedback.textContent = "Filtre uma pasta ou busca com até 450 cartas para reorganizar."; return; }
        if (await mutation("/api/portfolio/cards/bulk", "POST", { action: "reorder", card_ids: ids })) {
            const positions = ids.map((id) => cardById.get(id).position).sort((a, b) => a - b);
            ids.forEach((id, index) => { cardById.get(id).position = positions[index]; });
            renderInventory(focusId);
        }
    }   

    function askDelete(title, message, operation) {
        pendingDelete = operation;
        document.querySelector("#confirm-title").textContent = title;
        document.querySelector("#confirm-message").textContent = message;
        document.querySelector("#confirm-feedback").textContent = "";
        document.querySelector("#confirm-dialog").showModal();
        document.querySelector("#confirm-cancel").focus();
    }

    function deleteCards(ids) {
        askDelete(ids.length === 1 ? "Excluir esta cópia?" : `Excluir ${ids.length} cartas?`,
            "As cópias selecionadas serão removidas do seu portfólio. Esta ação não pode ser desfeita.", async () => {
                if (await mutation("/api/portfolio/cards/bulk", "POST", { action: "delete", card_ids: ids })) {
                    for (const id of ids) {
                        cells.get(id).remove(); cells.delete(id); cardById.delete(id); selection.delete(id);
                        const index = cards.findIndex((card) => card.id === id);
                        cards.splice(index, 1);
                    }
                    document.querySelector("#confirm-dialog").close();
                    document.querySelector(".portfolio-header p").textContent = `${cards.length} carta(s) no inventário`;
                    renderInventory();
                    feedback.focus();
                }
            });
    }

    async function moveCards(ids, folderId) {
        if (await mutation("/api/portfolio/cards/bulk", "POST", { action: "move", card_ids: ids, folder_id: folderId || null })) {
            for (const id of ids) {
                cardById.get(id).folder_id = folderId || null;
                const button = cells.get(id).querySelector(".inventory-item");
                const template = document.getElementById(button.dataset.detailsId);
                template.content.querySelector('[data-role="card-folder"]').value = folderId;
                cells.get(id).querySelector(".select-card").checked = false;
                selection.delete(id);
            }
            if (ids.includes(selectedId)) details.querySelector('[data-role="card-folder"]').value = folderId;
            renderInventory();
        }
    }

    grid.addEventListener("click", (event) => {
        const button = event.target.closest(".inventory-item");
        if (button && !busy) selectCard(button.dataset.cardId, true);
    });
    grid.addEventListener("change", (event) => {
        if (!event.target.matches(".select-card") || busy) return;
        if (event.target.checked) selection.add(event.target.value);
        else selection.delete(event.target.value);
        updateSelection();
    });
    grid.addEventListener("dragstart", (event) => {
        const cell = event.target.closest(".inventory-cell");
        if (busy || sort.value !== "custom" || !cell || event.target.matches("input")) { event.preventDefault(); return; }
        draggedId = cell.dataset.cardId;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", draggedId);
        cell.classList.add("dragging");
    });
    grid.addEventListener("dragover", (event) => {
        if (draggedId && !busy && sort.value === "custom") { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }
    });
    grid.addEventListener("drop", (event) => {
        event.preventDefault();
        const target = event.target.closest(".inventory-cell")?.dataset.cardId;
        if (!draggedId || !target || draggedId === target) return;
        const ids = visibleCards.map((card) => card.id);
        const from = ids.indexOf(draggedId);
        const to = ids.indexOf(target);
        if (from < 0 || to < 0) return;
        ids.splice(from, 1); ids.splice(to, 0, draggedId);
        const moved = draggedId;
        draggedId = null;
        reorder(ids, moved);
    });

    grid.addEventListener("dragend", () => { draggedId = null; for (const cell of cells.values()) cell.classList.remove("dragging"); });
    details.addEventListener("click", (event) => {
        const action = event.target.closest("[data-action]")?.dataset.action;
        if (!action || busy || !selectedId) return;
        if (action === "refresh") loadPrices(selectedId, true);
        if (action === "delete") deleteCards([selectedId]);
        if (action === "move") moveCards([selectedId], details.querySelector('[data-role="card-folder"]').value);
        if (action === "earlier" || action === "later") {
            const ids = visibleCards.map((card) => card.id);
            const from = ids.indexOf(selectedId);
            const to = from + (action === "earlier" ? -1 : 1);
            if (to < 0 || to >= ids.length) return;
            [ids[from], ids[to]] = [ids[to], ids[from]];
            reorder(ids, selectedId);
        }
    });
    for (const input of [folderFilter, sort, search]) input.addEventListener("input", () => {
        if (busy) return;
        selection.clear();
        page = 0;
        for (const cell of cells.values()) cell.querySelector(".select-card").checked = false;
        renderInventory();
    });
    selectAll.addEventListener("change", () => {
        for (const card of pageCards) {
            if (selectAll.checked) selection.add(card.id); else selection.delete(card.id);
            cells.get(card.id).querySelector(".select-card").checked = selectAll.checked;
        }
        updateSelection();
    });

prevButton.addEventListener("click", () => { if (!busy) { page -= 1; renderInventory(); } });
nextButton.addEventListener("click", () => { if (!busy) { page += 1; renderInventory(); } });       

    document.querySelector("#clear-selection").addEventListener("click", () => {
        selection.clear(); for (const cell of cells.values()) cell.querySelector(".select-card").checked = false; updateSelection();
    });
    document.querySelector("#bulk-move").addEventListener("click", () => moveCards([...selection], document.querySelector("#bulk-folder").value));
    document.querySelector("#bulk-delete").addEventListener("click", () => deleteCards([...selection]));
    document.querySelector("#confirm-cancel").addEventListener("click", () => document.querySelector("#confirm-dialog").close());
    document.querySelector("#confirm-delete").addEventListener("click", () => { if (pendingDelete && !busy) pendingDelete(); });
    document.querySelector("#confirm-dialog").addEventListener("close", () => { pendingDelete = null; });

    function editFolder(id = null) {
        editingFolder = id;
        document.querySelector("#folder-dialog-title").textContent = id ? "Renomear pasta" : "Nova pasta";
        document.querySelector("#folder-name").value = folders.find((folder) => folder.id === id)?.name || "";
        document.querySelector("#folder-feedback").textContent = "";
        document.querySelector("#folder-dialog").showModal();
    }
    document.querySelector("#new-folder").addEventListener("click", () => editFolder());
    document.querySelector("#rename-folder").addEventListener("click", () => editFolder(folderFilter.value));
    document.querySelector("#folder-cancel").addEventListener("click", () => document.querySelector("#folder-dialog").close());
    document.querySelector("#folder-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.target;
        if (!form.reportValidity()) return;
        const success = await mutation(editingFolder ? `/api/portfolio/folders/${encodeURIComponent(editingFolder)}` : "/api/portfolio/folders",
            editingFolder ? "PATCH" : "POST", { name: document.querySelector("#folder-name").value });
        if (success) { rememberView(); window.location.reload(); }
    });
    document.querySelector("#delete-folder").addEventListener("click", () => {
        const folder = folders.find((entry) => entry.id === folderFilter.value);
        if (!folder) return;
        askDelete("Excluir pasta?", `A pasta “${folder.name}” será excluída. Suas cartas serão mantidas em Sem pasta.`, async () => {
            if (await mutation(`/api/portfolio/folders/${encodeURIComponent(folder.id)}`, "DELETE")) {
                folderFilter.value = "none"; rememberView(); window.location.reload();
            }
        });
    });
    for (const dialog of document.querySelectorAll("dialog")) dialog.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });

    const view = new URL(window.location.href).searchParams;
    if ([...folderFilter.options].some((option) => option.value === view.get("folder"))) folderFilter.value = view.get("folder");
    if ([...sort.options].some((option) => option.value === view.get("sort"))) sort.value = view.get("sort");
    search.value = view.get("q") || "";
    const initialId = view.get("card");
    renderInventory(initialId);
})();