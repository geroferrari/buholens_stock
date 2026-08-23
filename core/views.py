import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from inventory.models import Producto
from stockero.permissions import es_administrador
from prescriptions.models import Receta
from sales.models import Venta

from .forms import ConfiguracionForm
from .models import Configuracion

# Qué modelos tienen papelera, con su etiqueta para la URL/plantilla.
MODELOS_PAPELERA = {
    "receta": Receta,
    "producto": Producto,
    "venta": Venta,
}


def _solo_admin(request, que="La papelera"):
    if not es_administrador(request.user):
        messages.error(request, f"{que} es solo para administradores/as.")
        return redirect("home")
    return None


@login_required
def papelera(request):
    """Muestra lo borrado (recuperable) de recetas, productos y ventas, con
    cuándo se va a eliminar solo. Solo admin."""
    redir = _solo_admin(request)
    if redir:
        return redir

    dias = settings.PAPELERA_DIAS_RETENCION
    recetas = (
        Receta.con_eliminados.en_papelera()
        .select_related("cliente").order_by("-eliminado_en")
    )
    productos = (
        Producto.con_eliminados.en_papelera()
        .select_related("marca", "categoria").order_by("-eliminado_en")
    )
    ventas = (
        Venta.con_eliminados.en_papelera()
        .select_related("cliente", "vendedor").order_by("-eliminado_en")
    )
    return render(request, "core/papelera.html", {
        "dias": dias,
        "purga_delta": datetime.timedelta(days=dias),
        "recetas": recetas,
        "productos": productos,
        "ventas": ventas,
        "total": recetas.count() + productos.count() + ventas.count(),
    })


@login_required
@require_POST
def restaurar(request, tipo, pk):
    """Saca un registro de la papelera (lo recupera)."""
    redir = _solo_admin(request)
    if redir:
        return redir
    Modelo = MODELOS_PAPELERA.get(tipo)
    if not Modelo:
        messages.error(request, "Tipo desconocido.")
        return redirect("core:papelera")
    obj = get_object_or_404(Modelo.con_eliminados, pk=pk)
    obj.restaurar()
    messages.success(request, "Recuperado correctamente.")
    return redirect("core:papelera")


@login_required
@require_POST
def eliminar_definitivo(request, tipo, pk):
    """Borra de verdad un registro de la papelera (sin vuelta atrás)."""
    redir = _solo_admin(request)
    if redir:
        return redir
    Modelo = MODELOS_PAPELERA.get(tipo)
    if not Modelo:
        messages.error(request, "Tipo desconocido.")
        return redirect("core:papelera")
    obj = get_object_or_404(Modelo.con_eliminados, pk=pk)
    try:
        obj.eliminar_definitivo()
    except ProtectedError:
        messages.error(
            request,
            "No se puede eliminar definitivamente: está en uso por otros registros "
            "(ej: un producto con ventas). Queda oculto en la papelera.",
        )
        return redirect("core:papelera")
    messages.success(request, "Eliminado definitivamente.")
    return redirect("core:papelera")


@login_required
def configuracion(request):
    """Datos de la óptica: nombre, contacto, logo y color de marca. Es lo que
    hace que la app sirva para cualquier óptica sin tocar código. Solo admin."""
    redir = _solo_admin(request, "La configuración")
    if redir:
        return redir

    # Singleton: se edita la fila existente o se crea la primera al guardar.
    actual = Configuracion.objects.first()
    if request.method == "POST":
        form = ConfiguracionForm(request.POST, request.FILES, instance=actual)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuración guardada.")
            return redirect("core:configuracion")
    else:
        form = ConfiguracionForm(instance=actual)

    return render(request, "core/configuracion.html", {"form": form})
