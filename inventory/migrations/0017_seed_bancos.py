from django.db import migrations

BANCOS = [
    "Banco Galicia", "Banco Santander", "BBVA", "Banco Nación", "Banco Provincia",
    "Banco Macro", "Banco Ciudad", "Banco Credicoop", "Banco Comafi", "Banco Supervielle",
    "Banco Patagonia", "ICBC", "HSBC", "Banco Hipotecario", "Banco Itaú",
    "Banco Columbia", "Brubank", "Banco del Sol", "Naranja X", "Mercado Pago",
    "Ualá", "Cuenta DNI", "Personal Pay", "Reba",
]


def crear_bancos(apps, schema_editor):
    Banco = apps.get_model("inventory", "Banco")
    for nombre in BANCOS:
        Banco.objects.using(schema_editor.connection.alias).get_or_create(nombre=nombre)


def eliminar_bancos(apps, schema_editor):
    Banco = apps.get_model("inventory", "Banco")
    Banco.objects.using(schema_editor.connection.alias).filter(nombre__in=BANCOS, planes__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0016_banco_planfinanciacion"),
    ]

    operations = [
        migrations.RunPython(crear_bancos, eliminar_bancos),
    ]
