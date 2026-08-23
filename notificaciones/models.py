from django.db import models


class SuscripcionPush(models.Model):
    """
    Un navegador/dispositivo suscrito a notificaciones push para un usuario.
    Un mismo usuario puede tener varias (celular, computadora del local, etc).
    Los datos los genera el navegador al aceptar el permiso de notificaciones;
    acá solo se guardan para poder mandarle avisos después.
    """
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.CASCADE, related_name="suscripciones_push",
    )
    # De quién es este celular. Como varias personas comparten el mismo login
    # (la compu del mostrador), el usuario no alcanza para saber a quién
    # avisarle: al activar los avisos se elige quién usa ESTE dispositivo, y
    # así la notificación le llega a la persona correcta igual.
    vendedor = models.ForeignKey(
        "sales.Vendedor", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="suscripciones_push",
        help_text="Quién usa este dispositivo (se elige al activar los avisos).",
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    dispositivo = models.CharField(
        max_length=300, blank=True, help_text="User-Agent, para reconocer de qué equipo es.",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "suscripción push"
        verbose_name_plural = "suscripciones push"

    def __str__(self):
        return f"Push de {self.usuario} ({self.endpoint[:40]}...)"
