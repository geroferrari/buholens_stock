import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.db.models.functions import Lower
from django.utils import timezone

from core.models import SoftDeleteModel


class Marca(models.Model):
    """Marca/fabricante de un producto (ej: Ray-Ban, Vulk). Catálogo único,
    compartido entre Producto (qué marca es) y Proveedor (qué marcas trae)."""
    nombre = models.CharField(max_length=80)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="marca_nombre_ci_unique"),
        ]

    def __str__(self):
        return self.nombre


class Categoria(models.Model):
    """Ej: Armazón, Cristal, Lente de contacto, Accesorio."""
    nombre = models.CharField(max_length=60)
    usa_receta = models.BooleanField(
        "trabaja con recetas",
        default=False,
        help_text="Marcar para cristales / lentes de contacto: al venderse se les puede asociar una "
        "receta (opcional, puede ser una venta sin aumento). Los armazones NO: son solo el armazón.",
    )
    controla_stock = models.BooleanField(
        default=True,
        help_text=(
            "Desmarcar para categorías que no son stock físico (ej: cristales hechos a medida "
            "en laboratorio). Esos productos no se escanean ni descuentan stock: se eligen de una "
            "lista al vender y solo suman su precio."
        ),
    )

    class Meta:
        verbose_name_plural = "categorías"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="categoria_nombre_ci_unique"),
        ]

    def __str__(self):
        return self.nombre


class Proveedor(models.Model):
    nombre = models.CharField(max_length=120)
    contacto = models.CharField(max_length=120, blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    marcas = models.ManyToManyField(
        Marca, blank=True, related_name="proveedores",
        help_text="Qué marcas trae este proveedor.",
    )

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="proveedor_nombre_ci_unique"),
        ]

    def __str__(self):
        return self.nombre


class Producto(SoftDeleteModel):
    """
    Cada Producto es una variante única y vendible (un armazón de un color/talle
    específico, o un tipo de cristal). El codigo_barras (interno, generado por
    este sistema e impreso en etiqueta propia) identifica la unidad para el lector.

    Tiene papelera (SoftDeleteModel): borrarlo lo oculta y se puede recuperar.
    """
    codigo_barras = models.CharField(
        max_length=64, unique=True, db_index=True, blank=True,
        help_text="Código interno propio, el que se imprime en la etiqueta. Se genera solo si se deja vacío.",
    )
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.SET_NULL, null=True, blank=True, related_name="productos"
    )

    marca = models.ForeignKey(Marca, on_delete=models.PROTECT, related_name="productos")
    modelo = models.CharField(max_length=80)
    color = models.CharField(max_length=60, blank=True)
    color_cristal = models.CharField(max_length=60, blank=True)
    calibre = models.CharField(max_length=30, blank=True, help_text="Ancho del aro, ej: '52'")
    material = models.CharField(max_length=60, blank=True, help_text="Ej: Acetato, Metal, TR90")

    precio_costo = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, blank=True, help_text="Costo sin IVA",
    )
    porcentaje_iva = models.DecimalField(max_digits=5, decimal_places=2, default=21)
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Precio de venta, con IVA incluido")

    stock_actual = models.IntegerField(default=0)
    stock_minimo = models.IntegerField(
        default=0, blank=True, help_text="Para alertas de reposición (fase futura)",
    )

    activo = models.BooleanField(default=True)
    foto = models.ImageField(upload_to="productos/", null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria", "marca__nombre", "modelo"]

    def __str__(self):
        partes = [self.marca.nombre if self.marca_id else "", self.modelo, self.color]
        nombre = " ".join(p for p in partes if p)
        return f"{nombre or 'Producto'} [{self.codigo_barras}]"

    @property
    def margen_ganancia_pct(self):
        if self.precio_costo:
            return round(((self.precio - self.precio_costo) / self.precio_costo) * 100, 1)
        return None

    @staticmethod
    def generar_codigo_barras():
        """Código interno único (12 dígitos) para imprimir etiqueta propia."""
        return str(uuid.uuid4().int)[:12]

    def save(self, *args, **kwargs):
        """Si no se cargó código de barras, se genera acá: así queda garantizado
        sin importar por dónde se cree el producto (formulario, admin, scripts)."""
        if not self.codigo_barras:
            codigo = Producto.generar_codigo_barras()
            while Producto.objects.filter(codigo_barras=codigo).exclude(pk=self.pk).exists():
                codigo = Producto.generar_codigo_barras()
            self.codigo_barras = codigo
        super().save(*args, **kwargs)


class MovimientoStock(models.Model):
    class Tipo(models.TextChoices):
        INGRESO = "IN", "Ingreso"
        EGRESO = "OUT", "Egreso"
        AJUSTE = "ADJ", "Ajuste"

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    cantidad = models.IntegerField(help_text="Positivo siempre; en Ajuste puede representar resta si se usa negativo.")
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="movimientos_stock"
    )
    nota = models.CharField(max_length=255, blank=True)

    # Referencia opcional al item de venta que generó el egreso
    venta_item = models.ForeignKey(
        "sales.VentaItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="movimientos"
    )

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()} x{self.cantidad} - {self.producto}"

    def clean(self):
        if self.tipo == self.Tipo.EGRESO and self.producto_id and self.cantidad:
            if self.producto.stock_actual < self.cantidad:
                raise ValidationError("Stock insuficiente para este egreso.")

    def save(self, *args, **kwargs):
        """Actualiza stock_actual del producto en la misma operación."""
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            if self.tipo == self.Tipo.INGRESO:
                delta = self.cantidad
            elif self.tipo == self.Tipo.EGRESO:
                delta = -self.cantidad
            else:  # AJUSTE: cantidad ya viene con el signo deseado
                delta = self.cantidad
            Producto.objects.filter(pk=self.producto_id).update(
                stock_actual=models.F("stock_actual") + delta
            )


class EscaneoNoEncontrado(models.Model):
    """
    Registro de cada vez que se escaneó un código de barras que no corresponde
    a ningún producto cargado (típicamente en el punto de venta). Queda acá
    para que alguien pueda revisar después qué pasó: ¿el producto nunca se
    cargó?, ¿se tipeó mal el código?, ¿es un producto de otro local?
    """
    class Origen(models.TextChoices):
        VENTA = "VTA", "Punto de venta"
        INGRESO = "ING", "Ingreso rápido de stock"

    codigo_barras = models.CharField(max_length=64)
    origen = models.CharField(max_length=3, choices=Origen.choices, default=Origen.VENTA)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="escaneos_no_encontrados"
    )
    venta = models.ForeignKey(
        "sales.Venta", on_delete=models.SET_NULL, null=True, blank=True, related_name="escaneos_no_encontrados",
        help_text="Si el escaneo ocurrió durante una venta, referencia a esa venta.",
    )
    atendido = models.BooleanField(
        default=False, help_text="Marcar cuando ya se revisó/resolvió (ej: se cargó el producto).",
    )

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "escaneos no encontrados"

    def __str__(self):
        return f"{self.codigo_barras} ({self.get_origen_display()}, {self.fecha:%d/%m/%Y %H:%M})"


class Promocion(models.Model):
    class TipoDescuento(models.TextChoices):
        PORCENTAJE = "PCT", "Porcentaje"
        MONTO_FIJO = "FIJ", "Monto fijo"
        DOS_POR_UNO = "2X1", "2x1 (cada 2 unidades, 1 es gratis)"

    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    tipo_descuento = models.CharField(max_length=3, choices=TipoDescuento.choices, default=TipoDescuento.PORCENTAJE)
    valor = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Si es porcentaje: un número de 0 a 100 (ej 15). Si es monto fijo: el descuento en "
        "$. Si es 2x1, no se usa (dejar en 0).",
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True, help_text="Dejar vacío si no tiene fecha de fin definida.")
    activa = models.BooleanField(default=True)

    # Alcance: a qué productos afecta. Si TODOS quedan vacíos, la promo no
    # aplica a nada (hay que completar al menos uno para que tenga efecto).
    # Si se completa alguno, aplica a lo que matchee (categoría, marca
    # puntual, o producto puntual — cualquiera de los tres).
    categorias = models.ManyToManyField(Categoria, blank=True, related_name="promociones")
    productos = models.ManyToManyField(Producto, blank=True, related_name="promociones")
    marcas = models.CharField(
        max_length=500, blank=True,
        help_text="Marcas separadas por coma (ej: Ray-Ban, Oakley). Vacío = no filtra por marca.",
    )

    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_inicio"]

    def __str__(self):
        return self.nombre

    def esta_vigente(self, fecha=None):
        fecha = fecha or timezone.localdate()
        if not self.activa:
            return False
        if fecha < self.fecha_inicio:
            return False
        if self.fecha_fin and fecha > self.fecha_fin:
            return False
        return True

    def _lista_marcas(self):
        return [m.strip().lower() for m in self.marcas.split(",") if m.strip()]

    def aplica_a(self, producto):
        # Si no se definió categoría, marca ni producto, la promo NO aplica a
        # nada (antes aplicaba a TODO el catálogo por default, lo cual es un
        # error fácil de cometer sin darse cuenta — un descuento "fantasma"
        # aplicándose solo porque a alguien se le pasó completar el alcance).
        tiene_alcance_definido = bool(self.marcas.strip()) or self.categorias.exists() or self.productos.exists()
        if not tiene_alcance_definido:
            return False
        if self.productos.filter(pk=producto.pk).exists():
            return True
        if self.marcas.strip() and producto.marca_id and producto.marca.nombre.strip().lower() in self._lista_marcas():
            return True
        if self.categorias.filter(pk=producto.categoria_id).exists():
            return True
        return False

    def precio_con_descuento(self, precio_base):
        """Precio POR UNIDAD con descuento. El 2x1 no se puede expresar como un
        precio unitario fijo (depende de cuántas unidades se llevan), así que
        acá se devuelve el precio sin cambios — el descuento real se calcula
        en `calcular_subtotal` según la cantidad."""
        if self.tipo_descuento == self.TipoDescuento.PORCENTAJE:
            descuento = precio_base * (self.valor / 100)
        elif self.tipo_descuento == self.TipoDescuento.MONTO_FIJO:
            descuento = self.valor
        else:
            descuento = 0
        return max(precio_base - descuento, 0)


class Banco(models.Model):
    """Catálogo de bancos/billeteras que ofrecen promociones de financiación
    (cuotas sin interés, etc). Se puede completar más allá de la lista
    precargada de bancos argentinos."""
    nombre = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class PlanFinanciacion(models.Model):
    """Promoción de financiación de un banco (ej: '6 cuotas sin interés').
    El costo financiero de estas promos normalmente lo termina absorbiendo el
    comercio (el banco le descuenta ese % al liquidar la venta), así que acá
    se carga ese % para poder ver, en la lista de precios, cuánto margen real
    queda si se vende con esa promo y no se le sube el precio al cliente."""
    banco = models.ForeignKey(Banco, on_delete=models.CASCADE, related_name="planes")
    nombre = models.CharField(max_length=120, help_text="Ej: '6 cuotas sin interés', 'Ahora 12'")
    cuotas = models.PositiveIntegerField(null=True, blank=True)
    costo_financiero_pct = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text="% que se descuenta del precio de venta si el comercio absorbe el costo de la promo "
        "(no se lo traslada al cliente). Ej: 12.5",
    )
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True, help_text="Dejar vacío si no tiene fecha de fin definida.")
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)

    # Alcance: a qué productos afecta esta promo (igual que en Promocion). Si
    # TODOS quedan vacíos, no aplica a nada — así en la lista de precios no
    # se resalta ningún producto "por las dudas" sin que alguien lo haya
    # configurado a propósito.
    categorias = models.ManyToManyField(Categoria, blank=True, related_name="planes_financiacion")
    proveedores = models.ManyToManyField(Proveedor, blank=True, related_name="planes_financiacion")
    marcas = models.CharField(
        max_length=500, blank=True,
        help_text="Marcas separadas por coma (ej: Ray-Ban, Oakley). Vacío = no filtra por marca.",
    )

    class Meta:
        ordering = ["banco__nombre", "cuotas"]

    def __str__(self):
        return f"{self.banco.nombre} — {self.nombre}"

    def esta_vigente(self, fecha=None):
        fecha = fecha or timezone.localdate()
        if not self.activo:
            return False
        if self.vigencia_desde and fecha < self.vigencia_desde:
            return False
        if self.vigencia_hasta and fecha > self.vigencia_hasta:
            return False
        return True

    def _lista_marcas(self):
        return [m.strip().lower() for m in self.marcas.split(",") if m.strip()]

    def aplica_a(self, producto):
        tiene_alcance_definido = bool(self.marcas.strip()) or self.categorias.exists() or self.proveedores.exists()
        if not tiene_alcance_definido:
            return False
        if self.marcas.strip() and producto.marca_id and producto.marca.nombre.strip().lower() in self._lista_marcas():
            return True
        if self.categorias.filter(pk=producto.categoria_id).exists():
            return True
        if producto.proveedor_id and self.proveedores.filter(pk=producto.proveedor_id).exists():
            return True
        return False


class OrdenCompra(models.Model):
    """
    Pedido de mercadería a un proveedor. Se arma en estado Borrador (se
    pueden agregar/quitar ítems libremente), se pasa a Enviada cuando ya se
    mandó al proveedor (a partir de ahí los ítems quedan fijos y solo se
    puede recibir mercadería), y termina en Recibida (parcial o total según
    haya llegado todo lo pedido).
    """
    class Estado(models.TextChoices):
        BORRADOR = "BOR", "Borrador"
        ENVIADA = "ENV", "Enviada"
        PARCIAL = "PAR", "Recibida parcialmente"
        RECIBIDA = "REC", "Recibida"
        CANCELADA = "CAN", "Cancelada"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="ordenes_compra")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    estado = models.CharField(max_length=3, choices=Estado.choices, default=Estado.BORRADOR)
    usuario = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="ordenes_compra"
    )
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "orden de compra"
        verbose_name_plural = "órdenes de compra"

    def __str__(self):
        return f"Orden #{self.pk or '?'} - {self.proveedor} ({self.get_estado_display()})"

    @property
    def total_estimado(self):
        return sum((item.subtotal_estimado for item in self.items.all()), Decimal("0"))

    def actualizar_estado_recepcion(self):
        """Recalcula el estado según cuánto se recibió de cada ítem. Se llama
        cada vez que se registra una recepción."""
        items = list(self.items.all())
        if not items:
            return
        algo_recibido = any(i.cantidad_recibida > 0 for i in items)
        todo_completo = all(i.cantidad_recibida >= i.cantidad_pedida for i in items)
        if todo_completo:
            self.estado = self.Estado.RECIBIDA
        elif algo_recibido:
            self.estado = self.Estado.PARCIAL
        else:
            self.estado = self.Estado.ENVIADA
        self.save(update_fields=["estado"])


class OrdenCompraItem(models.Model):
    """
    Un ítem del pedido. Si `producto` está seteado, es un producto ya
    cargado en el catálogo. Si no, es un modelo nuevo que todavía no existe
    (se pidió con marca/modelo a mano) — hay que cargarlo como Producto antes
    de poder recibir stock de él.
    """
    orden = models.ForeignKey(OrdenCompra, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(
        Producto, on_delete=models.SET_NULL, null=True, blank=True, related_name="items_orden_compra"
    )

    marca_texto = models.CharField(max_length=80, blank=True, help_text="Solo para ítems nuevos, que no están en el catálogo.")
    modelo_texto = models.CharField(max_length=80, blank=True)
    descripcion = models.CharField(max_length=255, blank=True, help_text="Color, calibre u otro detalle.")

    cantidad_pedida = models.PositiveIntegerField(default=1)
    cantidad_recibida = models.PositiveIntegerField(default=0)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.cantidad_pedida} x {self.nombre}"

    @property
    def nombre(self):
        if self.producto_id:
            return str(self.producto)
        partes = [self.marca_texto, self.modelo_texto, self.descripcion]
        return " ".join(p for p in partes if p) or "Ítem nuevo"

    @property
    def es_nuevo(self):
        return self.producto_id is None

    @property
    def pendiente(self):
        return max(self.cantidad_pedida - self.cantidad_recibida, 0)

    @property
    def subtotal_estimado(self):
        return self.cantidad_pedida * self.costo_unitario

    def clean(self):
        if not self.producto_id and not (self.marca_texto.strip() and self.modelo_texto.strip()):
            raise ValidationError("Un ítem nuevo (sin producto del catálogo) necesita al menos marca y modelo.")


# --- Productos "express" (venta sin relevamiento de stock) ---------------
# Para poder arrancar a vender sin haber cargado todo el catálogo, en el punto
# de venta se puede crear un producto mínimo al vuelo (marca/modelo + precio).
# Queda en esta categoría, que NO controla stock ni requiere receta, así se
# vende sin trabas; después se puede "normalizar" (moverlo a su categoría real
# y cargarle stock) desde el inventario.
CATEGORIA_PENDIENTE = "Pendiente de normalizar"
MARCA_SIN_ESPECIFICAR = "Sin marca"


def categoria_pendiente():
    """Categoría de los productos express: sin control de stock ni receta."""
    categoria, _ = Categoria.objects.get_or_create(
        nombre=CATEGORIA_PENDIENTE,
        defaults={"controla_stock": False, "usa_receta": False},
    )
    return categoria


def marca_para_express(texto=""):
    """Marca de un producto express: la que se tipeó (reusando la existente sin
    importar mayúsculas), o un placeholder si vino vacía. Se busca case-insensitive
    porque Marca.nombre tiene un índice único que ignora mayúsculas: un
    get_or_create por nombre exacto rompía al tipear una marca ya cargada con
    otra combinación de mayúsculas (ej: 'ray-ban' cuando existe 'Ray-Ban')."""
    nombre = (texto or "").strip() or MARCA_SIN_ESPECIFICAR
    existente = Marca.objects.filter(nombre__iexact=nombre).first()
    if existente:
        return existente
    try:
        return Marca.objects.create(nombre=nombre)
    except IntegrityError:
        # Carrera / diferencia de mayúsculas: ya existe, la reusamos.
        return Marca.objects.get(nombre__iexact=nombre)


def mejor_promocion_para(producto, fecha=None):
    """Devuelve (promocion, precio_final) con el mayor descuento vigente
    aplicable a ese producto, o (None, producto.precio) si no aplica ninguna."""
    candidatas = [
        p for p in Promocion.objects.filter(activa=True).prefetch_related("productos", "categorias")
        if p.esta_vigente(fecha) and p.aplica_a(producto)
    ]
    if not candidatas:
        return None, producto.precio
    mejor = min(candidatas, key=lambda p: p.precio_con_descuento(producto.precio))
    return mejor, mejor.precio_con_descuento(producto.precio)
