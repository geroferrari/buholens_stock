import copy
import threading
from contextlib import contextmanager
from functools import wraps

from django.conf import settings
from django.db import connections, transaction

_local = threading.local()


def get_current_tenant():
    return getattr(_local, "alias", None)


def set_current_tenant(alias):
    _local.alias = alias


def clear_current_tenant():
    _local.alias = None


@contextmanager
def tenant_context(alias):
    previous = get_current_tenant()
    set_current_tenant(alias)
    try:
        yield
    finally:
        set_current_tenant(previous)


def tenant_atomic(func):
    """Como @transaction.atomic, pero abre la transacción en la base del
    tenant activo en este thread (bare @transaction.atomic siempre apunta a
    'default', que bajo TenantRouter no es necesariamente donde el resto de
    la vista está leyendo/escribiendo)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with transaction.atomic(using=get_current_tenant() or "default"):
            return func(*args, **kwargs)
    return wrapper


def iter_tenant_aliases():
    """Recorre los tenants activos como (etiqueta, alias). Si todavía no hay
    ninguno dado de alta, cae en un único ('default', 'default') para que los
    comandos sigan funcionando en una instalación sin multi-tenant (dev/tests)."""
    from tenants.models import Tenant

    tenants = list(Tenant.objects.filter(activo=True))
    if not tenants:
        yield "default", "default"
        return
    for tenant in tenants:
        yield tenant.slug, get_or_register_tenant_db(tenant)


def get_or_register_tenant_db(tenant):
    alias = f"tenant_{tenant.slug}"
    if alias not in connections.databases:
        config = copy.deepcopy(settings.DATABASES["default"])
        if config["ENGINE"] == "django.db.backends.sqlite3":
            config["NAME"] = settings.BASE_DIR / f"{tenant.db_name}.sqlite3"
        else:
            config["NAME"] = tenant.db_name
        connections.databases[alias] = config
    return alias


class TenantRouter:
    def db_for_read(self, model, **hints):
        return self._alias_for(model)

    def db_for_write(self, model, **hints):
        return self._alias_for(model)

    def _alias_for(self, model):
        if model._meta.app_label == "tenants":
            return "default"
        return get_current_tenant() or "default"
