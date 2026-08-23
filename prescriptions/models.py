from django.db import models

from core.models import SoftDeleteModel
from customers.models import Cliente, ObraSocial


class Medico(models.Model):
    nombre = models.CharField(max_length=150)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Receta(SoftDeleteModel):
    """
    Receta óptica de un cliente, con graduación de Lejos y de Cerca por separado
    (como en el sistema actual). Se guarda un registro por cada control/pedido,
    para mantener historial.
    """

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="recetas")
    fecha_recibido = models.DateField()
    fecha_entrega = models.DateField(null=True, blank=True)
    medico = models.ForeignKey(
        Medico, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="recetas", help_text="Oftalmólogo/a que la emitió",
    )
    obra_social = models.ForeignKey(
        ObraSocial, on_delete=models.SET_NULL, null=True, blank=True, related_name="recetas",
    )

    # --- Lejos ---
    lejos_od_esfera = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_od_cilindro = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_od_eje = models.IntegerField(null=True, blank=True)
    lejos_od_adicion = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_oi_esfera = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_oi_cilindro = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_oi_eje = models.IntegerField(null=True, blank=True)
    lejos_oi_adicion = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    lejos_dnp = models.CharField(max_length=30, blank=True, help_text="Ej: '31/31.5'")
    lejos_tipo_cristal = models.CharField(max_length=60, blank=True)
    lejos_color_cristal = models.CharField(max_length=60, blank=True)
    lejos_tratamientos = models.CharField(max_length=150, blank=True, help_text="Ej: antirreflejo, filtro azul")

    # --- Cerca ---
    cerca_od_esfera = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cerca_od_cilindro = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cerca_od_eje = models.IntegerField(null=True, blank=True)
    cerca_oi_esfera = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cerca_oi_cilindro = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cerca_oi_eje = models.IntegerField(null=True, blank=True)
    cerca_dnp = models.CharField(max_length=30, blank=True)
    cerca_tipo_cristal = models.CharField(max_length=60, blank=True)
    cerca_color_cristal = models.CharField(max_length=60, blank=True)
    cerca_tratamientos = models.CharField(max_length=150, blank=True)

    # --- Bifocal / multifocal ---
    es_bifocal_multifocal = models.CharField(max_length=60, blank=True, help_text="Tipo, si aplica")
    di_lejos = models.CharField(max_length=30, blank=True)
    di_cerca = models.CharField(max_length=30, blank=True)
    altura = models.CharField(max_length=30, blank=True)

    # --- Lentes de contacto ---
    es_lentes_contacto = models.BooleanField(
        default=False, help_text="La receta es para lentes de contacto.",
    )
    marca_lentes_contacto = models.CharField(
        max_length=80, blank=True, help_text="Marca de los lentes de contacto (si es para lentes de contacto).",
    )

    observaciones = models.TextField(blank=True)
    archivo = models.FileField(
        upload_to="recetas/", null=True, blank=True,
        help_text="Foto/escaneo de la receta original",
    )
    entregada = models.BooleanField(
        default=False,
        help_text="Marcar cuando el cliente retira el pedido terminado.",
    )

    correcciones = models.JSONField(
        default=dict, blank=True,
        help_text="Valor anterior de cada campo que se corrigió, para mostrarlo tachado junto al nuevo.",
    )

    cargada_por = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="recetas_cargadas",
        help_text="Usuario que cargó la receta en el sistema (para el historial de carga de recetas).",
    )

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(
        auto_now=True,
        help_text="Cuándo se cargó o corrigió por última vez (para poder ordenar por 'última modificación').",
    )

    class Meta:
        ordering = ["-creado"]
        verbose_name_plural = "recetas"

    def __str__(self):
        return f"Receta {self.cliente} - {self.fecha_recibido}"


class OrdenLaboratorio(models.Model):
    """
    Orden para mandar al laboratorio: qué armazón se eligió + la receta con
    la que hay que armar los cristales, para un cliente puntual. Se genera
    normalmente desde el punto de venta al asociar una receta a un armazón,
    pero queda como registro propio (no depende de que la venta siga existiendo).
    """
    class Estado(models.TextChoices):
        PENDIENTE = "PEN", "Pendiente de enviar"
        ENVIADA = "ENV", "Enviada al laboratorio"
        RECIBIDA = "REC", "Recibida"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ordenes_laboratorio")
    receta = models.ForeignKey(Receta, on_delete=models.PROTECT, related_name="ordenes_laboratorio")
    producto = models.ForeignKey(
        "inventory.Producto", on_delete=models.PROTECT, related_name="ordenes_laboratorio",
        help_text="Producto que generó la orden (el cristal, si es el que lleva la receta asociada).",
    )
    armazon = models.ForeignKey(
        "inventory.Producto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Armazón donde se monta el cristal, si también se vendió en la misma venta.",
    )
    armazon_de_cliente = models.BooleanField(
        default=False, help_text="El cliente trajo su propio armazón.",
    )
    venta_item = models.ForeignKey(
        "sales.VentaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="orden_laboratorio",
        help_text="Ítem de venta que generó esta orden (si vino del punto de venta).",
    )
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.PENDIENTE)
    observaciones = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name_plural = "órdenes de laboratorio"

    def __str__(self):
        return f"Orden de laboratorio #{self.pk} - {self.cliente}"
