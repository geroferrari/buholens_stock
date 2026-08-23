# Paso 2 de 3: migración de datos (no toca el esquema).
# - Crea un Marca por cada valor distinto que había en Producto.marca (texto
#   libre) y lo enlaza vía marca_fk, sin perder la marca de ningún producto.
# - Copia codigo_patilla -> modelo en los productos que no tengan modelo
#   cargado, porque en la práctica eran el mismo dato (el código que venía
#   impreso en la patilla) y el campo modelo quedará como el único.
# - Fusiona categorías duplicadas del import legado: "Accesorios y Otros" en
#   "Accesorios" y "Armazón Receta Multifocal" en "Armazón Receta", moviendo
#   los productos antes de borrar la categoría vieja (si no, no se puede
#   borrar por la FK protegida).
from django.db import migrations
from django.db.models import F


def migrar_datos(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Producto = apps.get_model('inventory', 'Producto')
    Marca = apps.get_model('inventory', 'Marca')
    Categoria = apps.get_model('inventory', 'Categoria')

    # --- marca (texto) -> marca_fk ---
    marcas_cache = {}
    productos_con_marca = Producto.objects.using(db_alias).exclude(marca='').exclude(marca__isnull=True).only('id', 'marca')
    for producto in productos_con_marca.iterator():
        nombre = producto.marca.strip()
        if not nombre:
            continue
        marca = marcas_cache.get(nombre.lower())
        if marca is None:
            marca, _ = Marca.objects.using(db_alias).get_or_create(nombre=nombre)
            marcas_cache[nombre.lower()] = marca
        producto.marca_fk_id = marca.id
        producto.save(update_fields=['marca_fk'])

    # --- codigo_patilla -> modelo (solo donde modelo está vacío) ---
    Producto.objects.using(db_alias).filter(modelo='').exclude(codigo_patilla='').update(modelo=F('codigo_patilla'))

    # --- fusión de categorías duplicadas del import legado ---
    fusiones = [
        ('Accesorios y Otros', 'Accesorios'),
        ('Armazón Receta Multifocal', 'Armazón Receta'),
    ]
    for nombre_vieja, nombre_nueva in fusiones:
        vieja = Categoria.objects.using(db_alias).filter(nombre=nombre_vieja).first()
        if not vieja:
            continue
        nueva, _ = Categoria.objects.using(db_alias).get_or_create(
            nombre=nombre_nueva,
            defaults={'requiere_receta': vieja.requiere_receta, 'controla_stock': vieja.controla_stock},
        )
        Producto.objects.using(db_alias).filter(categoria=vieja).update(categoria=nueva)
        vieja.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_marca_and_producto_marca_fk'),
    ]

    operations = [
        migrations.RunPython(migrar_datos, migrations.RunPython.noop),
    ]
