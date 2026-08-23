from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from customers.models import Cliente
from inventory.models import Producto
from stockero.crud_views import BaseListView, BaseCreateView, BaseUpdateView, BaseDeleteView
from stockero.permissions import es_administrador
from stockero.utils import formato_local

from .forms import OrdenLaboratorioForm, RecetaForm
from .models import Medico, OrdenLaboratorio, Receta
from .templatetags.form_extras import CAMPOS_CON_SIGNO, signo as _con_signo


def _nombre_cargador(row, prefijo="cargada_por__"):
    """Nombre legible del usuario que cargó (nombre y apellido, o el usuario)."""
    nombre = " ".join(p for p in [row.get(prefijo + "first_name"), row.get(prefijo + "last_name")] if p).strip()
    return nombre or row.get(prefijo + "username") or "Sin usuario"

# Campos de graduación/receta propiamente dicha (no cliente/entregada/archivo,
# esos no se consideran "correcciones" de la receta). Agrupados igual que en
# el formulario, para reusar el mismo orden en la vista de solo lectura.
GRUPOS_CAMPOS = [
    ("Datos generales", ["fecha_recibido", "medico", "obra_social"]),
    ("Lejos - Ojo derecho", ["lejos_od_esfera", "lejos_od_cilindro", "lejos_od_eje", "lejos_od_adicion"]),
    ("Lejos - Ojo izquierdo", ["lejos_oi_esfera", "lejos_oi_cilindro", "lejos_oi_eje", "lejos_oi_adicion"]),
    ("Lejos - Otros", ["lejos_dnp", "lejos_tipo_cristal", "lejos_color_cristal", "lejos_tratamientos"]),
    ("Cerca - Ojo derecho", ["cerca_od_esfera", "cerca_od_cilindro", "cerca_od_eje"]),
    ("Cerca - Ojo izquierdo", ["cerca_oi_esfera", "cerca_oi_cilindro", "cerca_oi_eje"]),
    ("Cerca - Otros", ["cerca_dnp", "cerca_tipo_cristal", "cerca_color_cristal", "cerca_tratamientos"]),
    ("Bifocal / Multifocal", ["es_bifocal_multifocal", "di_lejos", "di_cerca", "altura"]),
    ("Lentes de contacto", ["es_lentes_contacto", "marca_lentes_contacto"]),
    ("Otros", ["observaciones"]),
]
CAMPOS_CORREGIBLES = {campo for _, campos in GRUPOS_CAMPOS for campo in campos}


class RecetaListView(BaseListView):
    model = Receta
    title = "Recetas"
    # Por default se muestran ordenadas por cuándo se CARGARON al sistema
    # (Receta.Meta.ordering = "-creado"), no por la fecha de la receta en sí,
    # para poder encontrar de un vistazo las que se cargaron hoy.
    headers = ["Cliente", "Cargada", "Fecha de la receta", "Doctor"]
    sort_fields = {"Cargada": "creado", "Fecha de la receta": "fecha_recibido"}
    search_fields = ["cliente__nombre", "cliente__apellido", "cliente__dni", "medico__nombre"]
    search_placeholder = "Buscar por cliente, doctor..."
    create_url_name = "prescriptions:receta_nueva"
    detalle_url_name = "prescriptions:receta_detalle"
    edit_url_name = "prescriptions:receta_editar"
    edit_label = "Corregir"
    delete_url_name = "prescriptions:receta_eliminar"
    export_csv_filename = "recetas.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("cliente", "medico")

    def get_row(self, obj):
        return [
            obj.cliente.nombre_completo, formato_local(obj.creado), obj.fecha_recibido,
            str(obj.medico) if obj.medico else "—",
        ]


def campos_receta_con_valor(receta):
    """Arma, agrupados, solo los campos de la receta que tienen datos
    cargados (nada de inputs/filas vacíos) — para la vista de solo lectura y
    para la orden de laboratorio imprimible. Si un campo fue corregido, se
    incluye el valor anterior para mostrarlo tachado al lado."""
    labels = {name: label for name, label in RecetaForm.Meta.labels.items()}
    correcciones = receta.correcciones or {}

    grupos = []
    for titulo, campos in GRUPOS_CAMPOS:
        filas = []
        for campo in campos:
            valor = getattr(receta, campo)
            if valor is None or valor == "":
                continue
            field = Receta._meta.get_field(campo)
            if field.choices:
                valor_mostrado = getattr(receta, f"get_{campo}_display")()
            elif isinstance(valor, bool):
                valor_mostrado = "Sí" if valor else "No"
            elif campo in CAMPOS_CON_SIGNO:
                valor_mostrado = _con_signo(valor)
            else:
                valor_mostrado = valor
            valor_anterior = correcciones.get(campo)
            if valor_anterior and campo in CAMPOS_CON_SIGNO:
                valor_anterior = _con_signo(valor_anterior)
            filas.append({
                "campo": campo,
                "label": labels.get(campo, field.verbose_name.capitalize()),
                "valor": valor_mostrado,
                "valor_anterior": valor_anterior,
            })
        if filas:
            grupos.append({"titulo": titulo, "filas": filas})
    return grupos


@login_required
def receta_detalle(request, pk):
    """Vista de solo lectura: muestra únicamente los campos con datos
    cargados (nada de inputs vacíos), y si un campo fue corregido alguna
    vez, el valor anterior tachado al lado del actual."""
    receta = get_object_or_404(Receta.objects.select_related("cliente"), pk=pk)
    grupos = campos_receta_con_valor(receta)
    return render(request, "prescriptions/receta_detalle.html", {"receta": receta, "grupos": grupos})


@login_required
def receta_historial(request):
    """Historial de carga de recetas (solo admin): cuántas cargó cada empleado
    (hoy / últimos 7 y 30 días / total) y el desglose por día — para ver si el
    equipo estuvo cargando recetas y cuánto."""
    if not es_administrador(request.user):
        messages.error(request, "El historial de carga de recetas es solo para administradores/as.")
        return redirect("home")

    hoy = timezone.localdate()
    hace_7 = hoy - timedelta(days=6)    # incluye hoy = 7 días
    hace_30 = hoy - timedelta(days=29)  # incluye hoy = 30 días
    campos = ["cargada_por__first_name", "cargada_por__last_name", "cargada_por__username"]

    por_empleado = [
        {
            "nombre": _nombre_cargador(row),
            "hoy": row["hoy"], "semana": row["semana"], "mes": row["mes"], "total": row["total"],
        }
        for row in Receta.objects.values("cargada_por", *campos).annotate(
            total=Count("id"),
            hoy=Count("id", filter=Q(creado__date=hoy)),
            semana=Count("id", filter=Q(creado__date__gte=hace_7)),
            mes=Count("id", filter=Q(creado__date__gte=hace_30)),
        ).order_by("-total")
    ]

    # Desglose por día (últimos 30 días), con detalle por empleado.
    por_dia = {}
    for row in (
        Receta.objects.filter(creado__date__gte=hace_30)
        .annotate(dia=TruncDate("creado"))
        .values("dia", *campos)
        .annotate(cantidad=Count("id"))
        .order_by("-dia", "-cantidad")
    ):
        entrada = por_dia.setdefault(row["dia"], {"dia": row["dia"], "total": 0, "detalle": []})
        entrada["total"] += row["cantidad"]
        entrada["detalle"].append({"nombre": _nombre_cargador(row), "cantidad": row["cantidad"]})
    por_dia = sorted(por_dia.values(), key=lambda d: d["dia"], reverse=True)

    return render(request, "prescriptions/receta_historial.html", {
        "por_empleado": por_empleado,
        "por_dia": por_dia,
        "total_general": Receta.objects.count(),
        "hoy": hoy,
    })


class RecetaCreateView(BaseCreateView):
    model = Receta
    form_class = RecetaForm
    title = "Nueva receta"
    template_name = "prescriptions/receta_form.html"
    cancel_url_name = "prescriptions:receta_lista"
    success_url = reverse_lazy("prescriptions:receta_lista")

    def _prueba(self):
        """Si se llegó desde 'agendar prueba' (?prueba=<id>), la prueba a linkear."""
        from contact_lenses.models import PruebaLentesContacto

        prueba_id = self.request.GET.get("prueba")
        if prueba_id and prueba_id.isdigit():
            return PruebaLentesContacto.objects.filter(pk=prueba_id).select_related("cliente").first()
        return None

    def _cliente_preseleccionado(self):
        # Puede venir por ?cliente=<id> (desde la ficha del cliente) o implícito
        # en ?prueba=<id> (la graduación es del cliente de esa prueba).
        prueba = self._prueba()
        if prueba and prueba.cliente_id:
            return prueba.cliente
        cliente_id = self.request.GET.get("cliente")
        if cliente_id and cliente_id.isdigit():
            return Cliente.objects.filter(pk=cliente_id).first()
        return None

    def get_initial(self):
        initial = super().get_initial()
        cliente = self._cliente_preseleccionado()
        if cliente:
            initial["cliente"] = cliente.pk
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cliente_seleccionado"] = self._cliente_preseleccionado()
        prueba = self._prueba()
        if prueba:
            ctx["prueba_asociada"] = prueba
            # Cancelar vuelve a la prueba (no al listado de recetas).
            ctx["cancel_url"] = reverse_lazy("contact_lenses:prueba_detalle", args=[prueba.pk])
        return ctx

    def form_valid(self, form):
        # Queda registrado quién la cargó, para el historial de carga de recetas.
        form.instance.cargada_por = self.request.user
        respuesta = super().form_valid(form)
        # Si vino desde una prueba de lentes de contacto, se linkea la graduación
        # a esa prueba (para que la vendedora la tenga a mano en el detalle).
        prueba = self._prueba()
        if prueba:
            prueba.receta = self.object
            prueba.save(update_fields=["receta"])
        return respuesta

    def get_success_url(self):
        prueba = self._prueba()
        if prueba:
            return reverse_lazy("contact_lenses:prueba_detalle", args=[prueba.pk])
        return super().get_success_url()


@login_required
@require_GET
def buscar_medicos_json(request):
    """Búsqueda de médicos por nombre para el buscador tipo autocompletar del
    formulario de receta (igual que buscar_clientes_json en customers)."""
    q = request.GET.get("q", "").strip()
    medicos = []
    if q:
        medicos = list(Medico.objects.filter(nombre__icontains=q)[:10].values("id", "nombre"))
    return JsonResponse({"resultados": medicos})


@login_required
@require_POST
def medico_nuevo_rapido_json(request):
    """Alta (o reutilización) automática de médico vía AJAX: a diferencia del
    alta de cliente, acá no hay un mini-formulario aparte — si el usuario
    tipeó un nombre que no matcheó ningún resultado de la lista, se usa (o se
    crea) directamente, para evitar duplicados como "Fernando Loza" /
    "Loza Fernando" cargados sueltos como texto libre."""
    nombre = request.POST.get("nombre", "").strip()
    if not nombre:
        return JsonResponse({"error": "nombre requerido"}, status=400)
    medico, _ = Medico.objects.get_or_create(nombre__iexact=nombre, defaults={"nombre": nombre})
    return JsonResponse({"id": medico.id, "label": str(medico)})


@login_required
@require_GET
def info_receta_cliente_json(request):
    """Última receta de un cliente (si tiene), para mostrar de un vistazo al
    elegir el cliente en otras pantallas (ej: agendar prueba de lentes de
    contacto) si hace falta cargarle la graduación o ya tiene una."""
    cliente_id = request.GET.get("cliente", "")
    receta = None
    if cliente_id.isdigit():
        receta = (
            Receta.objects.filter(cliente_id=cliente_id)
            .order_by("-fecha_recibido", "-creado").first()
        )
    if receta is None:
        return JsonResponse({"tiene_receta": False})
    return JsonResponse({
        "tiene_receta": True,
        "fecha": receta.fecha_recibido.strftime("%d/%m/%Y"),
        "medico": str(receta.medico) if receta.medico else None,
        "url": reverse("prescriptions:receta_detalle", args=[receta.pk]),
    })


class RecetaUpdateView(BaseUpdateView):
    model = Receta
    form_class = RecetaForm
    title = "Corregir receta"
    template_name = "prescriptions/receta_form.html"
    cancel_url_name = "prescriptions:receta_lista"

    def get_success_url(self):
        return reverse_lazy("prescriptions:receta_detalle", args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cliente_seleccionado"] = self.object.cliente
        ctx["medico_seleccionado"] = self.object.medico
        ctx["obra_social_seleccionada"] = self.object.obra_social
        return ctx

    def form_valid(self, form):
        # Guarda el valor previo de cada campo que cambió (y que no estaba
        # vacío), para poder mostrarlo tachado junto al nuevo en la vista de
        # solo lectura. OJO: self.object (== form.instance) ya tiene los
        # valores NUEVOS acá (ModelForm._post_clean() los pisa durante
        # is_valid(), antes de llegar a este método), así que hay que traer
        # una copia aparte desde la base para comparar contra lo viejo.
        anterior = Receta.objects.get(pk=self.object.pk)
        correcciones = dict(anterior.correcciones or {})
        for campo in form.changed_data:
            if campo not in CAMPOS_CORREGIBLES:
                continue
            valor_anterior = getattr(anterior, campo)
            if valor_anterior in (None, "", False):
                continue
            correcciones[campo] = str(valor_anterior)
        form.instance.correcciones = correcciones
        return super().form_valid(form)


class RecetaDeleteView(BaseDeleteView):
    model = Receta
    cancel_url_name = "prescriptions:receta_lista"
    success_url = reverse_lazy("prescriptions:receta_lista")


class OrdenLaboratorioListView(BaseListView):
    model = OrdenLaboratorio
    title = "Órdenes de laboratorio"
    headers = ["Cliente", "Armazón", "Fecha", "Estado"]
    search_fields = ["cliente__nombre", "cliente__apellido", "cliente__dni"]
    search_placeholder = "Buscar por cliente..."
    detalle_url_name = "prescriptions:orden_laboratorio_imprimir"
    delete_url_name = "prescriptions:orden_laboratorio_eliminar"

    def get_queryset(self):
        return super().get_queryset().select_related("cliente", "producto", "receta")

    def get_row(self, obj):
        return [
            obj.cliente.nombre_completo or "—", str(obj.producto),
            formato_local(obj.creado), obj.get_estado_display(),
        ]


@login_required
def orden_laboratorio_nueva(request):
    """Carga a mano una orden de laboratorio suelta: cliente + receta ya
    cargada + cristal a usar, sin pasar por una venta ni cargar precio."""
    if request.method == "POST":
        form = OrdenLaboratorioForm(request.POST)
        if form.is_valid():
            orden = form.save()
            messages.success(request, "Orden de laboratorio creada.")
            return redirect("prescriptions:orden_laboratorio_imprimir", pk=orden.pk)
    else:
        form = OrdenLaboratorioForm()
    return render(request, "prescriptions/orden_laboratorio_form.html", {
        "form": form, "title": "Nueva orden de laboratorio",
    })


@login_required
@require_GET
def recetas_de_cliente_json(request):
    """Recetas de un cliente (independiente de cualquier venta), para elegir
    cuál usar al cargar una orden de laboratorio a mano."""
    cliente_id = request.GET.get("cliente", "")
    recetas = []
    if cliente_id.isdigit():
        recetas = list(
            Receta.objects.filter(cliente_id=cliente_id).order_by("-fecha_recibido")
            .annotate(medico_nombre=F("medico__nombre")).values("id", "fecha_recibido", "medico_nombre")
        )
    return JsonResponse({"recetas": [
        {
            "id": r["id"], "fecha_recibido": r["fecha_recibido"].strftime("%d/%m/%Y"),
            "medico": r["medico_nombre"],
        }
        for r in recetas
    ]})


@login_required
@require_GET
def buscar_armazones_json(request):
    """Busca armazones (no cristales) por marca/modelo/color, para elegir en
    qué armazón se monta un cristal al cargar una orden de laboratorio."""
    q = request.GET.get("q", "").strip()
    productos = []
    if q:
        productos = list(
            Producto.objects.filter(activo=True, categoria__usa_receta=False)
            .filter(Q(marca__nombre__icontains=q) | Q(modelo__icontains=q) | Q(color__icontains=q))
            .select_related("marca", "categoria")[:15]
        )
    return JsonResponse({"resultados": [
        {"id": p.id, "label": f"{p} — {p.categoria.nombre}"} for p in productos
    ]})


@login_required
def orden_laboratorio_imprimir(request, pk):
    orden = get_object_or_404(
        OrdenLaboratorio.objects.select_related(
            "cliente", "producto", "producto__marca", "armazon", "receta", "venta_item", "venta_item__venta",
        ),
        pk=pk,
    )
    grupos = campos_receta_con_valor(orden.receta)
    return render(request, "prescriptions/orden_laboratorio_imprimir.html", {"orden": orden, "grupos": grupos})


class OrdenLaboratorioDeleteView(BaseDeleteView):
    model = OrdenLaboratorio
    cancel_url_name = "prescriptions:orden_laboratorio_lista"
    success_url = reverse_lazy("prescriptions:orden_laboratorio_lista")
