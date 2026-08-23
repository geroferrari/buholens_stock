// Notificaciones push: registra el service worker y maneja el panel de
// "Avisos en el celular" (activar / probar / desactivar).
//
// Como varias personas comparten el mismo login (la compu del mostrador), al
// activar los avisos se elige QUIÉN usa este dispositivo. Eso queda guardado
// en el servidor junto con la suscripción, así el aviso le llega a la persona
// correcta aunque el usuario sea compartido.
//
// En iPhone las notificaciones web SOLO funcionan si la web fue agregada a la
// pantalla de inicio (límite de Apple, iOS 16.4+). Si detectamos iPhone sin
// instalar, en vez del botón mostramos las instrucciones.
(function () {
    if (!('serviceWorker' in navigator)) return;

    navigator.serviceWorker.register('/sw.js').catch(function (e) {
        console.warn('No se pudo registrar el service worker', e);
    });

    function base64ToUint8Array(base64) {
        const padding = '='.repeat((4 - (base64.length % 4)) % 4);
        const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
        const raw = window.atob(b64);
        return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
    }

    function csrf() {
        return document.cookie.split('; ').find((r) => r.startsWith('csrftoken='))?.split('=')[1];
    }

    // Devuelve siempre un objeto (nunca tira): si el servidor no contesta JSON
    // —una página de error 403/500, un redirect al login— lo informa con el
    // código y un extracto, así el problema se ve en pantalla en vez de quedar
    // como un genérico "no se pudo contactar al servidor".
    async function post(url, datos) {
        const token = csrf();
        if (!token) {
            return {ok: false, error: 'No se encontró la cookie de sesión (csrftoken). Probá recargar la página o volver a iniciar sesión.'};
        }
        let respuesta;
        try {
            respuesta = await fetch(url, {
                method: 'POST',
                headers: {'X-CSRFToken': token, 'Content-Type': 'application/json'},
                body: JSON.stringify(datos || {}),
                credentials: 'same-origin',
            });
        } catch (e) {
            return {ok: false, error: 'No hay conexión con el servidor (' + e.message + ').'};
        }
        const texto = await respuesta.text();
        try {
            return JSON.parse(texto);
        } catch (e) {
            const extracto = texto.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 180);
            const pista = respuesta.status === 403 ? ' (permiso/CSRF rechazado)'
                : respuesta.status === 404 ? ' (la dirección no existe: ¿falta deployar?)'
                : respuesta.status >= 500 ? ' (error del servidor: mirá los logs de Railway)' : '';
            return {ok: false, error: `El servidor respondió ${respuesta.status}${pista}. ${extracto}`};
        }
    }

    const esIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const instalada = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;

    async function init() {
        const panel = document.getElementById('push-panel');
        if (!panel) return;

        const estadoEl = document.getElementById('push-estado');
        const btnActivar = document.getElementById('push-activar');
        const btnDesactivar = document.getElementById('push-desactivar');
        const btnProbar = document.getElementById('push-probar');
        const ayudaIOS = document.getElementById('push-ayuda-ios');
        const quienWrap = document.getElementById('push-quien-wrap');
        const quienSelect = document.getElementById('push-quien');

        function mostrar(texto, clase) {
            estadoEl.textContent = texto;
            estadoEl.className = 'small ' + (clase || 'text-muted');
        }

        function botones({activar = false, suscripto = false, quien = false} = {}) {
            btnActivar.classList.toggle('d-none', !activar);
            btnDesactivar.classList.toggle('d-none', !suscripto);
            btnProbar.classList.toggle('d-none', !suscripto);
            quienWrap.classList.toggle('d-none', !quien);
        }

        // iPhone sin instalar: no hay forma de recibir avisos; mostramos el cómo.
        if (esIOS && !instalada) {
            ayudaIOS.classList.remove('d-none');
            mostrar('Para recibir avisos en iPhone hay que agregar la app a la pantalla de inicio.', 'text-warning');
            botones();
            return;
        }

        const registro = await navigator.serviceWorker.ready;
        let suscripcion = await registro.pushManager.getSubscription();

        const estado = await fetch(
            '/notificaciones/estado/?endpoint=' + encodeURIComponent(suscripcion ? suscripcion.endpoint : '')
        ).then((r) => r.json());

        if (!estado.configurado) {
            mostrar('Los avisos no están configurados en el servidor todavía.');
            botones();
            return;
        }

        // Lista de personas para decir de quién es este dispositivo.
        quienSelect.innerHTML = '<option value="">— elegir persona —</option>';
        estado.vendedores.forEach(function (v) {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = v.nombre;
            if (String(v.id) === String(estado.vendedor_id)) opt.selected = true;
            quienSelect.appendChild(opt);
        });

        function pintarSuscripto(nombre) {
            mostrar(nombre
                ? `✅ Avisos activados en este dispositivo, a nombre de ${nombre}.`
                : '✅ Avisos activados en este dispositivo. Elegí quién lo usa para recibir sus avisos.',
                nombre ? 'text-success' : 'text-warning');
            botones({suscripto: true, quien: true});
        }

        if (estado.suscripto) {
            pintarSuscripto(estado.vendedor_nombre);
        } else if (Notification.permission === 'denied') {
            mostrar('Bloqueaste los avisos en este dispositivo. Habilitalos desde los ajustes del navegador.', 'text-danger');
            botones();
            return;
        } else {
            mostrar('Los avisos están desactivados en este dispositivo.');
            botones({activar: true, quien: true});
        }

        btnActivar.addEventListener('click', async function () {
            btnActivar.disabled = true;
            try {
                const permiso = await Notification.requestPermission();
                if (permiso !== 'granted') {
                    mostrar('No diste permiso para los avisos.', 'text-danger');
                    botones({activar: true, quien: true});
                    return;
                }
                suscripcion = await registro.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: base64ToUint8Array(estado.clave_publica),
                });
                const datos = suscripcion.toJSON();
                datos.vendedor_id = quienSelect.value;
                const r = await post('/notificaciones/suscribir/', datos);
                if (!r.ok) {
                    mostrar('❌ ' + r.error, 'text-danger');
                    botones({activar: true, quien: true});
                    return;
                }
                pintarSuscripto(r.vendedor);
            } catch (e) {
                console.error(e);
                mostrar('No se pudieron activar los avisos en este dispositivo.', 'text-danger');
                botones({activar: true, quien: true});
            } finally {
                btnActivar.disabled = false;
            }
        });

        // Cambiar de persona con los avisos ya activados: se reenvía la misma
        // suscripción con el nuevo dueño.
        quienSelect.addEventListener('change', async function () {
            if (!suscripcion) return;
            const datos = suscripcion.toJSON();
            datos.vendedor_id = quienSelect.value;
            const r = await post('/notificaciones/suscribir/', datos);
            if (!r.ok) {
                mostrar('❌ ' + r.error, 'text-danger');
                return;
            }
            pintarSuscripto(r.vendedor);
        });

        btnDesactivar.addEventListener('click', async function () {
            const endpoint = suscripcion ? suscripcion.endpoint : '';
            if (suscripcion) await suscripcion.unsubscribe();
            suscripcion = null;
            await post('/notificaciones/desuscribir/', {endpoint: endpoint});
            mostrar('Avisos desactivados en este dispositivo.');
            botones({activar: true, quien: true});
        });

        btnProbar.addEventListener('click', async function () {
            btnProbar.disabled = true;
            mostrar('Enviando notificación de prueba…');
            try {
                const r = await post('/notificaciones/probar/', {
                    endpoint: suscripcion ? suscripcion.endpoint : '',
                });
                if (r.ok) {
                    mostrar('✅ Notificación enviada. Si no la ves en unos segundos, revisá los avisos '
                            + 'de la app en los ajustes del celular.', 'text-success');
                } else {
                    // El motivo real (lo que respondió Apple/Google), para no
                    // tener que adivinar mirando los logs del servidor.
                    mostrar('❌ ' + (r.error || 'No se pudo enviar la notificación de prueba.'), 'text-danger');
                }
            } catch (e) {
                mostrar('❌ No se pudo contactar al servidor para enviar la prueba.', 'text-danger');
            } finally {
                btnProbar.disabled = false;
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
