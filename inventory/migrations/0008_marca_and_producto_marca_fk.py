# Paso 1 de 3 de la migración de "marca" (texto libre -> catálogo propio):
# acá solo se crea el modelo Marca y un campo puente (marca_fk) en Producto,
# sin tocar todavía el campo viejo. Los datos se migran en el paso 2
# (0009_migrar_marcas_y_modelo.py) y recién ahí se limpian los campos viejos
# (0010_producto_cleanup_campos.py). Se separa así para no perder datos:
# no se puede "convertir" un CharField a ForeignKey en un solo paso.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_alter_producto_codigo_barras'),
    ]

    operations = [
        migrations.CreateModel(
            name='Marca',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=80, unique=True)),
            ],
            options={
                'ordering': ['nombre'],
            },
        ),
        migrations.AddField(
            model_name='proveedor',
            name='marcas',
            field=models.ManyToManyField(blank=True, help_text='Qué marcas trae este proveedor.', related_name='proveedores', to='inventory.marca'),
        ),
        migrations.AddField(
            model_name='producto',
            name='marca_fk',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='productos', to='inventory.marca'),
        ),
    ]
