import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import SuscripcionPush
from .services import enviar_con_detalle, push_configurado


@login_required
@require_GET
def estado_push(request):
    """Datos que el navegador necesita para suscribirse: la clave pública VAPID,
    la lista de personas (para elegir de quién es este dispositivo) y, si se pasa
    ?endpoint=, si ESTE dispositivo ya está suscripto y a nombre de quién."""
    from sales.models import Vendedor

    endpoint = request.GET.get("endpoint", "")
    suscripcion = SuscripcionPush.objects.filter(endpoint=endpoint).first() if endpoint else None
    return JsonResponse({
        "configurado": push_configurado(),
        "clave_publica": getattr(settings, "VAPID_PUBLIC_KEY", ""),
        "suscripto": bool(suscripcion),
        "vendedor_id": suscripcion.vendedor_id if suscripcion else None,
        "vendedor_nombre": suscripcion.vendedor.nombre if suscripcion and suscripcion.vendedor else "",
        "vendedores": list(Vendedor.objects.filter(activo=True).values("id", "nombre")),
    })


@login_required
@require_POST
def suscribir(request):
    """Guarda (o actualiza) la suscripción que generó el navegador."""
    try:
        datos = json.loads(request.body or "{}")
        endpoint = datos["endpoint"]
        claves = datos["keys"]
        p256dh, auth = claves["p256dh"], claves["auth"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Datos de suscripción inválidos."}, status=400)

    from sales.models import Vendedor

    # De quién es este dispositivo (opcional): permite avisarle a la persona
    # correcta aunque varias compartan el mismo usuario.
    vendedor = None
    vendedor_id = datos.get("vendedor_id")
    if vendedor_id:
        vendedor = Vendedor.objects.filter(pk=vendedor_id, activo=True).first()

    SuscripcionPush.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "usuario": request.user,
            "vendedor": vendedor,
            "p256dh": p256dh,
            "auth": auth,
            "dispositivo": request.META.get("HTTP_USER_AGENT", "")[:300],
        },
    )
    return JsonResponse({"ok": True, "vendedor": vendedor.nombre if vendedor else ""})


@login_required
@require_POST
def desuscribir(request):
    """Da de baja este dispositivo (el usuario apagó los avisos)."""
    try:
        endpoint = json.loads(request.body or "{}").get("endpoint", "")
    except ValueError:
        endpoint = ""
    if endpoint:
        SuscripcionPush.objects.filter(usuario=request.user, endpoint=endpoint).delete()
    else:
        request.user.suscripciones_push.all().delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def probar(request):
    """Manda una notificación de prueba a ESTE dispositivo (o a todos los del
    usuario si no se pasa el endpoint). Devuelve el motivo si algo falla, para
    poder diagnosticar sin tener que mirar los logs del servidor."""
    if not push_configurado():
        return JsonResponse({
            "ok": False, "enviadas": 0,
            "error": "El servidor no tiene cargadas las claves VAPID (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY).",
        })

    try:
        endpoint = json.loads(request.body or "{}").get("endpoint", "")
    except ValueError:
        endpoint = ""

    suscripciones = request.user.suscripciones_push.all()
    if endpoint:
        suscripciones = suscripciones.filter(endpoint=endpoint)
    suscripciones = list(suscripciones)
    if not suscripciones:
        return JsonResponse({
            "ok": False, "enviadas": 0,
            "error": "Este dispositivo no figura suscrito. Probá desactivar y volver a activar los avisos.",
        })

    enviadas, errores = enviar_con_detalle(
        suscripciones,
        titulo="🔔 Probando avisos",
        cuerpo="Si ves esto, las notificaciones están funcionando.",
        url="/",
    )
    return JsonResponse({
        "ok": enviadas > 0, "enviadas": enviadas, "error": " | ".join(errores),
    })
