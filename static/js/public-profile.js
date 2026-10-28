/* Perfil público: filtro por coleção e início de conversa. */
// Filtro por coleção compartilhada, sem recarregar a página.
document.querySelector(".folder-chips")?.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-folder]");
    if (!chip) return;
    for (const other of document.querySelectorAll(".chip-button")) other.setAttribute("aria-pressed", String(other === chip));
    for (const card of document.querySelectorAll(".public-card")) card.hidden = Boolean(chip.dataset.folder) && card.dataset.folder !== chip.dataset.folder;
});
// Abre (ou reabre) a conversa com este perfil e vai para ela.
document.querySelector("[data-start-chat]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const feedback = document.querySelector("#chat-feedback");
    button.disabled = true;
    feedback.textContent = "";
    try {
        const response = await fetch("/api/chat/conversations", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ handle: button.dataset.startChat })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Não foi possível abrir a conversa.");
        window.location.assign(data.url);
    } catch (error) {
        feedback.textContent = error.message;
        button.disabled = false;
    }
});