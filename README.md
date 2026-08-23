# Stockero · Sistema de stock para ópticas

Producto de **BuhoLen** (software para ópticas). Sistema web para control de
stock, ventas por escaneo de código de barras y recetas ópticas de clientes.

Es **genérico**: no tiene el nombre, el logo ni los datos de ninguna óptica
escritos en el código. Todo eso se carga desde **Gestión → Configuración de la
óptica** después de instalarlo (ver "Puesta en marcha"). Los neutros de la
interfaz y el pie de página son de BuhoLen (el producto); el nombre, el logo y
el color de marca son de cada óptica.

## Documentación

- **`DESARROLLO.md`** — cómo levantar el ambiente local (Postgres en Docker).
- **`OPERACION.md`** — pasos manuales para dejarlo andando en producción
  (datos de la óptica, backups, notificaciones push, crons).

## Qué incluye

- **Inventario**: productos, categorías, proveedores, movimientos de stock con trazabilidad completa (auditables desde Gestión → Movimientos de stock).
- **Punto de venta con lector de código de barras**: cada escaneo agrega el
  producto al carrito; los cristales/productos a medida se eligen de una
  lista (no se escanean, no controlan stock); al confirmar se descuenta
  stock de forma atómica. Cada venta registra qué vendedor/a la atendió.
- **Promociones**: descuentos por porcentaje o monto fijo, con vigencia por
  fechas, aplicables por categoría y/o marca. Se aplican solas en el punto
  de venta y quedan registradas en cada ítem vendido.
- **Devoluciones**: registro por escaneo, con reingreso automático de stock
  cuando corresponde e historial auditable.
- **Dashboard** (admin): facturación, ventas por vendedor/a, productos y
  marcas más vendidos, evolución diaria, con filtro de fechas.
- **Clientes** (ningún dato obligatorio) **y recetas ópticas** (Lejos/Cerca,
  tratamientos, armazón), vinculadas a los ítems vendidos. Alta rápida de
  cliente y captura de mail para promociones desde el propio punto de venta.
- **Perfiles**: grupo "Administrador" (todo) y "Empleado" (vender, ingresar
  mercadería, devoluciones, clientes y recetas; sin acceso a configuración,
  precios, promociones ni reportes). Login propio en `/accounts/login/`.
- **Impresión de etiquetas** de código de barras (individual o en lote)
  compatibles con Brother QL.
- **Configuración de la óptica**: nombre, logo, color de marca, dirección,
  teléfono, mail y reglas de teléfono (característica de la zona, código de
  país para WhatsApp). Se refleja en la barra superior, el ticket, las órdenes
  de laboratorio, el ícono de la app en el celular y los avisos push.
- **Repreciado en lote** por proveedor, marca o categoría, con revisión previa,
  y **suite de tests** (240 tests:
  seguridad XSS/CSRF, permisos y lógica de negocio) con `python manage.py test`.

## Cómo correrlo en local

```bash
python -m venv venv
source venv/bin/activate  # en Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abrir `http://localhost:8000/`. El usuario que crees con `createsuperuser` te
sirve tanto para el panel de admin como para vender y escanear.

Esto levanta la base de **control** (multi-tenant: cada óptica vive en su
propia base, resuelta por subdominio — ver "Multi-tenant" en `DESARROLLO.md`
para dar de alta una óptica en local, y `OPERACION.md` para producción).

## Puesta en marcha para una óptica nueva

Recién instalado, el sistema arranca con datos genéricos ("Mi Óptica", color
azul, ícono neutro). Para dejarlo con la identidad de la óptica:

1. **Cargar los datos de la óptica**: entrar como administrador/a a
   **Gestión → ⚙️ Configuración de la óptica** y completar nombre, logo, color
   de marca, dirección, teléfono y mail. Eso es lo que sale en la barra
   superior, el ticket de venta, las órdenes de laboratorio, el ícono de la app
   en el celular y los avisos push.

   En esa misma pantalla se configuran las reglas de teléfono: la
   **característica de la zona** (para completar solos los números que se cargan
   sin ella) y el **código de país / prefijo de celular** con el que se arman los
   links de WhatsApp. Si se dejan vacías, los teléfonos se guardan tal cual se
   escriben.

2. **Cargar los vendedores/as** en Gestión → Vendedores (es de quien queda
   registrada cada venta).

3. **Crear los usuarios y roles**:

   ```bash
   # solo los roles (Administrador / Empleado)
   python manage.py configurar_usuarios

   # caso típico: un usuario compartido de mostrador + logins de administración,
   # y a qué usuario le corresponde cada vendedor/a (para los avisos al celular)
   python manage.py configurar_usuarios \
       --empleado mostrador --admin ana --admin luis \
       --vincular 'Ana=ana' --vincular 'Sofi=mostrador'

   # los usuarios nuevos quedan sin contraseña utilizable:
   python manage.py changepassword ana
   ```

## Usuarios y perfiles

Hay dos roles: **Administrador** (todo) y **Empleado** (vender, ingresar
mercadería, devoluciones, clientes y recetas; sin acceso a configuración,
precios, promociones ni reportes). Se crean con `configurar_usuarios` (ver
arriba) o a mano desde `/admin-panel/` → Usuarios.

Los empleados inician sesión en `/accounts/login/` (no necesitan acceso al panel
de admin). Si todo el mostrador comparte la misma computadora, no hace falta un
usuario por persona: alcanza con un usuario compartido de tipo "Empleado", y al
confirmar cada venta se elige del desplegable qué vendedor/a la atendió (los
vendedores se cargan en Gestión → Vendedores).

## Cargar el stock inicial

Los productos se cargan desde **Gestión → Productos**. Para actualizar precios
en lote está **Gestión → 💲 Lista de precios**, que permite repreciar por
proveedor, marca o categoría (por porcentaje o recalculando sobre el costo) y
revisar los valores antes de confirmar.

Los productos generan un código de barras interno, así que después hay que
**imprimir las etiquetas** para pegarlas en cada producto (ver la sección de
impresión más abajo).

## Deploy a internet (Railway / Render / Fly.io)

Cualquiera de estas plataformas sirve; el proyecto ya viene listo para
Postgres + variables de entorno. Pasos generales (son casi idénticos en
Railway o Render):

1. Subí este proyecto a un repositorio de GitHub.
2. Creá un nuevo servicio "Web Service" apuntando al repo, y agregá un
   servicio de PostgreSQL (la plataforma te da un `DATABASE_URL`
   automáticamente, o lo arma con las variables sueltas — en ese caso
   armalo vos como `postgres://user:pass@host:puerto/db`).
3. Variables de entorno a configurar:
   - `SECRET_KEY`: una cadena larga y aleatoria (podés generarla con
     `python -c "import secrets; print(secrets.token_urlsafe(50))"`)
   - `DEBUG`: `False`
   - `ALLOWED_HOSTS`: el dominio que te asigne la plataforma, ej.
     `mi-optica.up.railway.app`
   - `CSRF_TRUSTED_ORIGINS`: `https://mi-optica.up.railway.app`
   - `DATABASE_URL`: la que te da el servicio de Postgres
4. Comando de arranque (build): `pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput`
5. Comando de inicio (start): el que ya está en `Procfile`
   (`gunicorn stockero.wsgi --log-file -`)
6. Una vez desplegado, corré `python manage.py createsuperuser` desde la
   consola/shell que te da la plataforma para crear el primer usuario.

## Impresión de etiquetas (Brother QL-700)

Para el MVP el código de barras se genera automáticamente al cargar cada
producto (campo `codigo_barras`, visible y editable en el admin). Falta un
paso de "generar PDF de etiqueta e imprimir en la Brother QL" — es la
siguiente pieza a construir; la librería `brother_ql` en Python permite
generar e imprimir etiquetas con código de barras directamente desde este
mismo sistema, sin pasos manuales. Si querés, lo armamos como siguiente
iteración.

## Lector de código de barras

Cualquier lector **USB tipo "pistola"** que funcione como teclado (HID) sirve
sin instalar drivers ni nada especial — al escanear, "tipea" el código en el
campo con foco y manda Enter, que es justo como está armada la pantalla de
venta. Opciones conocidas y confiables: Honeywell Voyager 1200g/1250g,
Zebra DS2208, o alternativas genéricas más económicas en Mercado Libre (buscá
"lector código de barras USB" — confirmá que sea "plug and play"/USB HID, no
uno que pida instalar un programa aparte). Con que lea códigos 1D (lineales)
alcanza; si querés a futuro leer también QR (por ejemplo en recetas o
comprobantes), buscá uno "2D" — el precio no cambia mucho.

## Modelo de datos (resumen)

- `inventory.Categoria`, `Proveedor`, `Producto`, `MovimientoStock`
- `customers.Cliente`
- `prescriptions.Receta` (graduación Lejos/Cerca, tratamientos, armazón)
- `sales.Venta`, `VentaItem` (vincula producto vendido ↔ receta usada)

## Qué queda para después del MVP

- Impresión de etiquetas directo desde el sistema (Brother QL-700)
- Alertas de stock mínimo / reposición
- Reportes (ventas por período, productos más vendidos, etc.)
- Permisos diferenciados por usuario/vendedor
- Facturación fiscal (si lo necesitan más adelante)
