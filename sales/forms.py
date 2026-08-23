from django import forms

from stockero.form_utils import BootstrapModelForm

from .models import Vendedor


class VendedorForm(BootstrapModelForm):
    class Meta:
        model = Vendedor
        fields = ["nombre", "activo", "usuario"]

    def clean_nombre(self):
        """Evita crear (o renombrar) un vendedor con un nombre que ya existe,
        sin importar mayúsculas/espacios — así no se acumulan duplicados como
        tres "Ana" que después no se pueden borrar por estar en uso."""
        nombre = self.cleaned_data["nombre"].strip()
        existente = Vendedor.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            existente = existente.exclude(pk=self.instance.pk)
        if existente.exists():
            raise forms.ValidationError(f"Ya existe un vendedor/a con el nombre «{nombre}».")
        return nombre
