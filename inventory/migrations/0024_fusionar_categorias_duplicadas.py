import unicodedata

from django.db import migrations


def _norm(texto):
    """minúsculas, sin acentos y sin espacios de más: para detectar duplicados
    que el índice único (que solo ignora mayúsculas) deja pasar."""
    base = unicodedata.normalize("NFD", texto or "")
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return " ".join(base.lower().split())


def _tiene_acento(texto):
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", texto or ""))


def fusionar(apps, schema_editor):
    """Une categorías que son la misma salvo acentos/espacios (ej: 'Armazon Sol'
    y 'Armazón Sol'): mueve productos y promociones a una sola y borra el resto.
    Idempotente: si no hay duplicados, no hace nada."""
    db_alias = schema_editor.connection.alias
    Categoria = apps.get_model("inventory", "Categoria")
    Producto = apps.get_model("inventory", "Producto")

    grupos = {}
    for cat in Categoria.objects.using(db_alias).all():
        grupos.setdefault(_norm(cat.nombre), []).append(cat)

    for variantes in grupos.values():
        if len(variantes) < 2:
            continue
        # Se conserva la mejor escrita (con acento) y, a igualdad, la que tenga
        # más productos (menos datos que mover).
        canonica = max(
            variantes,
            key=lambda c: (_tiene_acento(c.nombre), Producto.objects.using(db_alias).filter(categoria=c).count()),
        )
        for otra in variantes:
            if otra.pk == canonica.pk:
                continue
            Producto.objects.using(db_alias).filter(categoria=otra).update(categoria=canonica)
            # M2M: promociones y planes de financiación que apuntaban a la que se borra.
            for promo in otra.promociones.all():
                promo.categorias.add(canonica)
                promo.categorias.remove(otra)
            for plan in otra.planes_financiacion.all():
                plan.categorias.add(canonica)
                plan.categorias.remove(otra)
            otra.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0023_alter_ordencompra_options"),
    ]

    operations = [
        # No tiene reversa: una vez fusionadas, no se sabe qué producto era de
        # cuál de las categorías duplicadas.
        migrations.RunPython(fusionar, migrations.RunPython.noop),
    ]
