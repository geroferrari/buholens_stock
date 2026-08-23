from django.contrib import admin

from .models import Venta, VentaItem


class VentaItemInline(admin.TabularInline):
    model = VentaItem
    extra = 0
    autocomplete_fields = ("producto", "receta")
    readonly_fields = ("precio_unitario",)


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ("id", "fecha", "cliente", "estado", "total", "es_obra_social", "obra_social_resuelta")
    list_filter = ("estado", "fecha", "es_obra_social")
    search_fields = ("cliente__nombre", "cliente__apellido", "cliente__dni")
    autocomplete_fields = ("cliente",)
    inlines = [VentaItemInline]
    readonly_fields = ("total",)

    def has_delete_permission(self, request, obj=None):
        # No se borran ventas confirmadas para no perder trazabilidad de stock.
        if obj and obj.estado == Venta.Estado.CONFIRMADA:
            return False
        return super().has_delete_permission(request, obj)
