import csv
import functools
import operator

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView


from stockero.permissions import es_administrador


class BaseListView(LoginRequiredMixin, ListView):
    """Lista genérica: cada subclase define `headers` (nombres de columna) y
    `get_row(obj)` (valores de cada columna para esa fila)."""
    template_name = "crud/list.html"
    paginate_by = 50
    title = ""
    headers = []
    search_fields = []
    search_placeholder = "Buscar..."
    create_url_name = None
    edit_url_name = None
    delete_url_name = None
    detalle_url_name = None  # si se define, agrega un botón "Ver" que linkea a este detalle
    edit_label = "Editar"  # subclases pueden pisarlo (ej: "Corregir")
    admin_only_actions = False  # si es True, crear/editar/eliminar quedan ocultos para no-admins
    export_csv_filename = None  # si se define, habilita "exportar CSV" con ?export=csv
    sort_fields = {}  # {"Nombre": "nombre", ...}: headers ordenables y su campo de modelo
    default_sort = None  # header por defecto si no viene ?sort= (None = el ordering del modelo)

    def get(self, request, *args, **kwargs):
        if self.export_csv_filename and request.GET.get("export") == "csv":
            return self.export_csv()
        return super().get(request, *args, **kwargs)

    def export_csv(self):
        """Exporta TODAS las filas que matchean la búsqueda actual (no solo la
        página visible), con las mismas columnas que la tabla en pantalla."""
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.export_csv_filename}"'
        response.write("﻿")  # BOM: para que Excel abra los acentos bien
        writer = csv.writer(response)
        writer.writerow(self.headers)
        for obj in self.get_queryset():
            writer.writerow(self.get_row(obj))
        return response

    def annotate_queryset(self, qs):
        """Hook para que las subclases agreguen .annotate() antes de que se
        apliquen búsqueda y orden (ej: para poder ordenar por una columna
        calculada, como la fecha de la última receta de un cliente)."""
        return qs

    def get_queryset(self):
        qs = self.annotate_queryset(super().get_queryset())
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            # Cada palabra debe aparecer en ALGUNO de los campos (no necesariamente
            # todas en el mismo campo): así "Juan Perez" encuentra al cliente con
            # nombre="Juan" y apellido="Perez", sin importar el orden.
            for palabra in q.split():
                condiciones = [Q(**{f"{campo}__icontains": palabra}) for campo in self.search_fields]
                qs = qs.filter(functools.reduce(operator.or_, condiciones))

        sort_header = self.request.GET.get("sort") or self.default_sort
        if sort_header and sort_header in self.sort_fields:
            campo = self.sort_fields[sort_header]
            desc = self.request.GET.get("dir") == "desc"
            # nulls_last siempre (en asc y en desc): un cliente sin receta no
            # debe aparecer primero solo porque NULL "pesa más" en la base.
            # El "pk" al final desempata filas con el mismo valor, para que el
            # orden no cambie de una página a la otra al paginar.
            orden = F(campo).desc(nulls_last=True) if desc else F(campo).asc(nulls_last=True)
            qs = qs.order_by(orden, "pk")
        else:
            qs = qs.order_by(*self.model._meta.ordering, "pk")
        return qs

    def get_row(self, obj):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        puede_editar = (not self.admin_only_actions) or es_administrador(self.request.user)
        ctx["title"] = self.title
        ctx["headers"] = self.headers
        search_query = self.request.GET.get("q", "")
        ctx["search_query"] = search_query

        params_sin_page = self.request.GET.copy()
        params_sin_page.pop("page", None)
        ctx["querystring"] = params_sin_page.urlencode()

        sort_actual = self.request.GET.get("sort") or self.default_sort
        dir_actual = self.request.GET.get("dir", "asc")
        columnas = []
        for h in self.headers:
            campo = self.sort_fields.get(h)
            if not campo:
                columnas.append({"label": h, "sortable": False})
                continue
            es_activa = h == sort_actual
            dir_siguiente = "desc" if (es_activa and dir_actual == "asc") else "asc"
            params = self.request.GET.copy()
            params["sort"] = h
            params["dir"] = dir_siguiente
            params.pop("page", None)
            columnas.append({
                "label": h,
                "sortable": True,
                "url": f"?{params.urlencode()}",
                "activa": es_activa,
                "dir": dir_actual if es_activa else None,
            })
        ctx["columnas"] = columnas
        ctx["search_placeholder"] = self.search_placeholder
        ctx["show_search"] = bool(self.search_fields)
        ctx["export_csv"] = bool(self.export_csv_filename)
        ctx["create_url"] = reverse_lazy(self.create_url_name) if (self.create_url_name and puede_editar) else None
        ctx["edit_label"] = self.edit_label
        rows = []
        for obj in ctx["object_list"]:
            rows.append({
                "id": obj.pk,
                "obj": obj,
                "cells": self.get_row(obj),
                "detalle_url": reverse_lazy(self.detalle_url_name, args=[obj.pk]) if self.detalle_url_name else None,
                "edit_url": reverse_lazy(self.edit_url_name, args=[obj.pk]) if (self.edit_url_name and puede_editar) else None,
                "delete_url": reverse_lazy(self.delete_url_name, args=[obj.pk]) if (self.delete_url_name and puede_editar) else None,
            })
        ctx["rows"] = rows
        return ctx


class BaseFormViewMixin:
    template_name = "crud/form.html"
    title = ""
    cancel_url_name = None
    success_message = "Guardado correctamente."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["cancel_url"] = reverse_lazy(self.cancel_url_name) if self.cancel_url_name else None
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


class BaseCreateView(BaseFormViewMixin, LoginRequiredMixin, CreateView):
    pass


class BaseUpdateView(BaseFormViewMixin, LoginRequiredMixin, UpdateView):
    pass


class BaseDeleteView(LoginRequiredMixin, DeleteView):
    template_name = "crud/confirm_delete.html"
    cancel_url_name = None
    success_message = "Eliminado correctamente."
    proteccion_msg = "No se puede eliminar: está en uso por otro registro (ventas, movimientos de stock, recetas, etc)."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cancel_url"] = reverse_lazy(self.cancel_url_name) if self.cancel_url_name else None
        return ctx

    def form_valid(self, form):
        success_url = self.get_success_url()
        try:
            self.object.delete()
        except ProtectedError as e:
            messages.error(self.request, self._mensaje_proteccion(e))
            return redirect(success_url)
        messages.success(self.request, self.success_message)
        return redirect(success_url)

    def _mensaje_proteccion(self, error):
        """Arma un mensaje concreto (ej: "1 orden de compra") a partir de los
        objetos que bloquean el borrado, en vez del genérico de siempre, para
        que quede claro qué hay que resolver antes de poder eliminar."""
        protegidos = error.protected_objects
        conteos = {}
        for obj in protegidos:
            nombre = obj._meta.verbose_name_plural if len(protegidos) != 1 else obj._meta.verbose_name
            conteos[nombre] = conteos.get(nombre, 0) + 1
        detalle = ", ".join(f"{n} {nombre}" for nombre, n in conteos.items())
        return f"No se puede eliminar: tiene {detalle} asociada(s)." if detalle else self.proteccion_msg
