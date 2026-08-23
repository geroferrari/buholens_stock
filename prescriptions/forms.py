from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from customers.models import ObraSocial
from inventory.models import Producto
from stockero.form_utils import BootstrapModelForm

from .models import OrdenLaboratorio, Receta


def validar_archivo_receta(file):
    max_size = 10 * 1024 * 1024
    if file.size > max_size:
        raise ValidationError(f"El archivo no puede ser mayor a 10 MB (tamaño actual: {file.size / 1024 / 1024:.1f} MB)")
    mime_types_permitidos = ['image/jpeg', 'image/png', 'image/gif', 'application/pdf']
    if file.content_type not in mime_types_permitidos:
        raise ValidationError(f"Solo se permiten JPEG, PNG, GIF o PDF (tipo recibido: {file.content_type})")


class RecetaForm(BootstrapModelForm):
    class Meta:
        model = Receta
        # entregada/fecha_entrega no se usan (quedó reemplazado por el
        # seguimiento de entrega por ítem de venta): se dejan en el modelo
        # por si se retoman más adelante, pero no se cargan ni se muestran.
        exclude = ["creado", "correcciones", "cargada_por", "entregada", "fecha_entrega"]
        widgets = {
            # format="%Y-%m-%d" a mano: sin esto Django renderiza la fecha en
            # formato local (dd/mm/aaaa) y el <input type="date"> del
            # navegador, que solo acepta ISO (aaaa-mm-dd), la descarta
            # silenciosamente — el campo se ve vacío aunque el valor exista.
            "fecha_recibido": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "fecha_recibido": "Fecha de la receta",
            "es_lentes_contacto": "¿Es para lentes de contacto?",
            "marca_lentes_contacto": "Marca de los lentes de contacto",
            "lejos_od_esfera": "Esférico", "lejos_od_cilindro": "Cilíndrico",
            "lejos_od_eje": "Eje", "lejos_od_adicion": "Adición",
            "lejos_oi_esfera": "Esférico", "lejos_oi_cilindro": "Cilíndrico",
            "lejos_oi_eje": "Eje", "lejos_oi_adicion": "Adición",
            "cerca_od_esfera": "Esférico", "cerca_od_cilindro": "Cilíndrico", "cerca_od_eje": "Eje",
            "cerca_oi_esfera": "Esférico", "cerca_oi_cilindro": "Cilíndrico", "cerca_oi_eje": "Eje",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "archivo" in self.fields:
            self.fields["archivo"].validators = [validar_archivo_receta]

        # Fecha de la receta: por default hoy (se suele cargar el mismo día
        # que se recibe), pero se puede cambiar a una fecha anterior si hace
        # falta; nunca a futuro (ver clean_fecha_recibido). Solo aplica al
        # crear: si ya hay instancia (corrección), se respeta su valor.
        if not self.instance.pk:
            self.fields["fecha_recibido"].initial = date.today()
        self.fields["fecha_recibido"].widget.attrs["max"] = date.today().isoformat()

        qs = ObraSocial.objects.filter(activa=True)
        if self.instance and self.instance.obra_social_id and not qs.filter(pk=self.instance.obra_social_id).exists():
            qs = ObraSocial.objects.filter(Q(activa=True) | Q(pk=self.instance.obra_social_id))
        self.fields["obra_social"].queryset = qs
        self.fields["obra_social"].required = False

        campos_step_025 = [
            "lejos_od_esfera", "lejos_od_cilindro", "lejos_od_adicion",
            "lejos_oi_esfera", "lejos_oi_cilindro", "lejos_oi_adicion",
            "cerca_od_esfera", "cerca_od_cilindro",
            "cerca_oi_esfera", "cerca_oi_cilindro",
        ]

        for campo in campos_step_025:
            self.fields[campo].widget.attrs["step"] = "0.25"

    def clean_fecha_recibido(self):
        fecha = self.cleaned_data["fecha_recibido"]
        if fecha > date.today():
            raise ValidationError("La fecha de la receta no puede ser posterior a hoy.")
        return fecha


class OrdenLaboratorioForm(BootstrapModelForm):
    """Carga a mano una orden de laboratorio suelta (sin venta ni precio):
    elegir cliente, una receta ya cargada de ese cliente, el cristal a usar
    y, opcionalmente, en qué armazón se monta."""

    class Meta:
        model = OrdenLaboratorio
        fields = ["cliente", "receta", "producto", "armazon", "armazon_de_cliente", "observaciones"]
        labels = {"producto": "Cristal"}
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # La receta se restringe a las del cliente elegido (llega por POST o,
        # si se reabre el form con errores, por los datos ya tipeados).
        cliente_id = self.data.get("cliente") or self.initial.get("cliente")
        self.fields["receta"].queryset = (
            Receta.objects.filter(cliente_id=cliente_id).order_by("-fecha_recibido")
            if cliente_id else Receta.objects.none()
        )
        # El cristal es un catálogo chico y finito: se lista entero de una,
        # sin necesidad de buscar (mismo criterio que el punto de venta).
        self.fields["producto"].queryset = (
            Producto.objects.filter(activo=True, categoria__nombre__icontains="cristal")
            .select_related("marca", "categoria").order_by("modelo")
        )
        self.fields["producto"].widget.attrs["data-searchable"] = "1"
        self.fields["armazon"].required = False

    def clean(self):
        cleaned = super().clean()
        # Uno u otro, nunca los dos: si trae el suyo no hay armazón del catálogo.
        if cleaned.get("armazon_de_cliente"):
            cleaned["armazon"] = None
        return cleaned
