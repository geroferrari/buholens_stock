from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from customers.models import Cliente
from inventory.models import Categoria, Marca, Producto
from .models import Medico, OrdenLaboratorio, Receta

PAYLOAD_XSS = '<script>alert("xss")</script>'


class SeguridadRecetaTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Cliente Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_observaciones_con_html_queda_escapado_en_el_listado_y_form(self):
        medico = Medico.objects.create(nombre=PAYLOAD_XSS)
        Receta.objects.create(
            cliente=self.cliente, fecha_recibido="2026-07-01",
            medico=medico, observaciones=PAYLOAD_XSS,
        )
        resp = self.client.get("/recetas/")
        self.assertNotIn(PAYLOAD_XSS, resp.content.decode())

        receta = Receta.objects.first()
        resp = self.client.get(f"/recetas/{receta.id}/editar/")
        html = resp.content.decode()
        self.assertNotIn(PAYLOAD_XSS, html)
        self.assertIn("&lt;script&gt;", html)


class RecetaCRUDTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Cliente Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _datos_minimos(self, **overrides):
        base = {
            "cliente": self.cliente.id, "fecha_recibido": "2026-07-01", "fecha_entrega": "",
            "medico": "", "obra_social": "",
            "lejos_od_esfera": "", "lejos_od_cilindro": "", "lejos_od_eje": "", "lejos_od_adicion": "",
            "lejos_oi_esfera": "", "lejos_oi_cilindro": "", "lejos_oi_eje": "", "lejos_oi_adicion": "",
            "lejos_dnp": "", "lejos_tipo_cristal": "", "lejos_color_cristal": "", "lejos_tratamientos": "",
            "cerca_od_esfera": "", "cerca_od_cilindro": "", "cerca_od_eje": "",
            "cerca_oi_esfera": "", "cerca_oi_cilindro": "", "cerca_oi_eje": "",
            "cerca_dnp": "", "cerca_tipo_cristal": "", "cerca_color_cristal": "", "cerca_tratamientos": "",
            "es_bifocal_multifocal": "", "di_lejos": "", "di_cerca": "", "altura": "",
            "observaciones": "",
        }
        base.update(overrides)
        return base

    def test_crear_receta(self):
        medico = Medico.objects.create(nombre="Dr. Test")
        self.client.post("/recetas/nueva/", self._datos_minimos(medico=medico.id))
        self.assertTrue(Receta.objects.filter(medico=medico).exists())

    def test_numeros_de_graduacion_se_guardan_bien(self):
        self.client.post("/recetas/nueva/", self._datos_minimos(
            lejos_od_esfera="-2.5", lejos_od_cilindro="-0.75", lejos_od_eje="90",
        ))
        r = Receta.objects.first()
        self.assertEqual(float(r.lejos_od_esfera), -2.5)
        self.assertEqual(r.lejos_od_eje, 90)

    def test_receta_de_lentes_de_contacto_guarda_marca(self):
        self.client.post("/recetas/nueva/", self._datos_minimos(
            es_lentes_contacto="on", marca_lentes_contacto="Acuvue",
        ))
        r = Receta.objects.latest("id")
        self.assertTrue(r.es_lentes_contacto)
        self.assertEqual(r.marca_lentes_contacto, "Acuvue")


class MedicoBuscarYAltaRapidaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_buscar_medicos_filtra_por_nombre(self):
        Medico.objects.create(nombre="Fernando Loza")
        Medico.objects.create(nombre="Ana Gómez")
        resp = self.client.get("/recetas/medicos/buscar/", {"q": "Loza"})
        data = resp.json()
        self.assertEqual(len(data["resultados"]), 1)
        self.assertEqual(data["resultados"][0]["nombre"], "Fernando Loza")

    def test_alta_rapida_reutiliza_medico_existente_case_insensitive(self):
        existente = Medico.objects.create(nombre="Fernando Loza")
        resp = self.client.post("/recetas/medicos/nuevo-rapido/", {"nombre": "fernando loza"})
        data = resp.json()
        self.assertEqual(data["id"], existente.id)
        self.assertEqual(Medico.objects.count(), 1)

    def test_alta_rapida_crea_medico_nuevo(self):
        resp = self.client.post("/recetas/medicos/nuevo-rapido/", {"nombre": "Dr. Nuevo"})
        data = resp.json()
        self.assertTrue(Medico.objects.filter(pk=data["id"], nombre="Dr. Nuevo").exists())

    def test_admin_no_permite_cargar_medico_duplicado_case_insensitive(self):
        Medico.objects.create(nombre="Fernando Loza")
        resp = self.client.post("/admin-panel/prescriptions/medico/add/", {"nombre": "fernando loza"})
        self.assertEqual(resp.status_code, 200)  # se queda en el form, no redirige
        self.assertContains(resp, "Ya existe un médico cargado")


class InfoRecetaClienteJsonTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")
        self.cliente = Cliente.objects.create(nombre="Cliente Test")

    def test_sin_recetas(self):
        resp = self.client.get("/recetas/info-cliente/", {"cliente": self.cliente.id})
        self.assertEqual(resp.json(), {"tiene_receta": False})

    def test_devuelve_la_mas_reciente(self):
        Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-01-01")
        ultima = Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-06-01")
        data = self.client.get("/recetas/info-cliente/", {"cliente": self.cliente.id}).json()
        self.assertTrue(data["tiene_receta"])
        self.assertEqual(data["fecha"], "01/06/2026")
        self.assertIn(str(ultima.pk), data["url"])


class OrdenLaboratorioTests(TestCase):
    """La orden de laboratorio nace 'Pendiente de enviar' y es un registro
    propio: no depende de que la venta que la originó siga existiendo."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Cliente Test")
        self.receta = Receta.objects.create(
            cliente=self.cliente, fecha_recibido=timezone.localdate(),
        )
        self.categoria = Categoria.objects.create(
            nombre="Cristal", usa_receta=True, controla_stock=False,
        )
        self.cristal = Producto.objects.create(
            codigo_barras="9600000001", categoria=self.categoria,
            marca=Marca.objects.create(nombre="Essilor"), precio=15000,
        )

    def test_nace_pendiente_de_enviar(self):
        orden = OrdenLaboratorio.objects.create(
            cliente=self.cliente, receta=self.receta, producto=self.cristal,
        )
        self.assertEqual(orden.estado, OrdenLaboratorio.Estado.PENDIENTE)

    def test_sobrevive_a_la_eliminacion_del_item_de_venta(self):
        # La FK a VentaItem es SET_NULL: si se borra el ítem (o la venta), la
        # orden queda como registro propio con venta_item en NULL.
        from sales.models import Venta, VentaItem, Vendedor

        venta = Venta.objects.create(vendedor=Vendedor.objects.create(nombre="V"))
        item = VentaItem.objects.create(
            venta=venta, producto=self.cristal, cantidad=1,
            precio_unitario=15000, receta=self.receta,
        )
        orden = OrdenLaboratorio.objects.create(
            cliente=self.cliente, receta=self.receta, producto=self.cristal, venta_item=item,
        )
        item.delete()
        orden.refresh_from_db()
        self.assertIsNone(orden.venta_item_id)
        self.assertTrue(OrdenLaboratorio.objects.filter(pk=orden.pk).exists())


class RecetaHistorialCargaTests(TestCase):
    """Historial de carga de recetas: queda quién cargó cada una y el resumen
    es solo para admin."""

    def setUp(self):
        self.cliente = Cliente.objects.create(nombre="Cliente Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.empleado = User.objects.create_user("empleado", password="test12345")

    def _crear_receta_via_view(self, medico=""):
        datos = {
            "cliente": self.cliente.id, "fecha_recibido": "2026-07-01", "fecha_entrega": "",
            "medico": medico, "obra_social": "",
            "lejos_od_esfera": "", "lejos_od_cilindro": "", "lejos_od_eje": "", "lejos_od_adicion": "",
            "lejos_oi_esfera": "", "lejos_oi_cilindro": "", "lejos_oi_eje": "", "lejos_oi_adicion": "",
            "lejos_dnp": "", "lejos_tipo_cristal": "", "lejos_color_cristal": "", "lejos_tratamientos": "",
            "cerca_od_esfera": "", "cerca_od_cilindro": "", "cerca_od_eje": "",
            "cerca_oi_esfera": "", "cerca_oi_cilindro": "", "cerca_oi_eje": "",
            "cerca_dnp": "", "cerca_tipo_cristal": "", "cerca_color_cristal": "", "cerca_tratamientos": "",
            "es_bifocal_multifocal": "", "di_lejos": "", "di_cerca": "", "altura": "",
            "observaciones": "",
        }
        return self.client.post("/recetas/nueva/", datos)

    def test_crear_receta_registra_quien_la_cargo(self):
        medico = Medico.objects.create(nombre="Dr. X")
        self.client.login(username="empleado", password="test12345")
        self._crear_receta_via_view(medico=medico.id)
        receta = Receta.objects.get(medico=medico)
        self.assertEqual(receta.cargada_por, self.empleado)

    def test_historial_es_solo_para_admin(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/recetas/historial-carga/")
        self.assertEqual(resp.status_code, 302)  # redirigido, no autorizado

    def test_historial_cuenta_por_empleado(self):
        # 2 recetas del empleado, 1 del admin.
        self.client.login(username="empleado", password="test12345")
        self._crear_receta_via_view()
        self._crear_receta_via_view()
        self.client.login(username="admin", password="test12345")
        self._crear_receta_via_view()

        resp = self.client.get("/recetas/historial-carga/")
        self.assertEqual(resp.status_code, 200)
        conteos = {e["nombre"]: e["total"] for e in resp.context["por_empleado"]}
        self.assertEqual(conteos.get("empleado"), 2)
        self.assertEqual(conteos.get("admin"), 1)
        self.assertEqual(resp.context["total_general"], 3)
