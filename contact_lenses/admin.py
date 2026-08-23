from django.contrib import admin

from .models import PruebaLentesContacto


@admin.register(PruebaLentesContacto)
class PruebaLentesContactoAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "nombre_cliente", "vendedor", "estado", "venta")
    list_filter = ("estado", "vendedor")
    search_fields = ("nombre_suelto", "cliente__nombre", "cliente__apellido")
    date_hierarchy = "fecha_hora"
