const cameraInput =
    document.querySelector("#card-camera");

const preview =
    document.querySelector("#preview");

const previewContainer =
    document.querySelector("#preview-container");

const form =
    document.querySelector("#scan-form");

const scanButton =
    document.querySelector("#scan-button");

const result =
    document.querySelector("#result");


cameraInput.addEventListener("change", () => {

    const file = cameraInput.files[0];

    if (!file) {
        return;
    }

    preview.src = URL.createObjectURL(file);

    previewContainer.classList.add("visible");

    scanButton.disabled = false;
});


form.addEventListener("submit", async (event) => {

    event.preventDefault();

    const file = cameraInput.files[0];

    if (!file) {
        return;
    }

    scanButton.disabled = true;

    scanButton.textContent =
        "Identificando...";

    result.innerHTML =
        "<p>Analisando carta...</p>";


    const formData = new FormData();

    formData.append(
        "card",
        file
    );


    try {

        const response = await fetch(
            "/scan",
            {
                method: "POST",
                body: formData
            }
        );

        const data = await response.json();

        console.log(data);

        if (!response.ok) {
            throw new Error(
                data.error || "Erro desconhecido"
            );
        }

        showResult(data);

    } catch (error) {

        result.innerHTML = `
            <p>
                Erro: ${error.message}
            </p>
        `;

    } finally {

        scanButton.disabled = false;

        scanButton.textContent =
            "Identificar carta";
    }

});


function showResult(data) {

    const detected = data.detected;

    let html = `
    <h2>Carta identificada</h2>

    <p>
        <strong>TCG:</strong>
        ${detected.game}
    </p>

    <p>
        <strong>Nome:</strong>
        ${detected.printed_name ?? "Não identificado"}
    </p>

    <p>
        <strong>Número:</strong>
        ${detected.collector_number ?? "Não identificado"}
    </p>

    <p>
        <strong>Idioma:</strong>
        ${detected.language}
    </p>
`;
    if (data.status === "retry") {

        result.innerHTML = `
        <div class="scan-message">

            <h2>
                Vamos tentar novamente
            </h2>

            <p>
                ${data.message}
            </p>

        </div>
    `;

        return;
    }

    if (data.status === "game_detected") {

        result.innerHTML = `
        <div class="scan-message">

            <h2>
                TCG identificado!
            </h2>

            <p>
                ${data.message}
            </p>

            <p>
                <strong>Carta:</strong>
                ${data.detected.printed_name
            ?? "Nome não identificado"
            }
            </p>

            <p>
                <strong>Idioma:</strong>
                ${data.detected.language}
            </p>

        </div>
    `;

        return;
    }

    if (data.status === "ok") {

        let html = `
        <h2>
            Encontramos sua carta
        </h2>

        <div class="candidates">
    `;


        for (const card of data.candidates) {

            const imageUrl =
                card.image
                    ? `${card.image}/high.webp`
                    : "";


            html += `
            <div class="candidate">

                ${imageUrl
                    ? `
                            <img
                                src="${imageUrl}"
                                alt="${card.name}"
                            >
                        `
                    : ""
                }

                <h3>
                    ${card.name}
                </h3>

                <p>
                    #${card.local_id}
                </p>

                <button
                    type="button"
                    class="confirm-card"
                    data-card-id="${card.id}"
                >
                    É esta
                </button>

            </div>
        `;
        }


        html += `
        </div>

        <button
            type="button"
            onclick="location.reload()"
        >
            Nenhuma dessas
        </button>
    `;


        result.innerHTML = html;
    }

    if (data.candidates.length > 0) {

        html += `
            <h2>
                Possíveis cartas
            </h2>
        `;

        for (const card of data.candidates) {

            const imageUrl =
                card.image
                    ? `${card.image}/low.webp`
                    : "";

            html += `
                <div class="candidate">

                    ${imageUrl
                    ?
                    `
                        <img
                            src="${imageUrl}"
                            alt="${card.name}"
                        >
                        `
                    :
                    ""
                }

                    <h3>
                        ${card.name}
                    </h3>

                    <p>
                        #${card.local_id}
                    </p>

                    <p>
                        Match:
                        ${card.score}%
                    </p>

                </div>
            `;
        }

    } else {

        html += `
            <p>
                Nenhuma carta correspondente
                encontrada na base.
            </p>
        `;

    }

    result.innerHTML = html;
}