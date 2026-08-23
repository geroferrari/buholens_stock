import csv
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from stockero.crud_views import BaseListView, BaseCreateView, BaseUpdateView, BaseDeleteView
from stockero.permissions import AdminRequiredMixin, es_administrador
from stockero.utils import formato_local
from tenants.db_router import get_current_tenant

from .forms import (
    BancoForm, CategoriaForm, MarcaForm, PlanFinanciacionForm,
    ProveedorForm, ProductoForm, PromocionForm,
)
from .models import (
    Banco, EscaneoNoEncontrado, Marca, MovimientoStock, PlanFinanciacion, Producto, Categoria, Proveedor, Promocion,
    OrdenCompra, OrdenCompraItem,
)


def _admin_o_redirigir(request):
    """Chequeo de permisos para las vistas de función de Órdenes de compra
    (no son BaseListView/CreateView, así que no heredan AdminRequiredMixin).
    Devuelve un redirect si no es admin, o None si puede seguir."""
    if not es_administrador(request.user):
        messages.error(request, "Esta acción requiere permisos de administrador/a.")
        return redirect("home")
    return None


@login_required
def ingreso_rapido(request):
    return render(request, "inventory/ingreso_rapido.html")


@login_required
@require_GET
def generar_codigo_barras_ajax(request):
    """Genera un código de barras único para completar a mano en el
    formulario de producto ANTES de guardar (en vez de dejarlo en blanco y
    que se genere solo al guardar, como pasaba antes)."""
    codigo = Producto.generar_codigo_barras()
    while Producto.objects.filter(codigo_barras=codigo).exists():
        codigo = Producto.generar_codigo_barras()
    return JsonResponse({"codigo": codigo})


@login_required
def etiquetas(request):
    """Imprime una o varias etiquetas. Recibe ?ids=1,2,3 (uno o más ids de Producto)."""
    ids = [i for i in request.GET.get("ids", "").split(",") if i.strip().isdigit()]
    productos = Producto.objects.filter(pk__in=ids)
    if not productos:
        return render(request, "inventory/_resultado_ingreso.html", {"error": "No se seleccionó ningún producto para imprimir."})
    return render(request, "inventory/etiquetas.html", {"productos": productos})


@login_required
@require_POST
def registrar_ingreso(request):
    codigo = request.POST.get("codigo", "").strip()
    try:
        cantidad = int(request.POST.get("cantidad", 1) or 1)
    except (TypeError, ValueError):
        cantidad = 1
    if cantidad < 1:
        return render(
            request, "inventory/_resultado_ingreso.html",
            {"error": "La cantidad debe ser 1 o más."},
        )
    contexto = {}

    try:
        producto = Producto.objects.get(codigo_barras=codigo)
    except Producto.DoesNotExist:
        contexto["error"] = f"No existe ningún producto con código {codigo}."
        contexto["codigo_no_encontrado"] = codigo
        EscaneoNoEncontrado.objects.create(
            codigo_barras=codigo, origen=EscaneoNoEncontrado.Origen.INGRESO, usuario=request.user,
        )
        return render(request, "inventory/_resultado_ingreso.html", contexto)

    movimiento = MovimientoStock.objects.create(
        producto=producto,
        tipo=MovimientoStock.Tipo.INGRESO,
        cantidad=cantidad,
        usuario=request.user,
        nota="Ingreso rápido por escaneo",
    )
    producto.refresh_from_db()
    contexto["producto"] = producto
    contexto["cantidad"] = cantidad
    contexto["movimiento_id"] = movimiento.id
    return render(request, "inventory/_resultado_ingreso.html", contexto)


@login_required
@require_POST
def deshacer_ingreso(request, movimiento_id):
    """Revierte un ingreso reciente hecho por error (ej: escaneo sin querer),
    generando un egreso equivalente — no se borra ni edita el movimiento
    original para no perder el rastro de auditoría (los movimientos de stock
    son inmutables, se corrigen con otro movimiento)."""
    movimiento = get_object_or_404(
        MovimientoStock, pk=movimiento_id, tipo=MovimientoStock.Tipo.INGRESO, usuario=request.user,
    )
    nota_deshecho = f"Deshace ingreso #{movimiento.id}"

    if movimiento.fecha < timezone.now() - timedelta(minutes=10):
        return render(request, "inventory/_resultado_ingreso.html", {
            "error": "Ya pasó demasiado tiempo para deshacer este ingreso. Corregilo con un ajuste de stock si hace falta.",
        })
    if MovimientoStock.objects.filter(nota=nota_deshecho).exists():
        return render(request, "inventory/_resultado_ingreso.html", {
            "error": "Ese ingreso ya se había deshecho.",
        })

    MovimientoStock.objects.create(
        producto=movimiento.producto,
        tipo=MovimientoStock.Tipo.EGRESO,
        cantidad=movimiento.cantidad,
        usuario=request.user,
        nota=nota_deshecho,
    )
    movimiento.producto.refresh_from_db()
    return render(request, "inventory/_resultado_ingreso.html", {
        "deshecho": True, "producto": movimiento.producto, "cantidad": movimiento.cantidad,
    })


# ---------- Marca ----------

class MarcaListView(BaseListView):
    model = Marca
    title = "Marcas"
    headers = ["Nombre"]
    admin_only_actions = True
    search_fields = ["nombre"]
    search_placeholder = "Buscar marca..."
    create_url_name = "inventory:marca_nueva"
    edit_url_name = "inventory:marca_editar"
    delete_url_name = "inventory:marca_eliminar"
    export_csv_filename = "marcas.csv"

    def get_row(self, obj):
        return [obj.nombre]


class MarcaCreateView(AdminRequiredMixin, BaseCreateView):
    model = Marca
    form_class = MarcaForm
    title = "Nueva marca"
    cancel_url_name = "inventory:marca_lista"
    success_url = reverse_lazy("inventory:marca_lista")


class MarcaUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Marca
    form_class = MarcaForm
    title = "Editar marca"
    cancel_url_name = "inventory:marca_lista"
    success_url = reverse_lazy("inventory:marca_lista")


class MarcaDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Marca
    cancel_url_name = "inventory:marca_lista"
    success_url = reverse_lazy("inventory:marca_lista")


# ---------- Categoría ----------

class CategoriaListView(BaseListView):
    model = Categoria
    title = "Categorías"
    headers = ["Nombre", "Requiere receta", "Controla stock"]
    admin_only_actions = True
    create_url_name = "inventory:categoria_nueva"
    edit_url_name = "inventory:categoria_editar"
    delete_url_name = "inventory:categoria_eliminar"
    export_csv_filename = "categorias.csv"

    def get_row(self, obj):
        return [obj.nombre, "Sí" if obj.usa_receta else "No", "Sí" if obj.controla_stock else "No"]


class CategoriaCreateView(AdminRequiredMixin, BaseCreateView):
    model = Categoria
    form_class = CategoriaForm
    title = "Nueva categoría"
    cancel_url_name = "inventory:categoria_lista"
    success_url = reverse_lazy("inventory:categoria_lista")


class CategoriaUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Categoria
    form_class = CategoriaForm
    title = "Editar categoría"
    cancel_url_name = "inventory:categoria_lista"
    success_url = reverse_lazy("inventory:categoria_lista")


class CategoriaDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Categoria
    cancel_url_name = "inventory:categoria_lista"
    success_url = reverse_lazy("inventory:categoria_lista")


# ---------- Proveedor ----------

class ProveedorListView(BaseListView):
    model = Proveedor
    title = "Proveedores"
    headers = ["Nombre", "Contacto", "Teléfono"]
    admin_only_actions = True
    search_fields = ["nombre"]
    search_placeholder = "Buscar proveedor..."
    create_url_name = "inventory:proveedor_nuevo"
    edit_url_name = "inventory:proveedor_editar"
    delete_url_name = "inventory:proveedor_eliminar"
    export_csv_filename = "proveedores.csv"

    def get_row(self, obj):
        return [obj.nombre, obj.contacto, obj.telefono]


class ProveedorCreateView(AdminRequiredMixin, BaseCreateView):
    model = Proveedor
    form_class = ProveedorForm
    title = "Nuevo proveedor"
    cancel_url_name = "inventory:proveedor_lista"
    success_url = reverse_lazy("inventory:proveedor_lista")


class ProveedorUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Proveedor
    form_class = ProveedorForm
    title = "Editar proveedor"
    cancel_url_name = "inventory:proveedor_lista"
    success_url = reverse_lazy("inventory:proveedor_lista")


class ProveedorDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Proveedor
    cancel_url_name = "inventory:proveedor_lista"
    success_url = reverse_lazy("inventory:proveedor_lista")


# ---------- Lista de precios (solo lectura) ----------

class PrecioListView(BaseListView):
    """Versión liviana y de solo lectura del listado de productos, pensada
    para consultar precios rápido (sin las columnas/acciones de gestión del
    listado completo de Productos). Además del buscador de siempre, tiene un
    campo para escanear el código de barras y ver el precio en un popup."""
    model = Producto
    title = "Lista de precios"
    template_name = "inventory/precio_list.html"
    headers = ["Marca", "Modelo", "Categoría", "Color", "Precio"]
    search_fields = ["marca__nombre", "modelo", "categoria__nombre"]
    search_placeholder = "Buscar por marca, modelo o categoría..."
    export_csv_filename = "precios.csv"

    def get_queryset(self):
        return (
            super().get_queryset().filter(activo=True)
            .select_related("marca", "categoria").order_by("marca__nombre", "modelo")
        )

    def get_row(self, obj):
        return [
            obj.marca.nombre if obj.marca_id else "—", obj.modelo, obj.categoria.nombre,
            obj.color or "—", f"${obj.precio}",
        ]


@login_required
@require_GET
def consultar_precio(request):
    """Busca un producto por código de barras para el escaneo de la página de
    precios: no tiene efectos secundarios, solo devuelve los datos para el
    popup."""
    codigo = request.GET.get("codigo", "").strip()
    try:
        producto = Producto.objects.select_related("marca", "categoria").get(codigo_barras=codigo, activo=True)
    except Producto.DoesNotExist:
        return JsonResponse({"encontrado": False, "codigo": codigo})

    return JsonResponse({
        "encontrado": True,
        "producto": str(producto),
        "marca": producto.marca.nombre if producto.marca_id else "—",
        "modelo": producto.modelo,
        "categoria": producto.categoria.nombre,
        "color": producto.color or "—",
        "precio": str(producto.precio),
        "stock_actual": producto.stock_actual,
    })


# ---------- Producto ----------

class ProductoListView(BaseListView):
    model = Producto
    title = "Productos"
    admin_only_actions = True
    template_name = "inventory/producto_list.html"
    search_fields = ["codigo_barras", "marca__nombre", "modelo"]
    search_placeholder = "Buscar por código, marca, modelo..."
    sort_fields = {"Stock": "stock_actual"}
    create_url_name = "inventory:producto_nuevo"
    edit_url_name = "inventory:producto_editar"
    delete_url_name = "inventory:producto_eliminar"
    export_csv_filename = "productos.csv"

    # Catálogo completo de columnas seleccionables (orden fijo de visualización).
    # Cada entrada: clave -> (etiqueta, función que extrae el valor de un Producto).
    COLUMNAS = {
        "codigo_barras": ("Código de barras", lambda o: o.codigo_barras),
        "categoria": ("Categoría", lambda o: o.categoria.nombre),
        "proveedor": ("Proveedor", lambda o: o.proveedor.nombre if o.proveedor else "—"),
        "marca": ("Marca", lambda o: o.marca.nombre if o.marca_id else "—"),
        "modelo": ("Modelo", lambda o: o.modelo),
        "color": ("Color", lambda o: o.color),
        "color_cristal": ("Color cristal", lambda o: o.color_cristal),
        "calibre": ("Calibre", lambda o: o.calibre),
        "material": ("Material", lambda o: o.material),
        "precio_costo": ("Costo", lambda o: f"${o.precio_costo}"),
        "porcentaje_iva": ("IVA %", lambda o: f"{o.porcentaje_iva}%"),
        "precio": ("Precio", lambda o: f"${o.precio}"),
        "margen_ganancia_pct": ("Margen %", lambda o: f"{o.margen_ganancia_pct}%" if o.margen_ganancia_pct is not None else "—"),
        "stock_actual": ("Stock", lambda o: o.stock_actual if o.categoria.controla_stock else "∞"),
        "stock_minimo": ("Stock mínimo", lambda o: o.stock_minimo if o.categoria.controla_stock else "—"),
        "activo": ("Activo", lambda o: "Sí" if o.activo else "No"),
        "creado": ("Creado", lambda o: formato_local(o.creado, "%d/%m/%Y")),
        "actualizado": ("Última modificación", lambda o: formato_local(o.actualizado)),
    }
    COLUMNAS_DEFAULT = [
        "codigo_barras", "categoria", "marca", "modelo", "color", "precio", "stock_actual", "actualizado",
    ]
    SESSION_KEY = "producto_columnas_visibles"

    def get_queryset(self):
        qs = super().get_queryset().select_related("categoria", "proveedor", "marca")
        if self.request.GET.get("stock_bajo") == "1":
            qs = qs.filter(categoria__controla_stock=True, stock_actual__lte=F("stock_minimo"))
        if self.request.GET.get("marca"):
            qs = qs.filter(marca_id=self.request.GET["marca"])
        if self.request.GET.get("proveedor"):
            qs = qs.filter(proveedor_id=self.request.GET["proveedor"])
        if self.request.GET.get("categoria"):
            qs = qs.filter(categoria_id=self.request.GET["categoria"])
        return qs

    def get_paginate_by(self, queryset):
        # Al filtrar por marca/proveedor/categoría (para actualizar precios en
        # bloque, por ejemplo), se muestran todos en una sola página: si no,
        # "marcar todos" del checkbox solo alcanzaría a los de la página visible.
        if self.request.GET.get("marca") or self.request.GET.get("proveedor") or self.request.GET.get("categoria"):
            return 500
        return self.paginate_by

    def get(self, request, *args, **kwargs):
        # Las columnas (y por lo tanto los headers) dependen de la sesión del
        # usuario, así que hay que resolverlas ANTES de exportar a CSV (esa
        # rama de BaseListView.get() no pasa por get_context_data()).
        self.columnas_visibles = self._columnas_visibles()
        self.headers = [self.COLUMNAS[k][0] for k in self.columnas_visibles]
        return super().get(request, *args, **kwargs)

    def _columnas_visibles(self):
        # Los empleados siempre ven el set de columnas por defecto; solo un
        # administrador puede haber guardado una selección propia en su sesión.
        if not es_administrador(self.request.user):
            return list(self.COLUMNAS_DEFAULT)
        guardadas = self.request.session.get(self.SESSION_KEY)
        if not guardadas:
            return list(self.COLUMNAS_DEFAULT)
        visibles = [k for k in guardadas if k in self.COLUMNAS]
        return visibles or list(self.COLUMNAS_DEFAULT)

    def get_row(self, obj):
        return [self.COLUMNAS[k][1](obj) for k in self.columnas_visibles]

    def get_context_data(self, **kwargs):
        self.columnas_visibles = self._columnas_visibles()
        self.headers = [self.COLUMNAS[k][0] for k in self.columnas_visibles]
        ctx = super().get_context_data(**kwargs)
        # Adjuntamos la URL de la foto (si existe) a cada fila, para el template propio
        fotos = {p.pk: (p.foto.url if p.foto else None) for p in ctx["object_list"]}
        stock_bajo_ids = {
            p.pk for p in ctx["object_list"]
            if p.categoria.controla_stock and p.stock_actual <= p.stock_minimo
        }
        for row in ctx["rows"]:
            row["foto_url"] = fotos.get(row["id"])
            row["stock_bajo"] = row["id"] in stock_bajo_ids
        ctx["columnas_disponibles"] = [
            {"key": k, "label": label, "activa": k in self.columnas_visibles}
            for k, (label, _) in self.COLUMNAS.items()
        ]
        ctx["stock_bajo_activo"] = self.request.GET.get("stock_bajo") == "1"
        ctx["total_stock_bajo"] = Producto.objects.filter(
            categoria__controla_stock=True, stock_actual__lte=F("stock_minimo"), activo=True,
        ).count()
        ctx["marcas"] = Marca.objects.all()
        ctx["proveedores"] = Proveedor.objects.all()
        ctx["categorias"] = Categoria.objects.all()
        ctx["marca_seleccionada"] = self.request.GET.get("marca", "")
        ctx["proveedor_seleccionado"] = self.request.GET.get("proveedor", "")
        ctx["categoria_seleccionada"] = self.request.GET.get("categoria", "")
        return ctx


class ProductoCreateView(AdminRequiredMixin, BaseCreateView):
    model = Producto
    form_class = ProductoForm
    title = "Nuevo producto"
    template_name = "inventory/producto_form.html"
    cancel_url_name = "inventory:producto_lista"
    success_url = reverse_lazy("inventory:producto_lista")

    def get_initial(self):
        # Permite llegar acá desde "ingreso rápido" con el código ya escaneado
        # precargado (?codigo_barras=...), para no tener que retipearlo.
        initial = super().get_initial()
        codigo = self.request.GET.get("codigo_barras")
        if codigo:
            initial["codigo_barras"] = codigo
        item = self._orden_compra_item()
        if item:
            initial["modelo"] = item.modelo_texto
            initial["precio_costo"] = item.costo_unitario
            if item.orden.proveedor_id:
                initial["proveedor"] = item.orden.proveedor_id
        return initial

    def _orden_compra_item(self):
        # Si se llegó acá desde "vincular producto" de un ítem nuevo de una
        # orden de compra (?orden_item_id=...), traemos ese ítem para
        # precargar datos y, al guardar, vincularlo automáticamente.
        orden_item_id = self.request.GET.get("orden_item_id")
        if not orden_item_id:
            return None
        return OrdenCompraItem.objects.filter(
            pk=orden_item_id, producto__isnull=True,
        ).select_related("orden").first()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["orden_compra_item"] = self._orden_compra_item()
        return ctx

    def get_success_url(self):
        item = self._orden_compra_item()
        if item:
            item.producto = self.object
            item.save(update_fields=["producto"])
            messages.success(
                self.request,
                f"{self.object} quedó vinculado al pedido #{item.orden_id} — ya se puede recibir.",
            )
            return str(reverse_lazy("inventory:orden_compra_detalle", args=[item.orden_id]))
        if self.request.POST.get("imprimir_etiqueta") == "1":
            return f"{reverse_lazy('inventory:etiquetas')}?ids={self.object.pk}"
        return str(self.success_url)


class ProductoUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Producto
    form_class = ProductoForm
    title = "Editar producto"
    template_name = "inventory/producto_form.html"
    cancel_url_name = "inventory:producto_lista"
    success_url = reverse_lazy("inventory:producto_lista")

    def get_success_url(self):
        if self.request.POST.get("imprimir_etiqueta") == "1":
            return f"{reverse_lazy('inventory:etiquetas')}?ids={self.object.pk}"
        return str(self.success_url)


class ProductoDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Producto
    cancel_url_name = "inventory:producto_lista"
    success_url = reverse_lazy("inventory:producto_lista")


class ProductoColumnasUpdateView(AdminRequiredMixin, View):
    """Guarda en la sesión del administrador qué columnas quiere ver en el listado de productos."""

    def post(self, request):
        seleccion = set(request.POST.getlist("columnas"))
        validas = [k for k in ProductoListView.COLUMNAS if k in seleccion]
        request.session[ProductoListView.SESSION_KEY] = validas or list(ProductoListView.COLUMNAS_DEFAULT)
        next_url = request.POST.get("next") or reverse_lazy("inventory:producto_lista")
        return redirect(next_url)


class ProductoEliminarMasivoView(AdminRequiredMixin, View):
    """Elimina en bloque los productos seleccionados en el listado."""

    def post(self, request):
        ids = [i for i in request.POST.get("ids", "").split(",") if i.strip().isdigit()]
        productos = Producto.objects.filter(pk__in=ids)
        eliminados = 0
        protegidos = 0
        for producto in productos:
            try:
                producto.delete()
                eliminados += 1
            except ProtectedError:
                protegidos += 1
        if eliminados:
            messages.success(request, f"{eliminados} producto(s) enviado(s) a la papelera. Se pueden recuperar desde ahí.")
        if protegidos:
            messages.error(
                request,
                f"{protegidos} producto(s) no se pudieron eliminar por estar en uso "
                "(ventas, movimientos de stock, recetas, etc).",
            )
        if not eliminados and not protegidos:
            messages.info(request, "No se seleccionó ningún producto para eliminar.")
        return redirect("inventory:producto_lista")


class ProductoActualizarPreciosView(AdminRequiredMixin, View):
    """Actualiza el precio (y opcionalmente el costo) de varios productos de
    una sola vez — pensado para actualizaciones de lista de un proveedor o de
    una marca completa, además de selecciones puntuales."""

    def post(self, request):
        ids = [i for i in request.POST.get("ids", "").split(",") if i.strip().isdigit()]
        productos = Producto.objects.filter(pk__in=ids)
        modo = request.POST.get("modo")
        actualizar_costo = request.POST.get("actualizar_costo") == "1"
        try:
            valor = Decimal(request.POST.get("valor", "").replace(",", "."))
        except (InvalidOperation, AttributeError):
            messages.error(request, "El valor ingresado no es un número válido.")
            return redirect("inventory:producto_lista")

        if not productos:
            messages.info(request, "No se seleccionó ningún producto para actualizar.")
            return redirect("inventory:producto_lista")

        def nuevo_precio(actual):
            if modo == "porcentaje":
                return max((actual * (1 + valor / 100)).quantize(Decimal("0.01")), Decimal("0"))
            return max(actual + valor, Decimal("0"))

        actualizados = 0
        for producto in productos:
            producto.precio = nuevo_precio(producto.precio)
            campos = ["precio"]
            if actualizar_costo and producto.precio_costo:
                producto.precio_costo = nuevo_precio(producto.precio_costo)
                campos.append("precio_costo")
            producto.save(update_fields=campos)
            actualizados += 1

        messages.success(request, f"Se actualizó el precio de {actualizados} producto(s).")
        return redirect(request.POST.get("next") or "inventory:producto_lista")


# ---------- Lista de precios (repricing por proveedor/marca/categoría) ----------

class ListaPreciosView(AdminRequiredMixin, View):
    """Pantalla para cuando un proveedor manda la lista de precios
    actualizada del mes: se filtran los productos correspondientes (por
    proveedor, marca y/o categoría), se carga el costo nuevo de cada uno y
    una fórmula (multiplicar o sumar) para calcular el precio de venta
    sugerido, con el margen resultante a la vista — todo se guarda de una."""

    def get(self, request):
        planes_financiacion = (
            PlanFinanciacion.objects.filter(activo=True).select_related("banco")
            .prefetch_related("categorias", "proveedores")
            .order_by("banco__nombre", "cuotas")
        )
        planes_financiacion = [p for p in planes_financiacion if p.esta_vigente()]

        promociones_vigentes = [
            p for p in Promocion.objects.filter(activa=True).prefetch_related("productos", "categorias")
            if p.esta_vigente()
        ]

        filtros_aplicados = bool(
            request.GET.get("proveedor") or request.GET.get("marca")
            or request.GET.get("categoria") or request.GET.get("q")
            or request.GET.get("financiacion") or request.GET.get("promocion")
        )
        productos = Producto.objects.none()
        if filtros_aplicados:
            productos = Producto.objects.filter(activo=True).select_related("marca", "categoria", "proveedor")
            if request.GET.get("financiacion"):
                # Financiación es excluyente con los filtros de catálogo (el
                # frontend ya los deshabilita entre sí): si por algún motivo
                # llegan los dos juntos, gana financiación y se ignoran los
                # demás en vez de combinarlos.
                plan_elegido = next((p for p in planes_financiacion if str(p.pk) == request.GET["financiacion"]), None)
                alcance = Q()
                if plan_elegido:
                    if plan_elegido.marcas.strip():
                        nombres_marca = [m.strip() for m in plan_elegido.marcas.split(",") if m.strip()]
                        alcance |= Q(marca__nombre__in=nombres_marca)
                    if plan_elegido.categorias.exists():
                        alcance |= Q(categoria__in=plan_elegido.categorias.all())
                    if plan_elegido.proveedores.exists():
                        alcance |= Q(proveedor__in=plan_elegido.proveedores.all())
                # Un Q() vacío (plan sin alcance definido, o plan_id inválido)
                # no debe traer TODO el catálogo — filtra a "nada" en ese caso.
                productos = productos.filter(alcance) if alcance else productos.none()
            elif request.GET.get("promocion"):
                # Mismo criterio que financiación pero para una promoción
                # (descuento al cliente): trae los productos alcanzados por su
                # marca/categoría/producto puntual. Se usa al crear una promo
                # para llevar a revisar los precios de lo que afecta.
                promo_elegida = next((p for p in promociones_vigentes if str(p.pk) == request.GET["promocion"]), None)
                alcance = Q()
                if promo_elegida:
                    if promo_elegida.marcas.strip():
                        nombres_marca = [m.strip() for m in promo_elegida.marcas.split(",") if m.strip()]
                        alcance |= Q(marca__nombre__in=nombres_marca)
                    if promo_elegida.categorias.exists():
                        alcance |= Q(categoria__in=promo_elegida.categorias.all())
                    if promo_elegida.productos.exists():
                        alcance |= Q(pk__in=promo_elegida.productos.values("pk"))
                productos = productos.filter(alcance) if alcance else productos.none()
            else:
                if request.GET.get("proveedor"):
                    productos = productos.filter(proveedor_id=request.GET["proveedor"])
                if request.GET.get("marca"):
                    productos = productos.filter(marca_id=request.GET["marca"])
                if request.GET.get("categoria"):
                    productos = productos.filter(categoria_id=request.GET["categoria"])
                if request.GET.get("q"):
                    q = request.GET["q"].strip()
                    productos = productos.filter(Q(modelo__icontains=q) | Q(marca__nombre__icontains=q))
            productos = productos.order_by("marca__nombre", "modelo")[:1000]

        # Para cada producto de la lista, qué promociones (descuento al
        # cliente) y qué planes de financiación (costo que absorbe el
        # comercio) lo afectan por su alcance. Se resalta en amarillo el
        # producto para que no se le pase por alto que su margen real "fluctúa"
        # respecto del precio de lista, y se le adjuntan los datos que el JS
        # usa para calcular en vivo cuánto se netea y el precio sugerido.
        for producto in productos:
            producto.planes_aplicables = [p for p in planes_financiacion if p.aplica_a(producto)]
            producto.promos_aplicables = [p for p in promociones_vigentes if p.aplica_a(producto)]

            # Financiación: el % más alto entre las que aplican (peor caso).
            producto.financ_pct = max(
                (p.costo_financiero_pct for p in producto.planes_aplicables), default=0,
            )
            # Promoción: la de mejor descuento por unidad (misma que usaría el
            # punto de venta). El 2x1 no se puede expresar como % por unidad,
            # así que se marca aparte y no entra en el cálculo del margen.
            producto.promo_tipo = ""
            producto.promo_valor = 0
            producto.tiene_2x1 = any(
                p.tipo_descuento == Promocion.TipoDescuento.DOS_POR_UNO for p in producto.promos_aplicables
            )
            promos_pct_fijo = [
                p for p in producto.promos_aplicables
                if p.tipo_descuento in (Promocion.TipoDescuento.PORCENTAJE, Promocion.TipoDescuento.MONTO_FIJO)
            ]
            if promos_pct_fijo and producto.precio:
                mejor = min(promos_pct_fijo, key=lambda p: p.precio_con_descuento(producto.precio))
                producto.promo_tipo = mejor.tipo_descuento
                producto.promo_valor = mejor.valor

        return render(request, "inventory/lista_precios.html", {
            "productos": productos,
            "filtros_aplicados": filtros_aplicados,
            "marcas": Marca.objects.all(),
            "proveedores": Proveedor.objects.all(),
            "categorias": Categoria.objects.all(),
            "marca_seleccionada": request.GET.get("marca", ""),
            "proveedor_seleccionado": request.GET.get("proveedor", ""),
            "financiacion_seleccionada": request.GET.get("financiacion", ""),
            "categoria_seleccionada": request.GET.get("categoria", ""),
            "search_query": request.GET.get("q", ""),
            "planes_financiacion": planes_financiacion,
        })


class ListaPreciosGuardarView(AdminRequiredMixin, View):
    """Guarda costo/precio de uno o varios productos de una. Se usa tanto
    para el botón "Guardar cambios" de abajo de toda la tabla (todos los
    productos filtrados, POST normal con redirect) como para el botón 💾 de
    cada fila (un solo producto, AJAX con respuesta JSON)."""

    def post(self, request):
        es_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        ids = {key.removeprefix("costo_") for key in request.POST if key.startswith("costo_")}
        actualizados = 0
        ahora = timezone.now()
        for pk in ids:
            campos = {}
            costo_raw = request.POST.get(f"costo_{pk}", "").strip()
            precio_raw = request.POST.get(f"precio_{pk}", "").strip()
            try:
                if costo_raw:
                    campos["precio_costo"] = Decimal(costo_raw.replace(",", "."))
                if precio_raw:
                    campos["precio"] = Decimal(precio_raw.replace(",", "."))
            except InvalidOperation:
                continue
            if campos:
                # .update() no dispara auto_now, así que "actualizado" se
                # pisa a mano (así la columna de última actualización
                # refleja bien cuándo se tocó el precio, no cuándo se creó
                # el producto).
                campos["actualizado"] = ahora
                if Producto.objects.filter(pk=pk).update(**campos):
                    actualizados += 1

        if es_ajax:
            return JsonResponse({"ok": True, "actualizados": actualizados, "actualizado_iso": ahora.isoformat()})
        messages.success(request, f"Se actualizaron {actualizados} producto(s).")
        return redirect(f"{reverse_lazy('inventory:lista_precios')}?{request.POST.get('querystring', '')}")


# ---------- Financiación (bancos y sus promos de cuotas) ----------

class BancoListView(AdminRequiredMixin, BaseListView):
    model = Banco
    title = "Bancos"
    headers = ["Nombre"]
    search_fields = ["nombre"]
    search_placeholder = "Buscar banco..."
    create_url_name = "inventory:banco_nuevo"
    edit_url_name = "inventory:banco_editar"
    delete_url_name = "inventory:banco_eliminar"
    export_csv_filename = "bancos.csv"

    def get_row(self, obj):
        return [obj.nombre]


class BancoCreateView(AdminRequiredMixin, BaseCreateView):
    model = Banco
    form_class = BancoForm
    title = "Nuevo banco"
    cancel_url_name = "inventory:banco_lista"
    success_url = reverse_lazy("inventory:banco_lista")


class BancoUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Banco
    form_class = BancoForm
    title = "Editar banco"
    cancel_url_name = "inventory:banco_lista"
    success_url = reverse_lazy("inventory:banco_lista")


class BancoDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Banco
    cancel_url_name = "inventory:banco_lista"
    success_url = reverse_lazy("inventory:banco_lista")


class PlanFinanciacionCreateView(AdminRequiredMixin, BaseCreateView):
    model = PlanFinanciacion
    form_class = PlanFinanciacionForm
    title = "Nuevo plan de financiación"
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")

    def get_success_url(self):
        # Si la promo tiene un alcance definido, se lleva al usuario directo a
        # la lista de precios filtrada por esos productos, para que revise si
        # quiere ajustarles el precio ahora que van a tener este costo extra.
        tiene_alcance = bool(
            self.object.marcas.strip() or self.object.categorias.exists() or self.object.proveedores.exists()
        )
        if tiene_alcance:
            messages.info(
                self.request,
                f"Revisá y actualizá los precios de los productos afectados por “{self.object}”.",
            )
            return f"{reverse_lazy('inventory:lista_precios')}?financiacion={self.object.pk}"
        return str(self.success_url)


class PlanFinanciacionUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = PlanFinanciacion
    form_class = PlanFinanciacionForm
    title = "Editar plan de financiación"
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")


class PlanFinanciacionDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = PlanFinanciacion
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")


# ---------- Promoción (se muestra junto con Financiación en la misma pantalla) ----------

class PromocionListView(AdminRequiredMixin, View):
    """Promociones (descuentos al cliente) y planes de financiación (costo
    que absorbe el comercio por cuotas sin interés) se muestran juntos: son
    las dos formas en las que un vendedor termina cobrando distinto al
    precio de lista, así que tiene sentido gestionarlas desde un solo lugar."""

    def get(self, request):
        promociones = Promocion.objects.all().order_by("-fecha_inicio")
        planes = PlanFinanciacion.objects.select_related("banco").order_by("banco__nombre", "cuotas")
        return render(request, "inventory/promociones_financiacion.html", {
            "promociones": promociones,
            "planes": planes,
        })


class PromocionCreateView(AdminRequiredMixin, BaseCreateView):
    model = Promocion
    form_class = PromocionForm
    title = "Nueva promoción"
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")

    def get_success_url(self):
        tiene_alcance = bool(
            self.object.marcas.strip() or self.object.categorias.exists() or self.object.productos.exists()
        )
        if tiene_alcance:
            messages.info(
                self.request,
                f"Revisá y actualizá los precios de los productos afectados por “{self.object}”.",
            )
            return f"{reverse_lazy('inventory:lista_precios')}?promocion={self.object.pk}"
        return str(self.success_url)


class PromocionUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Promocion
    form_class = PromocionForm
    title = "Editar promoción"
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")


class PromocionDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Promocion
    cancel_url_name = "inventory:promocion_lista"
    success_url = reverse_lazy("inventory:promocion_lista")


# ---------- Códigos escaneados sin producto (para revisar después) ----------

class EscaneoNoEncontradoListView(AdminRequiredMixin, BaseListView):
    """Solo lectura + borrado: cuando ya se revisó/resolvió un código (ej: se
    cargó el producto), se elimina la fila de la lista para no acumular ruido."""
    model = EscaneoNoEncontrado
    title = "Códigos escaneados no encontrados"
    headers = ["Código", "Origen", "Fecha", "Usuario", "Venta"]
    search_fields = ["codigo_barras"]
    search_placeholder = "Buscar por código..."
    delete_url_name = "inventory:escaneo_no_encontrado_eliminar"
    export_csv_filename = "codigos_no_encontrados.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("usuario", "venta")

    def get_row(self, obj):
        return [
            obj.codigo_barras, obj.get_origen_display(), formato_local(obj.fecha),
            obj.usuario.username if obj.usuario else "—",
            f"#{obj.venta_id}" if obj.venta_id else "—",
        ]


class EscaneoNoEncontradoDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = EscaneoNoEncontrado
    cancel_url_name = "inventory:escaneo_no_encontrado_lista"
    success_url = reverse_lazy("inventory:escaneo_no_encontrado_lista")


# ---------- Movimientos de stock (solo lectura, auditoría) ----------

# ---------- Órdenes de compra a proveedores ----------

class OrdenCompraListView(AdminRequiredMixin, BaseListView):
    model = OrdenCompra
    title = "Órdenes de compra"
    headers = ["N°", "Proveedor", "Fecha", "Estado", "Ítems", "Total estimado"]
    search_fields = ["proveedor__nombre"]
    search_placeholder = "Buscar por proveedor..."
    detalle_url_name = "inventory:orden_compra_detalle"
    delete_url_name = "inventory:orden_compra_eliminar"
    create_url_name = "inventory:orden_compra_nueva"
    export_csv_filename = "ordenes_compra.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("proveedor").prefetch_related("items")

    def get_row(self, obj):
        return [
            f"#{obj.pk}", obj.proveedor.nombre, formato_local(obj.fecha_creacion),
            obj.get_estado_display(), obj.items.count(), f"${obj.total_estimado}",
        ]


@login_required
def orden_compra_nueva(request):
    """Elegí el proveedor para arrancar un pedido. Si ya había un borrador
    sin confirmar para ese proveedor, se retoma en vez de crear uno nuevo."""
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        proveedor = get_object_or_404(Proveedor, pk=request.POST.get("proveedor_id"))
        orden = OrdenCompra.objects.filter(
            proveedor=proveedor, estado=OrdenCompra.Estado.BORRADOR,
        ).order_by("-fecha_creacion").first()
        if not orden:
            orden = OrdenCompra.objects.create(proveedor=proveedor, usuario=request.user)
        return redirect("inventory:orden_compra_armar", orden_id=orden.pk)

    return render(request, "inventory/orden_compra_nueva.html", {"proveedores": Proveedor.objects.all()})


@login_required
def orden_compra_armar(request, orden_id):
    """Pantalla de armado del pedido (solo mientras está en Borrador):
    productos del proveedor elegido con su stock actual, para agregar
    cantidades a pedir, más un alta rápida de ítems que todavía no existen
    en el catálogo (modelos nuevos)."""
    orden = get_object_or_404(OrdenCompra.objects.select_related("proveedor"), pk=orden_id)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response
    if orden.estado != OrdenCompra.Estado.BORRADOR:
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)

    q = request.GET.get("q", "").strip()
    productos = Producto.objects.filter(proveedor=orden.proveedor, activo=True).select_related("marca", "categoria")
    if q:
        productos = productos.filter(
            Q(marca__nombre__icontains=q) | Q(modelo__icontains=q) | Q(color__icontains=q)
        )
    productos = list(productos.order_by("marca__nombre", "modelo"))

    cantidades_pedidas = {
        i.producto_id: i.cantidad_pedida for i in orden.items.filter(producto__isnull=False)
    }
    for producto in productos:
        producto.cantidad_pedida_actual = cantidades_pedidas.get(producto.id, 0)

    return render(request, "inventory/orden_compra_armar.html", {
        "orden": orden,
        "productos": productos,
        "query": q,
        "items": orden.items.select_related("producto", "producto__marca").all(),
    })


@login_required
@require_POST
def orden_compra_agregar_producto(request, orden_id):
    orden = get_object_or_404(OrdenCompra, pk=orden_id, estado=OrdenCompra.Estado.BORRADOR)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    producto = get_object_or_404(Producto, pk=request.POST.get("producto_id"), proveedor=orden.proveedor)
    try:
        cantidad = max(1, int(request.POST.get("cantidad", 1) or 1))
    except (TypeError, ValueError):
        cantidad = 1

    item, _creado = OrdenCompraItem.objects.get_or_create(
        orden=orden, producto=producto,
        defaults={"cantidad_pedida": 0, "costo_unitario": producto.precio_costo},
    )
    OrdenCompraItem.objects.filter(pk=item.pk).update(cantidad_pedida=F("cantidad_pedida") + cantidad)
    messages.success(request, f"Se agregaron {cantidad} unidad(es) de {producto} al pedido.")
    return redirect("inventory:orden_compra_armar", orden_id=orden.pk)


@login_required
@require_POST
def orden_compra_agregar_manual(request, orden_id):
    """Agrega al pedido un ítem que todavía no existe en el catálogo (modelo
    nuevo): se carga a mano con marca/modelo y se vincula a un Producto de
    verdad recién cuando llegue (ver `orden_compra_recibir_item`)."""
    orden = get_object_or_404(OrdenCompra, pk=orden_id, estado=OrdenCompra.Estado.BORRADOR)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    marca_texto = request.POST.get("marca_texto", "").strip()
    modelo_texto = request.POST.get("modelo_texto", "").strip()
    descripcion = request.POST.get("descripcion", "").strip()
    try:
        cantidad = max(1, int(request.POST.get("cantidad_pedida", 1) or 1))
    except (TypeError, ValueError):
        cantidad = 1
    try:
        costo = Decimal((request.POST.get("costo_unitario", "0") or "0").replace(",", "."))
    except InvalidOperation:
        costo = Decimal("0")

    if not marca_texto or not modelo_texto:
        messages.error(request, "Para un ítem nuevo hace falta al menos marca y modelo.")
        return redirect("inventory:orden_compra_armar", orden_id=orden.pk)

    OrdenCompraItem.objects.create(
        orden=orden, marca_texto=marca_texto, modelo_texto=modelo_texto, descripcion=descripcion,
        cantidad_pedida=cantidad, costo_unitario=costo,
    )
    messages.success(request, f"Se agregó {marca_texto} {modelo_texto} al pedido.")
    return redirect("inventory:orden_compra_armar", orden_id=orden.pk)


@login_required
@require_POST
def orden_compra_quitar_item(request, orden_id, item_id):
    orden = get_object_or_404(OrdenCompra, pk=orden_id, estado=OrdenCompra.Estado.BORRADOR)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response
    OrdenCompraItem.objects.filter(pk=item_id, orden=orden).delete()
    return redirect("inventory:orden_compra_armar", orden_id=orden.pk)


@login_required
@require_POST
def orden_compra_confirmar(request, orden_id):
    """Pasa el pedido de Borrador a Enviada: a partir de acá los ítems quedan
    fijos (ya se mandó al proveedor) y lo único que se puede hacer es
    registrar la recepción de mercadería."""
    orden = get_object_or_404(OrdenCompra, pk=orden_id, estado=OrdenCompra.Estado.BORRADOR)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    if not orden.items.exists():
        messages.error(request, "Agregá al menos un ítem antes de confirmar el pedido.")
        return redirect("inventory:orden_compra_armar", orden_id=orden.pk)

    orden.notas = request.POST.get("notas", "").strip()
    orden.estado = OrdenCompra.Estado.ENVIADA
    orden.save(update_fields=["notas", "estado"])
    messages.success(request, "Pedido confirmado: ya se puede exportar/imprimir para mandarle al proveedor.")
    return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)


@login_required
@require_POST
def orden_compra_cancelar(request, orden_id):
    orden = get_object_or_404(OrdenCompra, pk=orden_id)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    if orden.items.filter(cantidad_recibida__gt=0).exists():
        messages.error(request, "No se puede cancelar: ya se recibió mercadería de este pedido.")
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)

    orden.estado = OrdenCompra.Estado.CANCELADA
    orden.save(update_fields=["estado"])
    messages.success(request, "Pedido cancelado.")
    return redirect("inventory:orden_compra_lista")


class OrdenCompraDeleteView(AdminRequiredMixin, BaseDeleteView):
    """Elimina una orden de compra por completo (con sus ítems, en cascada).
    Solo admin. A diferencia de 'cancelar' (que la conserva en estado
    Cancelada), esto la borra de verdad — pensado para limpiar pedidos de
    prueba. El stock ya ingresado por recepciones NO se revierte (esos
    movimientos son aparte); se avisa si el pedido tenía mercadería recibida."""
    model = OrdenCompra
    cancel_url_name = "inventory:orden_compra_lista"
    success_url = reverse_lazy("inventory:orden_compra_lista")
    success_message = "Pedido eliminado."

    def form_valid(self, form):
        if self.get_object().items.filter(cantidad_recibida__gt=0).exists():
            messages.warning(
                self.request,
                "Ojo: este pedido tenía mercadería recibida; el stock ya ingresado NO se revierte al eliminarlo.",
            )
        return super().form_valid(form)


@login_required
def orden_compra_detalle(request, orden_id):
    orden = get_object_or_404(
        OrdenCompra.objects.select_related("proveedor", "usuario")
        .prefetch_related("items__producto__marca"),
        pk=orden_id,
    )
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response
    if orden.estado == OrdenCompra.Estado.BORRADOR:
        return redirect("inventory:orden_compra_armar", orden_id=orden.pk)
    return render(request, "inventory/orden_compra_detalle.html", {"orden": orden})


@login_required
@require_POST
def orden_compra_recibir_item(request, orden_id, item_id):
    """Registra la llegada de mercadería de un ítem puntual: genera el
    ingreso de stock (el ítem ya tiene que estar vinculado a un Producto del
    catálogo) y actualiza cuánto quedó pendiente, admitiendo entregas
    parciales (el proveedor manda menos de lo pedido)."""
    orden = get_object_or_404(OrdenCompra, pk=orden_id)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    if orden.estado not in (OrdenCompra.Estado.ENVIADA, OrdenCompra.Estado.PARCIAL):
        messages.error(request, "Este pedido no está en condiciones de recibir mercadería.")
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)

    item = get_object_or_404(OrdenCompraItem, pk=item_id, orden=orden)
    if item.es_nuevo:
        messages.error(request, "Primero tenés que vincular este ítem a un producto del catálogo.")
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)

    try:
        cantidad = int(request.POST.get("cantidad", 0) or 0)
    except (TypeError, ValueError):
        cantidad = 0
    if cantidad < 1:
        messages.error(request, "Ingresá una cantidad válida para recibir.")
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)
    if cantidad > item.pendiente:
        messages.error(request, f"No se puede recibir más de lo pendiente ({item.pendiente}).")
        return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)

    with transaction.atomic(using=get_current_tenant() or "default"):
        MovimientoStock.objects.create(
            producto=item.producto, tipo=MovimientoStock.Tipo.INGRESO, cantidad=cantidad,
            usuario=request.user, nota=f"Recepción de orden de compra #{orden.pk}",
        )
        OrdenCompraItem.objects.filter(pk=item.pk).update(cantidad_recibida=F("cantidad_recibida") + cantidad)
        orden.actualizar_estado_recepcion()

    messages.success(request, f"Se recibieron {cantidad} unidad(es) de {item.nombre}.")
    return redirect("inventory:orden_compra_detalle", orden_id=orden.pk)


@login_required
def orden_compra_exportar_csv(request, orden_id):
    orden = get_object_or_404(OrdenCompra.objects.select_related("proveedor"), pk=orden_id)
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="orden_compra_{orden.pk}.csv"'
    response.write("﻿")  # BOM: para que Excel abra los acentos bien
    writer = csv.writer(response)
    writer.writerow(["Marca", "Modelo", "Descripción", "Cantidad pedida", "Costo unitario", "Subtotal estimado"])
    for item in orden.items.select_related("producto", "producto__marca"):
        if item.producto_id:
            marca = item.producto.marca.nombre if item.producto.marca_id else "—"
            modelo = item.producto.modelo
            descripcion = item.producto.color or "—"
        else:
            marca, modelo, descripcion = item.marca_texto, item.modelo_texto, (item.descripcion or "—")
        writer.writerow([marca, modelo, descripcion, item.cantidad_pedida, item.costo_unitario, item.subtotal_estimado])
    return response


@login_required
def orden_compra_pdf(request, orden_id):
    """Página lista para imprimir (Ctrl+P → Guardar como PDF) y mandarle al
    proveedor, igual que las etiquetas de código de barras."""
    orden = get_object_or_404(
        OrdenCompra.objects.select_related("proveedor").prefetch_related("items__producto__marca"), pk=orden_id,
    )
    redirect_response = _admin_o_redirigir(request)
    if redirect_response:
        return redirect_response
    return render(request, "inventory/orden_compra_pdf.html", {"orden": orden})


class MovimientoStockListView(AdminRequiredMixin, BaseListView):
    model = MovimientoStock
    title = "Movimientos de stock"
    headers = ["Fecha", "Producto", "Tipo", "Cantidad", "Usuario", "Nota"]
    search_fields = ["producto__codigo_barras", "producto__marca__nombre", "producto__modelo", "nota"]
    search_placeholder = "Buscar por código, marca o nota..."
    export_csv_filename = "movimientos_stock.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("producto", "usuario")

    def get_row(self, obj):
        return [
            formato_local(obj.fecha), str(obj.producto), obj.get_tipo_display(),
            obj.cantidad, obj.usuario.username if obj.usuario else "—", obj.nota or "—",
        ]
