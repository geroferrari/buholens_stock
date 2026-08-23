from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from tenants.db_router import tenant_atomic
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_GET, require_POST

from customers.models import Cliente, ObraSocial
from inventory.models import (
    EscaneoNoEncontrado, Producto, MovimientoStock, Promocion,
    categoria_pendiente, marca_para_express, mejor_promocion_para,
)
from stockero.crud_views import BaseListView, BaseCreateView, BaseUpdateView, BaseDeleteView
from stockero.permissions import AdminRequiredMixin, es_administrador
from stockero.utils import formato_local
from prescriptions.forms import RecetaForm
from prescriptions.models import OrdenLaboratorio, Receta

from .forms import VendedorForm
from .models import Venta, VentaItem, Vendedor, Devolucion

MENSAJE_WHATSAPP_LISTO = "Hola! Tu anteojo ya está listo para retirar."


def _cart_context(venta, **extra):
    """Contexto estándar para renderizar sales/_cart.html y sales/_cliente_info.html:
    además de la venta, arma la lista de promociones activas/vigentes para que
    cada item del carrito pueda elegir a mano cuál se le aplica (si le
    corresponde alguna)."""
    promociones_disponibles = [
        p for p in Promocion.objects.filter(activa=True).prefetch_related("productos", "categorias")
        if p.esta_vigente()
    ]
    return {
        "venta": venta,
        "promociones_disponibles": promociones_disponibles,
        "forma_pago_choices": Venta.FormaPago.choices,
        "obras_sociales": ObraSocial.objects.filter(activa=True),
        # Determina si el paso "cristales" del wizard tiene algo que mostrar
        # (se salta si la venta no tiene ningún item que use receta).
        "hay_items_con_receta": any(i.producto.categoria.usa_receta for i in venta.items.all()),
        **extra,
    }


def _receta_detalle_dict(receta):
    """Serializa una receta con el detalle óptico relevante, para poder
    mostrarlo en un popup (y así validar que es la receta correcta) antes de
    asociarla a una venta, o simplemente para consultarla desde el carrito."""
    return {
        "id": receta.id,
        "cliente": str(receta.cliente),
        "fecha_recibido": receta.fecha_recibido.strftime("%d/%m/%Y"),
        "medico": str(receta.medico) if receta.medico else None,
        "obra_social": str(receta.obra_social) if receta.obra_social else None,
        "lejos": {
            "od": {
                "esfera": receta.lejos_od_esfera, "cilindro": receta.lejos_od_cilindro,
                "eje": receta.lejos_od_eje, "adicion": receta.lejos_od_adicion,
            },
            "oi": {
                "esfera": receta.lejos_oi_esfera, "cilindro": receta.lejos_oi_cilindro,
                "eje": receta.lejos_oi_eje, "adicion": receta.lejos_oi_adicion,
            },
            "dnp": receta.lejos_dnp, "tipo_cristal": receta.lejos_tipo_cristal,
            "tratamientos": receta.lejos_tratamientos,
        },
        "cerca": {
            "od": {"esfera": receta.cerca_od_esfera, "cilindro": receta.cerca_od_cilindro, "eje": receta.cerca_od_eje},
            "oi": {"esfera": receta.cerca_oi_esfera, "cilindro": receta.cerca_oi_cilindro, "eje": receta.cerca_oi_eje},
            "dnp": receta.cerca_dnp, "tipo_cristal": receta.cerca_tipo_cristal,
            "tratamientos": receta.cerca_tratamientos,
        },
        "observaciones": receta.observaciones,
    }


def _venta_fragments_payload(request, venta, cart_template="sales/_cart.html", receta_sugerida_candidata=None, **extra):
    context = _cart_context(venta, **extra)
    payload = {
        "cliente_html": render_to_string("sales/_cliente_info.html", context, request=request),
        "cart_html": render_to_string(cart_template, context, request=request),
    }
    if receta_sugerida_candidata:
        payload["receta_sugerida"] = _receta_detalle_dict(receta_sugerida_candidata)
    # El error también va suelto en el JSON (no solo ya renderizado adentro
    # del cart_html): así el JS que dispara la acción puede frenar antes de
    # dar por exitosa la operación (limpiar formularios, cerrar modales,
    # avanzar de paso, etc).
    if extra.get("error"):
        payload["error"] = extra["error"]
    return payload


def _render_venta_fragments(request, venta, **kwargs):
    """El punto de venta tiene DOS zonas que se actualizan por AJAX (los datos
    del cliente/vendedor arriba, y el carrito de productos abajo), así que
    cada acción devuelve los dos fragmentos ya renderizados en un JSON, y el
    JS decide dónde poner cada uno."""
    return JsonResponse(_venta_fragments_payload(request, venta, **kwargs))


def _ajustar_stock_forzado(producto, cantidad_necesaria, venta, usuario):
    """Cuando el stock del sistema no alcanza pero un admin decide vender
    igual (porque confía en que el producto está físicamente disponible),
    se registra un ajuste que lo lleva justo a la cantidad necesaria — así el
    stock queda consistente con la venta y, a la vez, el movimiento marcado
    como "forzado" queda de rastro para que alguien revise el conteo real."""
    faltante = cantidad_necesaria - producto.stock_actual
    MovimientoStock.objects.create(
        producto=producto,
        tipo=MovimientoStock.Tipo.AJUSTE,
        cantidad=faltante,
        usuario=usuario,
        nota=f"Ajuste forzado desde venta #{venta.pk}: el sistema marcaba stock insuficiente al vender. Revisar conteo físico.",
    )
    producto.refresh_from_db()
    venta.registrar_incidencia(f"Stock forzado en {producto}: faltaban {faltante} unidad(es).")


@login_required
def nueva_venta(request):
    # Si el usuario ya tiene una venta abierta pero todavía en blanco (sin
    # vendedor, cliente ni items), se reutiliza en vez de crear una nueva
    # cada vez que se entra a esta página: si no, el número de venta subía
    # solo con visitar la pantalla, sin haber vendido nada. Pero si ya tiene
    # algo cargado, NO se reutiliza: varios empleados comparten el mismo
    # login de la terminal (por eso el vendedor es independiente del usuario
    # de Django, ver Vendedor.usuario), así que la próxima persona que entre
    # a "nueva venta" tiene que arrancar un carrito propio, no heredar el de
    # quien ya estaba cargando una venta.
    venta = Venta.objects.filter(
        usuario=request.user, estado=Venta.Estado.ABIERTA,
        vendedor__isnull=True, cliente__isnull=True, items__isnull=True,
    ).order_by("-fecha").first()
    if not venta:
        venta = Venta.objects.create(usuario=request.user)
    return redirect("sales:pos", venta_id=venta.pk)


@login_required
@require_POST
def cancelar_venta(request, venta_id):
    """Cancela (elimina) una venta abierta que no se va a concretar. No toca
    stock porque las ventas abiertas todavía no descontaron nada. Se borra
    DEFINITIVO (no va a la papelera): es un carrito abandonado, no tiene sentido
    conservarlo ni ensuciar la papelera con carritos vacíos."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    venta.eliminar_definitivo()
    return redirect("home")


@login_required
def pos(request, venta_id):
    # Solo ventas abiertas: para VER el detalle de una venta ya confirmada o
    # anulada está venta_detalle (de solo lectura de verdad, sin ningún
    # control editable) — esta pantalla es para armar/cobrar la venta.
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    vendedores = Vendedor.objects.filter(activo=True)
    # _cart_context aporta las listas que el carrito necesita ya en la carga
    # inicial (promociones, formas de pago y obras sociales); sin esto queda
    # vacío hasta el primer refresco por AJAX.
    return render(request, "sales/pos.html", {**_cart_context(venta), "vendedores": vendedores})


@login_required
def venta_detalle(request, venta_id):
    """Resumen de solo lectura de una venta (abierta, confirmada o anulada):
    a diferencia de `pos`, acá no hay NADA editable, es puro repaso de lo
    que se vendió, cómo se pagó y el estado de entrega."""
    venta = get_object_or_404(
        Venta.objects.select_related("cliente", "vendedor")
        .prefetch_related("items__producto", "items__receta", "items__orden_laboratorio"),
        pk=venta_id,
    )
    # Solo tiene sentido "completar" una venta ya CONFIRMADA a la que todavía
    # le falta algo (cobrar el saldo y/o entregar). Calculado acá (no en el
    # template) para no depender de la precedencia de and/or del {% if %}.
    falta_completar = venta.estado == Venta.Estado.CONFIRMADA and (
        not venta.entregado or venta.saldo_pendiente > 0
    )
    return render(request, "sales/venta_detalle.html", {"venta": venta, "falta_completar": falta_completar})


@login_required
@require_POST
def set_vendedor(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    vendedor_id = request.POST.get("vendedor_id")
    venta.vendedor = get_object_or_404(Vendedor, pk=vendedor_id) if vendedor_id else None
    venta.save(update_fields=["vendedor"])
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def set_forma_pago(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    forma_pago = request.POST.get("forma_pago", "")
    if forma_pago not in Venta.FormaPago.values:
        forma_pago = ""
    venta.forma_pago = forma_pago
    if forma_pago == Venta.FormaPago.TARJETA:
        try:
            cuotas = int(request.POST.get("cuotas") or 0)
        except (TypeError, ValueError):
            cuotas = 0
        venta.cuotas = cuotas if cuotas > 0 else None
    else:
        venta.cuotas = None
    venta.save(update_fields=["forma_pago", "cuotas"])
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def set_obra_social(request, venta_id):
    """Marca (o desmarca) que la venta se gestiona por obra social: el cliente
    puede pagar una parte (o nada) en el momento, así que al confirmar la venta
    queda en la cola de 'Ventas por obra social' para revisar y terminar a mano.
    Al marcarla, si el cliente tiene una obra social cargada se preselecciona."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    es_obra_social = request.POST.get("es_obra_social") == "1"
    venta.es_obra_social = es_obra_social
    campos = ["es_obra_social"]
    if not es_obra_social:
        venta.obra_social = None  # al desmarcar, se olvida cuál
        campos.append("obra_social")
    elif venta.obra_social_id is None and venta.cliente and venta.cliente.obra_social_id:
        venta.obra_social_id = venta.cliente.obra_social_id  # default: la del cliente
        campos.append("obra_social")
    venta.save(update_fields=campos)
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def set_obra_social_cual(request, venta_id):
    """Elige qué obra social se usa en la venta (desplegable del carrito)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    obra_social_id = request.POST.get("obra_social_id") or None
    if obra_social_id:
        venta.obra_social = get_object_or_404(ObraSocial, pk=obra_social_id, activa=True)
    else:
        venta.obra_social = None
    venta.save(update_fields=["obra_social"])
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def aplicar_descuento_manual(request, venta_id):
    """Descuento a mano sobre el total de la venta (además de las
    promociones por producto), a criterio del vendedor/a."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    tipo = request.POST.get("tipo", "")
    if tipo not in Venta.TipoDescuentoManual.values:
        tipo = ""
    try:
        valor = Decimal(request.POST.get("valor", "").strip() or "0")
    except InvalidOperation:
        valor = Decimal("0")
    venta.descuento_manual_tipo = tipo
    venta.descuento_manual_valor = valor if tipo else Decimal("0")
    venta.save(update_fields=["descuento_manual_tipo", "descuento_manual_valor"])
    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def set_observaciones(request, venta_id):
    """Nota libre asociada a la venta (ej: algo que pasó durante la
    atención), para dejarlo registrado antes de confirmarla."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    venta.observaciones = request.POST.get("observaciones", "").strip()
    venta.save(update_fields=["observaciones"])
    return _render_venta_fragments(request, venta)


@login_required
@require_GET
def buscar_clientes(request, venta_id):
    q = request.GET.get("q", "").strip()
    clientes = []
    if q:
        clientes = list(Cliente.buscar(q)[:10].values("id", "nombre", "apellido", "dni", "email"))
    return JsonResponse({"resultados": clientes})


@login_required
@require_POST
def set_cliente(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    cliente_id = request.POST.get("cliente_id")
    venta.cliente = get_object_or_404(Cliente, pk=cliente_id) if cliente_id else None
    campos = ["cliente"]
    # Si el cliente tiene una obra social cargada, se precarga en la venta para
    # tenerla lista (se usa o no según se marque "es por obra social"). No se
    # pisa si ya se había elegido una a mano.
    if venta.cliente and venta.cliente.obra_social_id and not venta.obra_social_id:
        venta.obra_social_id = venta.cliente.obra_social_id
        campos.append("obra_social")
    venta.save(update_fields=campos)

    # Si el cliente elegido tiene recetas y todavía no se asoció ninguna a
    # esta venta, se sugiere la más reciente (el JS decide si mostrar el
    # popup de confirmación, según si vino de recién elegir un cliente).
    receta_sugerida_candidata = None
    if venta.cliente_id and not venta.receta_sugerida_id:
        receta_sugerida_candidata = venta.cliente.recetas.order_by("-fecha_recibido").first()

    return _render_venta_fragments(request, venta, receta_sugerida_candidata=receta_sugerida_candidata)


@login_required
@require_POST
def asociar_receta_venta(request, venta_id):
    """Asocia una receta a nivel de venta completa (no solo a un item): los
    items existentes que requieran receta y todavía no tengan una asignada
    la usan, y de ahora en más los que se agreguen a esta misma venta también
    la van a usar por default (ver `escanear`/`agregar_item_catalogo`)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    receta_id = request.POST.get("receta_id")
    receta = get_object_or_404(Receta, pk=receta_id) if receta_id else None

    venta.receta_sugerida = receta
    venta.save(update_fields=["receta_sugerida"])

    if receta:
        venta.items.filter(receta__isnull=True, producto__categoria__usa_receta=True).update(receta=receta)

    return _render_venta_fragments(request, venta)


@login_required
@require_GET
def detalle_receta(request, receta_id):
    """Detalle completo de una receta (para el popup de "ver receta" desde el
    carrito, o para validar antes de asociar la sugerida al elegir cliente)."""
    receta = get_object_or_404(Receta, pk=receta_id)
    return JsonResponse(_receta_detalle_dict(receta))


@login_required
@require_GET
def receta_modal_form(request, venta_id):
    """Fragmento del formulario de receta para cargarla sin salir del punto de
    venta (en un popup): el cliente ya viene fijo (no se puede elegir otro acá,
    a diferencia del formulario completo de Recetas)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    if not venta.cliente_id:
        return JsonResponse({"error": "Esta venta todavía no tiene un cliente asociado."}, status=400)
    form = RecetaForm(initial={"cliente": venta.cliente_id})
    html = render_to_string(
        "prescriptions/_receta_campos.html", {"form": form, "mostrar_cliente": False}, request=request,
    )
    return JsonResponse({"html": html})


@login_required
@require_POST
def receta_modal_crear(request, venta_id):
    """Crea la receta cargada en el popup y la deja como la receta sugerida de
    la venta (se acaba de cargar específicamente para esto), igual que si se
    hubiera confirmado el popup de "¿asociar esta receta?"."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    datos = request.POST.copy()
    datos["cliente"] = venta.cliente_id
    form = RecetaForm(data=datos, files=request.FILES)
    if not form.is_valid():
        html = render_to_string(
            "prescriptions/_receta_campos.html", {"form": form, "mostrar_cliente": False}, request=request,
        )
        return JsonResponse({"ok": False, "html": html})

    receta = form.save(commit=False)
    receta.cargada_por = request.user  # para el historial de carga de recetas
    receta.save()
    venta.receta_sugerida = receta
    venta.save(update_fields=["receta_sugerida"])
    venta.items.filter(receta__isnull=True, producto__categoria__usa_receta=True).update(receta=receta)

    payload = _venta_fragments_payload(request, venta)
    payload["ok"] = True
    return JsonResponse(payload)


@login_required
@require_POST
def cliente_nuevo_rapido(request, venta_id):
    """Alta de cliente sin salir del punto de venta. Ningún campo es
    obligatorio, pero si vino todo vacío no se crea nada (si no, "guardar" sin
    cargar nada por error deja clientes en blanco dando vueltas)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    obra_social_id = request.POST.get("obra_social_id") or None
    cliente = Cliente.crear_rapido(
        nombre=request.POST.get("nombre", "").strip(),
        apellido=request.POST.get("apellido", "").strip(),
        dni=request.POST.get("dni", "").strip(),
        telefono=request.POST.get("telefono", "").strip(),
        email=request.POST.get("email", "").strip(),
        direccion=request.POST.get("direccion", "").strip(),
        obra_social_id=obra_social_id if ObraSocial.objects.filter(pk=obra_social_id).exists() else None,
    )
    if cliente is None:
        return _render_venta_fragments(request, venta, error="Completá al menos un dato del cliente antes de guardar.")
    venta.cliente = cliente
    campos = ["cliente"]
    if cliente.obra_social_id and not venta.obra_social_id:
        venta.obra_social_id = cliente.obra_social_id
        campos.append("obra_social")
    venta.save(update_fields=campos)
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def cliente_email_rapido(request, venta_id):
    """Guarda (o actualiza) solo el mail del cliente, sin pedir más datos —
    útil para armar base de contactos aunque la venta no sea con receta."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    email = request.POST.get("email", "").strip()
    if email:
        if venta.cliente:
            venta.cliente.email = email
            venta.cliente.save(update_fields=["email"])
        else:
            cliente = Cliente.objects.create(email=email)
            venta.cliente = cliente
            venta.save(update_fields=["cliente"])
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def cliente_editar_rapido(request, venta_id):
    """Actualiza los datos del cliente ya asociado a la venta, sin salir del
    punto de venta — para completar/corregir datos que encontró incompletos
    al buscarlo (ej: agregar el DNI a un cliente que solo tenía el nombre)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    if not venta.cliente_id:
        return _render_venta_fragments(request, venta)

    cliente = venta.cliente
    cliente.nombre = request.POST.get("nombre", "").strip()
    cliente.apellido = request.POST.get("apellido", "").strip()
    cliente.dni = request.POST.get("dni", "").strip()
    cliente.telefono = request.POST.get("telefono", "").strip()
    cliente.email = request.POST.get("email", "").strip()
    cliente.direccion = request.POST.get("direccion", "").strip()
    cliente.save(update_fields=["nombre", "apellido", "dni", "telefono", "email", "direccion"])
    return _render_venta_fragments(request, venta, cliente_guardado=True)


@login_required
@require_GET
def recetas_de_cliente(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id)
    recetas = []
    if venta.cliente_id:
        recetas = list(
            Receta.objects.filter(cliente_id=venta.cliente_id)
            .order_by("-fecha_recibido")
            .values("id", "fecha_recibido")
            .annotate(medico=F("medico__nombre"))
        )
    return JsonResponse({"recetas": recetas})


@login_required
@require_GET
def buscar_recetas(request, venta_id):
    """Busca recetas de CUALQUIER cliente (no solo el de esta venta), para el
    caso de una compra con varias personas donde algún cristal usa la receta
    de otro cliente (ej: la pareja, un hijo)."""
    q = request.GET.get("q", "").strip()
    recetas = []
    if q:
        query = Q()
        for palabra in q.split():
            query &= (
                Q(cliente__nombre__icontains=palabra) | Q(cliente__apellido__icontains=palabra)
                | Q(cliente__dni__icontains=palabra)
            )
        recetas = list(
            Receta.objects.filter(query).select_related("cliente", "medico")
            .order_by("-fecha_recibido")[:20]
        )
    return JsonResponse({"resultados": [
        {
            "id": r.id,
            "fecha_recibido": r.fecha_recibido.strftime("%d/%m/%Y"),
            "medico": str(r.medico) if r.medico else None,
            "cliente": r.cliente.nombre_completo or r.cliente.dni or f"Cliente #{r.cliente_id}",
        }
        for r in recetas
    ]})


@login_required
@require_GET
def armazones_de_venta(request, venta_id):
    """Lista los items de ESTA venta que son armazones (no cristales), para
    poder elegir a cuál se le monta un cristal — una misma venta puede tener
    varios armazones para distintas personas de una familia, cada uno con su
    propio cristal y receta."""
    venta = get_object_or_404(Venta, pk=venta_id)
    armazones = [
        {"id": item.id, "label": f"{item.producto} (x{item.cantidad})"}
        for item in venta.items.select_related("producto__categoria")
        if not item.producto.categoria.usa_receta
    ]
    return JsonResponse({"armazones": armazones})


@login_required
@require_POST
def asociar_armazon_item(request, venta_id, item_id):
    """Asocia (o desasocia) el armazón donde se monta un cristal: puede ser
    otro item de la misma venta, o marcarse que el cliente trajo el suyo
    propio (son excluyentes entre sí)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    item = get_object_or_404(VentaItem, pk=item_id, venta=venta)

    if request.POST.get("armazon_de_cliente") == "1":
        item.armazon_venta_item = None
        item.armazon_de_cliente = True
    else:
        armazon_item_id = request.POST.get("armazon_item_id")
        item.armazon_venta_item = (
            get_object_or_404(VentaItem, pk=armazon_item_id, venta=venta) if armazon_item_id else None
        )
        item.armazon_de_cliente = False
    item.save(update_fields=["armazon_venta_item", "armazon_de_cliente"])
    return _render_venta_fragments(request, venta)


@login_required
@require_GET
def buscar_catalogo(request, venta_id):
    """Busca en TODO el catálogo por marca/modelo/categoría/color, para agregar
    un producto a mano sin escanearlo (ej: cristales a medida, o cualquier
    producto cuando no se tiene el código a mano). Con ?solo_cristales=1 se
    restringe a categorías de cristales (para el botón dedicado del punto de
    venta) y, como son un catálogo finito y acotado (~30 tipos), se listan
    todos de entrada sin necesidad de escribir nada."""
    q = request.GET.get("q", "").strip()
    solo_cristales = request.GET.get("solo_cristales") == "1"

    productos = Producto.objects.filter(activo=True)
    if solo_cristales:
        productos = productos.filter(categoria__nombre__icontains="cristal")
    if q:
        productos = productos.filter(
            Q(marca__nombre__icontains=q) | Q(modelo__icontains=q) | Q(color__icontains=q)
            | Q(color_cristal__icontains=q) | Q(categoria__nombre__icontains=q)
        )
    elif not solo_cristales:
        return JsonResponse({"resultados": []})

    productos = productos.select_related("categoria", "marca").order_by("modelo")[:50 if solo_cristales else 15]
    resultados = [
        {
            "id": p.id,
            "label": f"{p} — {p.categoria.nombre} — ${p.precio}",
            "nombre": str(p),
            "precio": str(p.precio),
            "controla_stock": p.categoria.controla_stock,
            "stock_actual": p.stock_actual,
        }
        for p in productos
    ]
    return JsonResponse({"resultados": resultados})


@login_required
@require_POST
@tenant_atomic
def agregar_item_catalogo(request, venta_id):
    """Agrega al carrito un producto elegido de la lista de búsqueda (no
    escaneado). Si la categoría controla stock, valida disponibilidad igual
    que al escanear; si no (cristales, servicios), no hay límite de stock."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    producto_id = request.POST.get("producto_id")
    producto = get_object_or_404(Producto.objects.select_for_update(), pk=producto_id, activo=True)
    forzar = request.POST.get("forzar") == "1" and es_administrador(request.user)
    try:
        cantidad = max(1, int(request.POST.get("cantidad", 1) or 1))
    except (TypeError, ValueError):
        cantidad = 1
    # Precio confirmado en el popup al agregar: si vino, pisa el de catálogo (y
    # cualquier promo). Una vez en el carrito el precio ya no se edita.
    precio_override = _parsear_precio(request.POST.get("precio")) if request.POST.get("precio") is not None else None

    item, creado = VentaItem.objects.get_or_create(
        venta=venta, producto=producto,
        defaults={"precio_unitario": producto.precio, "cantidad": 0},
    )

    nueva_cantidad = item.cantidad + cantidad
    if producto.categoria.controla_stock and nueva_cantidad > producto.stock_actual:
        if forzar:
            _ajustar_stock_forzado(producto, nueva_cantidad, venta, request.user)
        else:
            disponible = max(producto.stock_actual - item.cantidad, 0)
            if creado:
                item.delete()
            return _render_venta_fragments(
                request, venta,
                error=f"No hay stock suficiente de {producto}: quedan {disponible} disponible(s).",
                stock_insuficiente={"tipo": "catalogo", "producto_id": producto.id},
            )

    if creado:
        promo, precio_final = mejor_promocion_para(producto)
        item.precio_unitario = precio_final
        item.promocion = promo
        if producto.categoria.usa_receta and venta.receta_sugerida_id:
            item.receta = venta.receta_sugerida
    if precio_override is not None:
        item.precio_unitario = precio_override
        item.promocion = None
    item.cantidad = nueva_cantidad
    item.save()

    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


def _parsear_precio(valor):
    """Convierte a Decimal un precio tipeado a mano; None si es inválido o negativo."""
    try:
        precio = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, AttributeError, TypeError):
        return None
    return precio if precio >= 0 else None


@login_required
@require_POST
@tenant_atomic
def agregar_item_express(request, venta_id):
    """Agrega al carrito un producto que todavía NO está en el catálogo: se crea
    un Producto mínimo al vuelo (marca/modelo + precio) en la categoría
    "Pendiente de normalizar" (sin control de stock ni receta), para poder
    empezar a vender sin haber hecho el relevamiento de stock. Después se puede
    normalizar desde el inventario."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    descripcion = request.POST.get("descripcion", "").strip()
    precio = _parsear_precio(request.POST.get("precio"))
    try:
        cantidad = int(request.POST.get("cantidad") or 1)
    except (TypeError, ValueError):
        cantidad = 1
    cantidad = max(cantidad, 1)

    if not descripcion:
        return _render_venta_fragments(request, venta, error="Escribí una descripción del artículo (ej: 'Armazón Vulk negro').")
    if precio is None:
        return _render_venta_fragments(request, venta, error="Ingresá un precio válido para el artículo.")

    producto = Producto.objects.create(
        categoria=categoria_pendiente(),
        marca=marca_para_express(request.POST.get("marca")),
        modelo=descripcion,
        precio=precio,
        stock_actual=0,
    )
    VentaItem.objects.create(
        venta=venta, producto=producto, cantidad=cantidad, precio_unitario=precio,
    )
    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
@tenant_atomic
def set_precio_item(request, venta_id, item_id):
    """Sobrescribe a mano el precio unitario de un ítem del carrito (cualquiera,
    de catálogo o express). El precio a mano reemplaza a cualquier promoción
    que tuviera aplicada, para que no queden dos descuentos pisándose."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    item = get_object_or_404(VentaItem, pk=item_id, venta=venta)
    precio = _parsear_precio(request.POST.get("precio"))
    if precio is None:
        return _render_venta_fragments(request, venta, error="Ingresá un precio válido.")
    item.precio_unitario = precio
    item.promocion = None
    item.save(update_fields=["precio_unitario", "promocion"])
    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_GET
def consultar_codigo(request, venta_id):
    """Consulta (sin efectos) qué producto corresponde a un código escaneado,
    para mostrar un popup de confirmación de cantidad ANTES de agregarlo al
    carrito de verdad — así se evita sumar de más si el lector dispara dos
    veces o si se vuelve a escanear por error algo que ya está en el carrito."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    codigo = request.GET.get("codigo", "").strip()

    try:
        producto = Producto.objects.select_related("categoria", "marca").get(codigo_barras=codigo, activo=True)
    except Producto.DoesNotExist:
        return JsonResponse({"encontrado": False, "codigo": codigo})

    if not producto.categoria.controla_stock:
        return JsonResponse({
            "encontrado": True, "a_medida": True,
            "mensaje": f"{producto} es un producto a medida (ej: cristal): buscalo en 'Cristales y otros productos a medida', no se escanea.",
        })

    item_actual = venta.items.filter(producto=producto).first()
    return JsonResponse({
        "encontrado": True,
        "a_medida": False,
        "producto": str(producto),
        "precio": str(producto.precio),
        "stock_actual": producto.stock_actual,
        "cantidad_en_carrito": item_actual.cantidad if item_actual else 0,
    })


@login_required
@require_POST
@tenant_atomic
def escanear(request, venta_id):
    """Endpoint que efectivamente agrega el producto al carrito, una vez que
    el vendedor confirmó cantidad en el popup (ver `consultar_codigo`)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    codigo = request.POST.get("codigo", "").strip()
    try:
        cantidad = max(1, int(request.POST.get("cantidad", 1) or 1))
    except (TypeError, ValueError):
        cantidad = 1
    forzar = request.POST.get("forzar") == "1" and es_administrador(request.user)

    try:
        producto = Producto.objects.select_for_update().get(codigo_barras=codigo, activo=True)
    except Producto.DoesNotExist:
        EscaneoNoEncontrado.objects.create(
            codigo_barras=codigo, origen=EscaneoNoEncontrado.Origen.VENTA, usuario=request.user, venta=venta,
        )
        venta.registrar_incidencia(f"Código escaneado no encontrado: {codigo}")
        return _render_venta_fragments(
            request, venta, error=f"No se encontró ningún producto con código {codigo}"
        )

    if not producto.categoria.controla_stock:
        return _render_venta_fragments(
            request, venta,
            error=f"{producto} es un producto a medida (ej: cristal): buscalo en 'Cristales y otros productos a medida', no se escanea.",
        )

    item, creado = VentaItem.objects.get_or_create(
        venta=venta, producto=producto,
        defaults={"precio_unitario": producto.precio, "cantidad": 0},
    )
    nueva_cantidad = item.cantidad + cantidad
    if nueva_cantidad > producto.stock_actual:
        if forzar:
            _ajustar_stock_forzado(producto, nueva_cantidad, venta, request.user)
        else:
            disponible = max(producto.stock_actual - item.cantidad, 0)
            if creado:
                item.delete()
            return _render_venta_fragments(
                request, venta,
                error=f"No hay stock suficiente de {producto}: quedan {disponible} disponible(s).",
                stock_insuficiente={"tipo": "escaneo", "codigo": codigo, "cantidad": cantidad},
            )

    if creado:
        promo, precio_final = mejor_promocion_para(producto)
        item.precio_unitario = precio_final
        item.promocion = promo
        if producto.categoria.usa_receta and venta.receta_sugerida_id:
            item.receta = venta.receta_sugerida
    # Precio confirmado en el popup del escaneo: si vino, pisa el de catálogo.
    precio_override = _parsear_precio(request.POST.get("precio")) if request.POST.get("precio") is not None else None
    if precio_override is not None:
        item.precio_unitario = precio_override
        item.promocion = None
    item.cantidad = nueva_cantidad
    item.save()

    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def quitar_item(request, venta_id, item_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    VentaItem.objects.filter(pk=item_id, venta=venta).delete()
    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def asociar_receta(request, venta_id, item_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    item = get_object_or_404(VentaItem, pk=item_id, venta=venta)
    receta_id = request.POST.get("receta_id")
    item.receta = get_object_or_404(Receta, pk=receta_id) if receta_id else None
    item.save(update_fields=["receta"])
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def generar_orden_laboratorio(request, venta_id, item_id):
    """Crea (o reusa, si ya existe una para este ítem) la orden de
    laboratorio con el armazón + la receta asociada, y devuelve la URL para
    abrirla/imprimirla en una pestaña nueva."""
    venta = get_object_or_404(Venta, pk=venta_id)
    item = get_object_or_404(
        VentaItem.objects.select_related("producto", "receta", "armazon_venta_item__producto"),
        pk=item_id, venta=venta,
    )
    if not item.receta_id:
        return JsonResponse({"error": "Este ítem todavía no tiene una receta asociada."}, status=400)

    armazon = item.armazon_venta_item.producto if item.armazon_venta_item_id else None
    orden, creada = OrdenLaboratorio.objects.get_or_create(
        venta_item=item,
        defaults={
            "cliente": item.receta.cliente, "receta": item.receta, "producto": item.producto,
            "armazon": armazon, "armazon_de_cliente": item.armazon_de_cliente,
        },
    )
    if not creada and (orden.armazon_id != (armazon.id if armazon else None) or orden.armazon_de_cliente != item.armazon_de_cliente):
        orden.armazon = armazon
        orden.armazon_de_cliente = item.armazon_de_cliente
        orden.save(update_fields=["armazon", "armazon_de_cliente"])
    return JsonResponse({"url": reverse("prescriptions:orden_laboratorio_imprimir", args=[orden.pk])})


@login_required
@require_POST
def set_item_entregado(request, venta_id, item_id):
    """Tilda/destilda la entrega de UN ítem puntual (no de toda la venta):
    puede que el armazón ya se lo haya llevado y los cristales, a medida,
    todavía estén en el laboratorio. Funciona tanto en una venta abierta
    (mientras se arma el carrito) como en una ya confirmada (pantalla de
    'completar venta pendiente')."""
    venta = get_object_or_404(Venta, pk=venta_id)
    item = get_object_or_404(VentaItem, pk=item_id, venta=venta)
    entregado = request.POST.get("entregado") == "1"
    # Un cristal y el armazón donde se monta se entregan siempre juntos: no
    # tiene sentido marcar uno sin el otro.
    for relacionado in item.grupo_entrega():
        relacionado.entregado = entregado
        relacionado.save(update_fields=["entregado"])
    if venta.estado == Venta.Estado.ABIERTA:
        return _render_venta_fragments(request, venta)
    return JsonResponse({"ok": True, "entregado": item.entregado})


@login_required
@require_POST
def asociar_promocion_item(request, venta_id, item_id):
    """Elige (o saca) la promoción de UN ítem puntual del carrito, a mano —
    se puede forzar cualquier promoción activa sobre cualquier item, para el
    caso de una compra con varios productos donde solo alguno tiene descuento,
    o donde el producto se agregó a mano (no escaneado) y por eso no
    matcheaba el alcance automático de ninguna promoción. También se usa
    desde la pantalla de completar una venta pendiente (ya CONFIRMADA), por
    si se olvidó aplicar una promoción antes de cerrarla."""
    venta = get_object_or_404(
        Venta, pk=venta_id, estado__in=[Venta.Estado.ABIERTA, Venta.Estado.CONFIRMADA],
    )
    item = get_object_or_404(VentaItem, pk=item_id, venta=venta)
    promocion_id = request.POST.get("promocion_id")

    if promocion_id:
        item.promocion = get_object_or_404(Promocion, pk=promocion_id, activa=True)
        item.precio_unitario = item.promocion.precio_con_descuento(item.producto.precio)
    else:
        item.promocion = None
        item.precio_unitario = item.producto.precio
    item.save(update_fields=["promocion", "precio_unitario"])

    venta.recalcular_total()
    return _render_venta_fragments(request, venta)


@login_required
@require_POST
def confirmar_venta(request, venta_id):
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.ABIERTA)
    try:
        monto_pagado = Decimal(request.POST.get("monto_pagado", "").strip())
    except (InvalidOperation, ValueError):
        monto_pagado = None
    try:
        venta.confirmar(monto_pagado=monto_pagado)
    except ValidationError as e:
        return _render_venta_fragments(request, venta, error="; ".join(e.messages))
    return _render_venta_fragments(request, venta, cart_template="sales/_venta_confirmada.html")


@login_required
def venta_ticket(request, venta_id):
    """Comprobante imprimible para entregarle al cliente. Solo tiene sentido
    para una venta ya confirmada (con stock descontado y total definitivo)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.CONFIRMADA)
    return render(request, "sales/ticket.html", {"venta": venta})


# ---------- Ventas pendientes (reservas/encargos con saldo o sin entregar) ----------

@login_required
def venta_pendientes_buscar(request):
    """Busca ventas ya confirmadas que quedaron con saldo pendiente de pago
    y/o sin entregar (reservas, encargos con cristales a medida, etc), para
    completarlas cuando el cliente vuelve a pagar el resto o a retirar."""
    q = request.GET.get("q", "").strip()
    ventas = (
        Venta.objects.filter(estado=Venta.Estado.CONFIRMADA)
        # Las ventas por obra social sin resolver se gestionan aparte (ver
        # "Ventas por obra social"): acá solo interesa el saldo/entrega de
        # las demás, para no mezclar los dos trámites.
        .exclude(es_obra_social=True, obra_social_resuelta=False)
        .filter(Q(items__entregado=False) | Q(monto_pagado__lt=F("total")))
        .select_related("cliente", "vendedor")
        .distinct()
    )
    if q:
        ventas = ventas.filter(
            Q(cliente__nombre__icontains=q) | Q(cliente__apellido__icontains=q) | Q(cliente__dni__icontains=q)
        )
    return render(request, "sales/venta_pendientes_buscar.html", {"query": q, "ventas": ventas})


@login_required
def venta_completar(request, venta_id):
    """Pantalla de una venta ya confirmada que quedó con saldo y/o entrega
    pendiente: acá solo se consulta y se ajustan promociones; el pago del
    saldo y la entrega se hacen juntos, al final, con `marcar_entregado`."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.CONFIRMADA)
    promociones_disponibles = [
        p for p in Promocion.objects.filter(activa=True).prefetch_related("productos", "categorias")
        if p.esta_vigente()
    ]
    return render(request, "sales/venta_completar.html", {
        "venta": venta, "forma_pago_choices": Venta.FormaPago.choices,
        "promociones_disponibles": promociones_disponibles,
        "whatsapp_url": venta.cliente.whatsapp_url(MENSAJE_WHATSAPP_LISTO) if venta.cliente_id else None,
    })


@login_required
@require_POST
def marcar_notificado(request, venta_id):
    """Se llama al apretar el botón "Ya avisé" (acción explícita y separada
    de abrir el link de WhatsApp: no hay forma de saber si el mensaje se
    mandó de verdad solo porque se abrió el chat)."""
    venta = get_object_or_404(Venta, pk=venta_id)
    venta.notificado = True
    venta.save(update_fields=["notificado"])
    messages.success(request, "Se marcó como notificado.")
    next_url = request.POST.get("next")
    return redirect(next_url) if next_url else redirect("sales:venta_completar", venta_id=venta.id)


@login_required
@require_POST
def marcar_entregado(request, venta_id):
    """Botón final para cerrar la venta: tilda TODOS los items como
    entregados de una sola vez. Si todavía queda saldo, no se puede entregar
    "a cuenta": se cobra en el mismo momento, con la forma de pago que se
    elija acá (que puede ser distinta a la de la seña)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.CONFIRMADA)
    saldo = venta.saldo_pendiente
    if saldo > 0:
        forma_pago_saldo = request.POST.get("forma_pago_saldo", "")
        if forma_pago_saldo not in Venta.FormaPago.values:
            messages.error(request, "Elegí la forma de pago del saldo antes de marcar la entrega.")
            return redirect("sales:venta_completar", venta_id=venta.id)
        try:
            cuotas_saldo = int(request.POST.get("cuotas_saldo") or 0) or None
        except (TypeError, ValueError):
            cuotas_saldo = None
        if forma_pago_saldo == Venta.FormaPago.TARJETA and not cuotas_saldo:
            messages.error(request, "Indicá la cantidad de cuotas para el pago con tarjeta.")
            return redirect("sales:venta_completar", venta_id=venta.id)
        venta.registrar_pago_y_entrega(
            monto_adicional=saldo, forma_pago_saldo=forma_pago_saldo, cuotas_saldo=cuotas_saldo,
        )
    venta.items.update(entregado=True)
    messages.success(request, "Venta marcada como entregada.")
    next_url = request.POST.get("next")
    return redirect(next_url) if next_url else redirect("sales:venta_pendientes_buscar")


# ---------- Ventas por obra social (para revisar y terminar a mano) ----------

@login_required
def venta_obra_social_lista(request):
    """Ventas confirmadas marcadas como 'por obra social' que todavía no se
    revisaron a mano (separado de las ventas pendientes de pago/entrega:
    acá lo que falta es gestionar el trámite con la obra social, no
    necesariamente cobrar o entregar)."""
    ventas = (
        Venta.objects.filter(estado=Venta.Estado.CONFIRMADA, es_obra_social=True, obra_social_resuelta=False)
        .select_related("cliente", "vendedor")
        .order_by("-fecha")
    )
    return render(request, "sales/venta_obra_social_lista.html", {"ventas": ventas})


@login_required
@require_POST
def marcar_obra_social_resuelta(request, venta_id):
    """Se llama cuando el dueño del negocio ya terminó de gestionar la venta
    con la obra social (cobrado el copago, hecho el trámite, etc)."""
    venta = get_object_or_404(Venta, pk=venta_id, estado=Venta.Estado.CONFIRMADA)
    venta.obra_social_resuelta = True
    venta.save(update_fields=["obra_social_resuelta"])
    messages.success(request, "Venta marcada como resuelta.")
    next_url = request.POST.get("next")
    return redirect(next_url) if next_url else redirect("sales:venta_obra_social_lista")


# ---------- Vendedor (gestión de empleados que atienden ventas) ----------

class VendedorListView(AdminRequiredMixin, BaseListView):
    model = Vendedor
    title = "Vendedores"
    headers = ["Nombre", "Activo"]
    create_url_name = "sales:vendedor_nuevo"
    edit_url_name = "sales:vendedor_editar"
    delete_url_name = "sales:vendedor_eliminar"
    export_csv_filename = "vendedores.csv"

    def get_row(self, obj):
        return [obj.nombre, "Sí" if obj.activo else "No"]


class VendedorCreateView(AdminRequiredMixin, BaseCreateView):
    model = Vendedor
    form_class = VendedorForm
    title = "Nuevo vendedor"
    cancel_url_name = "sales:vendedor_lista"
    success_url = reverse_lazy("sales:vendedor_lista")


class VendedorUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = Vendedor
    form_class = VendedorForm
    title = "Editar vendedor"
    cancel_url_name = "sales:vendedor_lista"
    success_url = reverse_lazy("sales:vendedor_lista")


class VendedorDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = Vendedor
    cancel_url_name = "sales:vendedor_lista"
    success_url = reverse_lazy("sales:vendedor_lista")


# ---------- Devoluciones ----------

@login_required
def devolucion_nueva(request):
    return render(request, "sales/devolucion_nueva.html")


@login_required
@require_POST
def devolucion_registrar(request):
    codigo = request.POST.get("codigo", "").strip()
    try:
        cantidad = int(request.POST.get("cantidad", 1) or 1)
    except (TypeError, ValueError):
        cantidad = 1
    if cantidad < 1:
        return render(
            request, "sales/_resultado_devolucion.html",
            {"error": "La cantidad debe ser 1 o más."},
        )
    motivo = request.POST.get("motivo", "").strip()

    try:
        producto = Producto.objects.get(codigo_barras=codigo)
    except Producto.DoesNotExist:
        return render(
            request, "sales/_resultado_devolucion.html",
            {"error": f"No se encontró ningún producto con código {codigo}"},
        )

    monto = producto.precio * cantidad
    devolucion = Devolucion.objects.create(
        producto=producto, cantidad=cantidad, monto=monto, motivo=motivo, usuario=request.user,
    )
    if producto.categoria.controla_stock:
        MovimientoStock.objects.create(
            producto=producto, tipo=MovimientoStock.Tipo.INGRESO, cantidad=cantidad,
            usuario=request.user, nota=f"Devolución #{devolucion.id}",
        )
        producto.refresh_from_db()

    return render(request, "sales/_resultado_devolucion.html", {"devolucion": devolucion, "producto": producto})


class DevolucionListView(AdminRequiredMixin, BaseListView):
    model = Devolucion
    title = "Devoluciones"
    headers = ["Fecha", "Producto", "Cantidad", "Monto", "Motivo", "Usuario"]
    search_fields = ["producto__marca__nombre", "producto__modelo", "motivo"]
    search_placeholder = "Buscar por producto o motivo..."
    export_csv_filename = "devoluciones.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("producto", "usuario")

    def get_row(self, obj):
        return [
            formato_local(obj.fecha), str(obj.producto), obj.cantidad,
            f"${obj.monto}", obj.motivo or "—", obj.usuario.username if obj.usuario else "—",
        ]


# ---------- Caja del día ----------

@login_required
def caja_del_dia(request):
    """Cuánto dinero entró en un día (default hoy), discriminado por forma de
    pago, para hacer el cierre de caja."""
    from django.contrib import messages as django_messages
    from stockero.permissions import es_administrador

    if not es_administrador(request.user):
        django_messages.error(request, "Esta sección requiere permisos de administrador/a.")
        return redirect("home")

    import datetime
    from django.db.models import Sum, Count
    from django.utils import timezone

    hoy = timezone.localdate()
    try:
        fecha = datetime.date.fromisoformat(request.GET.get("fecha", ""))
    except ValueError:
        fecha = hoy

    ventas_qs = Venta.objects.filter(estado=Venta.Estado.CONFIRMADA, fecha__date=fecha)
    labels = dict(Venta.FormaPago.choices)
    filas = [
        {
            "forma_pago": labels.get(f["forma_pago"], "Sin especificar") if f["forma_pago"] else "Sin especificar",
            "cantidad": f["cantidad"],
            "total": f["total"] or 0,
        }
        for f in ventas_qs.values("forma_pago").annotate(total=Sum("total"), cantidad=Count("id")).order_by("forma_pago")
    ]
    resumen = ventas_qs.aggregate(total=Sum("total"), cantidad=Count("id"))

    return render(request, "sales/caja_del_dia.html", {
        "fecha": fecha.isoformat(),
        "filas": filas,
        "total_general": resumen["total"] or 0,
        "cantidad_general": resumen["cantidad"] or 0,
    })


# ---------- Dashboard ----------

@login_required
def dashboard(request):
    from django.contrib import messages as django_messages
    from stockero.permissions import es_administrador

    if not es_administrador(request.user):
        django_messages.error(request, "Esta sección requiere permisos de administrador/a.")
        return redirect("home")

    import datetime
    from django.db.models import Sum, Count, Max
    from django.db.models.functions import TruncDate, TruncDay, TruncMonth, TruncWeek
    from django.utils import timezone

    from inventory.models import OrdenCompraItem

    hoy = timezone.localdate()
    try:
        desde = datetime.date.fromisoformat(request.GET.get("desde", ""))
    except ValueError:
        desde = hoy - datetime.timedelta(days=30)
    try:
        hasta = datetime.date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        hasta = hoy

    ventas_qs = Venta.objects.filter(
        estado=Venta.Estado.CONFIRMADA, fecha__date__gte=desde, fecha__date__lte=hasta,
    )

    resumen = ventas_qs.aggregate(total=Sum("total"), cantidad=Count("id"))
    total_facturado = resumen["total"] or 0
    cantidad_ventas = resumen["cantidad"] or 0
    ticket_promedio = (total_facturado / cantidad_ventas) if cantidad_ventas else 0
    cantidad_incidencias = ventas_qs.filter(tiene_incidencias=True).count()

    por_vendedor = list(
        ventas_qs.values("vendedor__nombre")
        .annotate(total=Sum("total"), cantidad=Count("id"))
        .order_by("-total")
    )

    items_qs = VentaItem.objects.filter(venta__in=ventas_qs)
    top_productos = list(
        items_qs.values("producto__marca__nombre", "producto__modelo", "producto_id")
        .annotate(cantidad=Sum("cantidad"))
        .order_by("-cantidad")[:10]
    )
    top_marcas = list(
        items_qs.exclude(producto__marca__isnull=True)
        .values("producto__marca__nombre")
        .annotate(cantidad=Sum("cantidad"))
        .order_by("-cantidad")[:10]
    )
    por_dia = list(
        ventas_qs.annotate(dia=TruncDate("fecha"))
        .values("dia")
        .annotate(total=Sum("total"))
        .order_by("dia")
    )

    def nombre_producto(p):
        base = f"{p['producto__marca__nombre'] or ''} {p['producto__modelo']}".strip()
        return base or f"Producto #{p['producto_id']}"

    # ---------- Stock (estado actual, no depende del rango de fechas) ----------

    productos_activos = Producto.objects.filter(activo=True)

    stock_por_marca = list(
        productos_activos.values("marca__nombre")
        .annotate(total=Sum("stock_actual"))
        .order_by("-total")[:10]
    )

    productos_por_proveedor = list(
        productos_activos.values("proveedor__nombre")
        .annotate(cantidad=Count("id"))
        .order_by("cantidad")[:10]
    )

    stock_por_categoria = list(
        productos_activos.values("categoria__nombre")
        .annotate(total=Sum("stock_actual"))
        .order_by("-total")
    )

    productos_bajo_minimo = list(
        productos_activos.filter(stock_actual__lte=F("stock_minimo"))
        .order_by("stock_actual")[:15]
    )

    valor_inventario_por_categoria = list(
        productos_activos.values("categoria__nombre")
        .annotate(valor=Sum(F("stock_actual") * F("precio_costo")))
        .order_by("-valor")
    )

    ordenes_pendientes = list(
        OrdenCompraItem.objects.filter(orden__estado__in=["ENV", "PAR"])
        .values("orden__proveedor__nombre")
        .annotate(pendiente=Sum(F("cantidad_pedida") - F("cantidad_recibida")))
        .filter(pendiente__gt=0)
        .order_by("-pendiente")[:10]
    )

    # Rotación: de los productos con más stock, cuáles vendieron menos en el
    # período filtrado (candidatos a liquidar / dejar de reponer).
    vendidas_por_producto = {
        v["producto_id"]: v["vendidas"]
        for v in items_qs.values("producto_id").annotate(vendidas=Sum("cantidad"))
    }
    productos_alto_stock = list(
        productos_activos.filter(stock_actual__gt=0).select_related("marca").order_by("-stock_actual")[:30]
    )
    rotacion = sorted(
        ((p, vendidas_por_producto.get(p.id, 0)) for p in productos_alto_stock),
        key=lambda t: (t[1], -t[0].stock_actual),
    )[:10]

    # ---------- Clientes y recetas ----------
    # Tienen su propio período (rdesde/rhasta), independiente del de ventas, con
    # default a los últimos 12 meses: todos los gráficos de recetas se filtran
    # por ese rango.
    try:
        rdesde = datetime.date.fromisoformat(request.GET.get("rdesde", ""))
    except ValueError:
        rdesde = hoy.replace(day=1) - datetime.timedelta(days=365)
    try:
        rhasta = datetime.date.fromisoformat(request.GET.get("rhasta", ""))
    except ValueError:
        rhasta = hoy

    recetas_qs = Receta.objects.filter(fecha_recibido__gte=rdesde, fecha_recibido__lte=rhasta)
    total_recetas_periodo = recetas_qs.count()

    clientes_por_mes = list(
        Cliente.objects.filter(creado__date__gte=rdesde, creado__date__lte=rhasta)
        .annotate(mes=TruncMonth("creado")).values("mes")
        .annotate(cantidad=Count("id")).order_by("mes")
    )
    # El eje de "recetas por período" se adapta al rango elegido (rdesde/rhasta):
    # un rango corto agrupado por mes daría una sola barra, así que se afina a
    # semana o día según cuánto abarque.
    rango_dias = (rhasta - rdesde).days
    if rango_dias <= 31:
        trunc_periodo, fmt_periodo = TruncDay, "%d/%m"
    elif rango_dias <= 120:
        trunc_periodo, fmt_periodo = TruncWeek, "%d/%m"
    else:
        trunc_periodo, fmt_periodo = TruncMonth, "%m/%Y"
    recetas_por_mes = list(
        recetas_qs.annotate(periodo=trunc_periodo("fecha_recibido")).values("periodo")
        .annotate(cantidad=Count("id")).order_by("periodo")
    )
    # Lentes de contacto sí / no.
    lc = recetas_qs.aggregate(
        con=Count("id", filter=Q(es_lentes_contacto=True)),
        sin=Count("id", filter=Q(es_lentes_contacto=False)),
    )
    recetas_por_marca_lc = list(
        recetas_qs.filter(es_lentes_contacto=True).exclude(marca_lentes_contacto="")
        .values("marca_lentes_contacto").annotate(cantidad=Count("id")).order_by("-cantidad")[:12]
    )
    # Se agrupa por familia (primera palabra del nombre) para el gráfico: "OSDE",
    # "OSDE 210", "OSDE 310" son planes distintos en el catálogo pero para ver
    # de un vistazo de qué obra social son los clientes conviene juntarlos.
    obra_social_por_familia = {}
    for r in (
        recetas_qs.exclude(obra_social__isnull=True).values("obra_social__nombre")
        .annotate(cantidad=Count("id"))
    ):
        nombre = r["obra_social__nombre"]
        familia = nombre.split()[0].lower()
        entrada = obra_social_por_familia.setdefault(familia, {"nombre": nombre, "cantidad": 0})
        entrada["cantidad"] += r["cantidad"]
        if len(nombre) < len(entrada["nombre"]):
            entrada["nombre"] = nombre  # el más corto suele ser el genérico (ej: "OSDE" vs "OSDE 210")
    recetas_por_obra_social = sorted(obra_social_por_familia.values(), key=lambda r: -r["cantidad"])[:12]

    recetas_por_medico = list(
        recetas_qs.exclude(medico__isnull=True).values("medico__nombre")
        .annotate(cantidad=Count("id")).order_by("-cantidad")[:12]
    )

    # ---------- Lentes de contacto (período propio: lcdesde/lchasta) ----------
    from contact_lenses.models import PruebaLentesContacto

    try:
        lcdesde = datetime.date.fromisoformat(request.GET.get("lcdesde", ""))
    except ValueError:
        lcdesde = hoy - datetime.timedelta(days=30)
    try:
        lchasta = datetime.date.fromisoformat(request.GET.get("lchasta", ""))
    except ValueError:
        lchasta = hoy

    pruebas_qs = PruebaLentesContacto.objects.filter(fecha_hora__date__gte=lcdesde, fecha_hora__date__lte=lchasta)
    total_pruebas = pruebas_qs.count()
    pruebas_con_venta = pruebas_qs.filter(venta__estado=Venta.Estado.CONFIRMADA).count()
    tasa_conversion_lc = round(pruebas_con_venta / total_pruebas * 100, 1) if total_pruebas else 0

    estado_labels_lc = dict(PruebaLentesContacto.Estado.choices)
    pruebas_por_estado = list(
        pruebas_qs.values("estado").annotate(cantidad=Count("id")).order_by("estado")
    )
    pruebas_por_vendedor = list(
        pruebas_qs.values("vendedor__nombre").annotate(cantidad=Count("id")).order_by("-cantidad")
    )
    pruebas_por_mes = list(
        pruebas_qs.annotate(mes=TruncMonth("fecha_hora")).values("mes")
        .annotate(
            total=Count("id"),
            con_venta=Count("id", filter=Q(venta__estado=Venta.Estado.CONFIRMADA)),
        ).order_by("mes")
    )

    ventas_qs_lc = Venta.objects.filter(
        estado=Venta.Estado.CONFIRMADA, fecha__date__gte=lcdesde, fecha__date__lte=lchasta,
    )
    items_qs_lc = VentaItem.objects.filter(venta__in=ventas_qs_lc)
    top_productos_lc = list(
        items_qs_lc.filter(producto__categoria__nombre__icontains="contacto")
        .values("producto__marca__nombre", "producto__modelo", "producto_id")
        .annotate(cantidad=Sum("cantidad")).order_by("-cantidad")[:10]
    )

    # ¿Se vendió líquido junto con el lente de contacto, en la misma venta?
    ventas_con_lc = ventas_qs_lc.filter(
        items__producto__categoria__nombre__icontains="contacto"
    ).distinct()
    total_ventas_con_lc = ventas_con_lc.count()
    ventas_con_lc_y_liquido = ventas_con_lc.filter(
        items__producto__categoria__nombre__icontains="liquid"
    ).distinct().count()

    # Recompra: de los clientes que alguna vez compraron lentes de contacto o
    # líquido (histórico completo, no depende del período elegido arriba),
    # ¿volvieron a comprar o fue una compra única? Sirve para ver si siguen
    # viniendo a la óptica o se van a comprar a otro lado después de la prueba.
    compras_lc_por_cliente = list(
        VentaItem.objects.filter(venta__estado=Venta.Estado.CONFIRMADA, venta__cliente__isnull=False)
        .filter(Q(producto__categoria__nombre__icontains="contacto") | Q(producto__categoria__nombre__icontains="liquid"))
        .values("venta__cliente_id", "venta__cliente__nombre", "venta__cliente__apellido")
        .annotate(cantidad_compras=Count("venta_id", distinct=True), ultima_compra=Max("venta__fecha"))
    )
    total_clientes_lc = len(compras_lc_por_cliente)
    clientes_recurrentes_lc = sum(1 for c in compras_lc_por_cliente if c["cantidad_compras"] >= 2)
    clientes_unica_compra_lc = total_clientes_lc - clientes_recurrentes_lc
    tasa_recompra_lc = round(clientes_recurrentes_lc / total_clientes_lc * 100, 1) if total_clientes_lc else 0

    buckets_recompra = {"1": 0, "2": 0, "3": 0, "4+": 0}
    for c in compras_lc_por_cliente:
        clave = str(c["cantidad_compras"]) if c["cantidad_compras"] < 4 else "4+"
        buckets_recompra[clave] += 1

    # Candidatos a re-contactar: compraron una sola vez y hace más tiempo que
    # no vuelven primero en la lista.
    clientes_sin_volver = sorted(
        (c for c in compras_lc_por_cliente if c["cantidad_compras"] == 1),
        key=lambda c: c["ultima_compra"],
    )[:20]

    context = {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "total_facturado": total_facturado,
        "cantidad_ventas": cantidad_ventas,
        "ticket_promedio": round(ticket_promedio, 2),
        "cantidad_incidencias": cantidad_incidencias,
        "labels_vendedores": [v["vendedor__nombre"] or "Sin asignar" for v in por_vendedor],
        "data_vendedores": [float(v["total"] or 0) for v in por_vendedor],
        "labels_productos": [nombre_producto(p) for p in top_productos],
        "data_productos": [p["cantidad"] for p in top_productos],
        "labels_marcas": [m["producto__marca__nombre"] for m in top_marcas],
        "data_marcas": [m["cantidad"] for m in top_marcas],
        "labels_dias": [d["dia"].isoformat() for d in por_dia],
        "data_dias": [float(d["total"] or 0) for d in por_dia],

        # Stock
        "labels_stock_marca": [m["marca__nombre"] for m in stock_por_marca],
        "data_stock_marca": [m["total"] or 0 for m in stock_por_marca],
        "labels_prov_cantidad": [p["proveedor__nombre"] or "Sin proveedor" for p in productos_por_proveedor],
        "data_prov_cantidad": [p["cantidad"] for p in productos_por_proveedor],
        "labels_stock_categoria": [c["categoria__nombre"] for c in stock_por_categoria],
        "data_stock_categoria": [c["total"] or 0 for c in stock_por_categoria],
        "labels_bajo_minimo": [f"{p.marca.nombre} {p.modelo}".strip() for p in productos_bajo_minimo],
        "data_bajo_minimo": [p.stock_actual for p in productos_bajo_minimo],
        "cantidad_bajo_minimo": Producto.objects.filter(activo=True, stock_actual__lte=F("stock_minimo")).count(),
        "labels_valor_categoria": [c["categoria__nombre"] for c in valor_inventario_por_categoria],
        "data_valor_categoria": [float(c["valor"] or 0) for c in valor_inventario_por_categoria],
        "labels_ordenes_pendientes": [o["orden__proveedor__nombre"] for o in ordenes_pendientes],
        "data_ordenes_pendientes": [o["pendiente"] for o in ordenes_pendientes],
        "labels_rotacion": [f"{p.marca.nombre} {p.modelo}".strip() for p, _ in rotacion],
        "data_rotacion_stock": [p.stock_actual for p, _ in rotacion],
        "data_rotacion_vendido": [v for _, v in rotacion],

        # Clientes y recetas (período propio: rdesde/rhasta)
        "rdesde": rdesde.isoformat(),
        "rhasta": rhasta.isoformat(),
        "total_recetas_periodo": total_recetas_periodo,
        "labels_clientes_mes": [c["mes"].strftime("%m/%Y") for c in clientes_por_mes],
        "data_clientes_mes": [c["cantidad"] for c in clientes_por_mes],
        "labels_recetas_mes": [r["periodo"].strftime(fmt_periodo) for r in recetas_por_mes],
        "data_recetas_mes": [r["cantidad"] for r in recetas_por_mes],
        "data_lentes_contacto": [lc["con"] or 0, lc["sin"] or 0],
        "labels_marca_lc": [r["marca_lentes_contacto"] for r in recetas_por_marca_lc],
        "data_marca_lc": [r["cantidad"] for r in recetas_por_marca_lc],
        "labels_obra_social": [r["nombre"] for r in recetas_por_obra_social],
        "data_obra_social": [r["cantidad"] for r in recetas_por_obra_social],
        "labels_medico": [r["medico__nombre"] for r in recetas_por_medico],
        "data_medico": [r["cantidad"] for r in recetas_por_medico],

        # Lentes de contacto (período propio: lcdesde/lchasta)
        "lcdesde": lcdesde.isoformat(),
        "lchasta": lchasta.isoformat(),
        "total_pruebas_lc": total_pruebas,
        "pruebas_con_venta_lc": pruebas_con_venta,
        "tasa_conversion_lc": tasa_conversion_lc,
        "labels_estado_lc": [estado_labels_lc.get(e["estado"], e["estado"]) for e in pruebas_por_estado],
        "data_estado_lc": [e["cantidad"] for e in pruebas_por_estado],
        "labels_vendedor_lc": [v["vendedor__nombre"] or "Sin asignar" for v in pruebas_por_vendedor],
        "data_vendedor_lc": [v["cantidad"] for v in pruebas_por_vendedor],
        "labels_mes_lc": [m["mes"].strftime("%m/%Y") for m in pruebas_por_mes],
        "data_mes_total_lc": [m["total"] for m in pruebas_por_mes],
        "data_mes_venta_lc": [m["con_venta"] for m in pruebas_por_mes],
        "labels_top_lc": [nombre_producto(p) for p in top_productos_lc],
        "data_top_lc": [p["cantidad"] for p in top_productos_lc],
        "total_ventas_con_lc": total_ventas_con_lc,
        "data_liquido_lc": [ventas_con_lc_y_liquido, total_ventas_con_lc - ventas_con_lc_y_liquido],

        # Recompra (histórico completo)
        "total_clientes_lc": total_clientes_lc,
        "clientes_unica_compra_lc": clientes_unica_compra_lc,
        "clientes_recurrentes_lc": clientes_recurrentes_lc,
        "tasa_recompra_lc": tasa_recompra_lc,
        "labels_recompra_lc": list(buckets_recompra.keys()),
        "data_recompra_lc": list(buckets_recompra.values()),
        "clientes_sin_volver": [
            {
                "cliente_id": c["venta__cliente_id"],
                "nombre": f"{c['venta__cliente__nombre']} {c['venta__cliente__apellido']}".strip(),
                "ultima_compra": c["ultima_compra"],
            }
            for c in clientes_sin_volver
        ],
    }
    return render(request, "sales/dashboard.html", context)


# ---------- Historial de ventas (solo lectura) ----------

class VentaListView(AdminRequiredMixin, BaseListView):
    model = Venta
    title = "Historial de ventas"
    template_name = "sales/venta_lista.html"
    headers = ["N°", "Fecha", "Cliente", "Vendedor/a", "Estado", "Total", "Saldo", "Entregado", "Forma de pago", "Incidencias"]
    search_fields = ["cliente__nombre", "cliente__apellido", "cliente__dni", "vendedor__nombre"]
    search_placeholder = "Buscar por cliente o vendedor/a..."
    detalle_url_name = "sales:venta_detalle"
    export_csv_filename = "ventas.csv"
    sort_fields = {"Fecha": "fecha", "Total": "total"}

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente", "vendedor").prefetch_related("items__orden_laboratorio")
        request = self.request
        if request.GET.get("incidencias") == "1":
            qs = qs.filter(tiene_incidencias=True)
        if request.GET.get("estado"):
            qs = qs.filter(estado=request.GET["estado"])
        if request.GET.get("forma_pago"):
            qs = qs.filter(forma_pago=request.GET["forma_pago"])
        if request.GET.get("desde"):
            try:
                qs = qs.filter(fecha__date__gte=date.fromisoformat(request.GET["desde"]))
            except ValueError:
                pass
        if request.GET.get("hasta"):
            try:
                qs = qs.filter(fecha__date__lte=date.fromisoformat(request.GET["hasta"]))
            except ValueError:
                pass
        if request.GET.get("monto_min"):
            try:
                qs = qs.filter(total__gte=Decimal(request.GET["monto_min"].replace(",", ".")))
            except InvalidOperation:
                pass
        if request.GET.get("monto_max"):
            try:
                qs = qs.filter(total__lte=Decimal(request.GET["monto_max"].replace(",", ".")))
            except InvalidOperation:
                pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["incidencias_activo"] = self.request.GET.get("incidencias") == "1"
        ctx["show_search"] = False  # el buscador de cliente/vendedor va integrado en los filtros de abajo
        ctx["estado_choices"] = Venta.Estado.choices
        ctx["forma_pago_choices"] = Venta.FormaPago.choices
        ctx["filtro"] = {
            "estado": self.request.GET.get("estado", ""),
            "forma_pago": self.request.GET.get("forma_pago", ""),
            "desde": self.request.GET.get("desde", ""),
            "hasta": self.request.GET.get("hasta", ""),
            "monto_min": self.request.GET.get("monto_min", ""),
            "monto_max": self.request.GET.get("monto_max", ""),
        }
        return ctx

    def get_row(self, obj):
        forma_pago = obj.get_forma_pago_display() if obj.forma_pago else "—"
        if obj.forma_pago == Venta.FormaPago.TARJETA and obj.cuotas:
            forma_pago += f" ({obj.cuotas} cuota{'s' if obj.cuotas != 1 else ''})"
        if obj.forma_pago_saldo:
            saldo_display = obj.get_forma_pago_saldo_display()
            if obj.forma_pago_saldo == Venta.FormaPago.TARJETA and obj.cuotas_saldo:
                saldo_display += f" ({obj.cuotas_saldo} cuota{'s' if obj.cuotas_saldo != 1 else ''})"
            forma_pago += f" + {saldo_display} (saldo)"
        return [
            f"#{obj.pk}", formato_local(obj.fecha),
            str(obj.cliente) if obj.cliente else "Consumidor final",
            obj.vendedor.nombre if obj.vendedor else "—",
            obj.get_estado_display(), f"${obj.total}",
            f"${obj.saldo_pendiente}" if obj.saldo_pendiente else "—",
            "Sí" if obj.entregado else "Pendiente",
            forma_pago,
            f"⚠️ {obj.incidencias_detalle}" if obj.tiene_incidencias else "—",
        ]


@login_required
@require_POST
def venta_eliminar(request, venta_id):
    """Manda una venta a la papelera (solo admin). No se borra de una: queda
    recuperable unos días y, si nadie la recupera, se elimina sola (y ahí se
    devuelve el stock si estaba confirmada). Pensado sobre todo para limpiar
    ventas de prueba."""
    if not es_administrador(request.user):
        messages.error(request, "Eliminar ventas requiere permisos de administrador/a.")
        return redirect("sales:venta_lista")
    venta = get_object_or_404(Venta, pk=venta_id)
    venta.delete()  # borrado suave → papelera
    messages.success(request, f"Venta #{venta_id} enviada a la papelera. La podés recuperar desde ahí.")
    return redirect(request.POST.get("next") or "sales:venta_lista")
