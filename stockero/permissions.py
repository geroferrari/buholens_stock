from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect


def es_administrador(user):
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name="Administrador").exists())
    )


class AdminRequiredMixin(UserPassesTestMixin):
    """Solo usuarios del grupo Administrador (o superusuarios) pueden pasar."""

    def test_func(self):
        return es_administrador(self.request.user)

    def handle_no_permission(self):
        messages.error(self.request, "Esta acción requiere permisos de administrador/a.")
        return redirect("home")
