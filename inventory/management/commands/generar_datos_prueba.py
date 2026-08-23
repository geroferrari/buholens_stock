"""
Genera datos de prueba en todos los modelos del proyecto (configuración de la
óptica, categorías, proveedores, productos, promociones, planes de financiación,
clientes, recetas, vendedores, ventas, devoluciones, órdenes de compra, órdenes
de laboratorio, pruebas de lentes de contacto y usuarios) para poder recorrer la
app entera con algo cargado.

Es seguro correrlo más de una vez: cada sección se salta si ya hay datos
de ese tipo, así que no duplica todo en cada corrida.

Uso:
    python manage.py generar_datos_prueba
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from contact_lenses.models import PruebaLentesContacto
from core.models import Configuracion
from customers.models import Cliente, ObraSocial
from inventory.models import (
    Banco, Categoria, Marca, MovimientoStock, OrdenCompra, OrdenCompraItem,
    PlanFinanciacion, Producto, Promocion, Proveedor,
)
from prescriptions.models import Medico, OrdenLaboratorio, Receta
from sales.models import Devolucion, Venta, VentaItem, Vendedor
from tenants.db_router import get_or_register_tenant_db, tenant_context
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Genera datos de prueba en todos los modelos (idempotente: no duplica si ya hay datos)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", help="Slug de la óptica destino (por defecto, la base 'default').",
        )

    def handle(self, *args, **options):
        if options["tenant"]:
            tenant = Tenant.objects.get(slug=options["tenant"])
            with tenant_context(get_or_register_tenant_db(tenant)):
                self._generar()
        else:
            self._generar()

    def _generar(self):
        random.seed(42)

        self.crear_configuracion()
        self.crear_grupos_y_usuarios()
        categorias = self.crear_categorias()
        proveedores = self.crear_proveedores()
        productos = self.crear_productos(categorias, proveedores)
        self.crear_promociones(categorias, productos)
        self.crear_planes_financiacion()
        clientes = self.crear_clientes()
        recetas = self.crear_recetas(clientes)
        vendedores = self.crear_vendedores()
        self.crear_ventas_y_devoluciones(clientes, vendedores, productos)
        self.crear_ordenes_compra(proveedores, productos)
        self.crear_ordenes_laboratorio(recetas, productos)
        self.crear_pruebas_lentes_contacto(clientes, vendedores)

        self.stdout.write(self.style.SUCCESS("Listo. Datos de prueba generados/verificados."))

    # ---------- Configuración de la óptica ----------

    def crear_configuracion(self):
        """Deja la óptica con nombre y datos de contacto, así las pantallas y
        las impresiones no se ven con los valores por defecto."""
        if Configuracion.objects.exists():
            return
        Configuracion.objects.create(
            nombre="Óptica Demo",
            nombre_corto="Demo",
            direccion="Av. Siempreviva 742",
            telefono="11 5555-5555",
            email="hola@opticademo.test",
            caracteristica_telefonica="11",
            largo_telefono_local=8,
        )
        self.stdout.write("Configuración de la óptica cargada (Óptica Demo).")

    # ---------- Usuarios ----------

    def crear_grupos_y_usuarios(self):
        for nombre in ["Administrador", "Empleado"]:
            Group.objects.get_or_create(name=nombre)

        if not User.objects.filter(username="admin_demo").exists():
            admin = User.objects.create_user("admin_demo", password="demo1234")
            admin.groups.add(Group.objects.get(name="Administrador"))
            self.stdout.write("Usuario admin_demo / demo1234 (grupo Administrador) creado.")

        if not User.objects.filter(username="empleado_demo").exists():
            empleado = User.objects.create_user("empleado_demo", password="demo1234")
            empleado.groups.add(Group.objects.get(name="Empleado"))
            self.stdout.write("Usuario empleado_demo / demo1234 (grupo Empleado) creado.")

    # ---------- Inventory ----------

    def crear_categorias(self):
        datos = [
            ("Armazón Receta", False, True),
            ("Armazón Sol", False, True),
            ("Lentes de Contacto", True, True),
            ("Cristales", True, False),
            ("Accesorios", False, True),
        ]
        categorias = {}
        for nombre, usa_receta, controla_stock in datos:
            cat, _ = Categoria.objects.get_or_create(
                nombre=nombre,
                defaults={"usa_receta": usa_receta, "controla_stock": controla_stock},
            )
            categorias[nombre] = cat
        return categorias

    def crear_proveedores(self):
        datos = [
            ("INTEROPTICA", "Marina", "011-4555-1234"),
            ("Luxottica Argentina", "Juan Pérez", "011-4555-5678"),
            ("DAL METAL", "Sofía Gómez", "011-4555-9012"),
            ("Sun Optical Group", "Martín Ruiz", "011-4555-3456"),
            ("Mildred Distribuciones", "Laura Díaz", "011-4555-7890"),
        ]
        proveedores = []
        for nombre, contacto, telefono in datos:
            prov, _ = Proveedor.objects.get_or_create(
                nombre=nombre, defaults={"contacto": contacto, "telefono": telefono}
            )
            proveedores.append(prov)
        return proveedores

    def crear_marcas(self, marcas_por_categoria):
        marcas = {}
        for nombres in marcas_por_categoria.values():
            for nombre in nombres:
                if nombre not in marcas:
                    marcas[nombre], _ = Marca.objects.get_or_create(nombre=nombre)
        return marcas

    def crear_productos(self, categorias, proveedores):
        marcas_por_categoria = {
            "Armazón Receta": ["Vulk", "Vogue", "Polo", "Onix", "Deniro", "Ken Brisk"],
            "Armazón Sol": ["Ray-Ban", "Arnette", "Carrera", "Michael Kors", "Karun"],
            "Lentes de Contacto": ["Acuvue", "Biofinity", "Air Optix"],
            "Cristales": ["Zeiss", "Essilor", "Hoya"],
            "Accesorios": ["Generico", "Guru"],
        }
        marcas = self.crear_marcas(marcas_por_categoria)

        if not any(p.marcas.exists() for p in proveedores):
            todas = list(marcas.values())
            for prov in proveedores:
                prov.marcas.set(random.sample(todas, k=min(4, len(todas))))

        if Producto.objects.count() >= 40:
            return list(Producto.objects.all())

        colores = ["Negro", "Carey", "Dorado", "Plateado", "Azul", "Rosa", "Transparente", "Habano"]

        productos = []
        for categoria_nombre, cat in categorias.items():
            nombres_marca = marcas_por_categoria[categoria_nombre]
            for i in range(10):
                marca = marcas[random.choice(nombres_marca)]
                modelo = f"{marca.nombre[:3].upper()}-{random.randint(100, 999)}"
                costo = Decimal(random.randint(2000, 60000))
                precio = (costo * Decimal("1.6")).quantize(Decimal("1"))
                stock = 0 if not cat.controla_stock else random.randint(0, 25)
                producto = Producto.objects.create(
                    codigo_barras=Producto.generar_codigo_barras(),
                    categoria=cat,
                    proveedor=random.choice(proveedores),
                    marca=marca,
                    modelo=modelo,
                    color=random.choice(colores),
                    material=random.choice(["Acetato", "Metal", "TR90", ""]),
                    precio_costo=costo,
                    precio=precio,
                    stock_actual=stock,
                    stock_minimo=3,
                )
                productos.append(producto)
        self.stdout.write(f"{len(productos)} productos creados.")
        return productos

    def crear_promociones(self, categorias, productos):
        if Promocion.objects.exists():
            return
        hoy = timezone.localdate()
        vigente = Promocion.objects.create(
            nombre="Verano 2x1 en sol",
            descripcion="Descuento en toda la línea de armazones de sol.",
            tipo_descuento=Promocion.TipoDescuento.PORCENTAJE,
            valor=Decimal("20"),
            fecha_inicio=hoy - timedelta(days=10),
            fecha_fin=hoy + timedelta(days=20),
            activa=True,
        )
        vigente.categorias.add(categorias["Armazón Sol"])

        vencida = Promocion.objects.create(
            nombre="Liquidación invierno",
            descripcion="Promo ya finalizada, para probar el filtro de vigencia.",
            tipo_descuento=Promocion.TipoDescuento.MONTO_FIJO,
            valor=Decimal("5000"),
            fecha_inicio=hoy - timedelta(days=90),
            fecha_fin=hoy - timedelta(days=60),
            activa=True,
        )
        vencida.categorias.add(categorias["Armazón Receta"])

        Promocion.objects.create(
            nombre="Próximo lanzamiento",
            descripcion="Promo futura, todavía no vigente.",
            tipo_descuento=Promocion.TipoDescuento.PORCENTAJE,
            valor=Decimal("15"),
            fecha_inicio=hoy + timedelta(days=15),
            fecha_fin=None,
            activa=True,
        )
        self.stdout.write("3 promociones creadas.")

    # ---------- Customers / Prescriptions ----------

    def crear_clientes(self):
        if Cliente.objects.count() >= 15:
            return list(Cliente.objects.all())

        nombres = [
            ("María", "González"), ("Juan", "Pérez"), ("Lucía", "Fernández"), ("Carlos", "Gómez"),
            ("Ana", "Rodríguez"), ("Diego", "López"), ("Sofía", "Martínez"), ("Pablo", "Sánchez"),
            ("Valentina", "Díaz"), ("Martín", "Romero"), ("Camila", "Torres"), ("Federico", "Alvarez"),
            ("Julieta", "Ruiz"), ("Nicolás", "Suárez"), ("Florencia", "Castro"),
        ]
        clientes = []
        for i, (nombre, apellido) in enumerate(nombres):
            cliente, _ = Cliente.objects.get_or_create(
                dni=f"3{i:07d}",
                defaults={
                    "nombre": nombre,
                    "apellido": apellido,
                    "telefono": f"11{4000+i:04d}{5000+i:04d}",
                    "email": f"{nombre.lower()}.{apellido.lower()}@mail.com",
                    "direccion": f"Calle Falsa {100 + i}",
                },
            )
            clientes.append(cliente)
        self.stdout.write(f"{len(clientes)} clientes creados.")
        return clientes

    def crear_recetas(self, clientes):
        if Receta.objects.exists():
            return list(Receta.objects.all())
        hoy = timezone.localdate()
        medico, _ = Medico.objects.get_or_create(nombre="Dr. Fernando Ibáñez")
        obras_sociales = [ObraSocial.objects.get_or_create(nombre=n)[0] for n in ("Particular", "OSDE", "Swiss Medical")] + [None]
        for i, cliente in enumerate(clientes[:8]):
            Receta.objects.create(
                cliente=cliente,
                fecha_recibido=hoy - timedelta(days=random.randint(1, 45)),
                fecha_entrega=hoy - timedelta(days=random.randint(0, 5)) if i % 2 == 0 else None,
                medico=medico,
                obra_social=random.choice(obras_sociales),
                lejos_od_esfera=Decimal(random.choice([-2.5, -1.0, 0.0, 1.25, 2.0])),
                lejos_od_cilindro=Decimal(random.choice([0.0, -0.5, -0.75])),
                lejos_od_eje=random.choice([0, 90, 180]),
                lejos_oi_esfera=Decimal(random.choice([-2.25, -1.0, 0.0, 1.5, 2.0])),
                lejos_oi_cilindro=Decimal(random.choice([0.0, -0.5, -0.75])),
                lejos_oi_eje=random.choice([0, 90, 180]),
                lejos_dnp="31/31.5",
                lejos_tipo_cristal="Monofocal",
            )
        self.stdout.write("8 recetas creadas.")
        return list(Receta.objects.all())

    # ---------- Sales ----------

    def crear_vendedores(self):
        nombres = ["Rocío Benítez", "Tomás Acosta", "Agustina Vega"]
        vendedores = []
        for nombre in nombres:
            vendedor, _ = Vendedor.objects.get_or_create(nombre=nombre)
            vendedores.append(vendedor)
        return vendedores

    def crear_ventas_y_devoluciones(self, clientes, vendedores, productos):
        if Venta.objects.exists():
            return

        # Con stock >= 5 para tener margen: varias ventas pueden tomar el mismo
        # producto y no queremos que confirmar() falle por quedarse sin stock.
        vendibles = [
            p for p in productos
            if p.categoria.controla_stock and not p.categoria.usa_receta and p.stock_actual >= 5
        ]
        usuario_admin = User.objects.filter(username="admin_demo").first()

        # confirmar() exige forma de pago (y cuotas si es tarjeta), así que se
        # reparten las formas para que el dashboard y la caja tengan variedad.
        formas = [
            Venta.FormaPago.EFECTIVO, Venta.FormaPago.TARJETA,
            Venta.FormaPago.TRANSFERENCIA, Venta.FormaPago.QR,
        ]

        ventas_confirmadas = []
        for i in range(8):
            forma = formas[i % len(formas)]
            venta = Venta.objects.create(
                cliente=random.choice(clientes),
                vendedor=random.choice(vendedores),
                usuario=usuario_admin,
                forma_pago=forma,
                cuotas=random.choice([3, 6, 12]) if forma == Venta.FormaPago.TARJETA else None,
            )
            for producto in random.sample(vendibles, k=min(2, len(vendibles))):
                VentaItem.objects.create(
                    venta=venta, producto=producto, cantidad=1, precio_unitario=producto.precio,
                )
            venta.confirmar()
            ventas_confirmadas.append(venta)

        for i in range(2):
            venta = Venta.objects.create(
                cliente=random.choice(clientes), vendedor=random.choice(vendedores), usuario=usuario_admin,
            )
            producto = random.choice(vendibles)
            VentaItem.objects.create(venta=venta, producto=producto, cantidad=1, precio_unitario=producto.precio)
            # queda abierta a propósito, para probar el flujo de "venta en curso"

        for i in range(2):
            venta = Venta.objects.create(
                cliente=random.choice(clientes), vendedor=random.choice(vendedores),
                usuario=usuario_admin, estado=Venta.Estado.ANULADA,
            )
            producto = random.choice(vendibles)
            VentaItem.objects.create(venta=venta, producto=producto, cantidad=1, precio_unitario=producto.precio)

        self.stdout.write("12 ventas creadas (8 confirmadas, 2 abiertas, 2 anuladas).")

        for venta in ventas_confirmadas[:2]:
            item = venta.items.first()
            if not item:
                continue
            devolucion = Devolucion.objects.create(
                producto=item.producto, venta_item=item, cantidad=1,
                monto=item.precio_unitario, motivo="Cambio de talle", usuario=usuario_admin,
            )
            if item.producto.categoria.controla_stock:
                MovimientoStock.objects.create(
                    producto=item.producto, tipo=MovimientoStock.Tipo.INGRESO, cantidad=1,
                    usuario=usuario_admin, nota=f"Devolución #{devolucion.id}",
                )
        self.stdout.write("2 devoluciones creadas.")

    # ---------- Financiación ----------

    def crear_planes_financiacion(self):
        """Los bancos ya vienen sembrados por migración; acá se les cuelgan
        algunos planes de cuotas para que la pantalla no esté vacía."""
        if PlanFinanciacion.objects.exists():
            return
        planes = [
            ("Banco Galicia", "3 cuotas sin interés", 3, "0"),
            ("Banco Galicia", "6 cuotas sin interés", 6, "0"),
            ("Banco Nación", "12 cuotas fijas", 12, "15.5"),
            ("Mercado Pago", "6 cuotas con interés", 6, "22.0"),
            ("Banco Provincia", "3 cuotas sin interés", 3, "0"),
        ]
        creados = 0
        for banco_nombre, nombre, cuotas, cft in planes:
            banco = Banco.objects.filter(nombre=banco_nombre).first()
            if not banco:
                continue
            PlanFinanciacion.objects.create(
                banco=banco, nombre=nombre, cuotas=cuotas,
                costo_financiero_pct=Decimal(cft), activo=True,
            )
            creados += 1
        self.stdout.write(f"{creados} planes de financiación creados.")

    # ---------- Órdenes de compra ----------

    def crear_ordenes_compra(self, proveedores, productos):
        if OrdenCompra.objects.exists():
            return
        usuario = User.objects.filter(username="admin_demo").first()
        # Una por estado, para ver los distintos caminos de la pantalla.
        estados = [
            OrdenCompra.Estado.BORRADOR,
            OrdenCompra.Estado.ENVIADA,
            OrdenCompra.Estado.PARCIAL,
            OrdenCompra.Estado.RECIBIDA,
        ]
        for estado in estados:
            proveedor = random.choice(proveedores)
            orden = OrdenCompra.objects.create(
                proveedor=proveedor, estado=estado, usuario=usuario,
                notas="Reposición de temporada." if estado != OrdenCompra.Estado.BORRADOR else "",
            )
            for producto in random.sample(productos, k=3):
                pedida = random.randint(2, 10)
                if estado == OrdenCompra.Estado.RECIBIDA:
                    recibida = pedida
                elif estado == OrdenCompra.Estado.PARCIAL:
                    recibida = max(1, pedida // 2)
                else:
                    recibida = 0
                OrdenCompraItem.objects.create(
                    orden=orden, producto=producto,
                    cantidad_pedida=pedida, cantidad_recibida=recibida,
                    costo_unitario=producto.precio_costo,
                )
            # Un ítem "nuevo", que todavía no está en el catálogo.
            OrdenCompraItem.objects.create(
                orden=orden, marca_texto="Ray-Ban", modelo_texto="RB-3025",
                descripcion="Dorado, calibre 58", cantidad_pedida=2,
                costo_unitario=Decimal("45000"),
            )
        self.stdout.write(f"{len(estados)} órdenes de compra creadas (una por estado).")

    # ---------- Órdenes de laboratorio ----------

    def crear_ordenes_laboratorio(self, recetas, productos):
        if OrdenLaboratorio.objects.exists() or not recetas:
            return
        cristales = [p for p in productos if p.categoria.nombre == "Cristales"]
        armazones = [p for p in productos if p.categoria.nombre == "Armazón Receta"]
        if not cristales:
            return
        estados = [
            OrdenLaboratorio.Estado.PENDIENTE,
            OrdenLaboratorio.Estado.ENVIADA,
            OrdenLaboratorio.Estado.RECIBIDA,
        ]
        for i, receta in enumerate(recetas[:6]):
            OrdenLaboratorio.objects.create(
                cliente=receta.cliente,
                receta=receta,
                producto=random.choice(cristales),
                armazon=random.choice(armazones) if armazones and i % 3 else None,
                armazon_de_cliente=(i % 3 == 0),
                estado=estados[i % len(estados)],
                observaciones="Urgente, viaja el viernes." if i == 0 else "",
            )
        self.stdout.write("6 órdenes de laboratorio creadas.")

    # ---------- Pruebas de lentes de contacto ----------

    def crear_pruebas_lentes_contacto(self, clientes, vendedores):
        if PruebaLentesContacto.objects.exists():
            return
        ahora = timezone.localtime()
        # Ventas ya confirmadas que todavía no están tomadas por otra prueba.
        ventas_confirmadas = list(
            Venta.objects.filter(estado=Venta.Estado.CONFIRMADA, prueba_lentes__isnull=True)
        )
        # Repartidas alrededor de hoy para que el calendario se vea poblado.
        desfasajes = [-8, -3, -1, 0, 0, 1, 2, 5, 9]
        estados = [
            PruebaLentesContacto.Estado.REALIZADA,
            PruebaLentesContacto.Estado.REALIZADA,
            PruebaLentesContacto.Estado.CANCELADA,
        ]
        for i, dias in enumerate(desfasajes):
            fecha = (ahora + timedelta(days=dias)).replace(
                hour=random.choice([10, 11, 15, 17]), minute=random.choice([0, 30]),
                second=0, microsecond=0,
            )
            # Las pasadas ya tienen desenlace; las futuras siguen agendadas.
            estado = estados[i % len(estados)] if dias < 0 else PruebaLentesContacto.Estado.AGENDADA
            PruebaLentesContacto.objects.create(
                cliente=random.choice(clientes),
                vendedor=random.choice(vendedores),
                fecha_hora=fecha,
                estado=estado,
                # Algunas realizadas terminaron en venta, para ver el vínculo
                # prueba → venta en el detalle y en la agenda.
                venta=ventas_confirmadas.pop() if (
                    estado == PruebaLentesContacto.Estado.REALIZADA and ventas_confirmadas
                ) else None,
                observaciones="Primera prueba, usa anteojos hace 5 años." if i == 0 else "",
            )
        self.stdout.write(f"{len(desfasajes)} pruebas de lentes de contacto agendadas.")
