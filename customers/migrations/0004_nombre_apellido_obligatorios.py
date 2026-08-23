from django.db import migrations, models


def completar_nombre_faltante(apps, schema_editor):
    """Unos pocos clientes quedaron con nombre vacío y apellido cargado (por
    la heurística de separación de nombre completo en 0003, cuando el dato
    original era una sola palabra). Se copia el apellido al nombre para poder
    hacer ambos campos obligatorios sin perder el dato ya cargado."""
    Cliente = apps.get_model("customers", "Cliente")
    Cliente.objects.using(schema_editor.connection.alias).filter(nombre="").exclude(apellido="").update(nombre=models.F("apellido"))


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0003_apellido_y_validadores'),
    ]

    operations = [
        migrations.RunPython(completar_nombre_faltante, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='cliente',
            name='apellido',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='cliente',
            name='nombre',
            field=models.CharField(max_length=100),
        ),
    ]
