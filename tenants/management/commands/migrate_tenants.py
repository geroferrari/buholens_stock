from django.core.management import call_command
from django.core.management.base import BaseCommand

from tenants.db_router import get_or_register_tenant_db, tenant_context
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Corre las migraciones en la base de cada óptica activa."

    def handle(self, *args, **options):
        for tenant in Tenant.objects.filter(activo=True):
            alias = get_or_register_tenant_db(tenant)
            self.stdout.write(f"Migrando '{tenant.slug}'...")
            with tenant_context(alias):
                call_command("migrate", database=alias, interactive=False)
