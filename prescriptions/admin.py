from django import forms
from django.contrib import admin

from .models import Medico, Receta


class MedicoAdminForm(forms.ModelForm):
    class Meta:
        model = Medico
        fields = "__all__"

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"]
        existente = Medico.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if existente.exists():
            raise forms.ValidationError(f'Ya existe un médico cargado como "{existente.first().nombre}".')
        return nombre


@admin.register(Medico)
class MedicoAdmin(admin.ModelAdmin):
    form = MedicoAdminForm
    list_display = ("nombre",)
    search_fields = ("nombre",)


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    list_display = ("cliente", "fecha_recibido", "fecha_entrega", "medico")
    list_filter = ("fecha_recibido",)
    search_fields = ("cliente__nombre", "cliente__apellido", "cliente__dni", "medico__nombre")
    autocomplete_fields = ("cliente", "medico")
    fieldsets = (
        (None, {
            "fields": (
                "cliente", "fecha_recibido", "fecha_entrega",
                "medico", "obra_social",
            )
        }),
        ("Lejos", {
            "fields": (
                ("lejos_od_esfera", "lejos_od_cilindro", "lejos_od_eje", "lejos_od_adicion"),
                ("lejos_oi_esfera", "lejos_oi_cilindro", "lejos_oi_eje", "lejos_oi_adicion"),
                "lejos_dnp", "lejos_tipo_cristal", "lejos_color_cristal", "lejos_tratamientos",
            ),
        }),
        ("Cerca", {
            "fields": (
                ("cerca_od_esfera", "cerca_od_cilindro", "cerca_od_eje"),
                ("cerca_oi_esfera", "cerca_oi_cilindro", "cerca_oi_eje"),
                "cerca_dnp", "cerca_tipo_cristal", "cerca_color_cristal", "cerca_tratamientos",
            ),
        }),
        ("Bifocal / Multifocal", {
            "fields": ("es_bifocal_multifocal", "di_lejos", "di_cerca", "altura"),
            "classes": ("collapse",),
        }),
        ("Otros", {
            "fields": ("observaciones", "archivo"),
        }),
    )
