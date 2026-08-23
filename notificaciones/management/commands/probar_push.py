from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from notificaciones.models import SuscripcionPush
from notificaciones.services import enviar_con_detalle, push_configurado


class Command(BaseCommand):
    help = (
        "Diagnostica las notificaciones push: muestra si las claves están cargadas, "
        "qué dispositivos hay suscritos y manda una notificación de prueba mostrando "
        "el error exacto si falla. Ej: python manage.py probar_push --usuario ana"
    )

    def add_arguments(self, parser):
        parser.add_argument("--usuario", help="Mandar solo a los dispositivos de este usuario.")
        parser.add_argument("--enviar", action="store_true", help="Además de diagnosticar, manda la prueba.")

    def handle(self, *args, **options):
        self.stdout.write("== Configuración ==")
        publica = getattr(settings, "VAPID_PUBLIC_KEY", "")
        privada = getattr(settings, "VAPID_PRIVATE_KEY", "")
        self.stdout.write(f"  VAPID_PUBLIC_KEY : {'cargada (' + publica[:12] + '…)' if publica else 'FALTA'}")
        self.stdout.write(f"  VAPID_PRIVATE_KEY: {'cargada' if privada else 'FALTA'}")
        contacto = getattr(settings, "VAPID_CONTACTO", "")
        self.stdout.write(f"  VAPID_CONTACTO   : {contacto}")
        # Apple valida este mail: con un dominio inventado devuelve BadJwtToken
        # y NO llegan las notificaciones a iPhone (Google en cambio lo acepta).
        if (not contacto) or contacto.endswith(".local") or "@" not in contacto:
            self.stdout.write(self.style.ERROR(
                "  ⚠ Ese mail no parece real. Apple lo rechaza (BadJwtToken) y no van a llegar\n"
                "    las notificaciones a iPhone. Poné un mail de verdad en VAPID_CONTACTO."
            ))
        if not push_configurado():
            self.stdout.write(self.style.ERROR(
                "\nFaltan las claves VAPID: el push está desactivado. Cargalas en las variables de entorno."
            ))
            return

        suscripciones = SuscripcionPush.objects.select_related("usuario", "vendedor")
        if options["usuario"]:
            usuario = User.objects.filter(username=options["usuario"]).first()
            if not usuario:
                self.stdout.write(self.style.ERROR(f"No existe el usuario '{options['usuario']}'."))
                return
            suscripciones = suscripciones.filter(usuario=usuario)

        suscripciones = list(suscripciones)
        self.stdout.write(f"\n== Dispositivos suscritos ({len(suscripciones)}) ==")
        for s in suscripciones:
            servicio = "Apple" if "apple.com" in s.endpoint else ("Google" if "google" in s.endpoint else "otro")
            duenio = s.vendedor.nombre if s.vendedor else "(sin persona elegida)"
            self.stdout.write(f"  #{s.pk} {s.usuario.username:12} → {duenio:12} [{servicio}] {s.endpoint[:50]}…")
        if not suscripciones:
            self.stdout.write(self.style.WARNING(
                "  Ninguno. Hay que entrar a la app y tocar 'Activar avisos' en el dispositivo."
            ))
            return

        if not options["enviar"]:
            self.stdout.write("\n(Agregá --enviar para mandar una notificación de prueba.)")
            return

        self.stdout.write("\n== Enviando prueba ==")
        enviadas, errores = enviar_con_detalle(
            suscripciones,
            titulo="🔔 Probando avisos",
            cuerpo="Prueba enviada desde el servidor.",
            url="/",
        )
        self.stdout.write(self.style.SUCCESS(f"  Enviadas OK: {enviadas}"))
        for motivo in errores:
            self.stdout.write(self.style.ERROR(f"  FALLÓ: {motivo}"))
