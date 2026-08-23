"""
Envío de notificaciones push (Web Push) a los navegadores suscritos.

Todo acá está pensado para no romper nunca el flujo que lo llama: si el push
no está configurado, si el navegador se desuscribió o si el servicio de push
falla, se ignora en silencio (y se borra la suscripción muerta si corresponde).
Agendar una prueba tiene que funcionar igual aunque el aviso no salga.
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def push_configurado():
    """True si hay claves VAPID cargadas (si no, el push queda desactivado)."""
    return bool(getattr(settings, "VAPID_PUBLIC_KEY", "") and getattr(settings, "VAPID_PRIVATE_KEY", ""))


def _detalle_error(suscripcion, codigo, exc):
    """Mensaje corto y accionable para mostrar/loguear cuando un envío falla."""
    servicio = "Apple" if "push.apple.com" in suscripcion.endpoint else (
        "Google" if "googleapis.com" in suscripcion.endpoint or "google.com" in suscripcion.endpoint else "el servicio de push"
    )
    cuerpo = ""
    respuesta = getattr(exc, "response", None)
    if respuesta is not None:
        cuerpo = (getattr(respuesta, "text", "") or "")[:200]
    if codigo == 403:
        # Apple es estricta con el 'sub' del token: exige un mailto: con dominio
        # real. Un VAPID_CONTACTO inventado (ej: @optica.local) da BadJwtToken,
        # aunque Google lo acepte sin chistar.
        if "BadJwtToken" in cuerpo or "InvalidJwt" in cuerpo:
            return (f"{servicio} rechazó el token de firma (BadJwtToken). Lo más común es que "
                    f"VAPID_CONTACTO no sea un mail real: hoy vale '{settings.VAPID_CONTACTO}'. "
                    f"Poné un mail de verdad en esa variable y redeployá. Detalle: {cuerpo}")
        return (f"{servicio} rechazó las credenciales (403). Puede que las claves VAPID del servidor "
                f"no sean las mismas con las que se suscribió este dispositivo: probá desactivar y "
                f"volver a activar los avisos. Detalle: {cuerpo}")
    if codigo == 400:
        return (f"{servicio} rechazó el pedido (400). Suele ser el mail de contacto (VAPID_CONTACTO) "
                f"inválido o mal formado. Detalle: {cuerpo}")
    if codigo in (404, 410):
        return f"La suscripción de este dispositivo ya no existe ({codigo}): hay que volver a activarla."
    return f"{servicio} devolvió {codigo}. Detalle: {cuerpo or exc}"


def _enviar_a_suscripcion(suscripcion, payload):
    """Manda el push a un dispositivo. Devuelve None si salió bien, o un texto
    con el motivo si falló. Si el navegador ya no existe (404/410), además
    borra la suscripción."""
    try:
        # El import va acá adentro a propósito: si falta la dependencia en el
        # servidor, se informa como un error más (y no tumba el request).
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.error("Falta la dependencia 'pywebpush' en el servidor: el push no puede enviarse.")
        return ("Falta instalar 'pywebpush' en el servidor. Está en requirements.txt: "
                "hay que commitearlo y redeployar.")

    try:
        webpush(
            subscription_info={
                "endpoint": suscripcion.endpoint,
                "keys": {"p256dh": suscripcion.p256dh, "auth": suscripcion.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_CONTACTO}"},
            timeout=10,
        )
        return None
    except WebPushException as exc:
        codigo = getattr(exc.response, "status_code", None)
        motivo = _detalle_error(suscripcion, codigo, exc)
        if codigo in (404, 410):
            suscripcion.delete()
            logger.info("Suscripción push dada de baja (%s): %s", codigo, suscripcion.endpoint[:60])
        else:
            logger.warning("Falló el envío de push (%s): %s", codigo, exc)
        return motivo
    except Exception as exc:  # timeouts, DNS, etc: nunca deben romper al que llama
        logger.exception("Error inesperado enviando push")
        return f"Error inesperado al enviar: {exc}"


def enviar_con_detalle(suscripciones, titulo, cuerpo, url="/"):
    """Como los envíos normales, pero devuelve (enviadas, [motivos de falla]).
    Se usa para el botón 'Probar' y el comando de diagnóstico."""
    payload = {"titulo": titulo, "cuerpo": cuerpo, "url": url}
    enviadas, errores = 0, []
    for s in suscripciones:
        motivo = _enviar_a_suscripcion(s, payload)
        if motivo is None:
            enviadas += 1
        else:
            errores.append(motivo)
    return enviadas, errores


def _enviar_a_varias(suscripciones, titulo, cuerpo, url):
    return enviar_con_detalle(suscripciones, titulo, cuerpo, url)[0]


def enviar_push_a_usuario(usuario, titulo, cuerpo, url="/"):
    """Manda una notificación a todos los dispositivos de ese usuario.
    Devuelve cuántas salieron (0 si no hay nada configurado/suscrito)."""
    if not usuario or not usuario.is_authenticated or not push_configurado():
        return 0
    return _enviar_a_varias(usuario.suscripciones_push.all(), titulo, cuerpo, url)


def enviar_push_a_vendedor(vendedor, titulo, cuerpo, url="/"):
    """Manda la notificación a los dispositivos de ESA persona.

    Primero busca los celulares registrados a nombre de ese vendedor (lo que
    permite avisarle a la persona correcta aunque comparta el login con otras).
    Si no hay ninguno, cae en los dispositivos del usuario vinculado que
    todavía no declararon de quién son.
    """
    if not vendedor or not push_configurado():
        return 0
    propios = list(vendedor.suscripciones_push.all())
    if propios:
        return _enviar_a_varias(propios, titulo, cuerpo, url)
    if vendedor.usuario_id:
        sin_dueño = vendedor.usuario.suscripciones_push.filter(vendedor__isnull=True)
        return _enviar_a_varias(sin_dueño, titulo, cuerpo, url)
    return 0
