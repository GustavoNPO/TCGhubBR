/* Sessão em todas as páginas: sair e voltar ao login quando a sessão expira. */
(() => {
    const nativeFetch = window.fetch.bind(window);

    // Uma chamada da API que responde 401 significa sessão expirada ou encerrada
    // em outro dispositivo: leva ao login e volta para a mesma página depois.
    window.fetch = async (...args) => {
        const response = await nativeFetch(...args);
        if (response.status === 401) {
            const target = new URL(typeof args[0] === "string" ? args[0] : args[0].url, window.location.href);
            if (target.origin === window.location.origin && !target.pathname.startsWith("/api/auth/")) {
                window.location.assign(`/entrar?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
            }
        }
        return response;
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-logout]");
        if (!button) return;
        button.disabled = true;
        try {
            const response = await nativeFetch("/api/auth/logout", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ everywhere: button.dataset.logout === "everywhere" })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Não foi possível sair.");
            window.location.assign(data.redirect_url || "/entrar");
        } catch (error) {
            button.disabled = false;
            const status = document.querySelector("[data-session-status]");
            if (status) status.textContent = error.message;
        }
    });
})();