from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0009_venta_cuotas_saldo_venta_descuento_manual_tipo_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ventaitem',
            name='entregado',
            field=models.BooleanField(default=True, help_text='Destildar si este ítem puntual todavía no se entregó (ej: cristal a medida en el laboratorio, mientras el armazón ya se lo llevó).'),
        ),
    ]
