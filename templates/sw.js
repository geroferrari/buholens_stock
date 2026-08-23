{% load static %}// Service worker SOLO para notificaciones push.
//
// A propósito NO cachea ni intercepta pedidos de red (no hay listener de
// 'fetch'): así no puede servir páginas viejas ni romper nada de la app. Lo
// único que hace es mostrar la notificación que llega y abrir la pantalla
// correspondiente cuando se la toca.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
    let datos = {};
    try { datos = event.data ? event.data.json() : {}; } catch (e) { datos = {}; }
    const titulo = datos.titulo || '{{ optica.nombre|escapejs }}';
    event.waitUntil(self.registration.showNotification(titulo, {
        body: datos.cuerpo || '',
        icon: '{% if optica.logo %}{{ optica.logo.url|escapejs }}{% else %}{% static "img/icon-192.png" %}{% endif %}',
        badge: '{% static "img/icon-192.png" %}',
        data: {url: datos.url || '/'},
    }));
});

// Al tocar la notificación: si ya hay una ventana abierta la reutiliza, si no abre una.
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const destino = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        self.clients.matchAll({type: 'window', includeUncontrolled: true}).then((ventanas) => {
            for (const v of ventanas) {
                if ('focus' in v) { v.navigate(destino); return v.focus(); }
            }
            if (self.clients.openWindow) return self.clients.openWindow(destino);
        })
    );
});
