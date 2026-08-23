from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from core.models import SoftDeleteModel
from tenants.db_router import tenant_atomic
from customers.models import Cliente, ObraSocial
from inventory.models import Producto, MovimientoStock, Promocion
from prescriptions.models import OrdenLaboratorio, Receta


class Vendedor(models.Model):
    """
    Persona que atiende al mostrador. Es independiente del usuario de Django
    con el que se inició sesión en la computadora: varios empleados comparten
    una misma sesión/terminal, pero cada venta queda atribuida al vendedor
    que la eligió al confirmar.
    """
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="vendedores",
        help_text="Usuario con el que esta persona entra al sistema. Sirve para mandarle avisos "
        "al celular (ej: cuando le agendan una prueba de lentes de contacto).",
    )

    class Meta:
        ordering = ["nombre"]
        constraints = [
            # No dos vendedores con el mismo nombre (ignorando mayúsculas): así
            # no se acumulan duplicados accidentales (ej: varios "Ana") desde
            # ningún lado (formulario, admin o scripts).
            models.UniqueConstraint(Lower("nombre"), name="vendedor_nombre_unico_ci"),
        ]

    def __str__(self):
        return self.nombre


class Venta(SoftDeleteModel):
    class Estado(models.TextChoices):
        ABIERTA = "OPEN", "Abierta"
        CONFIRMADA = "DONE", "Confirmada"
        ANULADA = "VOID", "Anulada"

    class FormaPago(models.TextChoices):
        EFECTIVO = "EFE", "Efectivo"
        TARJETA = "TAR", "Tarjeta"
        TRANSFERENCIA = "TRA", "Transferencia"
        QR = "QR", "QR"

    cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas"
    )
    receta_sugerida = models.ForeignKey(
        Receta, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Receta que el vendedor eligió asociar a esta venta al elegir el cliente: los "
        "items que requieran receta la usan de default (se puede cambiar por item igual).",
    )
    vendedor = models.ForeignKey(
        Vendedor, on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas",
        help_text="Empleado que atendió la venta.",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=4, choices=Estado.choices, default=Estado.ABIERTA)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas"
    )
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Forma de pago del pago inicial (el total si paga todo de una, o la seña
    # si deja el resto para cuando retira). El pago del saldo puede ser con
    # otra forma de pago distinta, ver forma_pago_saldo más abajo.
    forma_pago = models.CharField(max_length=3, choices=FormaPago.choices, blank=True)
    cuotas = models.PositiveIntegerField(
        null=True, blank=True, help_text="Solo aplica si la forma de pago es tarjeta.",
    )
    forma_pago_saldo = models.CharField(
        max_length=3, choices=FormaPago.choices, blank=True,
        help_text="Forma de pago con la que se canceló el saldo (puede ser distinta a la de la seña).",
    )
    cuotas_saldo = models.PositiveIntegerField(null=True, blank=True)

    # --- Descuento manual: además de las promociones por producto, un
    # descuento puntual sobre el total de la venta (ej: "le hago un 10% extra
    # a este cliente"), a criterio del vendedor/a. ---
    class TipoDescuentoManual(models.TextChoices):
        PORCENTAJE = "PCT", "Porcentaje"
        MONTO_FIJO = "FIJ", "Monto fijo"

    descuento_manual_tipo = models.CharField(max_length=3, choices=TipoDescuentoManual.choices, blank=True)
    descuento_manual_valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # --- Reservas / encargos: el cliente puede pagar parcial (seña) y/o
    # retirar el pedido más adelante (ej: mientras se hacen los cristales). El
    # stock ya se descuenta al confirmar (queda "reservado" para ese cliente),
    # independientemente de cuánto pagó o si ya se lo llevó. ---
    monto_pagado = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Cuánto pagó el cliente hasta ahora (puede ser menor al total si dejó una seña).",
    )
    tiene_incidencias = models.BooleanField(
        default=False,
        help_text="Se marca sola si durante la venta hubo que forzar stock insuficiente o se "
        "escaneó un código que no existía, para poder revisarlo después.",
    )
    incidencias_detalle = models.TextField(blank=True)
    observaciones = models.TextField(
        blank=True,
        help_text="Notas a mano del vendedor/a sobre esta venta puntual (ej: algo que pasó "
        "durante la atención), para que quede registrado junto a la venta.",
    )

    notificado = models.BooleanField(
        default=False,
        help_text="Se avisó al cliente (ej: por WhatsApp) que su pedido está listo para retirar.",
    )

    # --- Ventas por obra social: muy customizado según cada obra social (puede
    # que el cliente no pague nada en el momento), así que por ahora solo se
    # marca que la venta es por obra social y queda en una cola aparte para
    # que el dueño del negocio la revise y la termine a mano. ---
    es_obra_social = models.BooleanField(
        default=False,
        help_text="La venta se gestiona por obra social: puede que el cliente no pague nada en el "
        "momento. Queda en 'Ventas por obra social' para revisar y terminar a mano.",
    )
    obra_social = models.ForeignKey(
        ObraSocial, on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas",
        help_text="Qué obra social se usa en esta venta (si es_obra_social).",
    )
    obra_social_resuelta = models.BooleanField(
        default=False,
        help_text="Se marca a mano cuando ya se terminó de gestionar la venta con la obra social "
        "(ej: se cobró o se descartó el trámite).",
    )

    class Meta:
        ordering = ["-fecha"]
        indexes = [
            # La caja, el dashboard y los reportes filtran por estado + fecha
            # (ej: ventas confirmadas de un día/rango). Índice compuesto para
            # que no degrade cuando se acumulen años de ventas.
            models.Index(fields=["estado", "fecha"], name="venta_estado_fecha_idx"),
        ]

    def __str__(self):
        return f"Venta #{self.pk} - {self.cliente or 'Consumidor final'} ({self.get_estado_display()})"

    def recalcular_total(self):
        subtotal = sum((item.subtotal for item in self.items.all()), start=0)
        descuento = 0
        if self.descuento_manual_valor:
            if self.descuento_manual_tipo == self.TipoDescuentoManual.PORCENTAJE:
                descuento = subtotal * (self.descuento_manual_valor / 100)
            elif self.descuento_manual_tipo == self.TipoDescuentoManual.MONTO_FIJO:
                descuento = self.descuento_manual_valor
        self.total = max(subtotal - descuento, 0)
        self.save(update_fields=["total"])

    def registrar_incidencia(self, texto):
        """Marca la venta para revisar después (ej: se forzó stock insuficiente,
        o se escaneó un código que no existía), acumulando el detalle."""
        self.tiene_incidencias = True
        self.incidencias_detalle = f"{self.incidencias_detalle}\n{texto}" if self.incidencias_detalle else texto
        self.save(update_fields=["tiene_incidencias", "incidencias_detalle"])

    @property
    def subtotal(self):
        """Total antes del descuento manual (pero ya con las promociones por
        producto aplicadas) — para poder mostrar el "antes/después" del
        descuento manual en el carrito."""
        return sum((item.subtotal for item in self.items.all()), start=0)

    @property
    def saldo_pendiente(self):
        return max(self.total - self.monto_pagado, 0)

    @property
    def entregado(self):
        """True solo si TODOS los items ya se entregaron — la entrega se
        controla por ítem (puede que se lleve el armazón hoy y los cristales,
        hechos a medida, los retire después), esto es solo un resumen."""
        return not self.items.filter(entregado=False).exists()

    @property
    def estado_entrega(self):
        """Resumen de 3 estados para mostrar en los listados: Entregado
        (todos los items), Notificado (se avisó pero todavía no lo retiró) o
        Pendiente (ni siquiera se avisó)."""
        if self.entregado:
            return "entregado"
        if self.notificado:
            return "notificado"
        return "pendiente"

    @tenant_atomic
    def confirmar(self, monto_pagado=None):
        """Descuenta stock de todos los items y cierra la venta. Todo o nada.
        `monto_pagado` puede ser menor al total (seña). La entrega se
        controla por ítem (VentaItem.entregado, tildado por default) — cada
        uno se puede destildar desde el carrito antes de confirmar, para el
        caso de una reserva/encargo que el cliente retira después."""
        if self.estado != self.Estado.ABIERTA:
            raise ValidationError("Solo se pueden confirmar ventas abiertas.")
        if not self.vendedor_id:
            raise ValidationError("Elegí qué vendedor/a atendió la venta antes de confirmar.")
        if not self.forma_pago and not self.es_obra_social:
            raise ValidationError("Elegí la forma de pago antes de confirmar la venta.")
        if self.forma_pago == self.FormaPago.TARJETA and not self.cuotas:
            raise ValidationError("Indicá la cantidad de cuotas para el pago con tarjeta.")

        items = list(self.items.select_related("producto").select_for_update())
        if not items:
            raise ValidationError("La venta no tiene items.")

        for item in items:
            producto = Producto.objects.select_for_update().get(pk=item.producto_id)
            if producto.categoria.controla_stock and producto.stock_actual < item.cantidad:
                raise ValidationError(
                    f"Stock insuficiente para {producto}: quedan {producto.stock_actual}, "
                    f"se intentan vender {item.cantidad}."
                )
            # La receta es opcional aun para cristales / lentes de contacto: puede
            # ser una venta sin aumento. Se puede asociar, pero no se exige.

        for item in items:
            if not item.producto.categoria.controla_stock:
                continue
            MovimientoStock.objects.create(
                producto=item.producto,
                tipo=MovimientoStock.Tipo.EGRESO,
                cantidad=item.cantidad,
                usuario=self.usuario,
                nota=f"Venta #{self.pk} ({self.vendedor.nombre})",
                venta_item=item,
            )

        self.recalcular_total()
        if monto_pagado is not None:
            self.monto_pagado = monto_pagado
        elif self.es_obra_social:
            self.monto_pagado = 0
        else:
            self.monto_pagado = self.total
        # Nunca se registra un pago mayor al total (no hay saldo a favor / crédito):
        # si el cliente da de más, el vuelto se maneja en efectivo, no queda en el
        # sistema. También se descartan negativos.
        self.monto_pagado = max(min(self.monto_pagado, self.total), 0)
        # En una venta por obra social el cliente puede abonar una parte ahora
        # (una seña / lo que le corresponde pagar): si abona algo, necesitamos
        # saber con qué forma de pago lo hizo.
        if self.es_obra_social and self.monto_pagado > 0 and not self.forma_pago:
            raise ValidationError("Elegí la forma de pago de lo que abona el cliente por la obra social.")
        self.estado = self.Estado.CONFIRMADA
        self.save(update_fields=["estado", "monto_pagado"])

    def registrar_pago_y_entrega(self, monto_adicional=None, forma_pago_saldo="", cuotas_saldo=None):
        """Para completar más adelante una venta ya confirmada: sumar un pago
        adicional (ej: el cliente vino a pagar el saldo, con la forma de pago
        que haya elegido para esa parte, distinta o no de la de la seña).
        Marcar la entrega de cada ítem es aparte, ver VentaItem.entregado."""
        campos = ["monto_pagado"]
        if monto_adicional:
            self.monto_pagado = self.monto_pagado + monto_adicional
            if forma_pago_saldo:
                self.forma_pago_saldo = forma_pago_saldo
                self.cuotas_saldo = cuotas_saldo
                campos += ["forma_pago_saldo", "cuotas_saldo"]
        self.save(update_fields=campos)

    @tenant_atomic
    def eliminar_definitivo(self, using=None, keep_parents=False):
        """Al borrar DEFINITIVAMENTE una venta confirmada, se devuelve al stock
        lo que había descontado (la venta deja de existir, el stock vuelve). Se
        registra un ingreso por cada ítem con control de stock, y recién ahí se
        elimina de verdad. Mientras está en la papelera (borrado suave) el stock
        NO se toca, por si se recupera."""
        if self.estado == self.Estado.CONFIRMADA:
            for item in self.items.select_related("producto__categoria"):
                if item.producto.categoria.controla_stock:
                    MovimientoStock.objects.create(
                        producto=item.producto,
                        tipo=MovimientoStock.Tipo.INGRESO,
                        cantidad=item.cantidad,
                        usuario=self.usuario,
                        nota=f"Devolución de stock por eliminación de la venta #{self.pk}.",
                    )
        else:
            # Venta que se cancela sin haberse confirmado: si se llegó a
            # generar alguna orden de laboratorio de prueba mientras se
            # armaba el carrito, no tiene que quedar huérfana en el sistema
            # (el FK a venta_item es SET_NULL, no CASCADE, porque para una
            # venta CONFIRMADA sí interesa conservar la orden como historial
            # aunque la venta se borre después).
            OrdenLaboratorio.objects.filter(venta_item__venta=self).delete()
        return super().eliminar_definitivo(using=using, keep_parents=keep_parents)


class VentaItem(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="ventas_items")
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    entregado = models.BooleanField(
        default=True,
        help_text="Destildar si este ítem puntual todavía no se entregó (ej: cristal a medida "
        "en el laboratorio, mientras el armazón ya se lo llevó).",
    )

    # Si el producto es un cristal (o requiere receta), se asocia la receta usada
    receta = models.ForeignKey(
        Receta, on_delete=models.SET_NULL, null=True, blank=True, related_name="items_vendidos"
    )

    # Un cristal se monta en un armazón: si ese armazón también se vendió en
    # esta misma venta (como otro item), se lo asocia acá para que la orden
    # de laboratorio sepa en qué armazón montarlo. Si el cliente trajo su
    # propio armazón (no se vendió ninguno en esta venta), se usa el flag de
    # abajo en cambio. Son mutuamente excluyentes.
    armazon_venta_item = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="cristales_asociados",
        help_text="Item de esta misma venta que es el armazón donde se monta este cristal.",
    )
    armazon_de_cliente = models.BooleanField(
        default=False,
        help_text="El cliente trajo su propio armazón: no se vendió ninguno en esta venta.",
    )

    # Si el producto tenía una promoción vigente al momento de agregarlo, queda
    # registrada acá (para reportes) y el precio_unitario ya viene con el
    # descuento aplicado.
    promocion = models.ForeignKey(
        "inventory.Promocion", on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas_items"
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.cantidad} x {self.producto}"

    def grupo_entrega(self):
        """Items que se entregan siempre juntos: un cristal y el armazón de
        esta misma venta donde se monta (no tiene sentido entregar uno sin el
        otro). Incluye a `self`."""
        if self.armazon_venta_item_id:
            return [self, self.armazon_venta_item]
        return [self, *self.cristales_asociados.all()]

    @property
    def subtotal(self):
        # El 2x1 no se puede representar como un precio unitario fijo (el
        # descuento depende de cuántas unidades se llevan): cada par de
        # unidades solo cobra una, y si la cantidad es impar la última
        # unidad suelta se cobra entera.
        if self.promocion_id and self.promocion.tipo_descuento == Promocion.TipoDescuento.DOS_POR_UNO:
            unidades_a_pagar = self.cantidad - (self.cantidad // 2)
            return unidades_a_pagar * self.precio_unitario
        return self.cantidad * self.precio_unitario

    @property
    def subtotal_sin_promocion(self):
        """Lo que costaría este item al precio actual de catálogo, sin
        ninguna promoción — para mostrar el descuento real en el carrito
        (incluye el caso 2x1, donde el precio unitario no cambia)."""
        return self.cantidad * self.producto.precio

    # La receta es opcional: para cristales / lentes de contacto se puede
    # asociar una (ver Categoria.usa_receta, que ahora significa "trabaja
    # con recetas"), pero nunca es obligatoria — puede ser una venta sin aumento.


class Devolucion(models.Model):
    """
    Registro de una devolución de mercadería. Si el producto controla stock,
    reingresa automáticamente (vía MovimientoStock) al confirmarse. Los
    cristales u otros productos a medida no generan movimiento de stock, pero
    igual queda el registro para llevar cuenta de reintegros/reclamos.
    """
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="devoluciones")
    venta_item = models.ForeignKey(
        VentaItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="devoluciones"
    )
    cantidad = models.PositiveIntegerField(default=1)
    monto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    motivo = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="devoluciones"
    )

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"Devolución de {self.cantidad} x {self.producto} (${self.monto})"
