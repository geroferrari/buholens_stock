from django.db import models

from customers.models import Cliente
from sales.models import Vendedor, Venta


class PruebaLentesContacto(models.Model):
    """
    Una prueba de lentes de contacto que se le agenda a un/a vendedor/a en un
    horario puntual. Si la prueba termina en venta, se registra como una Venta
    real del sistema (linkeada acá), con todo lo del punto de venta: productos,
    forma de pago, promociones, etc.
    """

    class Estado(models.TextChoices):
        AGENDADA = "AGE", "Agendada"
        REALIZADA = "REA", "Realizada"
        CANCELADA = "CAN", "Cancelada"

    # Cliente: puede ser uno ya cargado, o alguien que todavía no es cliente
    # (recién viene a probarse) — en ese caso se usa nombre_suelto.
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, null=True, blank=True,
        related_name="pruebas_lentes_contacto",
    )
    nombre_suelto = models.CharField(
        max_length=120, blank=True,
        help_text="Nombre de quien se prueba, si todavía no está cargado como cliente.",
    )
    telefono = models.CharField(max_length=40, blank=True)

    vendedor = models.ForeignKey(
        Vendedor, on_delete=models.PROTECT, related_name="pruebas_lentes_contacto",
        help_text="Quién hace la prueba.",
    )

    fecha_hora = models.DateTimeField(help_text="Cuándo está agendada la prueba.")
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.AGENDADA)

    # Si la prueba terminó en venta, se registra como una Venta real del POS y
    # se linkea acá. El monto de la comisión sale del total de esa venta.
    venta = models.ForeignKey(
        Venta, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="prueba_lentes",
        help_text="Venta que generó esta prueba (si terminó en venta).",
    )

    # Graduación del cliente cargada para esta prueba: al agendar se ofrece
    # cargarla, así queda en el sistema y la vendedora la tiene a mano.
    receta = models.ForeignKey(
        "prescriptions.Receta", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pruebas_lentes_contacto",
        help_text="Graduación del cliente asociada a esta prueba.",
    )

    observaciones = models.TextField(blank=True)
    # Se marca cuando ya se mandó el recordatorio del día de la prueba, para
    # que el comando pueda correr varias veces sin avisar dos veces lo mismo.
    recordatorio_enviado = models.BooleanField(
        default=False,
        help_text="Ya se envió el aviso recordatorio del día de la prueba.",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha_hora"]
        verbose_name = "prueba de lentes de contacto"
        verbose_name_plural = "pruebas de lentes de contacto"
        indexes = [
            # La agenda, el recordatorio diario y el reporte de comisión filtran
            # por estado + fecha_hora.
            models.Index(fields=["estado", "fecha_hora"], name="prueba_estado_fecha_idx"),
        ]

    def __str__(self):
        return f"Prueba {self.nombre_cliente} - {self.fecha_hora:%d/%m/%Y %H:%M}"

    @property
    def nombre_cliente(self):
        """Nombre a mostrar: el cliente cargado, o el nombre suelto, o un placeholder."""
        if self.cliente_id:
            return self.cliente.nombre_completo
        return self.nombre_suelto or "Sin nombre"

    @property
    def telefono_contacto(self):
        """Teléfono a usar: el propio de la prueba o, si no, el del cliente."""
        if self.telefono:
            return self.telefono
        if self.cliente_id:
            return self.cliente.telefono
        return ""

    @property
    def venta_abierta(self):
        """Tiene una venta linkeada que todavía se está armando en el POS."""
        return bool(self.venta_id) and self.venta.estado == Venta.Estado.ABIERTA

    @property
    def venta_confirmada(self):
        """Tiene una venta linkeada ya confirmada (cerrada)."""
        return bool(self.venta_id) and self.venta.estado == Venta.Estado.CONFIRMADA

    @property
    def monto_venta(self):
        """Monto de la venta que salió de la prueba. Solo cuenta si la venta
        linkeada está confirmada; si no, todavía no hay plata firme."""
        if self.venta_confirmada:
            return self.venta.total
        return None

    @property
    def color_estado(self):
        """Clase de color de Bootstrap para badges/filas según el estado."""
        return {
            self.Estado.AGENDADA: "warning",
            self.Estado.REALIZADA: "success",
            self.Estado.CANCELADA: "secondary",
        }.get(self.estado, "secondary")
