// Punto de venta (POS). Extraído del inline de templates/sales/pos.html.
// Depende de `ventaId` (definido inline antes de cargar este archivo) y de
// receta_cerca.js (initRecetaCercaAutocalc). No es un módulo: comparte scope global.
const csrftoken = document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1];

document.getElementById('modal-cancelar-venta-confirmar').addEventListener('click', () => {
    document.getElementById('form-cancelar-venta').submit();
});

function postForm(url, data) {
    const body = new URLSearchParams(data);
    return fetch(url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrftoken, 'Content-Type': 'application/x-www-form-urlencoded'},
        body,
    }).then(r => {
        if (!r.ok) {
            // Si el server devuelve un error (500, etc) el body no es JSON:
            // sin este chequeo, r.json() explota en silencio y el carrito
            // simplemente no se actualiza, sin ningún aviso.
            throw new Error(`Error del servidor (${r.status}). Probá de nuevo; si sigue pasando, avisá a soporte.`);
        }
        return r.json();
    }).catch(err => {
        alert(err.message || 'Ocurrió un error inesperado al procesar la acción.');
        throw err;
    });
}

// Cada acción del punto de venta devuelve DOS fragmentos de HTML (los datos
// del cliente/vendedor arriba, y el carrito abajo) más, opcionalmente, una
// receta sugerida para ofrecer asociar. Este helper aplica los fragmentos y
// dispara el popup de la receta si corresponde.
function aplicarFragmentos(data) {
    document.getElementById('cliente-info-container').innerHTML = data.cliente_html;
    document.getElementById('cart-container').innerHTML = data.cart_html;
    document.getElementById('resumen-venta-container').innerHTML = data.resumen_html;
    rebindCartEvents();
    poblarSelectRecetaVenta();
    // El carrito puede traer el buscador de obra social recién renderizado.
    if (window.initSearchableSelects) window.initSearchableSelects(document.getElementById('cart-container'));
    mostrarPaso(wizardStep);
    mostrarPromptRecetaSiCorresponde(data);
}

// Arma el detalle óptico de una receta (dict devuelto por `detalle_receta` o
// por `receta_sugerida`) como HTML legible, para validar que es la correcta
// antes de asociarla, o simplemente para consultarla desde el carrito.
function renderRecetaDetalleHtml(r) {
    const val = (v) => (v === null || v === undefined || v === '') ? '—' : v;
    const filaOjo = (nombre, lejos, cerca) => `
        <tr>
            <td class="fw-bold">${nombre}</td>
            <td>${val(lejos.esfera)}</td><td>${val(lejos.cilindro)}</td><td>${val(lejos.eje)}</td><td>${val(lejos.adicion)}</td>
            <td>${val(cerca.esfera)}</td><td>${val(cerca.cilindro)}</td><td>${val(cerca.eje)}</td>
        </tr>`;
    const datosGenerales = [
        `Fecha de la receta: <strong>${r.fecha_recibido}</strong>`,
        r.medico ? `Doctor/a: <strong>${r.medico}</strong>` : '',
        r.obra_social ? `Obra social: <strong>${r.obra_social}</strong>` : '',
    ].filter(Boolean).join(' · ');
    return `
        <p class="mb-2">${datosGenerales}</p>
        <div class="table-responsive">
        <table class="table table-sm table-bordered text-center mb-2">
            <thead class="table-light">
                <tr><th rowspan="2" class="align-middle">Ojo</th><th colspan="4">Lejos</th><th colspan="3">Cerca</th></tr>
                <tr><th>Esf.</th><th>Cil.</th><th>Eje</th><th>Adic.</th><th>Esf.</th><th>Cil.</th><th>Eje</th></tr>
            </thead>
            <tbody>
                ${filaOjo('OD', r.lejos.od, r.cerca.od)}
                ${filaOjo('OI', r.lejos.oi, r.cerca.oi)}
            </tbody>
        </table>
        </div>
        <p class="small text-muted mb-1">
            ${[
                r.lejos.dnp ? 'DNP lejos: ' + r.lejos.dnp : '',
                r.lejos.tipo_cristal ? 'Cristal lejos: ' + r.lejos.tipo_cristal : '',
                r.lejos.tratamientos ? 'Tratamientos: ' + r.lejos.tratamientos : '',
            ].filter(Boolean).join(' · ')}
        </p>
        ${r.observaciones ? `<p class="mb-0"><strong>Observaciones:</strong> ${r.observaciones}</p>` : ''}
    `;
}

// ---- Wizard: la pantalla se recorre paso a paso (vendedor, cliente, receta,
// productos, cristales, obra social, forma de pago, promociones, entrega y
// pago) en vez de mostrar todo junto. Las claves son los data-step de cada
// tarjeta (con huecos: el 6 se fusionó con el 11) — el paso 3 (Receta) vive
// DENTRO de _cliente_info.html, anidado en el wrapper del paso 2, no tiene
// tarjeta propia en pos.html. pasosVisibles() filtra los que no aplican y
// todo lo demás (numeración de "Paso X de Y", las pastillas de progreso) se
// calcula por POSICIÓN en esa lista filtrada, no por esta clave cruda, así
// los números siempre quedan correlativos aunque se salteen pasos.
const WIZARD_LABELS = {
    1: 'Vendedor', 2: 'Cliente', 3: 'Receta', 4: 'Productos', 5: 'Cristales',
    7: 'Obra social', 8: 'Forma de pago', 9: 'Promociones',
    10: 'Observaciones', 11: 'Entrega y pago',
};
let wizardStep = 1;
let wizardMaxVisitado = 1;

function hayCristalesEnCarrito() {
    const card = document.querySelector('#cart-container [data-hay-items-con-receta]');
    return card ? card.dataset.hayItemsConReceta === '1' : false;
}

// Sin cliente cargado (o solo con el mail, alta rápida sin nombre/apellido/DNI)
// no tiene sentido pedir receta ni gestionar obra social a nombre de nadie.
function clienteCompleto() {
    const card = document.querySelector('#cart-container [data-cliente-completo]');
    return card ? card.dataset.clienteCompleto === '1' : false;
}

function pasosVisibles() {
    const todos = Object.keys(WIZARD_LABELS).map(Number);
    return todos.filter(p => {
        if (p === 5) return hayCristalesEnCarrito() && clienteCompleto();
        if (p === 7) return clienteCompleto();
        return true;
    });
}

function renderWizardProgress() {
    const cont = document.getElementById('wizard-progress');
    if (!cont) return;
    cont.innerHTML = '';
    // El número de la pastilla es la posición en la lista de pasos VISIBLES
    // ahora mismo (no el data-step crudo): si se agrega/saca un cliente y
    // aparecen o desaparecen "Cristales"/"Obra social", la numeración se
    // reacomoda sola en vez de quedar con huecos (ej: "1, 2, 4, 5...").
    pasosVisibles().forEach((p, idx) => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'btn btn-sm ' + (p === wizardStep ? 'btn-primary' : (p <= wizardMaxVisitado ? 'btn-outline-primary' : 'btn-outline-secondary disabled'));
        pill.textContent = `${idx + 1}. ${WIZARD_LABELS[p]}`;
        if (p <= wizardMaxVisitado) pill.addEventListener('click', () => mostrarPaso(p));
        cont.appendChild(pill);
    });
}

function mostrarPaso(n) {
    const pasos = pasosVisibles();
    // Si el paso pedido ya no existe (ej: se sacó el último cristal estando
    // en el paso 5), cae al paso visible más cercano hacia atrás.
    if (!pasos.includes(n)) n = pasos.filter(p => p <= n).pop() ?? pasos[0];
    wizardStep = n;
    wizardMaxVisitado = Math.max(wizardMaxVisitado, n);
    document.querySelectorAll('.wizard-step').forEach(el => {
        // Normalmente cada tarjeta pertenece a un solo paso (data-step), pero
        // alguna (ver #tour-paso2) tiene que quedar visible en varios a la vez
        // porque adentro anida contenido de más de un paso (data-steps="2,3").
        const pasosDeEsteEl = (el.dataset.steps || el.dataset.step || '').split(',').map(Number);
        el.style.display = pasosDeEsteEl.includes(n) ? '' : 'none';
    });
    const idx = pasos.indexOf(n);
    document.getElementById('wizard-back').disabled = idx <= 0;
    document.getElementById('wizard-next').style.display = idx >= pasos.length - 1 ? 'none' : '';
    document.getElementById('wizard-step-label').textContent = `Paso ${idx + 1} de ${pasos.length} · ${WIZARD_LABELS[n]}`;
    renderWizardProgress();
}

function irSiguientePaso() {
    const pasos = pasosVisibles();
    const idx = pasos.indexOf(wizardStep);
    if (idx < pasos.length - 1) mostrarPaso(pasos[idx + 1]);
}
function irPasoAnterior() {
    const pasos = pasosVisibles();
    const idx = pasos.indexOf(wizardStep);
    if (idx > 0) mostrarPaso(pasos[idx - 1]);
}
document.getElementById('wizard-next').addEventListener('click', irSiguientePaso);
document.getElementById('wizard-back').addEventListener('click', irPasoAnterior);

// Select de "asociar receta a la venta" (paso 3): lista las recetas del
// cliente (mismo endpoint que usan los selects por item) y al elegir una
// avanza al paso siguiente, igual que al confirmar la receta sugerida.
function poblarSelectRecetaVenta() {
    const sel = document.getElementById('select-receta-venta');
    if (!sel) return;
    fetch(`/ventas/${ventaId}/recetas/`)
        .then(r => r.json())
        .then(data => {
            data.recetas.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.id;
                opt.textContent = r.fecha_recibido + (r.medico ? ' · ' + r.medico : '');
                sel.appendChild(opt);
            });
        });
    sel.addEventListener('change', () => {
        if (!sel.value) return;
        postForm(`/ventas/${ventaId}/receta-venta/`, {receta_id: sel.value}).then(data => {
            aplicarFragmentos(data);
            if (wizardStep === 3) irSiguientePaso();
        });
    });
    const btnQuitarRecetaVenta = document.getElementById('btn-quitar-receta-venta');
    if (btnQuitarRecetaVenta) {
        btnQuitarRecetaVenta.addEventListener('click', () => {
            postForm(`/ventas/${ventaId}/receta-venta/`, {receta_id: ''}).then(data => aplicarFragmentos(data));
        });
    }
}

const modalRecetaSugerida = new bootstrap.Modal(document.getElementById('modal-receta-sugerida'));
function mostrarPromptRecetaSiCorresponde(data) {
    if (!data.receta_sugerida) return;
    const r = data.receta_sugerida;
    document.getElementById('modal-receta-sugerida-body').innerHTML = `
        <p>Este cliente tiene una receta cargada. Revisá los datos para confirmar que es la correcta antes de asociarla a la venta:</p>
        ${renderRecetaDetalleHtml(r)}`;
    const btnConfirmar = document.getElementById('btn-confirmar-receta-sugerida');
    const btnNuevo = btnConfirmar.cloneNode(true); // evita acumular listeners si se ofrece de nuevo
    btnConfirmar.parentNode.replaceChild(btnNuevo, btnConfirmar);
    btnNuevo.addEventListener('click', () => {
        postForm(`/ventas/${ventaId}/receta-venta/`, {receta_id: r.id}).then(data2 => {
            document.getElementById('cliente-info-container').innerHTML = data2.cliente_html;
            document.getElementById('cart-container').innerHTML = data2.cart_html;
            rebindCartEvents();
            poblarSelectRecetaVenta();
            modalRecetaSugerida.hide();
            if (wizardStep === 3) irSiguientePaso();
        });
    });
    modalRecetaSugerida.show();
}

const modalVerReceta = new bootstrap.Modal(document.getElementById('modal-ver-receta'));

// Buscar receta de OTRO cliente para un cristal puntual (venta con varias
// personas, cada una con su propia receta). El botón se re-crea con cada
// refresco del carrito, así que se delega en document.
const modalBuscarRecetaEl = document.getElementById('modal-buscar-receta');
const modalBuscarReceta = new bootstrap.Modal(modalBuscarRecetaEl);
const buscarRecetaInput = document.getElementById('buscar-receta-input');
const buscarRecetaResultados = document.getElementById('buscar-receta-resultados');
let itemIdParaRecetaOtroCliente = null;
let buscarRecetaTimeout;

document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-buscar-receta-otro-cliente');
    if (!btn) return;
    e.preventDefault();
    itemIdParaRecetaOtroCliente = btn.dataset.itemId;
    modalBuscarReceta.show();
});
modalBuscarRecetaEl.addEventListener('shown.bs.modal', () => buscarRecetaInput.focus());
modalBuscarRecetaEl.addEventListener('hidden.bs.modal', () => {
    buscarRecetaInput.value = '';
    buscarRecetaResultados.innerHTML = '';
    codigoInput.focus();
});
buscarRecetaInput.addEventListener('input', () => {
    clearTimeout(buscarRecetaTimeout);
    const q = buscarRecetaInput.value.trim();
    if (q.length < 2) { buscarRecetaResultados.innerHTML = ''; return; }
    buscarRecetaTimeout = setTimeout(() => {
        fetch(`/ventas/${ventaId}/recetas/buscar/?q=${encodeURIComponent(q)}`)
            .then(r => r.json())
            .then(data => {
                buscarRecetaResultados.innerHTML = '';
                if (data.resultados.length === 0) {
                    const vacio = document.createElement('div');
                    vacio.className = 'list-group-item text-muted';
                    vacio.textContent = 'Sin resultados';
                    buscarRecetaResultados.appendChild(vacio);
                    return;
                }
                data.resultados.forEach(r => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'list-group-item list-group-item-action';
                    btn.textContent = `${r.cliente} — ${r.fecha_recibido}` + (r.medico ? ` · ${r.medico}` : '');
                    btn.addEventListener('click', () => {
                        postForm(`/ventas/${ventaId}/items/${itemIdParaRecetaOtroCliente}/receta/`, {receta_id: r.id}).then(data2 => {
                            aplicarFragmentos(data2);
                            modalBuscarReceta.hide();
                        });
                    });
                    buscarRecetaResultados.appendChild(btn);
                });
            });
    }, 250);
});

const modalRecetaNuevaEl = document.getElementById('modal-receta-nueva');
// focus:false desactiva el "focus trap" de Bootstrap para este modal: como el
// formulario se inyecta por AJAX (no está en el HTML original), el trap se
// arma mal y termina devolviendo el foco al botón de cerrar cada vez que se
// hace click en un campo — no se podía tipear nada, solo funcionaban los
// controles nativos (spinners de los number input) porque no dependen del foco.
const modalRecetaNueva = new bootstrap.Modal(modalRecetaNuevaEl, {focus: false});
// El botón "Cargar receta de este cliente" se re-crea cada vez que se
// refresca el panel de datos del cliente, así que el listener se engancha
// por delegación en document (si no, dejaría de andar después del primer
// refresh). Ojo: el modal se abre RECIÉN cuando el formulario ya está
// cargado adentro (no antes) — si se abre primero y se inyecta el HTML
// después, el "focus trap" de Bootstrap ya quedó armado sin los campos
// nuevos y termina devolviendo el foco al botón de cerrar en vez de dejar
// tipear en los inputs.
document.addEventListener('click', (e) => {
    const btn = e.target.closest('#btn-abrir-receta-nueva');
    if (!btn) return;
    e.preventDefault();
    const body = document.getElementById('modal-receta-nueva-body');
    body.innerHTML = '<p class="text-muted">Cargando...</p>';
    fetch(`/ventas/${ventaId}/receta-nueva-modal/`)
        .then(r => r.json())
        .then(data => {
            body.innerHTML = data.html || `<p class="text-danger">${data.error}</p>`;
            if (window.initRecetaCercaAutocalc) window.initRecetaCercaAutocalc(body);
            modalRecetaNueva.show();
        });
});
document.getElementById('btn-guardar-receta-nueva').addEventListener('click', () => {
    const form = document.getElementById('modal-receta-nueva-body');
    const inputs = form.querySelectorAll('input, select, textarea');
    const data = new URLSearchParams();
    inputs.forEach(el => {
        if (el.type === 'checkbox') { if (el.checked) data.append(el.name, 'on'); return; }
        if (el.type === 'file') return; // el archivo escaneado no se sube desde este popup
        data.append(el.name, el.value);
    });
    fetch(`/ventas/${ventaId}/receta-nueva-modal/crear/`, {
        method: 'POST',
        headers: {'X-CSRFToken': csrftoken},
        body: data,
    })
        .then(r => r.json())
        .then(resultado => {
            if (!resultado.ok) {
                const body = document.getElementById('modal-receta-nueva-body');
                body.innerHTML = resultado.html;
                if (window.initRecetaCercaAutocalc) window.initRecetaCercaAutocalc(body);
                return;
            }
            document.getElementById('cliente-info-container').innerHTML = resultado.cliente_html;
            document.getElementById('cart-container').innerHTML = resultado.cart_html;
            rebindCartEvents();
            poblarSelectRecetaVenta();
            modalRecetaNueva.hide();
            if (wizardStep === 3) irSiguientePaso();
        });
});

const codigoInput = document.getElementById('codigo-barras-input');

function confirmarYAgregar(codigo, cantidad, precio) {
    const datos = {codigo, cantidad};
    if (precio !== undefined && precio !== null && precio !== '') datos.precio = precio;
    postForm(`/ventas/${ventaId}/escanear/`, datos).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
}

// Modal compartido para confirmar precio/cantidad de un artículo elegido del
// catálogo o de cristales, ANTES de sumarlo al carrito (donde ya no se edita).
const modalConfirmarItemEl = document.getElementById('modal-confirmar-item');
const modalConfirmarItem = new bootstrap.Modal(modalConfirmarItemEl);
function abrirConfirmarItem(p, cerrarModalId) {
    document.getElementById('ci-nombre').textContent = p.nombre || p.label;
    document.getElementById('ci-stock').textContent = p.controla_stock
        ? `Stock disponible: ${p.stock_actual}` : 'Producto a medida (sin control de stock)';
    document.getElementById('ci-precio').value = p.precio;
    document.getElementById('ci-cantidad').value = 1;

    const btn = document.getElementById('ci-confirmar');
    const nuevo = btn.cloneNode(true); // limpia listeners previos
    btn.parentNode.replaceChild(nuevo, btn);
    nuevo.addEventListener('click', () => {
        postForm(`/ventas/${ventaId}/catalogo/agregar/`, {
            producto_id: p.id,
            cantidad: document.getElementById('ci-cantidad').value || '1',
            precio: document.getElementById('ci-precio').value,
        }).then(data => {
            aplicarFragmentos(data);
            modalConfirmarItem.hide();
            codigoInput.focus();
        });
    });

    // Se cierra el modal de búsqueda y, recién cuando terminó de cerrarse, se
    // abre el de confirmación (evita que queden dos backdrops encimados).
    if (cerrarModalId) {
        const el = document.getElementById(cerrarModalId);
        el.addEventListener('hidden.bs.modal', () => modalConfirmarItem.show(), {once: true});
        bootstrap.Modal.getOrCreateInstance(el).hide();
    } else {
        modalConfirmarItem.show();
    }
}
modalConfirmarItemEl.addEventListener('shown.bs.modal', () => {
    document.getElementById('ci-precio').focus();
    document.getElementById('ci-precio').select();
});
modalConfirmarItemEl.addEventListener('hidden.bs.modal', () => codigoInput.focus());

// Cada Enter en el input del lector agrega directo, sin popup de confirmación
// (el precio y la cantidad se pueden ajustar después, ya en el carrito). El
// endpoint /escanear/ ya cubre los casos raros por su cuenta: código no
// encontrado, producto a medida (no se escanea) o sin stock — todos vuelven
// como error en el carrito, con botón de "forzar" cuando corresponde.
codigoInput.addEventListener('keydown', function(e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const codigo = codigoInput.value.trim();
    codigoInput.value = '';
    if (!codigo) return;
    confirmarYAgregar(codigo, 1);
});

// Mantener el foco en el input del lector, para que un lector físico (USB o
// Bluetooth) siempre pueda "tipear" ahí.
document.addEventListener('click', (e) => {
    if (!e.target.closest('#cliente-buscar') && !e.target.closest('#cliente-resultados')
        && !e.target.closest('#catalogo-buscar') && !e.target.closest('#catalogo-resultados')
        && !e.target.closest('#cristal-buscar') && !e.target.closest('#cristal-resultados')
        && !e.target.closest('#form-cliente-nuevo') && !e.target.closest('#toggle-cliente-nuevo')
        && !e.target.closest('#form-email-rapido') && !e.target.closest('#toggle-email-rapido')
        && !e.target.closest('#cliente-info-container')
        && !e.target.closest('#cart-container')
        && !e.target.closest('#modal-agregar-producto') && !e.target.closest('#modal-agregar-cristal')
        && !e.target.closest('#modal-item-express') && !e.target.closest('#modal-confirmar-item')
        && !e.target.closest('#modal-receta-sugerida')
        && !e.target.closest('#modal-receta-nueva') && !e.target.closest('#modal-ver-receta')) {
        codigoInput.focus();
    }
});

document.getElementById('modal-agregar-producto').addEventListener('shown.bs.modal', () => {
    document.getElementById('catalogo-buscar').focus();
});
document.getElementById('modal-agregar-producto').addEventListener('hidden.bs.modal', () => {
    document.getElementById('catalogo-buscar').value = '';
    document.getElementById('catalogo-resultados').innerHTML = '';
    codigoInput.focus();
});

// Ítem express: vender algo que no está en el catálogo, con precio a mano.
const modalItemExpressEl = document.getElementById('modal-item-express');
const modalItemExpress = bootstrap.Modal.getOrCreateInstance(modalItemExpressEl);
modalItemExpressEl.addEventListener('shown.bs.modal', () => {
    document.getElementById('express-descripcion').focus();
});
modalItemExpressEl.addEventListener('hidden.bs.modal', () => {
    ['express-descripcion', 'express-precio', 'express-marca'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('express-cantidad').value = '1';
    document.getElementById('express-error').classList.add('d-none');
    codigoInput.focus();
});
document.getElementById('btn-agregar-express').addEventListener('click', () => {
    const descripcion = document.getElementById('express-descripcion').value.trim();
    const precio = document.getElementById('express-precio').value;
    const errorBox = document.getElementById('express-error');
    if (!descripcion || precio === '' || Number(precio) < 0) {
        errorBox.textContent = 'Completá la descripción y un precio válido.';
        errorBox.classList.remove('d-none');
        return;
    }
    postForm(`/ventas/${ventaId}/express/agregar/`, {
        descripcion,
        precio,
        cantidad: document.getElementById('express-cantidad').value || '1',
        marca: document.getElementById('express-marca').value.trim(),
    }).then(data => {
        if (data.error) {
            errorBox.textContent = data.error;
            errorBox.classList.remove('d-none');
            return;
        }
        aplicarFragmentos(data);
        modalItemExpress.hide();
    });
});

document.getElementById('modal-agregar-cristal').addEventListener('shown.bs.modal', () => {
    document.getElementById('cristal-buscar').focus();
    cargarCristales('');
});
document.getElementById('modal-agregar-cristal').addEventListener('hidden.bs.modal', () => {
    document.getElementById('cristal-buscar').value = '';
    document.getElementById('cristal-resultados').innerHTML = '';
    codigoInput.focus();
});

// Forma de pago: el select y el input de cuotas se re-renderizan con cada
// actualización del carrito, así que se delega el evento en document (no
// hace falta re-bindear después de cada innerHTML).
document.addEventListener('change', (e) => {
    if (e.target.id !== 'select-forma-pago' && e.target.id !== 'input-cuotas') return;
    const formaPago = document.getElementById('select-forma-pago').value;
    const colCuotas = document.getElementById('col-cuotas');
    const inputCuotas = document.getElementById('input-cuotas');
    if (formaPago === 'TAR') {
        colCuotas.style.display = '';
    } else {
        colCuotas.style.display = 'none';
        inputCuotas.value = '';
    }
    postForm(`/ventas/${ventaId}/forma-pago/`, {forma_pago: formaPago, cuotas: inputCuotas.value}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});
window.addEventListener('load', () => codigoInput.focus());

// ¿Es por obra social? el checkbox se re-renderiza con cada actualización
// del carrito, así que se delega el evento en document.
document.addEventListener('change', (e) => {
    if (e.target.id !== 'chk-obra-social') return;
    postForm(`/ventas/${ventaId}/obra-social/`, {es_obra_social: e.target.checked ? '1' : '0'}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});

// Qué obra social se usa (desplegable que aparece al marcar "es por obra social").
document.addEventListener('change', (e) => {
    if (e.target.id !== 'select-obra-social') return;
    postForm(`/ventas/${ventaId}/obra-social/cual/`, {obra_social_id: e.target.value}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});

// Cómo interviene la obra social: reintegro, cubre parte, o cubre el anteojo completo.
document.addEventListener('change', (e) => {
    if (e.target.id !== 'select-obra-social-tipo') return;
    postForm(`/ventas/${ventaId}/obra-social/tipo/`, {obra_social_tipo: e.target.value}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});

// Monto que cubre la obra social (tipo "parcial"): se resta del total.
document.addEventListener('change', (e) => {
    if (e.target.id !== 'input-obra-social-cobertura') return;
    postForm(`/ventas/${ventaId}/obra-social/cobertura/`, {cobertura: e.target.value}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});

// Ítems cubiertos por completo por la obra social (tipo "completo"): se
// resta su valor del total.
document.addEventListener('change', (e) => {
    if (!e.target.classList.contains('chk-item-cubierto-obra-social')) return;
    const itemId = e.target.dataset.itemId;
    postForm(`/ventas/${ventaId}/items/${itemId}/obra-social-cubierto/`, {cubierto: e.target.checked ? '1' : '0'}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
    });
});

// Al elegir un monto con "Paga el total" o un botón de porcentaje, se fija:
// el input queda bloqueado (no se puede tipear otra cosa por error) y el
// valor elegido se muestra abajo, con un link para volver a habilitarlo.
function fijarMontoPagado(valor) {
    const inp = document.getElementById('input-monto-pagado');
    if (!inp) return;
    inp.value = valor;
    inp.disabled = true;
    const resumen = document.getElementById('monto-pagado-fijado');
    const resumenValor = document.getElementById('monto-pagado-fijado-valor');
    if (resumen && resumenValor) {
        resumenValor.textContent = valor;
        resumen.classList.remove('d-none');
    }
}

// "Paga el total": llena el monto con el total (el input-group se re-renderiza
// con cada refresco del carrito, así que se delega en document). El campo no
// deja cargar más que el total (el vuelto se maneja en efectivo).
document.addEventListener('click', (e) => {
    if (e.target.id !== 'btn-paga-total') return;
    const inp = document.getElementById('input-monto-pagado');
    if (inp) fijarMontoPagado(inp.dataset.total || 0);
});

// Botones 10%/25%/50%: completan el monto con esa fracción del total.
document.addEventListener('click', (e) => {
    if (!e.target.classList.contains('btn-paga-porcentaje')) return;
    const inp = document.getElementById('input-monto-pagado');
    if (!inp) return;
    const total = Number(inp.dataset.total || 0);
    const porcentaje = Number(e.target.dataset.porcentaje);
    fijarMontoPagado((total * porcentaje / 100).toFixed(2));
});

// "Cambiar monto": vuelve a habilitar el input para tipear un monto distinto.
document.addEventListener('click', (e) => {
    if (e.target.id !== 'btn-cambiar-monto-pagado') return;
    const inp = document.getElementById('input-monto-pagado');
    if (inp) inp.disabled = false;
    document.getElementById('monto-pagado-fijado')?.classList.add('d-none');
});

document.addEventListener('input', (e) => {
    if (e.target.id !== 'input-monto-pagado') return;
    const total = Number(e.target.dataset.total || 0);
    if (Number(e.target.value) > total) e.target.value = total;
});

// Selección de vendedor/a
const selectVendedor = document.getElementById('select-vendedor');
selectVendedor.addEventListener('change', () => {
    postForm(`/ventas/${ventaId}/vendedor/`, {vendedor_id: selectVendedor.value}).then(data => {
        aplicarFragmentos(data);
        codigoInput.focus();
        if (selectVendedor.value && wizardStep === 1) irSiguientePaso();
    });
});

// Alta rápida de cliente (sin salir del punto de venta)
document.getElementById('toggle-cliente-nuevo').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('form-cliente-nuevo').classList.toggle('d-none');
});

document.getElementById('toggle-email-rapido').addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('form-email-rapido').classList.toggle('d-none');
});

document.getElementById('btn-guardar-cliente-nuevo').addEventListener('click', () => {
    postForm(`/ventas/${ventaId}/cliente/nuevo-rapido/`, {
        nombre: document.getElementById('nc-nombre').value,
        apellido: document.getElementById('nc-apellido').value,
        dni: document.getElementById('nc-dni').value,
        telefono: document.getElementById('nc-telefono').value,
        email: document.getElementById('nc-email').value,
        direccion: document.getElementById('nc-direccion').value,
        obra_social_id: document.getElementById('nc-obra-social').value,
    }).then(data => {
        aplicarFragmentos(data);
        if (data.error) { codigoInput.focus(); return; } // formulario vacío: se queda como está para que se complete y reintente
        ['nc-nombre', 'nc-apellido', 'nc-dni', 'nc-telefono', 'nc-email', 'nc-direccion', 'nc-obra-social'].forEach(id => document.getElementById(id).value = '');
        document.getElementById('form-cliente-nuevo').classList.add('d-none');
        codigoInput.focus();
        if (wizardStep === 2) irSiguientePaso();
    });
});

// Guardar solo el mail (para promociones), sin pedir el resto de los datos
document.getElementById('btn-email-rapido').addEventListener('click', () => {
    const emailInput = document.getElementById('email-rapido');
    if (!emailInput.value.trim()) return;
    postForm(`/ventas/${ventaId}/cliente/email-rapido/`, {email: emailInput.value.trim()}).then(data => {
        aplicarFragmentos(data);
        emailInput.value = '';
        codigoInput.focus();
    });
});

// Búsqueda de cliente: funciona igual que el buscador de marcas (se escribe
// para filtrar, se hace click en un resultado de la lista y queda como una
// "cajita" abajo, con una x para sacarlo) — la única diferencia es que acá la
// lista de opciones se busca en el servidor a medida que se escribe, en vez
// de tener todas precargadas, porque puede haber miles de clientes.
const clienteBuscar = document.getElementById('cliente-buscar');
const clienteResultados = document.getElementById('cliente-resultados');
const clienteSeleccionado = document.getElementById('cliente-seleccionado');
let clienteTimeout;

function renderClienteChip(texto) {
    clienteSeleccionado.innerHTML = '';
    const chip = document.createElement('span');
    chip.className = 'badge text-bg-primary d-flex align-items-center gap-2 py-2 px-3 fs-6 fw-normal';
    chip.textContent = texto;
    const btnX = document.createElement('button');
    btnX.type = 'button';
    btnX.className = 'btn-close btn-close-white btn-quitar-cliente';
    btnX.style.fontSize = '0.6rem';
    btnX.setAttribute('aria-label', 'Quitar cliente');
    chip.appendChild(btnX);
    clienteSeleccionado.appendChild(chip);
}

clienteSeleccionado.addEventListener('click', (e) => {
    if (!e.target.classList.contains('btn-quitar-cliente')) return;
    postForm(`/ventas/${ventaId}/cliente/`, {cliente_id: ''}).then(data => {
        aplicarFragmentos(data);
        clienteSeleccionado.innerHTML = '';
        codigoInput.focus();
    });
});

clienteBuscar.addEventListener('input', () => {
    clearTimeout(clienteTimeout);
    const q = clienteBuscar.value.trim();
    if (q.length < 2) { clienteResultados.innerHTML = ''; clienteResultados.style.display = 'none'; return; }
    clienteTimeout = setTimeout(() => {
        fetch(`/ventas/${ventaId}/clientes/buscar/?q=${encodeURIComponent(q)}`)
            .then(r => r.json())
            .then(data => {
                clienteResultados.innerHTML = '';
                if (data.resultados.length === 0) {
                    clienteResultados.style.display = 'none';
                    return;
                }
                data.resultados.forEach(cl => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'list-group-item list-group-item-action py-1';
                    btn.dataset.id = cl.id;
                    const nombreCompleto = [cl.nombre, cl.apellido].filter(Boolean).join(' ');
                    btn.textContent = (nombreCompleto || cl.email || 'Cliente #' + cl.id)
                        + (cl.dni ? ' — DNI ' + cl.dni : '')
                        + (nombreCompleto && cl.email ? ' — ' + cl.email : '');
                    btn.addEventListener('mousedown', (e) => {
                        e.preventDefault(); // que no se pierda el click por el blur del input
                        postForm(`/ventas/${ventaId}/cliente/`, {cliente_id: btn.dataset.id}).then(data => {
                            aplicarFragmentos(data);
                            if (wizardStep === 2) irSiguientePaso();
                        });
                        renderClienteChip(btn.textContent);
                        clienteResultados.innerHTML = '';
                        clienteResultados.style.display = 'none';
                        clienteBuscar.value = '';
                        codigoInput.focus();
                    });
                    clienteResultados.appendChild(btn);
                });
                clienteResultados.style.display = '';
            });
    }, 250);
});
clienteBuscar.addEventListener('blur', () => {
    setTimeout(() => { clienteResultados.style.display = 'none'; }, 150);
});

// Búsqueda de cristales / catálogo (no se escanean)
const catalogoBuscar = document.getElementById('catalogo-buscar');
let catalogoTimeout;
catalogoBuscar.addEventListener('input', () => {
    clearTimeout(catalogoTimeout);
    const q = catalogoBuscar.value.trim();
    const resultados = document.getElementById('catalogo-resultados');
    if (q.length < 2) { resultados.innerHTML = ''; return; }
    catalogoTimeout = setTimeout(() => {
        fetch(`/ventas/${ventaId}/catalogo/buscar/?q=${encodeURIComponent(q)}`)
            .then(r => r.json())
            .then(data => {
                resultados.innerHTML = '';
                if (data.resultados.length === 0) {
                    const vacio = document.createElement('div');
                    vacio.className = 'list-group-item text-muted';
                    vacio.textContent = 'Sin resultados';
                    resultados.appendChild(vacio);
                    return;
                }
                data.resultados.forEach(p => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'list-group-item list-group-item-action';
                    btn.dataset.id = p.id;
                    btn.textContent = p.label + (p.controla_stock ? ` (stock: ${p.stock_actual})` : '');
                    btn.addEventListener('click', () => {
                        abrirConfirmarItem(p, 'modal-agregar-producto');
                        resultados.innerHTML = '';
                        catalogoBuscar.value = '';
                    });
                    resultados.appendChild(btn);
                });
            });
    }, 250);
});

// Búsqueda dedicada de cristales: como es un catálogo chico y finito (~30
// tipos), se listan todos apenas se abre el modal, sin necesidad de escribir
// nada; escribir solo filtra esa lista.
const cristalBuscar = document.getElementById('cristal-buscar');
let cristalTimeout;

function cargarCristales(q) {
    const resultados = document.getElementById('cristal-resultados');
    fetch(`/ventas/${ventaId}/catalogo/buscar/?solo_cristales=1&q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(data => {
            resultados.innerHTML = '';
            if (data.resultados.length === 0) {
                const vacio = document.createElement('div');
                vacio.className = 'list-group-item text-muted';
                vacio.textContent = 'Sin resultados';
                resultados.appendChild(vacio);
                return;
            }
            data.resultados.forEach(p => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'list-group-item list-group-item-action';
                btn.dataset.id = p.id;
                btn.textContent = p.label;
                btn.addEventListener('click', () => {
                    abrirConfirmarItem(p, 'modal-agregar-cristal');
                    resultados.innerHTML = '';
                    cristalBuscar.value = '';
                });
                resultados.appendChild(btn);
            });
        });
}

cristalBuscar.addEventListener('input', () => {
    clearTimeout(cristalTimeout);
    const q = cristalBuscar.value.trim();
    cristalTimeout = setTimeout(() => cargarCristales(q), 250);
});

function poblarSelectsReceta() {
    const selects = document.querySelectorAll('.select-receta');
    if (selects.length === 0) return;
    fetch(`/ventas/${ventaId}/recetas/`)
        .then(r => r.json())
        .then(data => {
            selects.forEach(sel => {
                const seleccionada = sel.dataset.selected;
                let encontrada = false;
                data.recetas.forEach(r => {
                    const opt = document.createElement('option');
                    opt.value = r.id;
                    opt.textContent = r.fecha_recibido + (r.medico ? ' · ' + r.medico : '');
                    if (String(r.id) === seleccionada) { opt.selected = true; encontrada = true; }
                    sel.appendChild(opt);
                });
                // La receta asignada puede ser de OTRO cliente (venta con
                // varias personas): no está en la lista de arriba, hay que
                // traerla aparte para que el select la muestre seleccionada.
                if (seleccionada && !encontrada) {
                    fetch(`/ventas/recetas/${seleccionada}/detalle/`)
                        .then(r => r.json())
                        .then(r => {
                            const opt = document.createElement('option');
                            opt.value = seleccionada;
                            opt.textContent = `${r.fecha_recibido} · ${r.cliente}`;
                            opt.selected = true;
                            sel.appendChild(opt);
                        });
                }
                actualizarBotonVerReceta(sel);
            });
        });
}

function actualizarBotonVerReceta(select) {
    const btnVer = select.closest('.receta-cell')?.querySelector('.btn-ver-receta');
    if (btnVer) btnVer.disabled = !select.value;
}

function poblarSelectsArmazon() {
    const selects = document.querySelectorAll('.select-armazon');
    if (selects.length === 0) return;
    fetch(`/ventas/${ventaId}/armazones/`)
        .then(r => r.json())
        .then(data => {
            selects.forEach(sel => {
                const seleccionado = sel.dataset.selected;
                data.armazones.forEach(a => {
                    // Un item no puede ser armazón de sí mismo.
                    if (String(a.id) === sel.dataset.itemId) return;
                    const opt = document.createElement('option');
                    opt.value = a.id;
                    opt.textContent = a.label;
                    if (String(a.id) === seleccionado) opt.selected = true;
                    sel.appendChild(opt);
                });
                if (seleccionado === 'cliente') sel.value = 'cliente';
            });
        });
}

function rebindCartEvents() {
    const btnAplicarDescuento = document.getElementById('btn-aplicar-descuento');
    if (btnAplicarDescuento) {
        btnAplicarDescuento.addEventListener('click', () => {
            const tipo = document.getElementById('select-descuento-tipo').value;
            const valor = document.getElementById('input-descuento-valor').value;
            postForm(`/ventas/${ventaId}/descuento-manual/`, {tipo, valor}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    }
    const btnQuitarDescuento = document.getElementById('btn-quitar-descuento');
    if (btnQuitarDescuento) {
        btnQuitarDescuento.addEventListener('click', () => {
            postForm(`/ventas/${ventaId}/descuento-manual/`, {tipo: '', valor: ''}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    }
    document.querySelectorAll('.chk-item-entregado').forEach(chk => {
        chk.addEventListener('change', () => {
            postForm(`/ventas/${ventaId}/items/${chk.dataset.itemId}/entregado/`, {
                entregado: chk.checked ? '1' : '0',
            }).then(data => {
                if (data.cart_html) {
                    aplicarFragmentos(data);
                    codigoInput.focus();
                }
            });
        });
    });
    const btnForzarStock = document.getElementById('btn-forzar-stock');
    if (btnForzarStock) {
        btnForzarStock.addEventListener('click', () => {
            const tipo = btnForzarStock.dataset.tipo;
            if (tipo === 'escaneo') {
                postForm(`/ventas/${ventaId}/escanear/`, {
                    codigo: btnForzarStock.dataset.codigo, cantidad: btnForzarStock.dataset.cantidad, forzar: '1',
                }).then(data => { aplicarFragmentos(data); codigoInput.focus(); });
            } else {
                postForm(`/ventas/${ventaId}/catalogo/agregar/`, {
                    producto_id: btnForzarStock.dataset.productoId, forzar: '1',
                }).then(data => { aplicarFragmentos(data); codigoInput.focus(); });
            }
        });
    }
    const btnGuardarClienteEdit = document.getElementById('btn-guardar-cliente-edit');
    if (btnGuardarClienteEdit) {
        btnGuardarClienteEdit.addEventListener('click', () => {
            postForm(`/ventas/${ventaId}/cliente/editar-rapido/`, {
                nombre: document.getElementById('cli-nombre').value,
                apellido: document.getElementById('cli-apellido').value,
                dni: document.getElementById('cli-dni').value,
                telefono: document.getElementById('cli-telefono').value,
                email: document.getElementById('cli-email').value,
                direccion: document.getElementById('cli-direccion').value,
            }).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    }
    const inputObservaciones = document.getElementById('input-observaciones');
    if (inputObservaciones) {
        inputObservaciones.addEventListener('change', () => {
            postForm(`/ventas/${ventaId}/observaciones/`, {observaciones: inputObservaciones.value}).then(data => {
                aplicarFragmentos(data);
            });
        });
    }
    document.querySelectorAll('.input-precio-item').forEach(inp => {
        inp.addEventListener('change', () => {
            postForm(`/ventas/${ventaId}/items/${inp.dataset.itemId}/precio/`, {precio: inp.value}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    });
    document.querySelectorAll('.btn-quitar-item').forEach(btn => {
        btn.addEventListener('click', () => {
            postForm(`/ventas/${ventaId}/items/${btn.dataset.itemId}/quitar/`, {}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    });
    document.querySelectorAll('.select-receta').forEach(sel => {
        sel.addEventListener('change', () => {
            actualizarBotonVerReceta(sel);
            postForm(`/ventas/${ventaId}/items/${sel.dataset.itemId}/receta/`, {receta_id: sel.value}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    });
    document.querySelectorAll('.select-armazon').forEach(sel => {
        sel.addEventListener('change', () => {
            const body = sel.value === 'cliente'
                ? {armazon_de_cliente: '1'}
                : {armazon_item_id: sel.value};
            postForm(`/ventas/${ventaId}/items/${sel.dataset.itemId}/armazon/`, body).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    });
    document.querySelectorAll('.btn-ver-receta').forEach(btn => {
        btn.addEventListener('click', () => {
            const select = btn.closest('.receta-cell').querySelector('.select-receta');
            if (!select.value) return;
            fetch(`/ventas/recetas/${select.value}/detalle/`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('modal-ver-receta-body').innerHTML = renderRecetaDetalleHtml(data);
                    modalVerReceta.show();
                });
        });
    });
    document.querySelectorAll('.btn-orden-laboratorio').forEach(btn => {
        btn.addEventListener('click', () => {
            postForm(`/ventas/${ventaId}/items/${btn.dataset.itemId}/orden-laboratorio/`, {}).then(data => {
                window.open(data.url, '_blank');
            });
        });
    });
    document.querySelectorAll('.select-promocion-item').forEach(sel => {
        sel.addEventListener('change', () => {
            postForm(`/ventas/${ventaId}/items/${sel.dataset.itemId}/promocion/`, {promocion_id: sel.value}).then(data => {
                aplicarFragmentos(data);
                codigoInput.focus();
            });
        });
    });
    const btnConfirmar = document.getElementById('btn-confirmar-venta');
    if (btnConfirmar) {
        btnConfirmar.addEventListener('click', () => {
            btnConfirmar.disabled = true;
            const montoPagado = document.getElementById('input-monto-pagado').value;
            postForm(`/ventas/${ventaId}/confirmar/`, {monto_pagado: montoPagado}).then(data => {
                document.getElementById('cliente-info-container').innerHTML = data.cliente_html;
                document.getElementById('cart-container').innerHTML = data.cart_html;
                if (document.getElementById('codigo-barras-input')) {
                    document.getElementById('codigo-barras-input').disabled = true;
                }
                rebindCartEvents();
                // Venta confirmada: se acabó el wizard, se esconden sus
                // controles (steps, barra de progreso, atrás/siguiente).
                document.querySelectorAll('.wizard-step').forEach(el => el.style.display = 'none');
                document.getElementById('wizard-progress').style.display = 'none';
                document.getElementById('wizard-back').style.display = 'none';
                document.getElementById('wizard-next').style.display = 'none';
                document.getElementById('wizard-step-label').textContent = '';
            });
        });
    }
    poblarSelectsReceta();
    poblarSelectsArmazon();
}
rebindCartEvents();
poblarSelectRecetaVenta();
// Si ya viene con cliente asignado (ej: desde "iniciar venta" de una prueba
// de lentes de contacto), la receta es opcional: se salta directo al paso de
// cargar productos, en vez de dejar a la vista solo el paso de receta (donde
// no hay ningún control para agregar productos). Sigue pudiéndose volver
// atrás para asociar una receta si hace falta.
let pasoInicial = 1;
if (ventaInicial.vendedor) pasoInicial = 2;
if (ventaInicial.cliente) pasoInicial = 4;
wizardMaxVisitado = pasoInicial;
mostrarPaso(pasoInicial);
