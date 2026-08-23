import gzip
from datetime import datetime
from io import StringIO

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from tenants.db_router import iter_tenant_aliases

# Tablas que NO se respaldan: las regenera Django solo al migrar en una base
# nueva, e incluirlas rompería la restauración (choques de claves).
EXCLUIR = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]


class Command(BaseCommand):
    help = (
        "Genera un backup de los datos (dumpdata JSON comprimido) y lo manda por "
        "email, o lo guarda en un archivo con --to-file. Pensado para correr una "
        "vez por día (cron). Usa dumpdata (Python puro): no necesita pg_dump ni "
        "nada instalado en el servidor, así que funciona en Railway sin config extra.\n\n"
        "Restaurar: gunzip el .gz y 'python manage.py loaddata backup.json' sobre "
        "una base ya migrada."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Casilla destino (por defecto, BACKUP_EMAIL del entorno).")
        parser.add_argument("--to-file", help="Guardar en este archivo en vez de mandarlo por email.")

    def _generar_backup(self, alias, slug):
        """Devuelve (nombre_archivo, bytes_gzip) con el dump de los datos de un tenant."""
        buffer = StringIO()
        call_command(
            "dumpdata",
            *[f"--exclude={app}" for app in EXCLUIR],
            "--natural-foreign", "--natural-primary",
            database=alias,
            stdout=buffer,
        )
        crudo = buffer.getvalue().encode("utf-8")
        if len(crudo) < 100:  # un dump vacío/roto no llega ni a 100 bytes
            raise CommandError(f"El backup de '{slug}' salió vacío: algo falló al generar el dump.")
        nombre = f"backup_{slug}_{datetime.now():%Y-%m-%d_%H%M}.json.gz"
        return nombre, gzip.compress(crudo)

    def handle(self, *args, **options):
        for etiqueta, alias in iter_tenant_aliases():
            self.stdout.write(f"--- {etiqueta} ---")
            self._respaldar_tenant(etiqueta, alias, options)

    def _respaldar_tenant(self, etiqueta, alias, options):
        nombre, comprimido = self._generar_backup(alias, etiqueta)
        kb = len(comprimido) / 1024
        self.stdout.write(f"Backup generado: {nombre} ({kb:.0f} KB)")

        destino_archivo = options["to_file"]
        if destino_archivo:
            with open(destino_archivo, "wb") as f:
                f.write(comprimido)
            self.stdout.write(self.style.SUCCESS(f"Guardado en {destino_archivo}"))
            return

        email = options["email"] or getattr(settings, "BACKUP_EMAIL", "")
        if not email:
            raise CommandError(
                "No hay a dónde mandarlo: pasá --email o seteá la variable BACKUP_EMAIL."
            )
        if not getattr(settings, "EMAIL_HOST", ""):
            raise CommandError(
                "El email no está configurado (falta EMAIL_HOST). Configurá el SMTP o usá --to-file."
            )

        mensaje = EmailMessage(
            subject=f"Backup {etiqueta} — {datetime.now():%d/%m/%Y %H:%M}",
            body=(
                "Backup automático de la base de datos adjunto.\n\n"
                "Para restaurar: descomprimir el .gz y correr "
                "'python manage.py loaddata <archivo.json>' sobre una base migrada."
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[email],
            connection=get_connection(),
        )
        mensaje.attach(nombre, comprimido, "application/gzip")
        enviados = mensaje.send()
        if not enviados:
            raise CommandError(f"El servidor de email no aceptó el mensaje de '{etiqueta}' (0 enviados).")
        self.stdout.write(self.style.SUCCESS(f"Backup enviado por email a {email} ({kb:.0f} KB)"))
