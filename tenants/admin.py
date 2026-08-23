from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "nombre", "activo", "creado", "gestionar_usuarios_link")
    prepopulated_fields = {"slug": ("nombre",)}

    def gestionar_usuarios_link(self, obj):
        url = reverse("admin:tenants_tenant_gestionar_usuarios", args=[obj.pk])
        return format_html('<a href="{}">Gestionar usuarios →</a>', url)
    gestionar_usuarios_link.short_description = "Usuarios"

    def get_urls(self):
        urls = [
            path(
                "<int:pk>/gestionar-usuarios/",
                self.admin_site.admin_view(self.gestionar_usuarios_view),
                name="tenants_tenant_gestionar_usuarios",
            ),
            path(
                "volver-a-control/",
                self.admin_site.admin_view(self.volver_a_control_view),
                name="tenants_tenant_volver_a_control",
            ),
        ]
        return urls + super().get_urls()

    def gestionar_usuarios_view(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        request.session["admin_tenant_slug"] = tenant.slug
        volver_url = reverse("admin:tenants_tenant_volver_a_control")
        messages.info(
            request,
            format_html(
                "Ahora estás en la base de '{}'. <a href=\"{}\">Volver a la base de control</a>.",
                tenant.nombre, volver_url,
            ),
        )
        return redirect("admin:auth_user_changelist")

    def volver_a_control_view(self, request):
        request.session.pop("admin_tenant_slug", None)
        messages.info(request, "Volviste a la base de control.")
        return redirect("admin:index")
