from django.contrib.auth.models import User
from django.test import TestCase

from .models import Cliente

PAYLOAD_XSS = '<script>alert("xss")</script>'


class SeguridadClienteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_nombre_con_html_queda_escapado_en_el_listado(self):
        Cliente.objects.create(nombre=PAYLOAD_XSS, dni="30111222")
        resp = self.client.get("/clientes/")
        html = resp.content.decode()
        self.assertNotIn(PAYLOAD_XSS, html)
        self.assertIn("&lt;script&gt;", html)

    def test_busqueda_con_caracteres_raros_no_rompe(self):
        for intento in ["' OR '1'='1", '<img src=x onerror=alert(1)>', "%%%", "'; --"]:
            resp = self.client.get("/clientes/", {"q": intento})
            self.assertEqual(resp.status_code, 200)


class ClienteCRUDTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_crear_cliente(self):
        resp = self.client.post("/clientes/nuevo/", {
            "nombre": "Juan", "apellido": "Pérez", "dni": "30999888", "telefono": "", "email": "", "direccion": "",
        })
        self.assertTrue(Cliente.objects.filter(nombre="Juan", apellido="Pérez").exists())

    def test_editar_cliente(self):
        c = Cliente.objects.create(nombre="Nombre Viejo", apellido="Apellido")
        self.client.post(f"/clientes/{c.id}/editar/", {
            "nombre": "Nombre Nuevo", "apellido": "Apellido", "dni": "", "telefono": "", "email": "", "direccion": "",
        })
        c.refresh_from_db()
        self.assertEqual(c.nombre, "Nombre Nuevo")

    def test_eliminar_cliente_sin_ventas(self):
        c = Cliente.objects.create(nombre="Para Borrar")
        self.client.post(f"/clientes/{c.id}/eliminar/")
        self.assertFalse(Cliente.objects.filter(pk=c.pk).exists())

    def test_anonimo_no_accede(self):
        self.client.logout()
        resp = self.client.get("/clientes/")
        self.assertEqual(resp.status_code, 302)

    def test_cliente_sin_ningun_dato_es_valido(self):
        c = Cliente.objects.create()
        self.assertEqual(c.pk is not None, True)
        self.assertEqual(str(c), f"Cliente #{c.pk}")

    def test_whatsapp_anteojo_listo_incluye_nombre_y_mensaje(self):
        c = Cliente.objects.create(nombre="Juan", apellido="Pérez", telefono="1122334455")
        url = c.whatsapp_url_anteojo_listo
        self.assertIn("wa.me/5491122334455", url)
        self.assertIn("Hola%20Juan%20P", url)
        self.assertIn("listo%20para%20retirar", url)

    def test_whatsapp_anteojo_listo_sin_telefono_es_none(self):
        c = Cliente.objects.create(nombre="Sin Tel")
        self.assertIsNone(c.whatsapp_url_anteojo_listo)


class ObraSocialSinDuplicadosTests(TestCase):
    """No se deben poder cargar dos obras sociales iguales salvo mayúsculas
    (ej: 'Particular' / 'particular'); las variantes reales sí conviven."""

    def test_form_rechaza_duplicado_ignorando_mayusculas(self):
        from .forms import ObraSocialForm
        from .models import ObraSocial

        ObraSocial.objects.create(nombre="ZZ Cobertura Test")
        form = ObraSocialForm(data={"nombre": "zz cobertura test", "activa": True})
        self.assertFalse(form.is_valid())
        self.assertIn("nombre", form.errors)

    def test_form_permite_variantes_distintas(self):
        from .forms import ObraSocialForm
        from .models import ObraSocial

        ObraSocial.objects.create(nombre="ZZ Cober")
        form = ObraSocialForm(data={"nombre": "ZZ Cober 210", "activa": True})
        self.assertTrue(form.is_valid())

    def test_constraint_en_la_base_bloquea_duplicado(self):
        from django.db import IntegrityError, transaction
        from .models import ObraSocial

        ObraSocial.objects.create(nombre="ZZ Cobertura Test")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ObraSocial.objects.create(nombre="zz cobertura test")


class ObraSocialBuscarYAltaRapidaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_buscar_filtra_por_nombre(self):
        from .models import ObraSocial

        ObraSocial.objects.create(nombre="ZZ Swiss Medical")
        ObraSocial.objects.create(nombre="ZZ OSDE")
        resp = self.client.get("/clientes/obras-sociales/buscar/", {"q": "ZZ Swiss"})
        data = resp.json()
        self.assertEqual(len(data["resultados"]), 1)
        self.assertEqual(data["resultados"][0]["nombre"], "ZZ Swiss Medical")

    def test_alta_rapida_reutiliza_existente_case_insensitive(self):
        from .models import ObraSocial

        existente = ObraSocial.objects.create(nombre="ZZ Particular")
        resp = self.client.post("/clientes/obras-sociales/nueva-rapida/", {"nombre": "zz particular"})
        data = resp.json()
        self.assertEqual(data["id"], existente.id)
        self.assertEqual(ObraSocial.objects.filter(nombre__iexact="zz particular").count(), 1)

    def test_alta_rapida_crea_nueva(self):
        from .models import ObraSocial

        resp = self.client.post("/clientes/obras-sociales/nueva-rapida/", {"nombre": "ZZ Cobertura Nueva"})
        data = resp.json()
        self.assertTrue(ObraSocial.objects.filter(pk=data["id"], nombre="ZZ Cobertura Nueva").exists())
