import copy
from types import SimpleNamespace

from django.conf import settings
from django.db import connections
from django.test import RequestFactory, TestCase

from tenants.db_router import get_current_tenant, tenant_context
from tenants.middleware import AdminTenantSwitchMiddleware, TenantMiddleware
from tenants.models import Tenant

for _alias in ("tenant_a_test", "tenant_b_test", "tenant_demo"):
    if _alias not in connections.databases:
        _config = copy.deepcopy(settings.DATABASES["default"])
        _config["ENGINE"] = "django.db.backends.sqlite3"
        _config["NAME"] = ":memory:"
        _config["TEST"]["NAME"] = None
        connections.databases[_alias] = _config


class TenantIsolationTests(TestCase):
    databases = {"default", "tenant_a_test", "tenant_b_test"}

    def test_cross_tenant_isolation(self):
        from inventory.models import Categoria, Marca, Producto

        with tenant_context("tenant_a_test"):
            categoria = Categoria.objects.create(nombre="Armazones")
            marca = Marca.objects.create(nombre="Ray-Ban")
            Producto.objects.create(categoria=categoria, marca=marca, modelo="RB1234")

        with tenant_context("tenant_b_test"):
            self.assertEqual(Producto.objects.count(), 0)

        with tenant_context("tenant_a_test"):
            self.assertEqual(Producto.objects.count(), 1)

    def test_tenant_context_restores_previous_alias(self):
        with tenant_context("tenant_a_test"):
            with tenant_context("tenant_b_test"):
                self.assertEqual(get_current_tenant(), "tenant_b_test")
            self.assertEqual(get_current_tenant(), "tenant_a_test")
        self.assertIsNone(get_current_tenant())


class TenantMiddlewareTests(TestCase):
    databases = {"default", "tenant_demo"}

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(lambda request: get_current_tenant())
        Tenant.objects.create(nombre="Demo", slug="demo", db_name="stockero_demo")
        self._allowed_hosts = settings.ALLOWED_HOSTS
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, ".localhost"]
        self.addCleanup(setattr, settings, "ALLOWED_HOSTS", self._allowed_hosts)

    def test_resolves_known_subdomain(self):
        request = self.factory.get("/", HTTP_HOST="demo.localhost:8000")
        alias = self.middleware(request)
        self.assertEqual(alias, "tenant_demo")

    def test_falls_back_to_default_for_unknown_host(self):
        request = self.factory.get("/", HTTP_HOST="localhost:8000")
        alias = self.middleware(request)
        self.assertIsNone(alias)

    def test_falls_back_to_default_for_inactive_tenant(self):
        Tenant.objects.filter(slug="demo").update(activo=False)
        request = self.factory.get("/", HTTP_HOST="demo.localhost:8000")
        alias = self.middleware(request)
        self.assertIsNone(alias)


class AdminTenantSwitchMiddlewareTests(TestCase):
    databases = {"default", "tenant_demo"}

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = AdminTenantSwitchMiddleware(lambda request: get_current_tenant())
        Tenant.objects.create(nombre="Demo", slug="demo", db_name="stockero_demo")

    def _request(self, *, superuser, slug):
        request = self.factory.get("/admin-panel/")
        request.session = {"admin_tenant_slug": slug} if slug else {}
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=superuser)
        return request

    def test_superuser_con_override_activa_el_tenant(self):
        alias = self.middleware(self._request(superuser=True, slug="demo"))
        self.assertEqual(alias, "tenant_demo")

    def test_no_superuser_ignora_el_override(self):
        alias = self.middleware(self._request(superuser=False, slug="demo"))
        self.assertIsNone(alias)

    def test_sin_override_no_cambia_nada(self):
        alias = self.middleware(self._request(superuser=True, slug=None))
        self.assertIsNone(alias)
