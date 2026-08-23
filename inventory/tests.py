from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Categoria, Marca, MovimientoStock, OrdenCompra, OrdenCompraItem, Producto, Proveedor

PAYLOAD_XSS = '<script>alert("xss")</script>'


class SeguridadProductoTests(TestCase):
    """Django auto-escapa todo lo que se imprime con {{ }} en los templates,
    así que estos tests confirman que ese escape realmente está pasando en
    las páginas donde se muestran datos cargados por el usuario (nombre de
    producto, marca, etc)."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.client.login(username="admin", password="test12345")

    def test_marca_con_html_queda_escapada_en_el_listado(self):
        marca = Marca.objects.create(nombre=PAYLOAD_XSS)
        Producto.objects.create(
            codigo_barras="1111111111", categoria=self.categoria,
            marca=marca, modelo="Producto test", precio=1000,
        )
        resp = self.client.get("/inventario/productos/")
        html = resp.content.decode()
        # El script NUNCA debe aparecer tal cual (sin escapar) en el HTML
        self.assertNotIn(PAYLOAD_XSS, html)
        # Pero el texto sí debe estar presente, escapado
        self.assertIn("&lt;script&gt;", html)

    def test_modelo_con_html_queda_escapada_en_el_formulario_de_edicion(self):
        p = Producto.objects.create(
            codigo_barras="2222222222", categoria=self.categoria, marca=self.marca,
            modelo=PAYLOAD_XSS, precio=1000,
        )
        resp = self.client.get(f"/inventario/productos/{p.id}/editar/")
        html = resp.content.decode()
        self.assertNotIn(PAYLOAD_XSS, html)

    def test_busqueda_con_caracteres_raros_no_rompe(self):
        # Intentos típicos de inyección SQL/XSS en el buscador: como usamos el
        # ORM (queries parametrizadas), esto no debería ni romper ni ejecutar nada.
        intentos = ["' OR '1'='1", '"; DROP TABLE inventory_producto; --', "<img src=x onerror=alert(1)>", "%%%"]
        for intento in intentos:
            resp = self.client.get("/inventario/productos/", {"q": intento})
            self.assertEqual(resp.status_code, 200)
        # La tabla sigue existiendo y Django sigue funcionando
        self.assertTrue(Categoria.objects.filter(pk=self.categoria.pk).exists())


class PermisosProductoTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")
        self.producto = Producto.objects.create(
            codigo_barras="3333333333", categoria=self.categoria, marca=self.marca, precio=1000, stock_actual=5,
        )
        Group.objects.get_or_create(name="Administrador")
        Group.objects.get_or_create(name="Empleado")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.empleado.groups.add(Group.objects.get(name="Empleado"))

    def test_empleado_no_puede_crear_producto(self):
        marca = Marca.objects.create(nombre="X")
        self.client.login(username="empleado", password="test12345")
        resp = self.client.post("/inventario/productos/nuevo/", {
            "categoria": self.categoria.id, "marca": marca.id, "precio": "100", "porcentaje_iva": "21",
        })
        self.assertEqual(resp.status_code, 302)  # redirigido, no autorizado
        self.assertFalse(Producto.objects.filter(marca=marca).exists())

    def test_empleado_no_puede_eliminar_producto(self):
        self.client.login(username="empleado", password="test12345")
        self.client.post(f"/inventario/productos/{self.producto.id}/eliminar/")
        self.assertTrue(Producto.objects.filter(pk=self.producto.pk).exists())

    def test_empleado_puede_ver_listado(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.get("/inventario/productos/")
        self.assertEqual(resp.status_code, 200)

    def test_anonimo_es_redirigido_a_login(self):
        resp = self.client.get("/inventario/productos/")
        self.assertEqual(resp.status_code, 302)

    def test_admin_si_puede_crear_producto(self):
        marca = Marca.objects.create(nombre="Nueva Marca")
        self.client.login(username="admin", password="test12345")
        resp = self.client.post("/inventario/productos/nuevo/", {
            "categoria": self.categoria.id, "marca": marca.id, "modelo": "Modelo Test",
            "precio": "100", "porcentaje_iva": "21",
        })
        self.assertTrue(Producto.objects.filter(marca=marca).exists())


class LogicaProductoTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón Receta")
        self.marca = Marca.objects.create(nombre="TestMarca")

    def test_producto_puede_tener_foto(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buffer = io.BytesIO()
        Image.new("RGB", (10, 10), "blue").save(buffer, format="PNG")
        foto = SimpleUploadedFile("test.png", buffer.getvalue(), content_type="image/png")

        p = Producto.objects.create(
            codigo_barras="4141414141", categoria=self.categoria, marca=self.marca, precio=100, foto=foto,
        )
        self.assertTrue(p.foto)
        self.assertIn("productos/", p.foto.name)
        p.foto.delete(save=False)  # limpieza del archivo de test

    def test_producto_sin_foto_es_valido(self):
        p = Producto.objects.create(codigo_barras="4242424242", categoria=self.categoria, marca=self.marca, precio=100)
        self.assertFalse(p.foto)

    def test_codigo_de_barras_se_genera_automaticamente(self):
        codigo = Producto.generar_codigo_barras()
        self.assertEqual(len(codigo), 12)
        self.assertTrue(codigo.isdigit())

    def test_no_se_puede_borrar_categoria_en_uso(self):
        Producto.objects.create(codigo_barras="4444444444", categoria=self.categoria, marca=self.marca, precio=100)
        with self.assertRaises(Exception):
            # ProtectedError al intentar borrar por FK on_delete=PROTECT
            self.categoria.delete()
        self.assertTrue(Categoria.objects.filter(pk=self.categoria.pk).exists())

    def test_no_se_puede_repetir_codigo_de_barras(self):
        Producto.objects.create(codigo_barras="5555555555", categoria=self.categoria, marca=self.marca, precio=100)
        with self.assertRaises(Exception):
            Producto.objects.create(codigo_barras="5555555555", categoria=self.categoria, marca=self.marca, precio=200)


class OrdenCompraLogicaTests(TestCase):
    """Órdenes de compra a proveedores: modelo de datos y transiciones de
    estado (sin pasar por las vistas)."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón")
        self.marca = Marca.objects.create(nombre="Ray-Ban")
        self.proveedor = Proveedor.objects.create(nombre="Óptica Sur")
        self.producto = Producto.objects.create(
            codigo_barras="5000000001", categoria=self.categoria, marca=self.marca,
            modelo="Aviator", precio=1000, proveedor=self.proveedor, stock_actual=2,
        )
        self.orden = OrdenCompra.objects.create(proveedor=self.proveedor)

    def test_item_nuevo_sin_marca_ni_modelo_no_es_valido(self):
        item = OrdenCompraItem(orden=self.orden, cantidad_pedida=1)
        with self.assertRaises(ValidationError):
            item.clean()

    def test_item_nuevo_con_marca_y_modelo_es_valido(self):
        item = OrdenCompraItem(orden=self.orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=1)
        item.clean()  # no debe lanzar

    def test_item_vinculado_a_producto_no_requiere_texto(self):
        item = OrdenCompraItem(orden=self.orden, producto=self.producto, cantidad_pedida=1)
        item.clean()  # no debe lanzar

    def test_nombre_usa_producto_si_esta_vinculado(self):
        item = OrdenCompraItem.objects.create(orden=self.orden, producto=self.producto, cantidad_pedida=1)
        self.assertIn("Aviator", item.nombre)
        self.assertFalse(item.es_nuevo)

    def test_nombre_usa_texto_libre_si_es_nuevo(self):
        item = OrdenCompraItem.objects.create(
            orden=self.orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=1,
        )
        self.assertEqual(item.nombre, "Vulk X1")
        self.assertTrue(item.es_nuevo)

    def test_pendiente_descuenta_lo_ya_recibido(self):
        item = OrdenCompraItem.objects.create(
            orden=self.orden, producto=self.producto, cantidad_pedida=10, cantidad_recibida=4,
        )
        self.assertEqual(item.pendiente, 6)

    def test_total_estimado_suma_subtotales(self):
        OrdenCompraItem.objects.create(orden=self.orden, producto=self.producto, cantidad_pedida=3, costo_unitario=100)
        OrdenCompraItem.objects.create(orden=self.orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=2, costo_unitario=50)
        self.assertEqual(self.orden.total_estimado, 400)

    def test_estado_pasa_a_parcial_cuando_falta_un_item(self):
        i1 = OrdenCompraItem.objects.create(orden=self.orden, producto=self.producto, cantidad_pedida=5, cantidad_recibida=5)
        OrdenCompraItem.objects.create(orden=self.orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=5, cantidad_recibida=0)
        self.orden.actualizar_estado_recepcion()
        self.assertEqual(self.orden.estado, OrdenCompra.Estado.PARCIAL)

    def test_estado_pasa_a_recibida_cuando_completan_todos_los_items(self):
        OrdenCompraItem.objects.create(orden=self.orden, producto=self.producto, cantidad_pedida=5, cantidad_recibida=5)
        self.orden.actualizar_estado_recepcion()
        self.assertEqual(self.orden.estado, OrdenCompra.Estado.RECIBIDA)


class OrdenCompraFlujoTests(TestCase):
    """Flujo completo vía las vistas: armar pedido, confirmar, recibir
    mercadería (y que eso mueva el stock), permisos de administrador."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Armazón")
        self.marca = Marca.objects.create(nombre="Ray-Ban")
        self.proveedor = Proveedor.objects.create(nombre="Óptica Sur")
        self.producto = Producto.objects.create(
            codigo_barras="5000000002", categoria=self.categoria, marca=self.marca,
            modelo="Wayfarer", precio=1000, proveedor=self.proveedor, stock_actual=3,
        )
        Group.objects.get_or_create(name="Administrador")
        Group.objects.get_or_create(name="Empleado")
        self.admin = User.objects.create_superuser("admin", password="test12345")
        self.empleado = User.objects.create_user("empleado", password="test12345")
        self.empleado.groups.add(Group.objects.get(name="Empleado"))

    def test_empleado_no_puede_crear_pedido(self):
        self.client.login(username="empleado", password="test12345")
        resp = self.client.post("/inventario/ordenes-compra/nueva/", {"proveedor_id": self.proveedor.id})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(OrdenCompra.objects.exists())

    def test_admin_puede_armar_y_confirmar_pedido(self):
        self.client.login(username="admin", password="test12345")
        self.client.post("/inventario/ordenes-compra/nueva/", {"proveedor_id": self.proveedor.id})
        orden = OrdenCompra.objects.get(proveedor=self.proveedor)

        self.client.post(
            f"/inventario/ordenes-compra/{orden.pk}/agregar-producto/",
            {"producto_id": self.producto.id, "cantidad": 5},
        )
        item = orden.items.get(producto=self.producto)
        self.assertEqual(item.cantidad_pedida, 5)

        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/confirmar/", {"notas": "urgente"})
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenCompra.Estado.ENVIADA)

    def test_recibir_mercaderia_suma_stock_y_marca_recibida(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        item = OrdenCompraItem.objects.create(orden=orden, producto=self.producto, cantidad_pedida=5)

        resp = self.client.post(
            f"/inventario/ordenes-compra/{orden.pk}/items/{item.pk}/recibir/", {"cantidad": 5},
        )
        self.assertEqual(resp.status_code, 302)

        item.refresh_from_db()
        orden.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(item.cantidad_recibida, 5)
        self.assertEqual(orden.estado, OrdenCompra.Estado.RECIBIDA)
        self.assertEqual(self.producto.stock_actual, 8)  # 3 inicial + 5 recibidas
        self.assertTrue(MovimientoStock.objects.filter(producto=self.producto, tipo=MovimientoStock.Tipo.INGRESO).exists())

    def test_recepcion_parcial_dos_tandas(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        item = OrdenCompraItem.objects.create(orden=orden, producto=self.producto, cantidad_pedida=10)

        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/items/{item.pk}/recibir/", {"cantidad": 4})
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenCompra.Estado.PARCIAL)

        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/items/{item.pk}/recibir/", {"cantidad": 6})
        orden.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(item.cantidad_recibida, 10)
        self.assertEqual(orden.estado, OrdenCompra.Estado.RECIBIDA)

    def test_no_se_puede_recibir_mas_de_lo_pendiente(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        item = OrdenCompraItem.objects.create(orden=orden, producto=self.producto, cantidad_pedida=3)

        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/items/{item.pk}/recibir/", {"cantidad": 99})
        item.refresh_from_db()
        self.assertEqual(item.cantidad_recibida, 0)

    def test_no_se_puede_recibir_item_nuevo_sin_vincular_producto(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        item = OrdenCompraItem.objects.create(orden=orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=2)

        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/items/{item.pk}/recibir/", {"cantidad": 2})
        item.refresh_from_db()
        self.assertEqual(item.cantidad_recibida, 0)

    def test_crear_producto_desde_item_nuevo_lo_vincula_al_pedido(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        item = OrdenCompraItem.objects.create(
            orden=orden, marca_texto="Vulk", modelo_texto="X1", cantidad_pedida=2, costo_unitario=500,
        )

        resp = self.client.post(
            f"/inventario/productos/nuevo/?orden_item_id={item.pk}",
            {
                "categoria": self.categoria.id, "marca": self.marca.id, "modelo": "X1",
                "precio": "1000", "porcentaje_iva": "21",
            },
        )
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertIsNotNone(item.producto_id)
        self.assertFalse(item.es_nuevo)
        self.assertIn(f"/inventario/ordenes-compra/{orden.pk}/", resp.url)

    def test_cancelar_pedido_sin_recepcion(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.ENVIADA)
        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/cancelar/")
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenCompra.Estado.CANCELADA)

    def test_no_se_puede_cancelar_pedido_con_recepcion(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.PARCIAL)
        OrdenCompraItem.objects.create(orden=orden, producto=self.producto, cantidad_pedida=5, cantidad_recibida=2)
        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/cancelar/")
        orden.refresh_from_db()
        self.assertNotEqual(orden.estado, OrdenCompra.Estado.CANCELADA)

    def test_admin_elimina_orden_de_compra(self):
        self.client.login(username="admin", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.BORRADOR)
        OrdenCompraItem.objects.create(orden=orden, producto=self.producto, cantidad_pedida=3)
        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/eliminar/")
        self.assertFalse(OrdenCompra.objects.filter(pk=orden.pk).exists())

    def test_empleado_no_puede_eliminar_orden(self):
        self.client.login(username="empleado", password="test12345")
        orden = OrdenCompra.objects.create(proveedor=self.proveedor, estado=OrdenCompra.Estado.BORRADOR)
        self.client.post(f"/inventario/ordenes-compra/{orden.pk}/eliminar/")
        self.assertTrue(OrdenCompra.objects.filter(pk=orden.pk).exists())
