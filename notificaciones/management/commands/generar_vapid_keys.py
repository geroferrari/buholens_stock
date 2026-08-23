import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid01


class Command(BaseCommand):
    help = (
        "Genera un par de claves VAPID para las notificaciones push. "
        "Copiá los valores a las variables de entorno VAPID_PUBLIC_KEY y "
        "VAPID_PRIVATE_KEY (la privada es secreta: nunca se commitea)."
    )

    def handle(self, *args, **options):
        vapid = Vapid01()
        vapid.generate_keys()

        def b64(raw):
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        privada = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        publica = vapid.private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        self.stdout.write(self.style.SUCCESS("Claves VAPID generadas:\n"))
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64(publica)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64(privada)}")
        self.stdout.write(
            self.style.WARNING("\nCargalas como variables de entorno (Railway → Variables). "
                               "La privada es secreta.")
        )
