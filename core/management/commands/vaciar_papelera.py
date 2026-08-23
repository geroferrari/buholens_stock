import datetime

from django.conf import settings
from django.db.models import ProtectedError
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import Producto
from prescriptions.models import Receta
from sales.models import Venta
from tenants.db_router import iter_tenant_aliases, tenant_context

MODELOS = [("recetas", Receta), ("productos", Producto), ("ventas", Venta)]


class Command(BaseCommand):
    help = (
        "Elimina definitivamente lo que está en la papelera hace más de N días "
        "(PAPELERA_DIAS_RETENCION, por defecto 7). Pensado para correr una vez "
        "por día (cron). Lo que sigue en uso por otros registros no se borra: "
        "queda oculto en la papelera."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, help="Sobrescribe los días de retención para esta corrida.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Muestra qué se borraría, sin borrar.",
        )

    def handle(self, *args, **options):
        for etiqueta, alias in iter_tenant_aliases():
            self.stdout.write(f"--- {etiqueta} ---")
            with tenant_context(alias):
                self._purgar(options)

    def _purgar(self, options):
        dias = options["dias"] if options["dias"] is not None else settings.PAPELERA_DIAS_RETENCION
        limite = timezone.now() - datetime.timedelta(days=dias)
        self.stdout.write(f"Purgando lo borrado antes de {timezone.localtime(limite):%d/%m/%Y %H:%M} "
                          f"(retención: {dias} días).")

        total_borrado = 0
        for etiqueta, Modelo in MODELOS:
            viejos = Modelo.con_eliminados.filter(eliminado_en__isnull=False, eliminado_en__lt=limite)
            borrados = protegidos = 0
            for obj in viejos:
                if options["dry_run"]:
                    borrados += 1
                    continue
                try:
                    obj.eliminar_definitivo()
                    borrados += 1
                except ProtectedError:
                    protegidos += 1
            total_borrado += borrados
            extra = f" ({protegidos} siguen en uso, no se borran)" if protegidos else ""
            verbo = "se borrarían" if options["dry_run"] else "borradas"
            self.stdout.write(f"  {etiqueta}: {borrados} {verbo}{extra}")

        self.stdout.write(self.style.SUCCESS(f"Listo. Total: {total_borrado}."))
