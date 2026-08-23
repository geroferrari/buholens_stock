from django.db import migrations


def fusionar_duplicados(apps, schema_editor):
    """Antes de poder exigir que nombre sea único ignorando mayúsculas, hay
    que unificar los que ya están duplicados en la base (ej: "generico" y
    "Generico"). Para cada grupo de duplicados se conserva el que tiene más
    productos asociados (el que realmente se usa) y se reasignan las
    referencias del resto antes de borrarlos."""
    db_alias = schema_editor.connection.alias
    Marca = apps.get_model("inventory", "Marca")
    Categoria = apps.get_model("inventory", "Categoria")
    Proveedor = apps.get_model("inventory", "Proveedor")
    Producto = apps.get_model("inventory", "Producto")
    OrdenCompra = apps.get_model("inventory", "OrdenCompra")

    def grupos_duplicados(qs):
        vistos = {}
        for obj in qs.order_by("id"):
            clave = obj.nombre.strip().lower()
            vistos.setdefault(clave, []).append(obj)
        return [grupo for grupo in vistos.values() if len(grupo) > 1]

    for grupo in grupos_duplicados(Marca.objects.using(db_alias).all()):
        conteos = {m.id: Producto.objects.using(db_alias).filter(marca_id=m.id).count() for m in grupo}
        keeper = max(grupo, key=lambda m: conteos[m.id])
        for dup in grupo:
            if dup.id == keeper.id:
                continue
            Producto.objects.using(db_alias).filter(marca_id=dup.id).update(marca_id=keeper.id)
            for proveedor in Proveedor.objects.using(db_alias).filter(marcas=dup.id):
                proveedor.marcas.remove(dup)
                proveedor.marcas.add(keeper)
            dup.delete()

    for grupo in grupos_duplicados(Categoria.objects.using(db_alias).all()):
        conteos = {c.id: Producto.objects.using(db_alias).filter(categoria_id=c.id).count() for c in grupo}
        keeper = max(grupo, key=lambda c: conteos[c.id])
        for dup in grupo:
            if dup.id == keeper.id:
                continue
            Producto.objects.using(db_alias).filter(categoria_id=dup.id).update(categoria_id=keeper.id)
            dup.delete()

    for grupo in grupos_duplicados(Proveedor.objects.using(db_alias).all()):
        conteos = {p.id: Producto.objects.using(db_alias).filter(proveedor_id=p.id).count() for p in grupo}
        keeper = max(grupo, key=lambda p: conteos[p.id])
        for dup in grupo:
            if dup.id == keeper.id:
                continue
            Producto.objects.using(db_alias).filter(proveedor_id=dup.id).update(proveedor_id=keeper.id)
            OrdenCompra.objects.using(db_alias).filter(proveedor_id=dup.id).update(proveedor_id=keeper.id)
            for marca in dup.marcas.all():
                keeper.marcas.add(marca)
            dup.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0018_planfinanciacion_categorias_planfinanciacion_marcas_and_more"),
    ]

    operations = [
        migrations.RunPython(fusionar_duplicados, migrations.RunPython.noop),
    ]
