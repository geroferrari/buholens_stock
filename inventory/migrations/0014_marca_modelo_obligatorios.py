import django.db.models.deletion
from django.db import migrations, models


def asignar_marca_faltante(apps, schema_editor):
    """Antes de exigir marca en todos los productos, a los que no la tengan
    cargada se les asigna una marca genérica "Sin marca" para no perder el
    producto ni inventar un dato que no tenemos."""
    db_alias = schema_editor.connection.alias
    Marca = apps.get_model("inventory", "Marca")
    Producto = apps.get_model("inventory", "Producto")
    sin_marca_qs = Producto.objects.using(db_alias).filter(marca__isnull=True)
    if sin_marca_qs.exists():
        marca_generica, _ = Marca.objects.using(db_alias).get_or_create(nombre="Sin marca")
        sin_marca_qs.update(marca=marca_generica)


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_alter_promocion_tipo_descuento_alter_promocion_valor'),
    ]

    operations = [
        migrations.RunPython(asignar_marca_faltante, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='producto',
            name='marca',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='productos', to='inventory.marca'
            ),
        ),
        migrations.AlterField(
            model_name='producto',
            name='modelo',
            field=models.CharField(max_length=80),
        ),
    ]
