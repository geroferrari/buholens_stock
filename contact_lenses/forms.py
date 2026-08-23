from django import forms

from stockero.form_utils import BootstrapModelForm
from sales.models import Vendedor

from .models import PruebaLentesContacto

# El input HTML datetime-local usa este formato para valor/parseo.
_DT_LOCAL = "%Y-%m-%dT%H:%M"


class PruebaForm(BootstrapModelForm):
    class Meta:
        model = PruebaLentesContacto
        fields = ["cliente", "vendedor", "fecha_hora", "observaciones"]
        widgets = {
            "fecha_hora": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format=_DT_LOCAL,
            ),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "fecha_hora": "Fecha y hora",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_hora"].input_formats = [_DT_LOCAL, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        # El cliente se elige con el buscador (o se crea al vuelo); es obligatorio.
        self.fields["cliente"].required = True
        # Solo vendedores activos como opciones.
        self.fields["vendedor"].queryset = Vendedor.objects.filter(activo=True)
