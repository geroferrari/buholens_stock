// Convierte cualquier <select data-searchable> en un buscador: se tipea para
// filtrar las opciones (sin importar mayúsculas ni acentos) y se elige de la
// lista. El <select> original queda oculto pero sigue siendo lo que se envía al
// guardar el formulario, así funciona sin tocar el backend.
//
// Pensado para listas medianas donde el <select> plano se hace incómodo, ej:
// obras sociales, donde tipear "osde" muestra "OSDE", "OSDE 210", "OSDE 410".
(function () {
    function normalizar(texto) {
        return (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
    }

    function mejorar(select) {
        if (select.dataset.searchableListo) return;
        select.dataset.searchableListo = "1";

        const opciones = Array.from(select.options).map((o) => ({
            value: o.value, text: o.text, vacia: o.value === "",
        }));

        const wrap = document.createElement("div");
        wrap.className = "position-relative";
        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);
        select.classList.add("d-none");

        const input = document.createElement("input");
        input.type = "text";
        input.className = select.className.replace("d-none", "").trim() || "form-control";
        input.classList.remove("d-none");
        input.setAttribute("autocomplete", "off");
        input.placeholder = "Buscar…";
        if (select.disabled) input.disabled = true;
        wrap.appendChild(input);

        const lista = document.createElement("div");
        lista.className = "list-group position-absolute w-100 shadow-sm";
        lista.style.cssText = "z-index:1050; max-height:240px; overflow-y:auto; display:none;";
        wrap.appendChild(lista);

        function textoSeleccionado() {
            const sel = opciones.find((o) => o.value === select.value);
            return sel && !sel.vacia ? sel.text : "";
        }
        input.value = textoSeleccionado();

        function render(filtro) {
            const q = normalizar(filtro);
            lista.innerHTML = "";
            opciones
                .filter((o) => !o.vacia && (!q || normalizar(o.text).includes(q)))
                .forEach((o) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "list-group-item list-group-item-action py-1";
                    btn.textContent = o.text;
                    btn.addEventListener("mousedown", (e) => {
                        e.preventDefault(); // que no dispare el blur antes del click
                        select.value = o.value;
                        select.dispatchEvent(new Event("change", { bubbles: true }));
                        input.value = o.text;
                        lista.style.display = "none";
                    });
                    lista.appendChild(btn);
                });
            // Opción para limpiar la selección, si el campo lo permite.
            if (opciones.some((o) => o.vacia)) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "list-group-item list-group-item-action py-1 text-muted fst-italic";
                btn.textContent = "— sin obra social —";
                btn.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    select.value = "";
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                    input.value = "";
                    lista.style.display = "none";
                });
                lista.appendChild(btn);
            }
            lista.style.display = lista.children.length ? "" : "none";
        }

        input.addEventListener("focus", () => render(""));
        input.addEventListener("input", () => render(input.value));
        input.addEventListener("blur", () => {
            setTimeout(() => { lista.style.display = "none"; }, 150);
            // Si quedó texto que no matchea ninguna opción, se restaura la selección real.
            if (input.value !== textoSeleccionado()) input.value = textoSeleccionado();
        });
    }

    function init(scope) {
        (scope || document).querySelectorAll("select[data-searchable]").forEach(mejorar);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => init());
    } else {
        init();
    }
    window.initSearchableSelects = init;
})();
