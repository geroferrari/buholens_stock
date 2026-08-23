from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0011_backfill_ventaitem_entregado'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='venta',
            name='entregado',
        ),
    ]
