// Convierte cualquier <select multiple class="js-tags-select"> en un buscador
// con "cajitas" (chips) para las opciones elegidas: se escribe para filtrar,
// se hace click en una opción de la lista para agregarla, y aparece como chip
// abajo (con una x para sacarla). El <select> original se oculta pero sigue
// existiendo y sincronizado, así el formulario se manda exactamente igual.
(function () {
    function setup(select) {
        if (select.dataset.tagsInit) return;
        select.dataset.tagsInit = "1";
        select.classList.add("d-none");

        const wrapper = document.createElement("div");
        wrapper.className = "position-relative";

        const input = document.createElement("input");
        input.type = "text";
        input.className = "form-control";
        input.autocomplete = "off";
        input.placeholder = "Escribí para buscar y hacé click para agregar...";

        const dropdown = document.createElement("div");
        dropdown.className = "list-group position-absolute w-100 shadow-sm";
        dropdown.style.zIndex = 1000;
        dropdown.style.maxHeight = "240px";
        dropdown.style.overflowY = "auto";
        dropdown.style.display = "none";

        const chips = document.createElement("div");
        chips.className = "d-flex flex-wrap gap-2 mt-2";

        wrapper.appendChild(input);
        wrapper.appendChild(dropdown);
        wrapper.appendChild(chips);
        select.after(wrapper);

        const opciones = () => Array.from(select.options);

        function renderChips() {
            chips.innerHTML = "";
            opciones().filter((o) => o.selected).forEach((o) => {
                const chip = document.createElement("span");
                chip.className = "badge text-bg-primary d-flex align-items-center gap-2 py-2 px-3 fs-6 fw-normal";
                chip.textContent = o.textContent;
                const btnX = document.createElement("button");
                btnX.type = "button";
                btnX.className = "btn-close btn-close-white";
                btnX.style.fontSize = "0.6rem";
                btnX.setAttribute("aria-label", "Quitar " + o.textContent);
                btnX.addEventListener("click", () => {
                    o.selected = false;
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                    renderChips();
                    renderDropdown();
                });
                chip.appendChild(btnX);
                chips.appendChild(chip);
            });
        }

        function renderDropdown() {
            const q = input.value.trim().toLowerCase();
            dropdown.innerHTML = "";
            const disponibles = opciones().filter(
                (o) => !o.selected && (!q || o.textContent.toLowerCase().includes(q))
            );
            if (disponibles.length === 0) {
                dropdown.style.display = "none";
                return;
            }
            disponibles.slice(0, 50).forEach((o) => {
                const item = document.createElement("button");
                item.type = "button";
                item.className = "list-group-item list-group-item-action py-1";
                item.textContent = o.textContent;
                // mousedown (no click) para que dispare ANTES del blur del input
                item.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    o.selected = true;
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                    input.value = "";
                    renderChips();
                    renderDropdown();
                    input.focus();
                });
                dropdown.appendChild(item);
            });
            dropdown.style.display = "";
        }

        input.addEventListener("focus", renderDropdown);
        input.addEventListener("input", renderDropdown);
        input.addEventListener("blur", () => {
            setTimeout(() => { dropdown.style.display = "none"; }, 150);
        });

        renderChips();
    }

    function init(root) {
        (root || document).querySelectorAll("select.js-tags-select").forEach(setup);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => init());
    } else {
        init();
    }

    window.initTagsSelects = init;
})();
