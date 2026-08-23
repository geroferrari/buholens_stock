import datetime

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from contact_lenses.models import PruebaLentesContacto
from tenants.db_router import iter_tenant_aliases, tenant_context


class Command(BaseCommand):
    help = (
        "Manda el recordatorio de las pruebas de lentes de contacto agendadas para "
        "hoy, a la persona que tiene que hacer cada una. Pensado para correr una vez "
        "por día (cron). Es idempotente: una prueba ya avisada no se vuelve a avisar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha", help="Día a recordar en formato YYYY-MM-DD (por defecto, hoy).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Muestra a quién se le avisaría, sin mandar nada ni marcar como avisado.",
        )
        parser.add_argument(
            "--reenviar", action="store_true",
            help="Incluye también las que ya tenían el recordatorio enviado.",
        )

    def handle(self, *args, **options):
        for etiqueta, alias in iter_tenant_aliases():
            self.stdout.write(f"--- {etiqueta} ---")
            with tenant_context(alias):
                self._recordar(options)

    def _recordar(self, options):
        from notificaciones.services import enviar_push_a_vendedor

        if options["fecha"]:
            try:
                fecha = datetime.date.fromisoformat(options["fecha"])
            except ValueError:
                self.stderr.write(self.style.ERROR("La fecha debe tener formato YYYY-MM-DD."))
                return
        else:
            fecha = timezone.localdate()

        pruebas = PruebaLentesContacto.objects.filter(
            estado=PruebaLentesContacto.Estado.AGENDADA,
            fecha_hora__date=fecha,
        ).select_related("vendedor", "cliente").order_by("fecha_hora")
        if not options["reenviar"]:
            pruebas = pruebas.filter(recordatorio_enviado=False)

        pruebas = list(pruebas)
        self.stdout.write(f"Pruebas agendadas para {fecha:%d/%m/%Y} pendientes de recordar: {len(pruebas)}")
        if not pruebas:
            return

        avisadas = 0
        for prueba in pruebas:
            hora = timezone.localtime(prueba.fecha_hora) if timezone.is_aware(prueba.fecha_hora) else prueba.fecha_hora
            quien = prueba.vendedor.nombre if prueba.vendedor else "(sin vendedor)"
            etiqueta = f"  {hora:%H:%M} {prueba.nombre_cliente} → {quien}"

            if options["dry_run"]:
                self.stdout.write(etiqueta + "  [simulacro]")
                continue

            enviadas = enviar_push_a_vendedor(
                prueba.vendedor,
                titulo="⏰ Prueba de lentes de contacto hoy",
                cuerpo=f"{hora:%H:%M} — {prueba.nombre_cliente}",
                url=reverse("contact_lenses:prueba_detalle", args=[prueba.pk]),
            )
            if enviadas:
                # Solo se marca si el aviso salió: si falló, se reintenta en la
                # próxima corrida en vez de perderse.
                prueba.recordatorio_enviado = True
                prueba.save(update_fields=["recordatorio_enviado"])
                avisadas += 1
                self.stdout.write(self.style.SUCCESS(etiqueta + f"  ✔ ({enviadas} dispositivo/s)"))
            else:
                self.stdout.write(self.style.WARNING(
                    etiqueta + "  sin avisar (esa persona no tiene avisos activados)"
                ))

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"\nRecordatorios enviados: {avisadas}/{len(pruebas)}"))
