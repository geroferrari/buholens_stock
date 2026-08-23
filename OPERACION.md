# Puesta en producción (pasos manuales)

Todo lo que sigue está **implementado en el código**, pero necesita un paso de
configuración manual (variables de entorno, un cron en la plataforma de hosting)
para quedar funcionando en una instalación nueva.

Los ejemplos usan Railway porque es donde se probó, pero aplican igual a Render,
Fly.io o un servidor propio: lo único que cambia es dónde se cargan las variables
de entorno y cómo se programan las tareas periódicas.

---

## 0. Multi-tenant: alta de una óptica nueva

Cada óptica es un **tenant** con su propia base Postgres, resuelta por
subdominio (`<slug>.tudominio.com`). Alta de un cliente nuevo:

```bash
python manage.py crear_optica --slug imago --nombre "Óptica Imago"
```

Esto crea la base en Postgres (`stockero_<slug>`) y la migra. Después, apuntar
DNS `imago.tudominio.com` a la app.

> **Pendiente de verificar:** el rol de Postgres en Railway necesita permiso
> `CREATEDB` para que `crear_optica` pueda crear la base sola. Si no lo tiene,
> hay que crear la base a mano desde el dashboard de Railway y correr
> `python manage.py migrate_tenants` para migrarla.

`ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` necesitan el subdominio wildcard:
```
ALLOWED_HOSTS=.tudominio.com
CSRF_TRUSTED_ORIGINS=https://*.tudominio.com
```

El `Procfile` ya corre `migrate_tenants` en cada deploy (migra la base de
cada óptica activa, además de la base de control).

---

## 1. Datos de la óptica

Recién creada, la óptica arranca genérica ("Mi Óptica", color azul, ícono
neutro). Entrar como administrador/a a **Gestión → ⚙️ Configuración de la óptica**
y cargar nombre, logo, color de marca, dirección, teléfono, mail y las reglas de
teléfono (característica de la zona y código de país para los links de WhatsApp).

Después, cargar los vendedores/as en Gestión → Vendedores y crear los usuarios
(agregando `--tenant <slug>` para que quede en la base de esa óptica):

```bash
python manage.py configurar_usuarios --tenant imago \
    --empleado mostrador --admin ana --admin luis \
    --vincular 'Ana=ana' --vincular 'Sofi=mostrador'

# los usuarios nuevos quedan sin contraseña utilizable. changepassword es de
# Django y no sabe de tenants (solo conoce la base 'default' al arrancar), así
# que para una óptica hay que asignarla desde el shell:
python manage.py shell -c "
from tenants.db_router import tenant_context, get_or_register_tenant_db
from tenants.models import Tenant
from django.contrib.auth.models import User
t = Tenant.objects.get(slug='imago')
with tenant_context(get_or_register_tenant_db(t)):
    u = User.objects.get(username='ana')
    u.set_password('<contraseña>')
    u.save()
"
```

---

## 2. Backups de la base de datos

Backup en dos capas.

### 2.a — Backups nativos del proveedor (capa principal) ⭐
Es lo más importante y no lleva código:
- Railway → servicio de **Postgres** → pestaña **Backups** → activar.
  (En otros proveedores, el equivalente: snapshots automáticos de la base.)

### 2.b — Copia offsite por email (capa secundaria)
Comando ya hecho: `python manage.py backup_db` (dump JSON comprimido que se
manda por email). Corre una vez por cada óptica activa, un mail por óptica.
Falta configurarlo:

1. **Variables de entorno**:
   ```
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=tucorreo@gmail.com
   EMAIL_HOST_PASSWORD=<contraseña de aplicación de Gmail>
   DEFAULT_FROM_EMAIL=tucorreo@gmail.com
   BACKUP_EMAIL=tucorreo@gmail.com
   ```
   > Gmail necesita **2FA activo** + una **"contraseña de aplicación"**
   > (Google → Seguridad → Contraseñas de aplicaciones), NO la clave normal.

2. **Cron diario**: en Railway, un servicio nuevo sobre el mismo repo con
   schedule `0 6 * * *` (UTC = 3 AM Argentina) y comando
   `python manage.py backup_db`.

**Restaurar:** descomprimir el `.gz` y, como `loaddata --database` tampoco
conoce los alias de tenant al arrancar, cargarlo desde el shell:
```bash
python manage.py shell -c "
from django.core.management import call_command
from tenants.db_router import get_or_register_tenant_db
from tenants.models import Tenant
alias = get_or_register_tenant_db(Tenant.objects.get(slug='imago'))
call_command('loaddata', 'archivo.json', database=alias)
"
```

---

## 3. Notificaciones push (avisos al celular)

Implementado (Web Push + PWA). **Limitación conocida:** las claves VAPID son
una sola por instancia (variable de entorno), compartidas por todas las
ópticas — no hay identidad de push distinta por tenant. Si eso llega a
importar, es un cambio aparte. Falta:

1. **Generar claves VAPID** y cargarlas como variables de entorno:
   ```
   python manage.py generar_vapid_keys
   ```
   → setear `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y
   `VAPID_CONTACTO=<un mail REAL>` (Apple rechaza mails falsos con BadJwtToken).
   Sin claves, el push queda desactivado y el resto de la app anda igual.

2. **Cada persona** activa los avisos en SU celular (botón 🔔 en la home) y
   elige "¿quién usa este celular?". En **iPhone** hay que "Agregar a inicio"
   primero (Safari → Compartir → Agregar a inicio) — límite de Apple.

3. **Cron del recordatorio** de pruebas del día: schedule diario
   (ej `0 11 * * *` = 8 AM Argentina), comando `python manage.py recordar_pruebas`
   (recorre todas las ópticas activas solo).

---

## 4. Papelera (purga automática)

La papelera (borrado recuperable de recetas, productos y ventas) ya funciona.
Para que lo borrado se elimine solo después de N días (default 7), falta el cron:

- Schedule diario (ej `30 6 * * *` = 3:30 AM Argentina), comando
  `python manage.py vaciar_papelera` (recorre todas las ópticas activas solo).
- Retención configurable con la variable `PAPELERA_DIAS_RETENCION` (default 7).
- Probar sin borrar: `python manage.py vaciar_papelera --dry-run`.
