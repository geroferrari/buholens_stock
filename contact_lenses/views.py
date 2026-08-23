import calendar
import datetime
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from customers.models import Cliente
from stockero.crud_views import BaseCreateView, BaseUpdateView, BaseDeleteView
from stockero.permissions import es_administrador
from sales.models import Venta

from .forms import PruebaForm
from .models import PruebaLentesContacto

logger = logging.getLogger(__name__)

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _local_date(dt):
    """Fecha local de un datetime, sea aware (USE_TZ=True) o naive."""
    if timezone.is_aware(dt):
        return timezone.localtime(dt).date()
    return dt.date()


# ---------- Agenda / calendario ----------

@login_required
def agenda(request):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month
    if not 1 <= mes <= 12:
        anio, mes = hoy.year, hoy.month

    cal = calendar.Calendar(firstweekday=0)  # 0 = lunes
    semanas_fechas = cal.monthdatescalendar(anio, mes)
    primera, ultima = semanas_fechas[0][0], semanas_fechas[-1][-1]

    pruebas = list(
        PruebaLentesContacto.objects
        .filter(fecha_hora__date__range=(primera, ultima))
        .select_related("cliente", "vendedor", "venta")
    )
    por_dia = {}
    for p in pruebas:
        por_dia.setdefault(_local_date(p.fecha_hora), []).append(p)

    semanas = []
    for semana in semanas_fechas:
        fila = []
        for dia in semana:
            fila.append({
                "fecha": dia,
                "en_mes": dia.month == mes,
                "es_hoy": dia == hoy,
                "pruebas": sorted(por_dia.get(dia, []), key=lambda x: x.fecha_hora),
            })
        semanas.append(fila)

    # Tabla: solo las pruebas del mes en curso (no los días de relleno).
    tabla = sorted(
        (p for p in pruebas if _local_date(p.fecha_hora).year == anio
         and _local_date(p.fecha_hora).month == mes),
        key=lambda x: x.fecha_hora,
    )

    mes_prev, anio_prev = (mes - 1, anio) if mes > 1 else (12, anio - 1)
    mes_next, anio_next = (mes + 1, anio) if mes < 12 else (1, anio + 1)

    return render(request, "contact_lenses/agenda.html", {
        "semanas": semanas,
        "dias_semana": DIAS_ES,
        "tabla": tabla,
        "anio": anio,
        "mes": mes,
        "mes_nombre": MESES_ES[mes],
        "nav_prev": {"anio": anio_prev, "mes": mes_prev},
        "nav_next": {"anio": anio_next, "mes": mes_next},
        "hoy": hoy,
    })


# ---------- Detalle y acciones ----------

@login_required
def prueba_detalle(request, pk):
    prueba = get_object_or_404(
        PruebaLentesContacto.objects.select_related("cliente", "vendedor", "venta", "receta"), pk=pk
    )
    # Graduación a mostrar: la asociada a la prueba, o la última del cliente.
    receta = prueba.receta
    if receta is None and prueba.cliente_id:
        receta = prueba.cliente.recetas.order_by("-fecha_recibido", "-creado").first()
    return render(request, "contact_lenses/prueba_detalle.html", {
        "prueba": prueba,
        "receta": receta,
        "Estado": PruebaLentesContacto.Estado,
    })


@login_required
def iniciar_venta(request, pk):
    """La prueba terminó en venta: se crea una Venta real del POS (con el
    cliente ya cargado) linkeada a la prueba, y se manda al POS a completarla.
    Acción de administración."""
    if not es_administrador(request.user):
        messages.error(request, "Registrar la venta requiere permisos de administrador/a.")
        return redirect("contact_lenses:prueba_detalle", pk=pk)
    prueba = get_object_or_404(PruebaLentesContacto, pk=pk)
    if request.method != "POST":
        return redirect("contact_lenses:prueba_detalle", pk=pk)

    # Si ya tiene una venta abierta, se continúa esa en vez de crear otra.
    if prueba.venta_abierta:
        return redirect("sales:pos", venta_id=prueba.venta_id)

    venta = Venta.objects.create(
        usuario=request.user, cliente=prueba.cliente, vendedor=prueba.vendedor,
    )
    prueba.venta = venta
    prueba.estado = PruebaLentesContacto.Estado.REALIZADA
    prueba.save(update_fields=["venta", "estado", "actualizado"])
    messages.success(request, "Venta iniciada: cargá los lentes y la forma de pago, y confirmá.")
    return redirect("sales:pos", venta_id=venta.pk)


@login_required
def marcar_realizada_sin_venta(request, pk):
    """La prueba se hizo pero el cliente no compró: queda realizada, sin venta.
    Acción de administración."""
    if not es_administrador(request.user):
        messages.error(request, "Esta acción requiere permisos de administrador/a.")
        return redirect("contact_lenses:prueba_detalle", pk=pk)
    prueba = get_object_or_404(PruebaLentesContacto, pk=pk)
    if request.method == "POST":
        prueba.estado = PruebaLentesContacto.Estado.REALIZADA
        prueba.venta = None
        prueba.save(update_fields=["estado", "venta", "actualizado"])
        messages.success(request, "Prueba marcada como realizada (sin venta).")
    return redirect("contact_lenses:prueba_detalle", pk=pk)


@login_required
def marcar_cancelada(request, pk):
    prueba = get_object_or_404(PruebaLentesContacto, pk=pk)
    if request.method == "POST":
        prueba.estado = PruebaLentesContacto.Estado.CANCELADA
        prueba.save(update_fields=["estado", "actualizado"])
        messages.success(request, "Prueba cancelada.")
    return redirect("contact_lenses:prueba_detalle", pk=pk)


@login_required
def reprogramar(request, pk):
    """Cambia la fecha/hora de una prueba agendada, sin tener que cancelarla y
    crear una nueva: reabre el recordatorio del día (por si ya se había
    mandado para la fecha vieja) y vuelve a avisar al vendedor con el horario
    nuevo."""
    prueba = get_object_or_404(PruebaLentesContacto, pk=pk)
    if request.method != "POST":
        return redirect("contact_lenses:prueba_detalle", pk=pk)
    if prueba.estado != PruebaLentesContacto.Estado.AGENDADA:
        messages.error(request, "Solo se puede reprogramar una prueba agendada.")
        return redirect("contact_lenses:prueba_detalle", pk=pk)

    nueva_fecha = parse_datetime(request.POST.get("fecha_hora", ""))
    if not nueva_fecha:
        messages.error(request, "Fecha y hora inválidas.")
        return redirect("contact_lenses:prueba_detalle", pk=pk)
    if timezone.is_naive(nueva_fecha):
        nueva_fecha = timezone.make_aware(nueva_fecha)

    prueba.fecha_hora = nueva_fecha
    prueba.recordatorio_enviado = False
    prueba.save(update_fields=["fecha_hora", "recordatorio_enviado", "actualizado"])
    _avisar_prueba_agendada(prueba, request.user)
    messages.success(request, "Prueba reprogramada.")
    return redirect("contact_lenses:prueba_detalle", pk=pk)


# ---------- CRUD ----------

def _avisar_prueba_agendada(prueba, quien_agendo=None):
    """Le manda una notificación al celular a la persona que tiene que hacer la
    prueba. Se busca por VENDEDOR (no por usuario), porque varias personas
    comparten el mismo login: cada celular declara de quién es al activar los
    avisos, y así el aviso llega al dueño correcto.

    Si esa persona no tiene ningún celular propio registrado, se cae en los
    dispositivos de su usuario vinculado; en ese caso no se le avisa a quien
    justo está agendando (sería avisarse a sí mismo).

    Nunca interrumpe el agendado: si el aviso falla, se ignora.
    """
    vendedor = prueba.vendedor
    if not vendedor:
        return 0
    try:
        from notificaciones.services import enviar_push_a_vendedor

        sin_celular_propio = not vendedor.suscripciones_push.exists()
        if sin_celular_propio and vendedor.usuario_id and vendedor.usuario_id == getattr(quien_agendo, "id", None):
            return 0

        fecha = timezone.localtime(prueba.fecha_hora) if timezone.is_aware(prueba.fecha_hora) else prueba.fecha_hora
        return enviar_push_a_vendedor(
            vendedor,
            titulo="👁 Nueva prueba de lentes de contacto",
            cuerpo=f"{prueba.nombre_cliente} — {fecha:%a %d/%m %H:%M}",
            url=reverse("contact_lenses:prueba_detalle", args=[prueba.pk]),
        )
    except Exception:  # el aviso es "mejor esfuerzo": nunca rompe el agendado
        logger.exception("No se pudo avisar de la prueba agendada #%s", prueba.pk)
        return 0


class PruebaCreateView(BaseCreateView):
    model = PruebaLentesContacto
    form_class = PruebaForm
    template_name = "contact_lenses/prueba_form.html"
    title = "Agendar prueba de lentes de contacto"
    cancel_url_name = "contact_lenses:agenda"
    success_message = "Prueba agendada."

    def get_initial(self):
        initial = super().get_initial()
        fecha = self.request.GET.get("fecha")
        if fecha:
            # Día clickeado en el calendario: default 10:00.
            initial["fecha_hora"] = f"{fecha}T10:00"
        cliente_id = self.request.GET.get("cliente")
        if cliente_id and cliente_id.isdigit():
            initial["cliente"] = cliente_id
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cliente_id = self.request.GET.get("cliente")
        if cliente_id and cliente_id.isdigit():
            ctx["cliente_seleccionado"] = Cliente.objects.filter(pk=cliente_id).first()
        return ctx

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        _avisar_prueba_agendada(self.object, self.request.user)
        return respuesta

    def get_success_url(self):
        prueba = self.object
        detalle = reverse("contact_lenses:prueba_detalle", args=[prueba.pk])
        # Guiado: si el cliente todavía no tiene ninguna graduación cargada, se
        # lo lleva directo a cargarla (con el cliente ya puesto), y de ahí vuelve
        # al detalle con la receta linkeada. Si ya tiene, va al detalle: desde
        # ahí puede cargar una nueva si hace falta.
        if prueba.cliente_id and not prueba.cliente.recetas.exists():
            url = reverse("prescriptions:receta_nueva")
            return f"{url}?prueba={prueba.pk}&volver={detalle}"
        return detalle


class PruebaUpdateView(BaseUpdateView):
    model = PruebaLentesContacto
    form_class = PruebaForm
    template_name = "contact_lenses/prueba_form.html"
    title = "Editar prueba"
    cancel_url_name = "contact_lenses:agenda"
    success_message = "Prueba actualizada."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cliente_seleccionado"] = self.object.cliente
        return ctx

    def get_success_url(self):
        return reverse("contact_lenses:prueba_detalle", args=[self.object.pk])


class PruebaDeleteView(BaseDeleteView):
    model = PruebaLentesContacto
    cancel_url_name = "contact_lenses:agenda"
    success_message = "Prueba eliminada."
    success_url = reverse_lazy("contact_lenses:agenda")
