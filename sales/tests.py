import datetime
from decimal import Decimal

from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.utils import timezone

from customers.models import Cliente
from inventory.models import Categoria, Marca, Producto, Promocion, mejor_promocion_para
from prescriptions.models import Receta
from .models import Venta, VentaItem, Vendedor, Devolucion

PAYLOAD_XSS = '<script>alert("xss")</script>'


class FlujoVentaTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="1000000001", categoria=self.categoria, marca=self.marca, precio=8000, stock_actual=10,
        )
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_escanear_agrega_al_carrito_y_confirmar_descuenta_stock(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})

        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.items.count(), 1)
        self.assertEqual(venta.total, 8000)

        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(self.producto.stock_actual, 9)

    def test_no_se_puede_confirmar_sin_vendedor(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.ABIERTA)  # sigue abierta, no se confirmó

    def test_no_se_puede_vender_mas_stock_del_disponible(self):
        self.producto.stock_actual = 1
        self.producto.save()
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        # segundo escaneo del mismo producto: no debería sumar porque no hay stock
        resp = self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        venta = Venta.objects.get(id=venta_id)
        item = venta.items.get(producto=self.producto)
        self.assertEqual(item.cantidad, 1)

    def test_codigo_inexistente_no_rompe(self):
        venta_id = self._iniciar_venta()
        resp = self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": "no-existe-9999"})
        self.assertEqual(resp.status_code, 200)
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.items.count(), 0)

    def test_confirmar_directo_por_modelo_es_atomico_si_falla(self):
        """Si algo falla durante confirmar(), no debe quedar stock descontado a medias."""
        venta = Venta.objects.create(usuario=self.admin, vendedor=self.vendedor)
        VentaItem.objects.create(venta=venta, producto=self.producto, cantidad=999999, precio_unitario=8000)
        stock_antes = self.producto.stock_actual
        with self.assertRaises(ValidationError):
            venta.confirmar()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, stock_antes)
        self.assertEqual(venta.estado, Venta.Estado.ABIERTA)


class CristalCatalogoTests(TestCase):
    """Los cristales no se escanean: se eligen de una lista y no descuentan stock."""

    def setUp(self):
        self.cat_armazon = Categoria.objects.create(nombre="Armazón Receta", controla_stock=True)
        self.cat_cristal = Categoria.objects.create(
            nombre="Cristal", usa_receta=True, controla_stock=False,
        )
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.armazon = Producto.objects.create(
            codigo_barras="2000000001", categoria=self.cat_armazon, marca=self.marca, precio=8000, stock_actual=5,
        )
        self.cristal = Producto.objects.create(
            codigo_barras="2000000002", categoria=self.cat_cristal,
            marca=Marca.objects.create(nombre="Essilor"),
            modelo="Organico 1.56", precio=15000, stock_actual=0,
        )
        self.cliente = Cliente.objects.create(nombre="Cliente Con Receta")
        self.receta = Receta.objects.create(cliente=self.cliente, fecha_recibido="2026-07-01")
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_escanear_codigo_de_cristal_es_rechazado(self):
        venta_id = self._iniciar_venta()
        resp = self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.cristal.codigo_barras})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.items.count(), 0)
        self.assertIn("no se escanea", resp.content.decode().lower())

    def test_agregar_cristal_desde_catalogo_y_confirmar_no_descuenta_stock(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": self.cliente.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.armazon.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/catalogo/agregar/", {"producto_id": self.cristal.id})

        venta = Venta.objects.get(id=venta_id)
        item_cristal = venta.items.get(producto=self.cristal)
        self.client.post(f"/ventas/{venta_id}/items/{item_cristal.id}/receta/", {"receta_id": self.receta.id})

        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta.refresh_from_db()
        self.armazon.refresh_from_db()
        self.cristal.refresh_from_db()

        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.total, 23000)
        self.assertEqual(self.armazon.stock_actual, 4)  # se descontó
        self.assertEqual(self.cristal.stock_actual, 0)  # no se toca

    def test_confirma_cristal_sin_receta(self):
        # La receta es OPCIONAL aun para cristales / lentes de contacto: puede
        # ser una venta sin aumento, así que confirma sin necesidad de receta.
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/catalogo/agregar/", {"producto_id": self.cristal.id})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)


class ClienteEnVentaTests(TestCase):
    """Ningún dato de cliente debería ser obligatorio para vender."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Sol")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="5000000001", categoria=self.categoria, marca=self.marca, precio=8000, stock_actual=5,
        )
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_venta_sin_ningun_dato_de_cliente_se_puede_hacer(self):
        venta_id = self._iniciar_venta()
        vendedor = Vendedor.objects.create(nombre="V")
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        resp = self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertIsNone(venta.cliente)

    def test_alta_rapida_de_cliente_solo_con_mail(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/nuevo-rapido/", {
            "nombre": "", "dni": "", "telefono": "", "email": "sol@ejemplo.com", "direccion": "",
        })
        venta = Venta.objects.get(id=venta_id)
        self.assertIsNotNone(venta.cliente)
        self.assertEqual(venta.cliente.email, "sol@ejemplo.com")
        self.assertEqual(venta.cliente.nombre, "")

    def test_alta_rapida_de_cliente_completa(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/nuevo-rapido/", {
            "nombre": "Ana Gómez", "dni": "30555444", "telefono": "1122334455",
            "email": "ana@ejemplo.com", "direccion": "Calle Falsa 123",
        })
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.cliente.nombre, "Ana Gómez")
        self.assertEqual(venta.cliente.dni, "30555444")

    def test_email_rapido_sin_cliente_previo_crea_uno_nuevo(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/email-rapido/", {"email": "rapido@ejemplo.com"})
        venta = Venta.objects.get(id=venta_id)
        self.assertIsNotNone(venta.cliente)
        self.assertEqual(venta.cliente.email, "rapido@ejemplo.com")
        self.assertEqual(venta.cliente.nombre, "")

    def test_email_rapido_con_cliente_ya_elegido_solo_actualiza_el_mail(self):
        cliente = Cliente.objects.create(nombre="Cliente Existente")
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": cliente.id})
        self.client.post(f"/ventas/{venta_id}/cliente/email-rapido/", {"email": "existente@ejemplo.com"})
        cliente.refresh_from_db()
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.cliente_id, cliente.id)  # sigue siendo el mismo cliente
        self.assertEqual(cliente.email, "existente@ejemplo.com")

    def test_email_rapido_vacio_no_hace_nada(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/email-rapido/", {"email": ""})
        venta = Venta.objects.get(id=venta_id)
        self.assertIsNone(venta.cliente)


class PromocionTests(TestCase):
    def setUp(self):
        self.categoria_sol = Categoria.objects.create(nombre="Armazón Sol")
        self.categoria_receta = Categoria.objects.create(nombre="Armazón Receta")
        self.producto_sol = Producto.objects.create(
            codigo_barras="6000000001", categoria=self.categoria_sol,
            marca=Marca.objects.create(nombre="Ray-Ban"), precio=10000,
        )
        self.producto_receta = Producto.objects.create(
            codigo_barras="6000000002", categoria=self.categoria_receta,
            marca=Marca.objects.create(nombre="Otra Marca"), precio=8000,
        )
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_promocion_sin_alcance_no_aplica_a_nada(self):
        """Una promo sin categoría/marca/producto definido NO aplica a nada,
        para evitar descuentos 'fantasma' (ver Promocion.aplica_a)."""
        promo = Promocion.objects.create(
            nombre="Sin alcance", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=10,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        )
        self.assertFalse(promo.aplica_a(self.producto_sol))
        self.assertFalse(promo.aplica_a(self.producto_receta))
        # El cálculo del descuento en sí sigue siendo correcto.
        self.assertEqual(promo.precio_con_descuento(10000), 9000)

    def test_promocion_por_categoria_no_afecta_otras_categorias(self):
        promo = Promocion.objects.create(
            nombre="Sol 20%", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=20,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        )
        promo.categorias.add(self.categoria_sol)
        self.assertTrue(promo.aplica_a(self.producto_sol))
        self.assertFalse(promo.aplica_a(self.producto_receta))

    def test_promocion_por_marca(self):
        promo = Promocion.objects.create(
            nombre="Ray-Ban 15%", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=15,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1), marcas="Ray-Ban, Oakley",
        )
        self.assertTrue(promo.aplica_a(self.producto_sol))
        self.assertFalse(promo.aplica_a(self.producto_receta))

    def test_promocion_vencida_no_esta_vigente(self):
        promo = Promocion.objects.create(
            nombre="Vieja", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=50,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=30),
            fecha_fin=timezone.localdate() - datetime.timedelta(days=1),
        )
        self.assertFalse(promo.esta_vigente())

    def test_promocion_inactiva_no_esta_vigente(self):
        promo = Promocion.objects.create(
            nombre="Inactiva", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=50,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1), activa=False,
        )
        self.assertFalse(promo.esta_vigente())

    def test_mejor_promocion_elige_el_mayor_descuento(self):
        Promocion.objects.create(
            nombre="10%", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=10,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        ).categorias.add(self.categoria_sol)
        Promocion.objects.create(
            nombre="30%", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=30,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        ).categorias.add(self.categoria_sol)
        promo, precio_final = mejor_promocion_para(self.producto_sol)
        self.assertEqual(promo.nombre, "30%")
        self.assertEqual(precio_final, 7000)

    def test_escanear_aplica_promocion_automaticamente(self):
        Promocion.objects.create(
            nombre="Sol 20%", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=20,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        ).categorias.add(self.categoria_sol)
        self.producto_sol.stock_actual = 5
        self.producto_sol.save()

        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto_sol.codigo_barras})

        venta = Venta.objects.get(id=venta_id)
        item = venta.items.get(producto=self.producto_sol)
        self.assertEqual(item.precio_unitario, 8000)  # 10000 - 20%
        self.assertIsNotNone(item.promocion)

    def test_admin_only_para_crear_promocion(self):
        self.client.logout()
        empleado = User.objects.create_user("empleado", password="test12345")
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name="Empleado")
        empleado.groups.add(Group.objects.get(name="Empleado"))
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/inventario/promociones/nueva/")
        self.assertEqual(resp.status_code, 302)


class DevolucionTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta", controla_stock=True)
        self.categoria_cristal = Categoria.objects.create(nombre="Cristal", controla_stock=False)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="7000000001", categoria=self.categoria, marca=self.marca, precio=8000, stock_actual=5,
        )
        self.cristal = Producto.objects.create(
            codigo_barras="7000000002", categoria=self.categoria_cristal, marca=self.marca, precio=15000, stock_actual=0,
        )
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_devolucion_de_producto_con_stock_lo_reingresa(self):
        self.client.post("/ventas/devoluciones/registrar/", {
            "codigo": self.producto.codigo_barras, "cantidad": 2, "motivo": "Talle incorrecto",
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, 7)
        self.assertEqual(Devolucion.objects.count(), 1)
        d = Devolucion.objects.first()
        self.assertEqual(d.monto, 16000)
        self.assertEqual(d.motivo, "Talle incorrecto")

    def test_devolucion_de_cristal_no_genera_movimiento_de_stock(self):
        from inventory.models import MovimientoStock
        self.client.post("/ventas/devoluciones/registrar/", {
            "codigo": self.cristal.codigo_barras, "cantidad": 1, "motivo": "",
        })
        self.cristal.refresh_from_db()
        self.assertEqual(self.cristal.stock_actual, 0)
        self.assertEqual(Devolucion.objects.count(), 1)
        self.assertEqual(MovimientoStock.objects.filter(producto=self.cristal).count(), 0)

    def test_devolucion_codigo_inexistente(self):
        resp = self.client.post("/ventas/devoluciones/registrar/", {"codigo": "no-existe", "cantidad": 1})
        self.assertIn("no se encontr", resp.content.decode().lower())
        self.assertEqual(Devolucion.objects.count(), 0)

    def test_empleado_puede_registrar_devolucion_pero_no_ver_el_listado(self):
        self.client.logout()
        empleado = User.objects.create_user("empleado", password="test12345")
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name="Empleado")
        empleado.groups.add(Group.objects.get(name="Empleado"))
        self.client.login(username="empleado", password="test12345")

        resp = self.client.post("/ventas/devoluciones/registrar/", {
            "codigo": self.producto.codigo_barras, "cantidad": 1, "motivo": "",
        })
        self.assertEqual(Devolucion.objects.count(), 1)

        resp = self.client.get("/ventas/devoluciones/")
        self.assertEqual(resp.status_code, 302)  # listado es admin-only


class DashboardTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.producto = Producto.objects.create(
            codigo_barras="8000000001", categoria=self.categoria,
            marca=Marca.objects.create(nombre="TestMarca"), precio=10000, stock_actual=10,
        )
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Dashboard")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _hacer_una_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")

    def test_dashboard_sin_ventas_no_rompe(self):
        resp = self.client.get("/ventas/dashboard/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No hay ventas confirmadas", resp.content.decode())

    def test_dashboard_con_ventas_muestra_totales(self):
        self._hacer_una_venta()
        resp = self.client.get("/ventas/dashboard/")
        html = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("10000", html.replace(",", ""))
        self.assertIn("Vendedora Dashboard", html)
        self.assertIn("TestMarca", html)

    def test_empleado_no_accede_al_dashboard(self):
        self.client.logout()
        empleado = User.objects.create_user("empleado", password="test12345")
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name="Empleado")
        empleado.groups.add(Group.objects.get(name="Empleado"))
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/ventas/dashboard/")
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_no_permite_html_injection_via_nombre_vendedor(self):
        vendedor_malicioso = Vendedor.objects.create(nombre='<script>alert("x")</script>')
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": vendedor_malicioso.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        resp = self.client.get("/ventas/dashboard/")
        # Va dentro de un json_script, así que no debe aparecer un <script> real inyectado
        self.assertNotIn('<script>alert', resp.content.decode())

    def test_estadisticas_de_recetas_por_periodo(self):
        from customers.models import Cliente, ObraSocial
        from prescriptions.models import Medico, Receta

        cli = Cliente.objects.create(nombre="Ana", apellido="Test")
        dr_house = Medico.objects.create(nombre="Dr. House")
        osde, _ = ObraSocial.objects.get_or_create(nombre="OSDE")
        # Dentro del período (default: últimos 12 meses).
        Receta.objects.create(cliente=cli, fecha_recibido=timezone.localdate(), medico=dr_house,
                              es_lentes_contacto=True, marca_lentes_contacto="Acuvue", obra_social=osde)
        Receta.objects.create(cliente=cli, fecha_recibido=timezone.localdate(), medico=dr_house,
                              es_lentes_contacto=False)
        # Fuera del período: no debe contar.
        Receta.objects.create(cliente=cli, fecha_recibido=timezone.localdate() - datetime.timedelta(days=800),
                              medico=Medico.objects.create(nombre="Dr. Viejo"))

        resp = self.client.get("/ventas/dashboard/")
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual(ctx["total_recetas_periodo"], 2)  # la vieja queda afuera
        self.assertEqual(dict(zip(ctx["labels_medico"], ctx["data_medico"])).get("Dr. House"), 2)
        self.assertEqual(ctx["data_lentes_contacto"], [1, 1])  # [con LC, sin LC]
        self.assertEqual(dict(zip(ctx["labels_marca_lc"], ctx["data_marca_lc"])).get("Acuvue"), 1)
        self.assertEqual(dict(zip(ctx["labels_obra_social"], ctx["data_obra_social"])).get("OSDE"), 1)
        # El gráfico de entregadas/pendientes ya no existe.
        self.assertNotContains(resp, "chart-recetas-estado")

    def test_periodo_de_recetas_es_independiente_del_de_ventas(self):
        from customers.models import Cliente
        from prescriptions.models import Receta

        cli = Cliente.objects.create(nombre="Ana", apellido="Test")
        Receta.objects.create(cliente=cli, fecha_recibido=datetime.date(2024, 3, 15))
        # Filtro de recetas a marzo 2024; el de ventas queda en su default.
        resp = self.client.get("/ventas/dashboard/?rdesde=2024-03-01&rhasta=2024-03-31")
        self.assertEqual(resp.context["total_recetas_periodo"], 1)
        resp2 = self.client.get("/ventas/dashboard/?rdesde=2024-04-01&rhasta=2024-04-30")
        self.assertEqual(resp2.context["total_recetas_periodo"], 0)


class RevisionGeneralTests(TestCase):
    """Tests de los arreglos de la revisión general de la aplicación."""

    def setUp(self):
        Group.objects.get_or_create(name="Empleado")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.empleado.groups.add(Group.objects.get(name="Empleado"))
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9100000001", categoria=self.categoria, marca=self.marca, precio=5000, stock_actual=10,
        )

    def test_empleado_no_staff_puede_iniciar_sesion_por_el_formulario_real(self):
        """El login del admin de Django rechaza usuarios no-staff; la pantalla
        propia de /accounts/login/ tiene que aceptarlos."""
        resp = self.client.get("/accounts/login/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post("/accounts/login/", {"username": "empleado", "password": "test12345"}, follow=True)
        self.assertTrue(resp.context["user"].is_authenticated)

    def test_logout_por_post_funciona(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.post("/accounts/logout/", follow=True)
        self.assertFalse(resp.context["user"].is_authenticated)

    def test_confirmar_devuelve_partial_sin_html_completo(self):
        """El resultado de confirmar se inserta en un div: no puede ser una
        página completa con <html>/navbar adentro."""
        self.client.login(username="admin", password="test12345")
        vendedor = Vendedor.objects.create(nombre="V")
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        resp = self.client.post(f"/ventas/{venta_id}/confirmar/")
        html = resp.content.decode()
        self.assertNotIn("<html", html)
        self.assertNotIn("navbar", html)
        self.assertIn("confirmada", html)

    def test_ventas_vacias_abandonadas_se_limpian(self):
        self.client.login(username="admin", password="test12345")
        for _ in range(3):
            self.client.get("/ventas/nueva/")
        # Las dos primeras quedaron vacías y deben haberse limpiado: queda solo 1 abierta
        self.assertEqual(Venta.objects.filter(estado=Venta.Estado.ABIERTA).count(), 1)

    def test_cancelar_venta_abierta_la_elimina(self):
        self.client.login(username="admin", password="test12345")
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/cancelar/")
        self.assertFalse(Venta.objects.filter(pk=venta_id).exists())

    def test_ingreso_con_cantidad_negativa_es_rechazado(self):
        self.client.login(username="admin", password="test12345")
        stock_antes = self.producto.stock_actual
        resp = self.client.post("/inventario/ingreso-rapido/registrar/", {
            "codigo": self.producto.codigo_barras, "cantidad": "-5",
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock_actual, stock_antes)
        self.assertIn("1 o más", resp.content.decode())

    def test_devolucion_con_cantidad_negativa_es_rechazada(self):
        self.client.login(username="admin", password="test12345")
        resp = self.client.post("/ventas/devoluciones/registrar/", {
            "codigo": self.producto.codigo_barras, "cantidad": "-3",
        })
        self.assertEqual(Devolucion.objects.count(), 0)

    def test_movimientos_e_historial_son_admin_only(self):
        self.client.login(username="empleado", password="test12345")
        self.assertEqual(self.client.get("/inventario/movimientos/").status_code, 302)
        self.assertEqual(self.client.get("/ventas/historial/").status_code, 302)
        self.client.login(username="admin", password="test12345")
        self.assertEqual(self.client.get("/inventario/movimientos/").status_code, 200)
        self.assertEqual(self.client.get("/ventas/historial/").status_code, 200)

    def test_buscador_de_clientes_encuentra_por_email(self):
        Cliente.objects.create(email="solo-mail@ejemplo.com")
        self.client.login(username="admin", password="test12345")
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        resp = self.client.get(f"/ventas/{venta_id}/clientes/buscar/", {"q": "solo-mail"})
        data = resp.json()
        self.assertEqual(len(data["resultados"]), 1)
        self.assertEqual(data["resultados"][0]["email"], "solo-mail@ejemplo.com")


class SeguridadVentaTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.producto = Producto.objects.create(
            codigo_barras="3000000001", categoria=self.categoria,
            marca=Marca.objects.create(nombre=PAYLOAD_XSS), precio=8000, stock_actual=5,
        )
        self.cliente = Cliente.objects.create(nombre=PAYLOAD_XSS)
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_nombre_de_producto_y_cliente_con_html_quedan_escapados_en_el_carrito(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": self.cliente.id})
        resp = self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        html = resp.content.decode()
        self.assertNotIn(PAYLOAD_XSS, html)
        self.assertIn("&lt;script&gt;", html)

    def test_busqueda_de_cliente_devuelve_json_sin_ejecutar_html(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        venta_id = resp.redirect_chain[-1][0].strip("/").split("/")[-1]
        resp = self.client.get(f"/ventas/{venta_id}/clientes/buscar/", {"q": "script"})
        # Es JSON: el navegador nunca lo interpreta como HTML directamente.
        self.assertEqual(resp["Content-Type"], "application/json")
        data = resp.json()
        # El texto crudo puede venir en el JSON (es dato, no maquetado);
        # lo que importa es que el frontend lo inserte con textContent, no
        # que el JSON en sí estÊ escapado.
        self.assertTrue(any(PAYLOAD_XSS in r["nombre"] for r in data["resultados"]))


class CSRFTests(TestCase):
    """Usamos un client con enforce_csrf_checks=True para confirmar que las
    vistas que cambian datos (POST) están protegidas contra CSRF."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="4000000001", categoria=self.categoria, marca=self.marca, precio=8000, stock_actual=5,
        )
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.csrf_client.login(username="admin", password="test12345")

    def test_post_sin_csrf_token_es_rechazado(self):
        venta = Venta.objects.create(usuario=self.admin)
        resp = self.csrf_client.post(f"/ventas/{venta.id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.assertEqual(resp.status_code, 403)


class PermisosVentaTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name="Administrador")
        Group.objects.get_or_create(name="Empleado")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.empleado.groups.add(Group.objects.get(name="Empleado"))
        self.vendedor = Vendedor.objects.create(nombre="Test")

    def test_empleado_puede_vender(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/ventas/nueva/")
        self.assertEqual(resp.status_code, 302)  # redirige al POS, no rechazado

    def test_empleado_no_puede_gestionar_vendedores(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/ventas/vendedores/nuevo/")
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post("/ventas/vendedores/nuevo/", {"nombre": "Intento Colado", "activo": "on"})
        self.assertFalse(Vendedor.objects.filter(nombre="Intento Colado").exists())

    def test_admin_puede_gestionar_vendedores(self):
        self.client.login(username="admin", password="test12345")
        resp = self.client.post("/ventas/vendedores/nuevo/", {"nombre": "Nueva Vendedora", "activo": "on"})
        self.assertTrue(Vendedor.objects.filter(nombre="Nueva Vendedora").exists())


class SaldoYSenaTests(TestCase):
    """Seña y saldo: confirmar con un monto menor al total deja saldo
    pendiente, y registrar el pago del saldo lo cancela."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9500000001", categoria=self.categoria, marca=self.marca,
            precio=10000, stock_actual=5,
        )
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")

    def _venta_confirmable(self, cantidad=1):
        venta = Venta.objects.create(vendedor=self.vendedor, forma_pago=Venta.FormaPago.EFECTIVO)
        VentaItem.objects.create(
            venta=venta, producto=self.producto, cantidad=cantidad,
            precio_unitario=self.producto.precio,
        )
        return venta

    def test_confirmar_sin_monto_paga_el_total(self):
        venta = self._venta_confirmable()
        venta.confirmar()
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.monto_pagado, 10000)
        self.assertEqual(venta.saldo_pendiente, 0)

    def test_confirmar_con_sena_deja_saldo_pendiente(self):
        venta = self._venta_confirmable()
        venta.confirmar(monto_pagado=Decimal("3000"))
        self.assertEqual(venta.monto_pagado, 3000)
        self.assertEqual(venta.saldo_pendiente, 7000)

    def test_registrar_pago_del_saldo_lo_cancela(self):
        venta = self._venta_confirmable()
        venta.confirmar(monto_pagado=Decimal("3000"))
        venta.registrar_pago_y_entrega(
            monto_adicional=Decimal("7000"),
            forma_pago_saldo=Venta.FormaPago.TARJETA, cuotas_saldo=3,
        )
        self.assertEqual(venta.monto_pagado, 10000)
        self.assertEqual(venta.saldo_pendiente, 0)
        self.assertEqual(venta.forma_pago_saldo, Venta.FormaPago.TARJETA)
        self.assertEqual(venta.cuotas_saldo, 3)


class DescuentoManualTests(TestCase):
    """El descuento manual sobre el total de la venta (porcentaje o monto
    fijo) se aplica bien y nunca deja el total negativo."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9500000002", categoria=self.categoria, marca=self.marca,
            precio=10000, stock_actual=5,
        )

    def _venta_con_subtotal_10000(self):
        venta = Venta.objects.create()
        VentaItem.objects.create(
            venta=venta, producto=self.producto, cantidad=1, precio_unitario=Decimal("10000"),
        )
        return venta

    def test_descuento_por_porcentaje(self):
        venta = self._venta_con_subtotal_10000()
        venta.descuento_manual_tipo = Venta.TipoDescuentoManual.PORCENTAJE
        venta.descuento_manual_valor = Decimal("10")
        venta.recalcular_total()
        self.assertEqual(venta.total, 9000)

    def test_descuento_por_monto_fijo(self):
        venta = self._venta_con_subtotal_10000()
        venta.descuento_manual_tipo = Venta.TipoDescuentoManual.MONTO_FIJO
        venta.descuento_manual_valor = Decimal("2500")
        venta.recalcular_total()
        self.assertEqual(venta.total, 7500)

    def test_descuento_no_puede_dejar_total_negativo(self):
        venta = self._venta_con_subtotal_10000()
        venta.descuento_manual_tipo = Venta.TipoDescuentoManual.MONTO_FIJO
        venta.descuento_manual_valor = Decimal("999999")
        venta.recalcular_total()
        self.assertEqual(venta.total, 0)

    def test_sin_descuento_el_total_es_el_subtotal(self):
        venta = self._venta_con_subtotal_10000()
        venta.recalcular_total()
        self.assertEqual(venta.total, 10000)


class Promo2x1Tests(TestCase):
    """El 2x1 se cobra por cantidad (cada 2 unidades se cobra 1, la unidad
    suelta se cobra entera); el precio unitario del catálogo no cambia."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Sol", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9500000003", categoria=self.categoria, marca=self.marca,
            precio=5000, stock_actual=10,
        )
        self.promo_2x1 = Promocion.objects.create(
            nombre="2x1", tipo_descuento=Promocion.TipoDescuento.DOS_POR_UNO, valor=0,
            fecha_inicio=timezone.localdate() - datetime.timedelta(days=1),
        )

    def _item(self, cantidad):
        venta = Venta.objects.create()
        return VentaItem.objects.create(
            venta=venta, producto=self.producto, cantidad=cantidad,
            precio_unitario=Decimal("5000"), promocion=self.promo_2x1,
        )

    def test_2x1_cantidad_par_cobra_la_mitad(self):
        self.assertEqual(self._item(cantidad=2).subtotal, 5000)  # paga 1 de 2

    def test_2x1_cantidad_impar_cobra_la_mitad_mas_una(self):
        self.assertEqual(self._item(cantidad=3).subtotal, 10000)  # paga 2 de 3

    def test_2x1_no_cambia_el_precio_unitario(self):
        self.assertEqual(self.promo_2x1.precio_con_descuento(5000), 5000)


class EntregaParcialTests(TestCase):
    """La entrega se controla por ítem: la venta figura 'entregada' solo si
    TODOS sus ítems se entregaron (ej: el armazón se lo lleva hoy, el cristal
    a medida lo retira cuando vuelve del laboratorio)."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9500000004", categoria=self.categoria, marca=self.marca,
            precio=5000, stock_actual=10,
        )
        self.venta = Venta.objects.create()

    def _item(self, entregado=True):
        return VentaItem.objects.create(
            venta=self.venta, producto=self.producto, cantidad=1,
            precio_unitario=Decimal("5000"), entregado=entregado,
        )

    def test_todos_los_items_entregados(self):
        self._item(entregado=True)
        self.assertTrue(self.venta.entregado)
        self.assertEqual(self.venta.estado_entrega, "entregado")

    def test_un_item_sin_entregar_deja_la_venta_pendiente(self):
        self._item(entregado=True)
        self._item(entregado=False)
        self.assertFalse(self.venta.entregado)
        self.assertEqual(self.venta.estado_entrega, "pendiente")

    def test_pendiente_pero_notificado(self):
        self._item(entregado=False)
        self.venta.notificado = True
        self.assertEqual(self.venta.estado_entrega, "notificado")


class IncidenciaTests(TestCase):
    """registrar_incidencia marca la venta para revisar y acumula el detalle."""

    def test_registrar_incidencia_marca_la_venta_y_guarda_el_detalle(self):
        venta = Venta.objects.create()
        venta.registrar_incidencia("Se forzó stock insuficiente")
        self.assertTrue(venta.tiene_incidencias)
        self.assertIn("Se forzó stock insuficiente", venta.incidencias_detalle)

    def test_las_incidencias_se_acumulan(self):
        venta = Venta.objects.create()
        venta.registrar_incidencia("Primera")
        venta.registrar_incidencia("Segunda")
        self.assertIn("Primera", venta.incidencias_detalle)
        self.assertIn("Segunda", venta.incidencias_detalle)


class VendedorSinDuplicadosTests(TestCase):
    """No se deben poder crear dos vendedores con el mismo nombre (así no se
    acumulan duplicados que después no se pueden borrar por estar en uso)."""

    def test_form_rechaza_nombre_repetido_ignorando_mayusculas(self):
        from .forms import VendedorForm
        Vendedor.objects.create(nombre="Guille")
        form = VendedorForm(data={"nombre": "  guille ", "activo": True})
        self.assertFalse(form.is_valid())
        self.assertIn("nombre", form.errors)

    def test_form_permite_editar_el_mismo_vendedor(self):
        from .forms import VendedorForm
        guille = Vendedor.objects.create(nombre="Guille")
        form = VendedorForm(data={"nombre": "Guille", "activo": False}, instance=guille)
        self.assertTrue(form.is_valid())

    def test_form_acepta_nombre_distinto(self):
        from .forms import VendedorForm
        Vendedor.objects.create(nombre="Guille")
        form = VendedorForm(data={"nombre": "Agos", "activo": True})
        self.assertTrue(form.is_valid())

    def test_constraint_en_la_base_bloquea_duplicado_case_insensitive(self):
        from django.db import IntegrityError, transaction
        Vendedor.objects.create(nombre="Guille")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vendedor.objects.create(nombre="guille")


class ItemExpressYPrecioAManoTests(TestCase):
    """Vender sin relevamiento de stock: se crea un producto express al vuelo
    (marca/modelo + precio) y el precio de cualquier ítem se puede editar."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Sol", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="9000000001", categoria=self.categoria, marca=self.marca,
            precio=8000, stock_actual=5,
        )
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_express_crea_producto_pendiente_sin_stock_y_lo_agrega(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {
            "descripcion": "Armazón Vulk negro", "precio": "45000", "cantidad": "1", "marca": "Vulk",
        })
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.items.count(), 1)
        item = venta.items.get()
        self.assertEqual(item.precio_unitario, Decimal("45000"))
        self.assertEqual(item.producto.modelo, "Armazón Vulk negro")
        self.assertEqual(item.producto.marca.nombre, "Vulk")
        self.assertEqual(item.producto.stock_actual, 0)
        # La categoría del express no controla stock ni requiere receta.
        self.assertFalse(item.producto.categoria.controla_stock)
        self.assertFalse(item.producto.categoria.usa_receta)
        self.assertEqual(venta.total, Decimal("45000"))

    def test_express_sin_marca_usa_placeholder(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {
            "descripcion": "Estuche", "precio": "3000",
        })
        item = Venta.objects.get(id=venta_id).items.get()
        self.assertEqual(item.producto.marca.nombre, "Sin marca")

    def test_express_reusa_marca_existente_ignorando_mayusculas(self):
        # Antes rompía: tipear una marca que ya existe con otra combinación de
        # mayúsculas violaba el índice único case-insensitive de Marca.
        Marca.objects.create(nombre="Vulk")
        venta_id = self._iniciar_venta()
        resp = self.client.post(f"/ventas/{venta_id}/express/agregar/", {
            "descripcion": "Armazón suelto", "precio": "1000", "marca": "vulk",
        })
        self.assertEqual(resp.status_code, 200)
        item = Venta.objects.get(id=venta_id).items.get()
        self.assertEqual(item.producto.marca.nombre, "Vulk")  # reusó la existente
        self.assertEqual(Marca.objects.filter(nombre__iexact="vulk").count(), 1)

    def test_express_sin_descripcion_o_precio_no_agrega_nada(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {"descripcion": "", "precio": "1000"})
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {"descripcion": "Algo", "precio": "abc"})
        self.assertEqual(Venta.objects.get(id=venta_id).items.count(), 0)

    def test_express_se_puede_confirmar_sin_stock_ni_receta(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {"descripcion": "Armazón suelto", "precio": "50000"})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/")
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.total, Decimal("50000"))

    def test_dos_express_no_reusan_el_mismo_producto(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {"descripcion": "Armazón A", "precio": "1000"})
        self.client.post(f"/ventas/{venta_id}/express/agregar/", {"descripcion": "Armazón B", "precio": "2000"})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.items.count(), 2)
        self.assertEqual(venta.total, Decimal("3000"))

    def test_precio_a_mano_sobre_producto_de_catalogo(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        venta = Venta.objects.get(id=venta_id)
        item = venta.items.get()
        self.assertEqual(item.precio_unitario, Decimal("8000"))
        self.client.post(f"/ventas/{venta_id}/items/{item.id}/precio/", {"precio": "12500"})
        item.refresh_from_db()
        venta.refresh_from_db()
        self.assertEqual(item.precio_unitario, Decimal("12500"))
        self.assertEqual(venta.total, Decimal("12500"))
        # El precio del catálogo NO cambia: solo el de esta línea.
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio, Decimal("8000"))

    def test_precio_a_mano_limpia_la_promocion(self):
        promo = Promocion.objects.create(
            nombre="10% Sol", tipo_descuento=Promocion.TipoDescuento.PORCENTAJE, valor=10,
            fecha_inicio=timezone.localdate(),
        )
        promo.categorias.add(self.categoria)
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        item = Venta.objects.get(id=venta_id).items.get()
        self.assertEqual(item.promocion_id, promo.id)  # entró con la promo
        self.client.post(f"/ventas/{venta_id}/items/{item.id}/precio/", {"precio": "5000"})
        item.refresh_from_db()
        self.assertIsNone(item.promocion_id)  # el precio a mano la reemplaza
        self.assertEqual(item.precio_unitario, Decimal("5000"))

    def test_precio_a_mano_invalido_no_cambia_nada(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        item = Venta.objects.get(id=venta_id).items.get()
        self.client.post(f"/ventas/{venta_id}/items/{item.id}/precio/", {"precio": "-99"})
        item.refresh_from_db()
        self.assertEqual(item.precio_unitario, Decimal("8000"))


class VentaObraSocialTests(TestCase):
    """Venta por obra social: se elige cuál obra social se usa y el cliente
    puede abonar una parte (o nada) en el momento."""

    def setUp(self):
        from customers.models import ObraSocial
        self.categoria = Categoria.objects.create(nombre="Armazón Receta OS", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="7000000001", categoria=self.categoria, marca=self.marca,
            precio=10000, stock_actual=10,
        )
        self.osde = ObraSocial.objects.create(nombre="OSDE Test")
        self.cliente = Cliente.objects.create(nombre="Con", apellido="Cobertura", obra_social=self.osde)
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_la_lista_estandar_quedo_sembrada_por_la_migracion(self):
        from customers.models import ObraSocial
        # Además de la de este test, las ~20 de la migración de datos.
        self.assertGreaterEqual(ObraSocial.objects.count(), 20)

    def test_marcar_obra_social_preselecciona_la_del_cliente(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": self.cliente.id})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        venta = Venta.objects.get(id=venta_id)
        self.assertTrue(venta.es_obra_social)
        self.assertEqual(venta.obra_social_id, self.osde.id)

    def test_desmarcar_limpia_la_obra_social(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": self.cliente.id})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "0"})
        venta = Venta.objects.get(id=venta_id)
        self.assertFalse(venta.es_obra_social)
        self.assertIsNone(venta.obra_social_id)

    def test_elegir_otra_obra_social_a_mano(self):
        from customers.models import ObraSocial
        otra = ObraSocial.objects.create(nombre="Swiss Test")
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        self.client.post(f"/ventas/{venta_id}/obra-social/cual/", {"obra_social_id": otra.id})
        self.assertEqual(Venta.objects.get(id=venta_id).obra_social_id, otra.id)

    def test_obra_social_sin_pago_confirma_sin_forma_de_pago(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        self.client.post(f"/ventas/{venta_id}/confirmar/", {"monto_pagado": "0"})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.monto_pagado, 0)
        self.assertEqual(venta.saldo_pendiente, Decimal("10000"))  # todo pendiente de la OS

    def test_obra_social_con_pago_parcial_requiere_forma_de_pago(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        # Abona una parte pero sin forma de pago: no se confirma.
        self.client.post(f"/ventas/{venta_id}/confirmar/", {"monto_pagado": "3000"})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.ABIERTA)

    def test_obra_social_con_pago_parcial_y_forma_de_pago_confirma(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/obra-social/", {"es_obra_social": "1"})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        self.client.post(f"/ventas/{venta_id}/confirmar/", {"monto_pagado": "3000"})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.monto_pagado, Decimal("3000"))
        self.assertEqual(venta.saldo_pendiente, Decimal("7000"))
        # Queda en la cola de obra social, sin resolver.
        self.assertTrue(venta.es_obra_social)
        self.assertFalse(venta.obra_social_resuelta)

    def test_elegir_cliente_con_obra_social_la_precarga_en_la_venta(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/cliente/", {"cliente_id": self.cliente.id})
        # Sin marcar es_obra_social todavía, pero la obra social ya quedó lista.
        self.assertEqual(Venta.objects.get(id=venta_id).obra_social_id, self.osde.id)


class PrecioAlAgregarYTopePagoTests(TestCase):
    """El precio se confirma al agregar el artículo (no en el carrito), y el
    pago nunca supera el total."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Sol Precio", controla_stock=True)
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="6000000001", categoria=self.categoria, marca=self.marca,
            precio=10000, stock_actual=10,
        )
        self.vendedor = Vendedor.objects.create(nombre="Vendedora Test")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def _iniciar_venta(self):
        resp = self.client.get("/ventas/nueva/", follow=True)
        return resp.redirect_chain[-1][0].strip("/").split("/")[-1]

    def test_catalogo_agrega_con_precio_confirmado_y_cantidad(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/catalogo/agregar/", {
            "producto_id": self.producto.id, "precio": "12500", "cantidad": "2",
        })
        item = Venta.objects.get(id=venta_id).items.get()
        self.assertEqual(item.precio_unitario, Decimal("12500"))
        self.assertEqual(item.cantidad, 2)
        # El precio del catálogo no cambió: solo la línea.
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.precio, Decimal("10000"))

    def test_escanear_agrega_con_precio_confirmado(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/escanear/", {
            "codigo": self.producto.codigo_barras, "cantidad": "1", "precio": "9000",
        })
        item = Venta.objects.get(id=venta_id).items.get()
        self.assertEqual(item.precio_unitario, Decimal("9000"))

    def test_no_se_registra_pago_mayor_al_total(self):
        venta_id = self._iniciar_venta()
        self.client.post(f"/ventas/{venta_id}/vendedor/", {"vendedor_id": self.vendedor.id})
        self.client.post(f"/ventas/{venta_id}/escanear/", {"codigo": self.producto.codigo_barras})
        self.client.post(f"/ventas/{venta_id}/forma-pago/", {"forma_pago": "EFE"})
        # Intenta abonar más que el total: se topea al total (sin saldo a favor).
        self.client.post(f"/ventas/{venta_id}/confirmar/", {"monto_pagado": "999999"})
        venta = Venta.objects.get(id=venta_id)
        self.assertEqual(venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(venta.monto_pagado, Decimal("10000"))
        self.assertEqual(venta.saldo_pendiente, 0)


class ConfigurarUsuariosTests(TestCase):
    """El comando arma los roles con los usuarios que le pasan por parámetro:
    típicamente un usuario compartido para el mostrador (rol Empleado) y
    usuarios propios para quienes administran. Sin nombres fijos en el código."""

    def _correr(self, *args):
        from io import StringIO

        from django.core.management import call_command

        call_command("configurar_usuarios", *args, stdout=StringIO())

    def _correr_caso_tipico(self):
        self._correr(
            "--empleado", "mostrador",
            "--admin", "guille",
            "--vincular", "Vero=mostrador",
            "--vincular", "Patri=mostrador",
            "--vincular", "Guille=guille",
        )

    def test_crea_roles_usuarios_y_vincula_vendedores(self):
        from stockero.permissions import es_administrador

        Vendedor.objects.create(nombre="Vero")
        Vendedor.objects.create(nombre="Patri")
        Vendedor.objects.create(nombre="Guille")
        self._correr_caso_tipico()

        empleado = User.objects.get(username="mostrador")
        guille = User.objects.get(username="guille")
        # El mostrador NO es admin; quien administra sí.
        self.assertFalse(es_administrador(empleado))
        self.assertTrue(es_administrador(guille))
        # Vero y Patri comparten el usuario del mostrador.
        self.assertEqual(Vendedor.objects.get(nombre="Vero").usuario, empleado)
        self.assertEqual(Vendedor.objects.get(nombre="Patri").usuario, empleado)
        self.assertEqual(Vendedor.objects.get(nombre="Guille").usuario, guille)

    def test_sin_argumentos_solo_crea_los_roles(self):
        self._correr()
        self.assertEqual(User.objects.count(), 0)
        self.assertTrue(Group.objects.filter(name="Administrador").exists())
        self.assertTrue(Group.objects.filter(name="Empleado").exists())

    def test_vinculo_mal_escrito_falla_claro(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._correr("--vincular", "SinIgual")

    def test_usuarios_nuevos_no_pueden_entrar_hasta_asignarles_clave(self):
        self._correr_caso_tipico()
        self.assertFalse(User.objects.get(username="guille").has_usable_password())

    def test_es_idempotente(self):
        self._correr_caso_tipico()
        cantidad = User.objects.count()
        self._correr_caso_tipico()
        self.assertEqual(User.objects.count(), cantidad)
