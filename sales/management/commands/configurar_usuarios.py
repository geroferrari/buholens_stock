from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sales.models import Vendedor
from tenants.db_router import get_or_register_tenant_db, tenant_context
from tenants.models import Tenant

# Rol con permisos de administración. OJO: el nombre "Administrador" es el que
# chequea stockero.permissions.es_administrador — no cambiarlo sin tocar eso.
GRUPO_ADMIN = "Administrador"
GRUPO_EMPLEADO = "Empleado"


class Command(BaseCommand):
    help = (
        "Crea/actualiza los usuarios y roles de la óptica y, opcionalmente, vincula "
        "cada vendedor/a con su usuario (para saber a quién avisarle al celular). "
        "Es idempotente: se puede correr las veces que haga falta. Los usuarios "
        "nuevos quedan SIN contraseña utilizable: hay que asignarla con "
        "'python manage.py changepassword <usuario>'.\n\n"
        "Ejemplos:\n"
        "  # solo crea los roles\n"
        "  python manage.py configurar_usuarios\n\n"
        "  # un login propio por persona, con permisos de administración\n"
        "  python manage.py configurar_usuarios --admin ana --admin luis\n\n"
        "  # usuario compartido de mostrador + vínculo vendedor→usuario\n"
        "  python manage.py configurar_usuarios --empleado mostrador \\\n"
        "      --vincular 'Ana=ana' --vincular 'Sofi=mostrador'\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", help="Slug de la óptica destino (por defecto, la base 'default').",
        )
        parser.add_argument(
            "--admin", action="append", default=[], metavar="USUARIO", dest="admins",
            help=f"Usuario con rol '{GRUPO_ADMIN}' (acceso total). Se puede repetir.",
        )
        parser.add_argument(
            "--empleado", action="append", default=[], metavar="USUARIO", dest="empleados",
            help=(
                f"Usuario con rol '{GRUPO_EMPLEADO}' (vender, mercadería, devoluciones, "
                "clientes y recetas). Se puede repetir. Sirve también para el usuario "
                "compartido del mostrador: las ventas igual quedan atribuidas a cada "
                "vendedor/a, porque se elige en cada venta."
            ),
        )
        parser.add_argument(
            "--vincular", action="append", default=[], metavar="VENDEDOR=USUARIO",
            dest="vinculos",
            help=(
                "Asocia un vendedor/a ya cargado con un usuario, para los avisos al "
                "celular. Se puede repetir. Varios vendedores pueden apuntar al mismo "
                "usuario (mostrador compartido)."
            ),
        )

    def handle(self, *args, **options):
        if options["tenant"]:
            tenant = Tenant.objects.get(slug=options["tenant"])
            alias = get_or_register_tenant_db(tenant)
        else:
            alias = "default"

        with tenant_context(alias), transaction.atomic(using=alias):
            self._configurar(options)

    def _configurar(self, options):
        vinculos = self._parsear_vinculos(options["vinculos"])

        grupo_admin, _ = Group.objects.get_or_create(name=GRUPO_ADMIN)
        grupo_empleado, _ = Group.objects.get_or_create(name=GRUPO_EMPLEADO)
        self.stdout.write(f"Roles: {GRUPO_ADMIN} y {GRUPO_EMPLEADO} listos.")

        sin_password = []

        def asegurar_usuario(username, grupo):
            usuario, creado = User.objects.get_or_create(username=username)
            if creado:
                usuario.set_unusable_password()  # se asigna aparte, nunca acá
                usuario.save()
                sin_password.append(username)
            # El rol se deja siempre consistente con lo que dice este comando.
            usuario.groups.remove(grupo_admin, grupo_empleado)
            usuario.groups.add(grupo)
            self.stdout.write(
                f"  {'creado ' if creado else 'ya existía'} {username:12} → {grupo.name}"
            )
            return usuario

        if options["admins"] or options["empleados"]:
            self.stdout.write("\nUsuarios:")
            for username in options["empleados"]:
                asegurar_usuario(username, grupo_empleado)
            for username in options["admins"]:
                asegurar_usuario(username, grupo_admin)

        if vinculos:
            self.stdout.write("\nVendedores vinculados:")
        for nombre_vendedor, username in vinculos.items():
            vendedor = Vendedor.objects.filter(nombre__iexact=nombre_vendedor).first()
            if not vendedor:
                self.stdout.write(self.style.WARNING(f"  (falta el vendedor '{nombre_vendedor}')"))
                continue
            usuario = User.objects.filter(username=username).first()
            if not usuario:
                self.stdout.write(self.style.WARNING(f"  (falta el usuario '{username}')"))
                continue
            if vendedor.usuario_id != usuario.id:
                vendedor.usuario = usuario
                vendedor.save(update_fields=["usuario"])
            self.stdout.write(f"  {vendedor.nombre:10} → {username}")

        if sin_password:
            self.stdout.write(self.style.WARNING(
                "\nUsuarios nuevos SIN contraseña (no pueden entrar hasta asignarla):"
            ))
            for username in sin_password:
                self.stdout.write(f"  python manage.py changepassword {username}")
        self.stdout.write(self.style.SUCCESS("\nListo."))

    def _parsear_vinculos(self, crudos):
        vinculos = {}
        for item in crudos:
            vendedor, sep, usuario = item.partition("=")
            vendedor, usuario = vendedor.strip(), usuario.strip()
            if not sep or not vendedor or not usuario:
                raise CommandError(f"--vincular espera 'VENDEDOR=USUARIO', recibí '{item}'.")
            vinculos[vendedor] = usuario
        return vinculos
