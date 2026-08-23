from django.db import DatabaseError, models
from django.utils import timezone


def _oscurecer(hex_color, factor):
    """Devuelve el color más oscuro (factor 0-1, donde 1 = igual). Se usa para
    derivar los tonos de hover/activo a partir del color de marca, así la óptica
    configura UN color y no tres."""
    try:
        crudo = hex_color.lstrip("#")
        if len(crudo) == 3:
            crudo = "".join(c * 2 for c in crudo)
        r, g, b = (int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return hex_color
    return "#{:02x}{:02x}{:02x}".format(*(int(c * factor) for c in (r, g, b)))


class Configuracion(models.Model):
    """
    Datos de la óptica que usa la app: nombre, contacto, logo y color de marca.
    Es una fila única (singleton): `save()` fuerza siempre pk=1 y se lee con
    `Configuracion.actual()`. Se edita desde Gestión → Configuración, así la
    misma aplicación sirve para cualquier óptica sin tocar código.
    """

    # Acento de BuhoLen, en una versión menos saturada que la de la web: en
    # una pantalla de trabajo que se mira todo el día, el naranja pleno cansa.
    COLOR_POR_DEFECTO = "#a8563a"

    nombre = models.CharField(
        "Nombre de la óptica", max_length=120, default="Mi Óptica",
        help_text="Aparece en el ticket, las órdenes de laboratorio y los avisos.",
    )
    nombre_corto = models.CharField(
        "Nombre corto", max_length=30, blank=True,
        help_text="El que se ve debajo del ícono en el celular. Si se deja vacío, se usa el nombre.",
    )
    direccion = models.CharField("Dirección", max_length=200, blank=True)
    telefono = models.CharField("Teléfono", max_length=60, blank=True)
    email = models.EmailField("Email de contacto", blank=True)
    logo = models.ImageField(
        "Logo", upload_to="marca/", blank=True,
        help_text="Se muestra en la barra superior y en las impresiones. Ideal cuadrado, fondo transparente.",
    )
    color_primario = models.CharField(
        "Color principal", max_length=7, default=COLOR_POR_DEFECTO,
        help_text="Color de marca en formato #rrggbb. Se usa en botones, links y destacados.",
    )
    mensaje_ticket = models.CharField(
        "Mensaje al pie del ticket", max_length=120, default="¡Gracias por su compra!", blank=True,
    )

    # --- Teléfonos de clientes ---
    # Los sistemas viejos suelen guardar el número local pelado y los links de
    # WhatsApp necesitan el número completo. Esto lo resuelve sin escribir la
    # zona de ninguna óptica en el código.
    caracteristica_telefonica = models.CharField(
        "Característica de la zona", max_length=5, blank=True,
        help_text=(
            "Sin 0 ni 15 (ej: 3489). Si se completa, los teléfonos que se carguen "
            "con solo el número local se completan solos con esta característica. "
            "Vacío = no tocar los teléfonos."
        ),
    )
    largo_telefono_local = models.PositiveSmallIntegerField(
        "Dígitos del número local", default=6,
        help_text="Cuántos dígitos tiene un número de la zona sin la característica.",
    )
    codigo_pais = models.CharField(
        "Código de país", max_length=5, default="54",
        help_text="Sin el +. Se usa para armar los links de WhatsApp.",
    )
    prefijo_movil = models.CharField(
        "Prefijo de celular", max_length=5, default="9", blank=True,
        help_text="Va entre el código de país y el número (en Argentina, 9). Vacío si tu país no lo usa.",
    )

    class Meta:
        verbose_name = "configuración"
        verbose_name_plural = "configuración"

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton: nunca hay más de una fila
        # Sin esto, un objects.create() con la fila ya existente explota con
        # IntegrityError en vez de pisarla (create() pide force_insert).
        kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)

    @classmethod
    def actual(cls):
        """La configuración vigente. Si todavía no se guardó ninguna (instalación
        nueva) o la tabla no existe aún (antes de migrar, ej. collectstatic en el
        deploy), devuelve una instancia con los valores por defecto en vez de
        romper: la app tiene que poder levantar sin configurar nada."""
        try:
            return cls.objects.first() or cls()
        except DatabaseError:
            return cls()

    @property
    def nombre_para_icono(self):
        return self.nombre_corto or self.nombre

    @property
    def color_primario_oscuro(self):
        """Tono de hover."""
        return _oscurecer(self.color_primario, 0.85)

    @property
    def color_primario_mas_oscuro(self):
        """Tono de botón apretado y de texto sobre fondo claro (más contraste)."""
        return _oscurecer(self.color_primario, 0.7)

    def completar_telefono(self, telefono):
        """Devuelve el teléfono con la característica de la zona adelante si vino
        cargado como número local pelado. Si no hay característica configurada,
        no toca nada."""
        if not telefono or not self.caracteristica_telefonica:
            return telefono
        if len(telefono) != self.largo_telefono_local:
            return telefono
        return self.caracteristica_telefonica + telefono

    def telefono_internacional(self, digitos):
        """Número en formato internacional (sin +) para armar links de WhatsApp.
        `digitos` ya viene sin separadores."""
        if digitos.startswith(self.codigo_pais):
            return digitos
        return self.codigo_pais + self.prefijo_movil + digitos.lstrip("0")

    @property
    def datos_contacto(self):
        """Dirección / teléfono / email, sin los que estén vacíos. Lo usan las
        impresiones para no dejar separadores sueltos."""
        return [d for d in (self.direccion, self.telefono, self.email) if d]


class SoftDeleteQuerySet(models.QuerySet):
    def eliminar_definitivo(self):
        """Borrado REAL de la base para todo el queryset (lo usa la purga)."""
        return super().delete()

    def en_papelera(self):
        return self.filter(eliminado_en__isnull=False)


class NoEliminadosManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager por defecto: deja afuera lo que está en la papelera, así los
    registros borrados desaparecen de listados, reportes, etc. sin tener que
    filtrarlos a mano en cada consulta. (from_queryset expone los métodos del
    queryset también en el manager)."""

    def get_queryset(self):
        return super().get_queryset().filter(eliminado_en__isnull=True)


class TodosManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Incluye también los de la papelera (para la papelera y la purga)."""


class SoftDeleteModel(models.Model):
    """
    Base para modelos con papelera: borrar NO elimina, marca `eliminado_en`.
    El registro desaparece de las consultas normales (manager `objects`) pero se
    puede recuperar, y una tarea programada lo purga después de un tiempo.

    - `Modelo.objects`         -> sin los de la papelera (default).
    - `Modelo.con_eliminados`  -> todos, incluidos los borrados.
    """
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)

    objects = NoEliminadosManager()
    con_eliminados = TodosManager()

    class Meta:
        abstract = True

    @property
    def en_papelera(self):
        return self.eliminado_en is not None

    def delete(self, using=None, keep_parents=False):
        """Borrado 'suave': manda a la papelera en vez de eliminar de la base."""
        self.eliminado_en = timezone.now()
        self.save(update_fields=["eliminado_en"])

    def restaurar(self):
        """Saca de la papelera (recupera el registro)."""
        self.eliminado_en = None
        self.save(update_fields=["eliminado_en"])

    def eliminar_definitivo(self, using=None, keep_parents=False):
        """Borrado REAL de la base. Lo usa la purga o el 'borrar definitivo' de
        la papelera. Las subclases pueden extenderlo (ej: la venta devuelve el
        stock antes de desaparecer)."""
        return super().delete(using=using, keep_parents=keep_parents)
