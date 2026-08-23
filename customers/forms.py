from django import forms
from django.db.models import Q

from stockero.form_utils import BootstrapModelForm

from .models import Cliente, ObraSocial


class ClienteForm(BootstrapModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "apellido", "dni", "telefono", "email", "direccion", "obra_social"]
        widgets = {
            "dni": forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]*"}),
            "telefono": forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ObraSocial.objects.filter(activa=True)
        if self.instance and self.instance.obra_social_id and not qs.filter(pk=self.instance.obra_social_id).exists():
            qs = ObraSocial.objects.filter(Q(activa=True) | Q(pk=self.instance.obra_social_id))
        self.fields["obra_social"].queryset = qs
        self.fields["obra_social"].required = False
        # Buscador: tipeando "osde" aparecen todas las variantes (OSDE 210, etc.).
        self.fields["obra_social"].widget.attrs["data-searchable"] = "1"


class ObraSocialForm(BootstrapModelForm):
    class Meta:
        model = ObraSocial
        fields = ["nombre", "activa"]

    def clean_nombre(self):
        """Evita duplicados ignorando mayúsculas (ej: 'Particular' vs
        'particular'), con un mensaje claro en vez del error crudo de la base."""
        nombre = self.cleaned_data["nombre"].strip()
        existentes = ObraSocial.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise forms.ValidationError(f"Ya existe una obra social «{existentes.first().nombre}».")
        return nombre
