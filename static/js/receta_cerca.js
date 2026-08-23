// Si el ojo tiene graduación de lejos Y adición cargada, se asume aumento
// (présbicia) y se autocompleta Cerca a partir de Lejos: la esfera de cerca
// es la de lejos + adición, y cilindro/eje se mantienen iguales. Si no hay
// adición cargada, no se toca nada (puede ser una receta sin aumento).
//
// Expone initRecetaCercaAutocalc(root) para poder bindearlo tanto en la carga
// normal de la página como en un formulario inyectado por AJAX (ej: el popup
// de "cargar receta" del punto de venta), donde los campos no existen todavía
// en el momento en que se carga este script.
(function () {
    function actualizarCerca(ojo, scope) {
        const adicionInput = scope.querySelector(`#id_lejos_${ojo}_adicion`);
        const adicion = parseFloat(adicionInput.value);
        if (isNaN(adicion)) return;

        const esferaLejos = parseFloat(scope.querySelector(`#id_lejos_${ojo}_esfera`).value);
        if (isNaN(esferaLejos)) return;

        scope.querySelector(`#id_cerca_${ojo}_esfera`).value = (esferaLejos + adicion).toFixed(2);
        scope.querySelector(`#id_cerca_${ojo}_cilindro`).value = scope.querySelector(`#id_lejos_${ojo}_cilindro`).value;
        scope.querySelector(`#id_cerca_${ojo}_eje`).value = scope.querySelector(`#id_lejos_${ojo}_eje`).value;
    }

    // Muestra/oculta el campo "marca de los lentes de contacto" según el
    // checkbox "¿es para lentes de contacto?". Funciona tanto en el formulario
    // de receta como en el popup de carga del punto de venta.
    function bindLentesContacto(scope) {
        const chk = scope.querySelector('#id_es_lentes_contacto');
        const wrap = scope.querySelector('#wrap-marca-lentes-contacto');
        if (!chk || !wrap || chk.dataset.lcBound) return;
        chk.dataset.lcBound = "1";
        const sync = () => { wrap.classList.toggle('d-none', !chk.checked); };
        chk.addEventListener('change', sync);
        sync();  // estado inicial (ej: al editar una receta ya marcada)
    }

    function bind(root) {
        const scope = root || document;
        ['od', 'oi'].forEach((ojo) => {
            ['esfera', 'cilindro', 'eje', 'adicion'].forEach((campo) => {
                const input = scope.querySelector(`#id_lejos_${ojo}_${campo}`);
                if (input && !input.dataset.cercaBound) {
                    input.dataset.cercaBound = "1";
                    input.addEventListener('input', () => actualizarCerca(ojo, scope));
                }
            });
        });
        bindLentesContacto(scope);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => bind());
    } else {
        bind();
    }
    window.initRecetaCercaAutocalc = bind;
})();
