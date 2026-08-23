# Paso 3 de 3: ya con los datos migrados (0009), se borra el campo viejo
# "marca" (texto) y se renombra "marca_fk" a "marca". También se borran los
# campos que se dejan de usar: codigo_patilla (ya copiado a modelo), talle,
# grupo, sexo, rango_edad y descripcion.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_migrar_marcas_y_modelo'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='producto',
            name='marca',
        ),
        migrations.RenameField(
            model_name='producto',
            old_name='marca_fk',
            new_name='marca',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='codigo_patilla',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='talle',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='grupo',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='sexo',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='rango_edad',
        ),
        migrations.RemoveField(
            model_name='producto',
            name='descripcion',
        ),
        migrations.AlterModelOptions(
            name='producto',
            options={'ordering': ['categoria', 'marca__nombre', 'modelo']},
        ),
    ]
