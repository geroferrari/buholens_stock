import re

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from tenants.db_router import get_or_register_tenant_db, tenant_context
from tenants.models import Tenant

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Command(BaseCommand):
    help = "Da de alta una óptica nueva: crea su base de datos y la migra."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Subdominio, ej: imago")
        parser.add_argument("--nombre", required=True, help="Nombre de la óptica")

    def handle(self, *args, **options):
        slug = options["slug"]
        nombre = options["nombre"]

        if not SLUG_RE.match(slug):
            raise CommandError("El slug solo puede tener minúsculas, números y guion bajo, empezando con una letra.")
        if Tenant.objects.filter(slug=slug).exists():
            raise CommandError(f"Ya existe una óptica con slug '{slug}'.")

        db_name = f"stockero_{slug}"

        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
            conn = connections["default"]
            conn.ensure_connection()
            conn.connection.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{db_name}"')
            self.stdout.write(f"Base '{db_name}' creada en Postgres.")

        tenant = Tenant.objects.create(nombre=nombre, slug=slug, db_name=db_name)

        alias = get_or_register_tenant_db(tenant)
        with tenant_context(alias):
            call_command("migrate", database=alias, interactive=False)

        self.stdout.write(self.style.SUCCESS(f"Óptica '{nombre}' ({slug}) lista."))
