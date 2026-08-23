from django.contrib import admin

from .models import (
    Categoria, EscaneoNoEncontrado, Marca, Proveedor, Producto, MovimientoStock,
    OrdenCompra, OrdenCompraItem,
)


@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    list_display = ("nombre",)
    search_fields = ("nombre",)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "usa_receta", "controla_stock")


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "contacto", "telefono")
    search_fields = ("nombre",)
    filter_horizontal = ("marcas",)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo_barras", "categoria", "marca", "modelo", "color",
        "precio", "stock_actual", "activo",
    )
    list_filter = ("categoria", "proveedor", "marca", "activo")
    search_fields = ("codigo_barras", "marca__nombre", "modelo")
    autocomplete_fields = ("marca",)
    readonly_fields = ("stock_actual", "margen_ganancia_pct")
    fieldsets = (
        (None, {
            "fields": ("codigo_barras", "categoria", "proveedor", "activo"),
        }),
        ("Datos del producto", {
            "fields": ("marca", "modelo", "color", "color_cristal", "calibre", "material", "foto"),
        }),
        ("Precio y stock", {
            "fields": (
                "precio_costo", "porcentaje_iva", "precio", "margen_ganancia_pct",
                "stock_actual", "stock_minimo",
            ),
        }),
    )
    # El codigo_barras se genera solo (Producto.save()) si se deja vacío; el
    # stock_actual SIEMPRE se mueve via MovimientoStock (por eso es readonly).


@admin.register(EscaneoNoEncontrado)
class EscaneoNoEncontradoAdmin(admin.ModelAdmin):
    list_display = ("codigo_barras", "origen", "fecha", "usuario", "atendido")
    list_filter = ("origen", "atendido")
    search_fields = ("codigo_barras",)


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ("fecha", "producto", "tipo", "cantidad", "usuario", "nota")
    list_filter = ("tipo", "fecha")
    search_fields = ("producto__codigo_barras", "producto__marca__nombre", "producto__modelo", "nota")
    autocomplete_fields = ("producto",)

    def save_model(self, request, obj, form, change):
        if not change and not obj.usuario_id:
            obj.usuario = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        # Los movimientos son inmutables: se corrigen con otro movimiento.
        return False


class OrdenCompraItemInline(admin.TabularInline):
    model = OrdenCompraItem
    extra = 0
    autocomplete_fields = ("producto",)


@admin.register(OrdenCompra)
class OrdenCompraAdmin(admin.ModelAdmin):
    list_display = ("id", "proveedor", "estado", "fecha_creacion", "usuario")
    list_filter = ("estado", "proveedor")
    inlines = [OrdenCompraItemInline]
