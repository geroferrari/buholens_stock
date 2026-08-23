# Copia Venta.entregado (a nivel de toda la venta) a cada uno de sus items,
# antes de borrar ese campo de Venta (ahora se controla item por item).
from django.db import migrations


def backfill(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Venta = apps.get_model('sales', 'Venta')
    VentaItem = apps.get_model('sales', 'VentaItem')
    for venta in Venta.objects.using(db_alias).filter(entregado=False).iterator():
        VentaItem.objects.using(db_alias).filter(venta=venta).update(entregado=False)


def revertir(apps, schema_editor):
    pass  # no hace falta: al revertir se vuelve a agregar Venta.entregado=True por default


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_ventaitem_entregado'),
    ]

    operations = [
        migrations.RunPython(backfill, revertir),
    ]
