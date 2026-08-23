from django import forms
from django.core.exceptions import ValidationError

from stockero.form_utils import BootstrapFormMixin, BootstrapModelForm

from .models import Banco, Categoria, Marca, PlanFinanciacion, Proveedor, Producto, Promocion


def validar_imagen_producto(file):
    max_size = 5 * 1024 * 1024
    if file.size > max_size:
        raise ValidationError(f"La imagen no puede ser mayor a 5 MB (tamaño actual: {file.size / 1024 / 1024:.1f} MB)")
    mime_types_permitidos = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if file.content_type not in mime_types_permitidos:
        raise ValidationError(f"Solo se permiten imágenes JPEG, PNG, GIF o WebP (tipo recibido: {file.content_type})")


class NombreUnicoSinMayusculasMixin:
    """Valida que `nombre` no se repita ignorando mayúsculas/minúsculas
    (ej: "Generico" y "generico" cuentan como el mismo nombre)."""

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"]
        qs = self._meta.model.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Ya existe un registro con ese nombre.")
        return nombre


class MarcaForm(NombreUnicoSinMayusculasMixin, BootstrapModelForm):
    class Meta:
        model = Marca
        fields = ["nombre"]


class CategoriaForm(NombreUnicoSinMayusculasMixin, BootstrapModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "usa_receta", "controla_stock"]


class ProveedorForm(NombreUnicoSinMayusculasMixin, BootstrapModelForm):
    class Meta:
        model = Proveedor
        fields = ["nombre", "contacto", "telefono", "marcas"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # OJO: no reemplazar el widget por uno nuevo acá — el de
        # ModelMultipleChoiceField ya viene con las choices (el queryset de
        # Marca) enganchadas; crear un SelectMultiple() nuevo las pierde y el
        # <select> queda vacío. Solo se le agregan los atributos que faltan.
        # La clase "js-tags-select" hace que se vea como buscador + chips
        # (ver static/js/tags_select.js), en vez del <select multiple> nativo.
        self.fields["marcas"].widget.attrs.update({"class": "form-select js-tags-select", "size": 8})


class ProductoForm(BootstrapModelForm):
    class Meta:
        model = Producto
        fields = [
            "codigo_barras", "categoria", "proveedor",
            "marca", "modelo", "color", "color_cristal", "calibre", "material",
            "precio_costo", "porcentaje_iva", "precio", "foto",
        ]
        # stock_minimo queda afuera del formulario a propósito: por ahora no
        # se usa (queda en 0, el default del modelo) para no pedirle ese dato
        # a nadie sin necesidad. El campo sigue existiendo en la base por si
        # en el futuro se retoma la idea de alertas de reposición.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["codigo_barras"].required = False
        self.fields["precio_costo"].required = False
        self.fields["foto"].validators = [validar_imagen_producto]

    def clean_precio_costo(self):
        return self.cleaned_data.get("precio_costo") or 0

    def clean(self):
        cleaned = super().clean()
        categoria = cleaned.get("categoria")
        # Los productos de categorías que no controlan stock (cristales,
        # servicios) no tienen código de fábrica: son "a medida" y se eligen
        # de un catálogo, no se escanean. Ahí el riesgo real es cargar el
        # mismo tipo dos veces sin darse cuenta (con otro código de barras
        # generado), así que se valida duplicado por marca+modelo+color en
        # vez de por código de barras.
        if categoria and not categoria.controla_stock:
            duplicado = Producto.objects.filter(
                categoria=categoria,
                marca=cleaned.get("marca"),
                modelo=cleaned.get("modelo"),
                color_cristal=cleaned.get("color_cristal"),
            )
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                raise ValidationError(
                    "Ya existe un producto igual en esta categoría (misma marca, modelo y color de "
                    "cristal). Si lo que cambió es el precio, editá ese producto en vez de crear uno nuevo."
                )
        return cleaned


class BancoForm(BootstrapModelForm):
    class Meta:
        model = Banco
        fields = ["nombre"]


class PlanFinanciacionForm(BootstrapModelForm):
    marcas_multi = forms.MultipleChoiceField(
        required=False, label="Marcas",
        help_text="Buscá y hacé click para elegir una o varias marcas a las que afecta esta promo. "
        "Si no elegís marca, categoría ni proveedor, no se resalta ningún producto en la lista de precios.",
    )

    class Meta:
        model = PlanFinanciacion
        fields = [
            "banco", "nombre", "cuotas", "costo_financiero_pct",
            "vigencia_desde", "vigencia_hasta", "activo", "observaciones",
            "categorias", "proveedores",
        ]
        widgets = {
            "vigencia_desde": forms.DateInput(attrs={"type": "date"}),
            "vigencia_hasta": forms.DateInput(attrs={"type": "date"}),
            "observaciones": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        marcas_existentes = Marca.objects.values_list("nombre", flat=True)
        self.fields["marcas_multi"].widget = forms.SelectMultiple(attrs={"class": "form-select js-tags-select"})
        self.fields["marcas_multi"].choices = [(m, m) for m in marcas_existentes]
        if self.instance.pk and self.instance.marcas:
            self.fields["marcas_multi"].initial = [m.strip() for m in self.instance.marcas.split(",") if m.strip()]
        self.fields["categorias"].widget.attrs.update({"class": "form-select js-tags-select"})
        self.fields["proveedores"].widget.attrs.update({"class": "form-select js-tags-select"})

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.marcas = ", ".join(self.cleaned_data.get("marcas_multi", []))
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class PromocionForm(BootstrapModelForm):
    marcas_multi = forms.MultipleChoiceField(
        required=False, label="Marcas",
        help_text="Buscá y hacé click para elegir una o varias marcas. Si no elegís ninguna, no filtra por marca.",
    )

    class Meta:
        model = Promocion
        fields = [
            "nombre", "descripcion", "tipo_descuento", "valor",
            "fecha_inicio", "fecha_fin", "activa", "categorias",
        ]
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
            "descripcion": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        marcas_existentes = Marca.objects.values_list("nombre", flat=True)
        # Importante: el widget se reasigna ANTES de setear choices, porque el
        # setter de ChoiceField.choices sincroniza las opciones con el widget
        # vigente en ese momento — si se hace al revés, el widget nuevo queda
        # sin opciones (aunque el campo internamente sí tenga las choices).
        self.fields["marcas_multi"].widget = forms.SelectMultiple(attrs={"class": "form-select js-tags-select"})
        self.fields["marcas_multi"].choices = [(m, m) for m in marcas_existentes]
        if self.instance.pk and self.instance.marcas:
            self.fields["marcas_multi"].initial = [m.strip() for m in self.instance.marcas.split(",") if m.strip()]
        # Igual que marcas: buscador + chips en vez del <select multiple> nativo.
        # OJO: solo se le agregan atributos al widget existente (no se reemplaza),
        # porque ModelMultipleChoiceField ya trae las choices (el queryset de
        # Categoria) enganchadas al widget — reemplazarlo las perdería.
        self.fields["categorias"].widget.attrs.update({"class": "form-select js-tags-select"})

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.marcas = ", ".join(self.cleaned_data.get("marcas_multi", []))
        if commit:
            instance.save()
            self.save_m2m()
        return instance
