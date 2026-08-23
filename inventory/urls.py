from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("ingreso-rapido/", views.ingreso_rapido, name="ingreso_rapido"),
    path("ingreso-rapido/registrar/", views.registrar_ingreso, name="registrar_ingreso"),
    path("ingreso-rapido/deshacer/<int:movimiento_id>/", views.deshacer_ingreso, name="deshacer_ingreso"),
    path("etiquetas/", views.etiquetas, name="etiquetas"),
    path("movimientos/", views.MovimientoStockListView.as_view(), name="movimiento_lista"),
    path("escaneos-no-encontrados/", views.EscaneoNoEncontradoListView.as_view(), name="escaneo_no_encontrado_lista"),
    path("escaneos-no-encontrados/<int:pk>/eliminar/", views.EscaneoNoEncontradoDeleteView.as_view(), name="escaneo_no_encontrado_eliminar"),

    path("marcas/", views.MarcaListView.as_view(), name="marca_lista"),
    path("marcas/nueva/", views.MarcaCreateView.as_view(), name="marca_nueva"),
    path("marcas/<int:pk>/editar/", views.MarcaUpdateView.as_view(), name="marca_editar"),
    path("marcas/<int:pk>/eliminar/", views.MarcaDeleteView.as_view(), name="marca_eliminar"),

    path("categorias/", views.CategoriaListView.as_view(), name="categoria_lista"),
    path("categorias/nueva/", views.CategoriaCreateView.as_view(), name="categoria_nueva"),
    path("categorias/<int:pk>/editar/", views.CategoriaUpdateView.as_view(), name="categoria_editar"),
    path("categorias/<int:pk>/eliminar/", views.CategoriaDeleteView.as_view(), name="categoria_eliminar"),

    path("proveedores/", views.ProveedorListView.as_view(), name="proveedor_lista"),
    path("proveedores/nuevo/", views.ProveedorCreateView.as_view(), name="proveedor_nuevo"),
    path("proveedores/<int:pk>/editar/", views.ProveedorUpdateView.as_view(), name="proveedor_editar"),
    path("proveedores/<int:pk>/eliminar/", views.ProveedorDeleteView.as_view(), name="proveedor_eliminar"),

    path("precios/", views.PrecioListView.as_view(), name="precio_lista"),
    path("precios/consultar/", views.consultar_precio, name="consultar_precio"),
    path("productos/", views.ProductoListView.as_view(), name="producto_lista"),
    path("productos/nuevo/", views.ProductoCreateView.as_view(), name="producto_nuevo"),
    path("productos/<int:pk>/editar/", views.ProductoUpdateView.as_view(), name="producto_editar"),
    path("productos/<int:pk>/eliminar/", views.ProductoDeleteView.as_view(), name="producto_eliminar"),
    path("productos/columnas/", views.ProductoColumnasUpdateView.as_view(), name="producto_columnas"),
    path("productos/generar-codigo/", views.generar_codigo_barras_ajax, name="generar_codigo_barras_ajax"),
    path("productos/eliminar-masivo/", views.ProductoEliminarMasivoView.as_view(), name="producto_eliminar_masivo"),
    path("productos/actualizar-precios-masivo/", views.ProductoActualizarPreciosView.as_view(), name="producto_actualizar_precios"),

    path("lista-precios/", views.ListaPreciosView.as_view(), name="lista_precios"),
    path("lista-precios/guardar/", views.ListaPreciosGuardarView.as_view(), name="lista_precios_guardar"),

    # Bancos, financiación y promociones: ocultas a propósito para reducir
    # complejidad por ahora. Descomentar para reactivar (junto con las
    # tarjetas en home.html/gestion.html). Ojo: "sales:asociar_promocion_item"
    # (aplica una promoción ya cargada a un ítem de venta) es independiente de
    # esto y sigue activo.
    # path("bancos/", views.BancoListView.as_view(), name="banco_lista"),
    # path("bancos/nuevo/", views.BancoCreateView.as_view(), name="banco_nuevo"),
    # path("bancos/<int:pk>/editar/", views.BancoUpdateView.as_view(), name="banco_editar"),
    # path("bancos/<int:pk>/eliminar/", views.BancoDeleteView.as_view(), name="banco_eliminar"),

    # path("financiacion/nuevo/", views.PlanFinanciacionCreateView.as_view(), name="plan_financiacion_nuevo"),
    # path("financiacion/<int:pk>/editar/", views.PlanFinanciacionUpdateView.as_view(), name="plan_financiacion_editar"),
    # path("financiacion/<int:pk>/eliminar/", views.PlanFinanciacionDeleteView.as_view(), name="plan_financiacion_eliminar"),

    # path("promociones/", views.PromocionListView.as_view(), name="promocion_lista"),
    # path("promociones/nueva/", views.PromocionCreateView.as_view(), name="promocion_nueva"),
    # path("promociones/<int:pk>/editar/", views.PromocionUpdateView.as_view(), name="promocion_editar"),
    # path("promociones/<int:pk>/eliminar/", views.PromocionDeleteView.as_view(), name="promocion_eliminar"),

    path("ordenes-compra/", views.OrdenCompraListView.as_view(), name="orden_compra_lista"),
    path("ordenes-compra/nueva/", views.orden_compra_nueva, name="orden_compra_nueva"),
    path("ordenes-compra/<int:orden_id>/armar/", views.orden_compra_armar, name="orden_compra_armar"),
    path("ordenes-compra/<int:orden_id>/agregar-producto/", views.orden_compra_agregar_producto, name="orden_compra_agregar_producto"),
    path("ordenes-compra/<int:orden_id>/agregar-manual/", views.orden_compra_agregar_manual, name="orden_compra_agregar_manual"),
    path("ordenes-compra/<int:orden_id>/items/<int:item_id>/quitar/", views.orden_compra_quitar_item, name="orden_compra_quitar_item"),
    path("ordenes-compra/<int:orden_id>/confirmar/", views.orden_compra_confirmar, name="orden_compra_confirmar"),
    path("ordenes-compra/<int:orden_id>/cancelar/", views.orden_compra_cancelar, name="orden_compra_cancelar"),
    path("ordenes-compra/<int:pk>/eliminar/", views.OrdenCompraDeleteView.as_view(), name="orden_compra_eliminar"),
    path("ordenes-compra/<int:orden_id>/", views.orden_compra_detalle, name="orden_compra_detalle"),
    path("ordenes-compra/<int:orden_id>/items/<int:item_id>/recibir/", views.orden_compra_recibir_item, name="orden_compra_recibir_item"),
    path("ordenes-compra/<int:orden_id>/exportar.csv", views.orden_compra_exportar_csv, name="orden_compra_exportar_csv"),
    path("ordenes-compra/<int:orden_id>/pdf/", views.orden_compra_pdf, name="orden_compra_pdf"),
]
