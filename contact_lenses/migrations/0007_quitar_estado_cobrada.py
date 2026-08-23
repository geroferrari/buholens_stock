from django.db import migrations, models


def cobradas_a_realizadas(apps, schema_editor):
    """El estado 'Cobrada' era parte de la liquidación de comisión, que ya no
    existe. Una prueba cobrada era, antes que nada, una prueba realizada: se
    convierten a ese estado para no dejar filas con un valor fuera de choices."""
    Prueba = apps.get_model("contact_lenses", "PruebaLentesContacto")
    Prueba.objects.using(schema_editor.connection.alias).filter(estado="COB").update(estado="REA")


class Migration(migrations.Migration):

    dependencies = [
        ("contact_lenses", "0006_pruebalentescontacto_prueba_estado_fecha_idx"),
    ]

    operations = [
        migrations.RunPython(cobradas_a_realizadas, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pruebalentescontacto",
            name="estado",
            field=models.CharField(
                choices=[("AGE", "Agendada"), ("REA", "Realizada"), ("CAN", "Cancelada")],
                default="AGE", max_length=3,
            ),
        ),
    ]
