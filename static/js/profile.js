
/* Edição do perfil público e da visibilidade do portfólio. */
(() => {
    const form = document.querySelector("#profile-form");
    const feedback = document.querySelector("#profile-feedback");
    const handleInput = document.querySelector("#profile-handle");
    const link = document.querySelector("#public-link");
    const save = document.querySelector("#profile-save");

    // O @ é normalizado enquanto se digita: o que aparece é o que será salvo.
    handleInput.addEventListener("input", () => {
        const clean = handleInput.value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
            .replace(/^@/, "").replace(/[^a-z0-9_]/g, "_").slice(0, 24);
        if (clean !== handleInput.value) handleInput.value = clean;
    });

    document.querySelector("#copy-link").addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(link.href);
            feedback.textContent = "Link copiado.";
        } catch {
            feedback.textContent = "Não foi possível copiar. Selecione o link e copie manualmente.";
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        // Sublinhados repetidos ou nas pontas vêm da digitação ("Lucas Zóser!" → "lucas_zoser").
        handleInput.value = handleInput.value.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
        save.disabled = true;
        feedback.textContent = "Salvando…";
        const payload = {
            display_name: document.querySelector("#profile-name").value,
            handle: handleInput.value,
            bio: document.querySelector("#profile-bio").value,
            profile_visibility: document.querySelector("#profile-public").checked ? "public" : "private",
            portfolio_visibility: document.querySelector("#portfolio-public").checked ? "public" : "private"
        };
        try {
            const response = await fetch("/api/me/profile", {
                method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Não foi possível salvar.");
            link.href = data.public_url; link.textContent = data.public_url;
            document.querySelector(".profile-heading h1").textContent = data.profile.display_name;
            feedback.textContent = data.profile.profile_visibility === "public"
                ? "Perfil salvo. Qualquer pessoa com o link pode vê-lo."
                : "Perfil salvo. Ele continua privado: só você vê a página pública.";
        } catch (error) {
            feedback.textContent = error.message;
        } finally {
            save.disabled = false;
        }
    });
})();
