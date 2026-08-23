import gzip
import json
import os
import tempfile
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings

from customers.models import Cliente, ObraSocial

from .models import Configuracion


class BackupDbTests(TestCase):
    def setUp(self):
        # Un dato cualquiera para que el backup no esté vacío.
        ObraSocial.objects.create(nombre="ZZ Backup Test OS")

    def test_backup_a_archivo_es_gzip_valido_con_los_datos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "backup.json.gz")
            call_command("backup_db", to_file=ruta, stdout=StringIO())
            self.assertTrue(os.path.exists(ruta))
            datos = json.loads(gzip.open(ruta, "rt", encoding="utf-8").read())
            modelos = {o["model"] for o in datos}
            self.assertIn("customers.obrasocial", modelos)

    def test_backup_excluye_tablas_regenerables(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "backup.json.gz")
            call_command("backup_db", to_file=ruta, stdout=StringIO())
            modelos = {o["model"] for o in json.loads(gzip.open(ruta, "rt", encoding="utf-8").read())}
            self.assertNotIn("contenttypes.contenttype", modelos)
            self.assertNotIn("sessions.session", modelos)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        EMAIL_HOST="smtp.test",
        BACKUP_EMAIL="gero@example.com",
    )
    def test_backup_por_email_adjunta_el_gz(self):
        call_command("backup_db", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["gero@example.com"])
        self.assertEqual(len(msg.attachments), 1)
        nombre, contenido, tipo = msg.attachments[0]
        self.assertTrue(nombre.endswith(".json.gz"))
        self.assertEqual(tipo, "application/gzip")
        # El adjunto es un gzip real con datos adentro.
        self.assertIn("customers.obrasocial", gzip.decompress(contenido).decode("utf-8"))

    @override_settings(EMAIL_HOST="smtp.test", BACKUP_EMAIL="")
    def test_sin_destino_avisa_claro(self):
        with self.assertRaises(CommandError):
            call_command("backup_db", stdout=StringIO())

    @override_settings(EMAIL_HOST="", BACKUP_EMAIL="gero@example.com")
    def test_sin_email_configurado_avisa_claro(self):
        with self.assertRaises(CommandError):
            call_command("backup_db", stdout=StringIO())


class PapeleraSoftDeleteTests(TestCase):
    """Borrar manda a la papelera (recuperable); la purga elimina lo viejo y la
    venta devuelve el stock al eliminarse definitivamente."""

    def setUp(self):
        from customers.models import Cliente
        from inventory.models import Categoria, Marca, Producto
        from prescriptions.models import Receta

        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.cliente = Cliente.objects.create(nombre="Ana", apellido="Test")
        self.receta = Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-07-01")
        self.categoria = Categoria.objects.create(nombre="Armazón Pap", controla_stock=True)
        self.producto = Producto.objects.create(
            categoria=self.categoria, marca=Marca.objects.create(nombre="MarcaPap"),
            precio=1000, stock_actual=7,
        )

    def test_borrar_manda_a_papelera_y_lo_oculta(self):
        from prescriptions.models import Receta
        rid = self.receta.pk
        self.receta.delete()
        self.assertFalse(Receta.objects.filter(pk=rid).exists())        # oculta
        self.assertTrue(Receta.con_eliminados.filter(pk=rid).exists())  # recuperable
        self.assertTrue(Receta.con_eliminados.get(pk=rid).en_papelera)

    def test_restaurar_desde_la_vista(self):
        from prescriptions.models import Receta
        self.receta.delete()
        self.client.login(username="admin", password="test12345")
        self.client.post(f"/papelera/receta/{self.receta.pk}/restaurar/")
        self.assertTrue(Receta.objects.filter(pk=self.receta.pk).exists())

    def test_eliminar_definitivo_desde_la_vista(self):
        from prescriptions.models import Receta
        self.receta.delete()
        self.client.login(username="admin", password="test12345")
        self.client.post(f"/papelera/receta/{self.receta.pk}/eliminar/")
        self.assertFalse(Receta.con_eliminados.filter(pk=self.receta.pk).exists())

    def test_papelera_es_solo_admin(self):
        self.client.login(username="empleado", password="test12345")
        self.assertEqual(self.client.get("/papelera/").status_code, 302)

    def test_papelera_admin_renderiza_con_items(self):
        self.receta.delete()
        self.producto.delete()
        self.client.login(username="admin", password="test12345")
        resp = self.client.get("/papelera/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Papelera")
        self.assertContains(resp, "Recuperar")

    def test_venta_en_papelera_no_toca_stock(self):
        from sales.models import Venta, VentaItem, Vendedor
        venta = Venta.objects.create(estado=Venta.Estado.CONFIRMADA, vendedor=Vendedor.objects.create(nombre="V"))
        VentaItem.objects.create(venta=venta, producto=self.producto, cantidad=3, precio_unitario=1000)
        venta.delete()  # a la papelera
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 7)  # no cambió
        self.assertFalse(Venta.objects.filter(pk=venta.pk).exists())  # oculta de listados/reportes

    def test_eliminar_definitivo_venta_confirmada_devuelve_stock(self):
        from sales.models import Venta, VentaItem, Vendedor
        venta = Venta.objects.create(estado=Venta.Estado.CONFIRMADA, vendedor=Vendedor.objects.create(nombre="V"))
        VentaItem.objects.create(venta=venta, producto=self.producto, cantidad=3, precio_unitario=1000)
        venta.delete()
        venta = Venta.con_eliminados.get(pk=venta.pk)
        venta.eliminar_definitivo()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 10)  # +3 devueltos

    def test_venta_eliminar_view_admin_si_empleado_no(self):
        from sales.models import Venta, Vendedor
        v1 = Venta.objects.create(estado=Venta.Estado.ABIERTA, vendedor=Vendedor.objects.create(nombre="V1"))
        self.client.login(username="empleado", password="test12345")
        self.client.post(f"/ventas/{v1.pk}/eliminar/")
        self.assertTrue(Venta.objects.filter(pk=v1.pk).exists())  # no la borró
        self.client.login(username="admin", password="test12345")
        self.client.post(f"/ventas/{v1.pk}/eliminar/")
        self.assertFalse(Venta.objects.filter(pk=v1.pk).exists())  # a papelera

    def test_purga_elimina_lo_viejo_y_conserva_lo_reciente(self):
        from io import StringIO
        from django.core.management import call_command
        from django.utils import timezone
        import datetime
        from prescriptions.models import Receta

        vieja = Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-01-01")
        vieja.delete()
        Receta.con_eliminados.filter(pk=vieja.pk).update(eliminado_en=timezone.now() - datetime.timedelta(days=10))
        reciente = Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-02-01")
        reciente.delete()  # eliminado_en = ahora

        call_command("vaciar_papelera", stdout=StringIO())  # retención default 7 días
        self.assertFalse(Receta.con_eliminados.filter(pk=vieja.pk).exists())    # purgada
        self.assertTrue(Receta.con_eliminados.filter(pk=reciente.pk).exists())  # sigue

    def test_purga_no_borra_lo_que_sigue_en_uso(self):
        from io import StringIO
        from django.core.management import call_command
        from django.utils import timezone
        import datetime
        from inventory.models import Producto
        from sales.models import Venta, VentaItem, Vendedor

        # Producto borrado hace mucho pero referenciado por una venta (PROTECT).
        venta = Venta.objects.create(vendedor=Vendedor.objects.create(nombre="V"))
        VentaItem.objects.create(venta=venta, producto=self.producto, cantidad=1, precio_unitario=1000)
        self.producto.delete()
        Producto.con_eliminados.filter(pk=self.producto.pk).update(
            eliminado_en=timezone.now() - datetime.timedelta(days=30))

        call_command("vaciar_papelera", stdout=StringIO())
        # No se pudo borrar (en uso): sigue en la papelera, no revienta.
        self.assertTrue(Producto.con_eliminados.filter(pk=self.producto.pk).exists())


class ConfiguracionTests(TestCase):
    """La configuración de la óptica es lo que reemplaza a los datos que antes
    estaban escritos en el código (nombre, contacto, logo, color)."""

    def setUp(self):
        self.cliente = Client()

    def _login(self, admin=False):
        usuario = User.objects.create_user("u", password="x")
        if admin:
            usuario.groups.add(Group.objects.get_or_create(name="Administrador")[0])
        self.cliente.force_login(usuario)
        return usuario

    def test_sin_configurar_devuelve_valores_por_defecto_sin_romper(self):
        self.assertEqual(Configuracion.objects.count(), 0)
        actual = Configuracion.actual()
        self.assertEqual(actual.nombre, "Mi Óptica")
        self.assertEqual(actual.color_primario, Configuracion.COLOR_POR_DEFECTO)

    def test_es_singleton(self):
        Configuracion.objects.create(nombre="Óptica Uno")
        Configuracion.objects.create(nombre="Óptica Dos")
        self.assertEqual(Configuracion.objects.count(), 1)
        self.assertEqual(Configuracion.actual().nombre, "Óptica Dos")

    def test_los_tonos_derivados_son_mas_oscuros_que_el_color_base(self):
        config = Configuracion(color_primario="#58c7da")
        self.assertEqual(config.color_primario_oscuro, "#4aa9b9")
        self.assertEqual(config.color_primario_mas_oscuro, "#3d8b98")

    def test_datos_contacto_omite_los_vacios(self):
        config = Configuracion(direccion="Calle 1", telefono="", email="a@b.com")
        self.assertEqual(config.datos_contacto, ["Calle 1", "a@b.com"])

    def test_nombre_para_icono_cae_al_nombre_largo(self):
        self.assertEqual(Configuracion(nombre="Óptica Sur").nombre_para_icono, "Óptica Sur")
        self.assertEqual(
            Configuracion(nombre="Óptica Sur", nombre_corto="Sur").nombre_para_icono, "Sur"
        )

    def test_el_nombre_configurado_aparece_en_las_pantallas(self):
        Configuracion.objects.create(nombre="Óptica Del Valle")
        self._login()
        respuesta = self.cliente.get("/")
        self.assertContains(respuesta, "Óptica Del Valle")

    def test_solo_admin_puede_editar_la_configuracion(self):
        self._login(admin=False)
        respuesta = self.cliente.get("/configuracion/")
        self.assertRedirects(respuesta, "/")

    def test_admin_guarda_la_configuracion(self):
        self._login(admin=True)
        respuesta = self.cliente.post("/configuracion/", {
            "nombre": "Óptica Norte",
            "nombre_corto": "Norte",
            "direccion": "Av. Siempreviva 742",
            "telefono": "11-2222-3333",
            "email": "hola@opticanorte.com",
            "color_primario": "#aa3366",
            "mensaje_ticket": "¡Gracias!",
            "largo_telefono_local": 6,
            "codigo_pais": "54",
            "prefijo_movil": "9",
        })
        self.assertRedirects(respuesta, "/configuracion/")
        self.assertEqual(Configuracion.actual().nombre, "Óptica Norte")

    def test_rechaza_un_color_invalido(self):
        self._login(admin=True)
        respuesta = self.cliente.post("/configuracion/", {
            "nombre": "Óptica Norte", "color_primario": "rojo",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "#rrggbb")
        self.assertEqual(Configuracion.objects.count(), 0)


class TelefonosConfigurablesTests(TestCase):
    """La característica de la zona y el prefijo internacional salen de la
    configuración, no del código (antes estaban fijos en 3489 / 549)."""

    def test_sin_caracteristica_configurada_el_telefono_queda_igual(self):
        cliente = Cliente.objects.create(nombre="Ana", telefono="511801")
        self.assertEqual(cliente.telefono, "511801")

    def test_con_caracteristica_completa_el_numero_local(self):
        Configuracion.objects.create(caracteristica_telefonica="3489", largo_telefono_local=6)
        cliente = Cliente.objects.create(nombre="Ana", telefono="511801")
        self.assertEqual(cliente.telefono, "3489511801")

    def test_no_toca_numeros_que_ya_estan_completos(self):
        Configuracion.objects.create(caracteristica_telefonica="3489", largo_telefono_local=6)
        cliente = Cliente.objects.create(nombre="Ana", telefono="3489511801")
        self.assertEqual(cliente.telefono, "3489511801")

    def test_whatsapp_usa_el_codigo_de_pais_configurado(self):
        Configuracion.objects.create(codigo_pais="54", prefijo_movil="9")
        cliente = Cliente.objects.create(nombre="Ana", telefono="3489511801")
        self.assertEqual(cliente.whatsapp_url(), "https://wa.me/5493489511801")

    def test_whatsapp_respeta_un_numero_que_ya_trae_el_pais(self):
        Configuracion.objects.create(codigo_pais="54", prefijo_movil="9")
        cliente = Cliente.objects.create(nombre="Ana", telefono="5493489511801")
        self.assertEqual(cliente.whatsapp_url(), "https://wa.me/5493489511801")

    def test_otro_pais_sin_prefijo_movil(self):
        Configuracion.objects.create(codigo_pais="34", prefijo_movil="")
        cliente = Cliente.objects.create(nombre="Ana", telefono="600123456")
        self.assertEqual(cliente.whatsapp_url(), "https://wa.me/34600123456")


class MarcaEnPantallasTests(TestCase):
    """Las pantallas que llevan la marca (PWA, ticket, orden de laboratorio)
    tienen que renderizar con los datos configurados y también sin configurar."""

    def setUp(self):
        self.cliente = Client()
        Configuracion.objects.create(
            nombre="Óptica Del Sur", nombre_corto="Del Sur",
            direccion="San Martín 100", telefono="4444-5555",
            email="hola@delsur.com", color_primario="#aa3366",
        )

    def test_manifest_es_json_valido_con_los_datos_de_la_optica(self):
        datos = json.loads(self.cliente.get("/manifest.json").content)
        self.assertIn("Óptica Del Sur", datos["name"])
        self.assertEqual(datos["short_name"], "Del Sur")
        self.assertEqual(datos["theme_color"], "#aa3366")

    def test_service_worker_usa_el_nombre_configurado(self):
        contenido = self.cliente.get("/sw.js").content.decode()
        self.assertIn("Óptica Del Sur", contenido)

    def test_el_ticket_muestra_nombre_y_datos_de_contacto(self):
        from sales.models import Venta

        usuario = User.objects.create_user("u", password="x")
        self.cliente.force_login(usuario)
        venta = Venta.objects.create(estado=Venta.Estado.CONFIRMADA, total=0)
        respuesta = self.cliente.get(f"/ventas/{venta.id}/ticket/")
        self.assertContains(respuesta, "ÓPTICA DEL SUR")
        self.assertContains(respuesta, "San Martín 100")
        self.assertContains(respuesta, "4444-5555")


class AdminSoloSuperuserTests(TestCase):
    """El panel de administración de Django (/admin-panel/) tiene que ser
    inaccesible para cualquiera que no sea superuser, aunque tenga is_staff."""

    def setUp(self):
        self.cliente = Client()

    def test_superuser_entra(self):
        User.objects.create_superuser("root", password="x")
        self.cliente.force_login(User.objects.get(username="root"))
        respuesta = self.cliente.get("/admin-panel/")
        self.assertEqual(respuesta.status_code, 200)

    def test_staff_no_superuser_no_entra(self):
        usuario = User.objects.create_user("staff", password="x", is_staff=True)
        self.cliente.force_login(usuario)
        respuesta = self.cliente.get("/admin-panel/", follow=True)
        self.assertEqual(respuesta.status_code, 200)  # redirige al login del admin
        self.assertIn("login", respuesta.request["PATH_INFO"])

    def test_usuario_comun_no_entra(self):
        usuario = User.objects.create_user("empleado", password="x")
        self.cliente.force_login(usuario)
        respuesta = self.cliente.get("/admin-panel/", follow=True)
        self.assertIn("login", respuesta.request["PATH_INFO"])
