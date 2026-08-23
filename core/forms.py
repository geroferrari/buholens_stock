import re

from django import forms

from stockero.form_utils import BootstrapModelForm

from .models import Configuracion

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ConfiguracionForm(BootstrapModelForm):
    class Meta:
        model = Configuracion
        fields = [
            "nombre", "nombre_corto", "direccion", "telefono", "email",
            "logo", "color_primario", "mensaje_ticket",
            "caracteristica_telefonica", "largo_telefono_local",
            "codigo_pais", "prefijo_movil",
        ]
        widgets = {
            # El selector de color nativo evita que se cargue cualquier cosa a mano.
            "color_primario": forms.TextInput(attrs={"type": "color"}),
        }

    # La pantalla se muestra en dos bloques: identidad de la óptica y reglas de
    # teléfonos (que son de otra naturaleza y confunden mezcladas con el logo).
    CAMPOS_TELEFONO = (
        "caracteristica_telefonica", "largo_telefono_local", "codigo_pais", "prefijo_movil",
    )

    @property
    def campos_identidad(self):
        return [f for f in self if f.name not in self.CAMPOS_TELEFONO]

    @property
    def campos_telefono(self):
        return [f for f in self if f.name in self.CAMPOS_TELEFONO]

    def clean_color_primario(self):
        color = (self.cleaned_data["color_primario"] or "").strip()
        if not HEX.match(color):
            raise forms.ValidationError("Usá un color en formato #rrggbb (por ejemplo #0d6efd).")
        return color.lower()
