/* A mesma apresentação de preços no cadastro e no portfólio. */
window.TCGPrices = (() => {
    const version = 3;
    // Pokémon: normal/holo/reverse. Magic: nonfoil/foil/etched. Só aparecem os do jogo da carta.
    const labels = { normal: "Normal", holo: "Holográfica", reverse: "Holográfica reversa",
        nonfoil: "Normal (não foil)", foil: "Foil", etched: "Foil etched" };
    const finishes = ["normal", "holo", "reverse", "nonfoil", "foil", "etched"];
    const node = (tag, value, className) => {
        const element = document.createElement(tag);
        if (value !== undefined) element.textContent = value;
        if (className) element.className = className;
        return element;
    };
    const money = (value, currency = "BRL") => new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(value);
    const day = (value) => {
        if (!value) return null;
        const timestamp = typeof value === "number" && value < 1e12 ? value * 1000 : value;
        const parsed = new Date(timestamp);
        return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleDateString("pt-BR");
    };
    // Origem curta e sempre visível: fonte, valor original e data da fonte.
    const origin = (quote) => [money(quote.amount, quote.currency), quote.source, day(quote.updated_at)].filter(Boolean).join(" · ");

    /* Acabamentos disponíveis com o preço de cada um; escolher o acabamento é escolher a linha. */
    function finishOptions(list, data, selected, onSelect) {
        list.replaceChildren();
        const variants = data.card?.variants || {};
        const quotes = new Map((data.quotes || []).map((quote) => [quote.variant, quote]));
        const available = finishes.filter((finish) => variants[finish] !== false && (variants[finish] || quotes.has(finish)));
        for (const finish of available.length ? available : finishes.filter((finish) => quotes.has(finish))) {
            const quote = quotes.get(finish);
            const option = node("label", undefined, "finish-option");
            const input = node("input");
            input.type = "radio"; input.name = "variant"; input.value = finish; input.checked = finish === selected;
            input.addEventListener("change", () => onSelect(finish));
            const text = node("span", undefined, "finish-text");
            text.append(node("span", labels[finish], "finish-name"),
                node("span", quote ? origin(quote) : "Sem referência para este acabamento", "finish-origin"));
            const price = node("span", quote && typeof quote.estimated_brl === "number" ? `≈ ${money(quote.estimated_brl)}`
                : quote ? money(quote.amount, quote.currency) : "—", "finish-price");
            option.append(input, text, price);
            list.append(option);
        }
        if (!list.children.length) list.append(node("p", "Sem referência internacional para esta edição.", "price-note"));
        return available;
    }

    /* Detalhes expansíveis: tipo de preço, câmbio e link da fonte. */
    function sources(panel, data) {
        panel.replaceChildren();
        for (const quote of data.quotes || []) {
            const block = node("div", undefined, "source-row");
            block.append(node("p", `${labels[quote.variant] || quote.variant} · ${quote.source} ${quote.price_type === "trend" ? "(tendência)" : "(market price)"}`, "source-title"));
            const facts = [`Valor na fonte: ${money(quote.amount, quote.currency)}`];
            if (quote.updated_at) facts.push(`atualizado em ${day(quote.updated_at)}`);
            if (quote.exchange_rate) facts.push(`câmbio ${quote.exchange_rate.rate.toFixed(2).replace(".", ",")} de ${day(quote.exchange_rate.date + "T12:00:00")} (${quote.exchange_rate.source})`);
            block.append(node("p", facts.join(" · "), "price-note"));
            if (quote.source === "TCGplayer" && /^\d+$/.test(String(quote.product_id || ""))) {
                const link = node("a", "Abrir no TCGplayer", "price-source-link");
                link.href = `https://www.tcgplayer.com/product/${quote.product_id}`;
                link.target = "_blank"; link.rel = "noopener noreferrer";
                block.append(link);
            }
            panel.append(block);
        }
        panel.append(node("p", "Preço do exterior convertido em reais: não confirma o valor no Brasil, o idioma ou a conservação da sua cópia.", "price-note"));
    }

    /* A referência brasileira é conferida na própria Liga, na página da carta. */
    function liga(panel, link) {
        panel.replaceChildren();
        if (!link?.url) return;
        const anchor = node("a", link.label || "Conferir preço na Liga", "button-link liga-button");
        anchor.href = link.url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
        anchor.append(node("span", " ↗", "external-mark"));
        // A Liga Magic abre a página da carta com todas as edições: a nota indica qual escolher.
        panel.append(anchor, node("p", link.note || (link.exact
            ? `Abre a carta na Liga: edição ${link.edition_code} · nº ${link.number}.`
            : "Edição sem correspondência confirmada na Liga: confira a coleção e o número na busca."),
            link.exact || link.note ? "price-note" : "price-warning"));
    }

    function snapshot(panel, data) {
        panel.replaceChildren();
        if (data.stale) panel.append(node("p", data.refresh_message, "price-warning"));
        const list = node("div", undefined, "finish-list");
        finishOptions(list, { quotes: data.quotes, card: { variants: {} } }, null, () => {});
        list.querySelectorAll("input").forEach((input) => input.remove());
        const brazil = node("div", undefined, "liga-link");
        liga(brazil, data.liga);
        const details = node("details", undefined, "price-details");
        const sourcesPanel = node("div");
        sources(sourcesPanel, data);
        details.append(node("summary", "Origem dos valores"), sourcesPanel);
        panel.append(list, brazil);
        if ((data.quotes || []).length) panel.append(details);
        if (data.checked_at) panel.append(node("p", `Consulta: ${new Date(data.checked_at).toLocaleString("pt-BR")}.`, "price-note"));
    }

    return { version, labels, money, finishOptions, sources, liga, snapshot };
})();