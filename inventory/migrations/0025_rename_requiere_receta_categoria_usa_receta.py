from django.db import migrations


class Migration(migrations.Migration):
    """El campo se llamaba 'requiere_receta' pero su significado cambió a
    'trabaja con recetas (opcional)': se renombra a 'usa_receta' para que el
    nombre no confunda. RenameField conserva los datos (no es drop + add)."""

    dependencies = [
        ("inventory", "0024_fusionar_categorias_duplicadas"),
    ]

    operations = [
        migrations.RenameField(
            model_name="categoria",
            old_name="requiere_receta",
            new_name="usa_receta",
        ),
    ]
