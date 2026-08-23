from tenants.db_router import get_current_tenant, get_or_register_tenant_db, tenant_context
from tenants.models import Tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        slug = host.split(".")[0] if "." in host else None
        tenant = Tenant.objects.filter(slug=slug, activo=True).first() if slug else None

        if tenant is None:
            return self.get_response(request)

        alias = get_or_register_tenant_db(tenant)
        with tenant_context(alias):
            return self.get_response(request)


class AdminTenantSwitchMiddleware:
    """Deja al superuser 'entrar' a la base de una óptica desde el admin
    (sin subdominio de por medio), vía tenants.admin.gestionar_usuarios_view.
    Va DESPUÉS de AuthenticationMiddleware: necesita request.user resuelto."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if get_current_tenant() is None and user is not None and user.is_authenticated and user.is_superuser:
            slug = request.session.get("admin_tenant_slug")
            tenant = Tenant.objects.filter(slug=slug, activo=True).first() if slug else None
            if tenant is not None:
                alias = get_or_register_tenant_db(tenant)
                with tenant_context(alias):
                    return self.get_response(request)

        return self.get_response(request)
