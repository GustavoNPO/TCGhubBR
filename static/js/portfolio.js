const inventoryItems = document.querySelectorAll(".inventory-item");
const selectedCard = document.querySelector("#selected-card");

inventoryItems.forEach((item) => {
    item.addEventListener("click", () => {
        const details = document.getElementById(item.dataset.detailsId);
        inventoryItems.forEach((other) => {
            other.classList.remove("selected");
            other.setAttribute("aria-pressed", "false");
        });
        item.classList.add("selected");
        item.setAttribute("aria-pressed", "true");
        selectedCard.replaceChildren(details.content.cloneNode(true));
    });
});