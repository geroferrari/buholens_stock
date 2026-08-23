import unicodedata

from django.db import migrations


def _norm(texto):
    """minúsculas y sin acentos, para comparar nombres de categoría."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def corregir(apps, schema_editor):
    """Solo los cristales y lentes de contacto trabajan con recetas; los
    armazones (incluido 'Armazón receta') NO: son solo el armazón. Corrige el
    flag según el nombre de cada categoría, dejando el resto como está."""
    Categoria = apps.get_model("inventory", "Categoria")
    for cat in Categoria.objects.using(schema_editor.connection.alias).all():
        n = _norm(cat.nombre)
        if "armaz" in n:
            nuevo = False
        elif "cristal" in n or ("lente" in n and "contacto" in n):
            nuevo = True
        else:
            continue  # otras categorías: no se tocan
        if cat.requiere_receta != nuevo:
            cat.requiere_receta = nuevo
            cat.save(update_fields=["requiere_receta"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0021_alter_categoria_requiere_receta"),
    ]

    operations = [
        migrations.RunPython(corregir, migrations.RunPython.noop),
    ]
