from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_POST

from stockero.crud_views import BaseListView, BaseCreateView, BaseUpdateView, BaseDeleteView
from stockero.permissions import AdminRequiredMixin, es_administrador
from stockero.utils import formato_local
from prescriptions.models import OrdenLaboratorio, Receta
from sales.models import Devolucion, Venta

from .forms import ClienteForm, ObraSocialForm
from .models import Cliente, ObraSocial


@login_required
@require_GET
def buscar_obras_sociales_json(request):
    """Búsqueda de obras sociales por nombre para el buscador tipo
    autocompletar del formulario de receta (igual que buscar_medicos_json)."""
    q = request.GET.get("q", "").strip()
    obras_sociales = []
    if q:
        obras_sociales = list(
            ObraSocial.objects.filter(activa=True, nombre__icontains=q)[:10].values("id", "nombre")
        )
    return JsonResponse({"resultados": obras_sociales})


@login_required
@require_POST
def obra_social_nueva_rapida_json(request):
    """Alta (o reutilización) automática de obra social vía AJAX: si el
    usuario tipeó un nombre que no matcheó ningún resultado de la lista, se
    usa (o se crea) directamente, sin obligar a elegir de la lista."""
    nombre = request.POST.get("nombre", "").strip()
    if not nombre:
        return JsonResponse({"error": "nombre requerido"}, status=400)
    obra_social, _ = ObraSocial.objects.get_or_create(nombre__iexact=nombre, defaults={"nombre": nombre})
    return JsonResponse({"id": obra_social.id, "label": str(obra_social)})


class ClienteListView(BaseListView):
    model = Cliente
    title = "Clientes"
    headers = ["Nombre", "Apellido", "DNI", "Teléfono", "Email", "Obra social", "Última receta", "Última modificación"]
    search_fields = ["nombre", "apellido", "dni", "telefono", "email"]
    sort_fields = {
        "Nombre": "nombre", "Apellido": "apellido", "DNI": "dni",
        "Obra social": "obra_social__nombre", "Última receta": "ultima_receta",
        "Última modificación": "ultima_modificacion",
    }
    search_placeholder = "Buscar por nombre, apellido o DNI..."
    template_name = "customers/cliente_list.html"
    create_url_name = "customers:cliente_nuevo"
    edit_url_name = "customers:cliente_editar"
    delete_url_name = "customers:cliente_eliminar"
    export_csv_filename = "clientes.csv"

    def get_queryset(self):
        return super().get_queryset().select_related("obra_social")

    def annotate_queryset(self, qs):
        return qs.annotate(
            ultima_receta=Max("recetas__fecha_recibido"),
            # Cuándo se cargó o corrigió por última vez alguna receta de este
            # cliente (no la fecha de la receta en sí, sino cuándo se tocó
            # en el sistema), para poder ordenar por "recién modificado".
            ultima_modificacion=Max("recetas__actualizado"),
        )

    def get_row(self, obj):
        ultima = obj.ultima_receta.strftime("%d/%m/%Y") if obj.ultima_receta else "—"
        ultima_mod = formato_local(obj.ultima_modificacion) if obj.ultima_modificacion else "—"
        return [
            obj.nombre or "—", obj.apellido or "—", obj.dni, obj.telefono, obj.email,
            obj.obra_social.nombre if obj.obra_social_id else "—", ultima, ultima_mod,
        ]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for row in ctx["rows"]:
            row["detalle_url"] = reverse_lazy("customers:cliente_detalle", args=[row["id"]])
        return ctx


@login_required
def cliente_detalle(request, pk):
    """Ficha única del cliente: datos + historial de ventas, recetas y
    devoluciones, para no tener que cruzar tres listados distintos a mano."""
    cliente = get_object_or_404(Cliente, pk=pk)
    ventas = (
        Venta.objects.filter(cliente=cliente)
        .select_related("vendedor")
        .prefetch_related("items__producto")
        .order_by("-fecha")
    )
    recetas = Receta.objects.filter(cliente=cliente).order_by("-fecha_recibido")
    devoluciones = (
        Devolucion.objects.filter(venta_item__venta__cliente=cliente).select_related("producto").order_by("-fecha")
        if es_administrador(request.user) else Devolucion.objects.none()
    )
    ordenes_laboratorio = (
        OrdenLaboratorio.objects.filter(cliente=cliente)
        .select_related("producto", "armazon", "venta_item__venta")
        .order_by("-creado")
    )
    return render(request, "customers/cliente_detalle.html", {
        "cliente": cliente, "ventas": ventas, "recetas": recetas, "devoluciones": devoluciones,
        "ordenes_laboratorio": ordenes_laboratorio,
    })


@login_required
@require_GET
def buscar_clientes_json(request):
    """Búsqueda de clientes por nombre/apellido/dni/email para usar en un
    buscador tipo autocompletar (igual que en el punto de venta), en vez de
    un <select> gigante con todos los clientes cargados."""
    q = request.GET.get("q", "").strip()
    clientes = []
    if q:
        clientes = list(Cliente.buscar(q)[:10].values("id", "nombre", "apellido", "dni", "email"))
    return JsonResponse({"resultados": clientes})


@login_required
@require_POST
def cliente_nuevo_rapido_json(request):
    """Alta rápida de cliente vía AJAX, para usar desde otras pantallas (ej: el
    formulario de recetas) sin perder lo ya cargado ahí ni navegar a otra
    página. Ningún campo es obligatorio, pero si vino todo vacío no se crea
    nada. Devuelve id + texto para mostrar, pensado para agregarse como
    <option> de un <select> por JS."""
    cliente = Cliente.crear_rapido(
        nombre=request.POST.get("nombre", "").strip(),
        apellido=request.POST.get("apellido", "").strip(),
        dni=request.POST.get("dni", "").strip(),
        telefono=request.POST.get("telefono", "").strip(),
        email=request.POST.get("email", "").strip(),
        direccion=request.POST.get("direccion", "").strip(),
    )
    if cliente is None:
        return JsonResponse({"error": "Completá al menos un dato del cliente."}, status=400)
    return JsonResponse({"id": cliente.id, "label": str(cliente)})


class ClienteCreateView(BaseCreateView):
    model = Cliente
    form_class = ClienteForm
    title = "Nuevo cliente"
    cancel_url_name = "customers:cliente_lista"
    success_url = reverse_lazy("customers:cliente_lista")


class ClienteUpdateView(BaseUpdateView):
    model = Cliente
    form_class = ClienteForm
    title = "Editar cliente"
    cancel_url_name = "customers:cliente_lista"
    success_url = reverse_lazy("customers:cliente_lista")


class ClienteDeleteView(BaseDeleteView):
    model = Cliente
    cancel_url_name = "customers:cliente_lista"
    success_url = reverse_lazy("customers:cliente_lista")


# ---------- Obras sociales ----------

class ObraSocialListView(AdminRequiredMixin, BaseListView):
    model = ObraSocial
    title = "Obras sociales"
    headers = ["Nombre", "Activa"]
    search_fields = ["nombre"]
    create_url_name = "customers:obra_social_nueva"
    edit_url_name = "customers:obra_social_editar"
    delete_url_name = "customers:obra_social_eliminar"
    export_csv_filename = "obras_sociales.csv"

    def get_row(self, obj):
        return [obj.nombre, "Sí" if obj.activa else "No"]


class ObraSocialCreateView(AdminRequiredMixin, BaseCreateView):
    model = ObraSocial
    form_class = ObraSocialForm
    title = "Nueva obra social"
    cancel_url_name = "customers:obra_social_lista"
    success_url = reverse_lazy("customers:obra_social_lista")


class ObraSocialUpdateView(AdminRequiredMixin, BaseUpdateView):
    model = ObraSocial
    form_class = ObraSocialForm
    title = "Editar obra social"
    cancel_url_name = "customers:obra_social_lista"
    success_url = reverse_lazy("customers:obra_social_lista")


class ObraSocialDeleteView(AdminRequiredMixin, BaseDeleteView):
    model = ObraSocial
    cancel_url_name = "customers:obra_social_lista"
    success_url = reverse_lazy("customers:obra_social_lista")
