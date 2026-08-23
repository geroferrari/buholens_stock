from django.db import migrations


def fusionar(apps, schema_editor):
    """Une obras sociales que son la misma salvo mayúsculas/espacios (ej:
    'Particular' y 'particular'): reasigna clientes y ventas a una sola y borra
    el resto. Idempotente. NO toca variantes con nombres realmente distintos
    (ej: 'OSDE' vs 'OSDE 210'). Corre antes de crear el índice único
    case-insensitive, para que no falle si había duplicados."""
    db_alias = schema_editor.connection.alias
    ObraSocial = apps.get_model("customers", "ObraSocial")
    Cliente = apps.get_model("customers", "Cliente")
    Venta = apps.get_model("sales", "Venta")

    grupos = {}
    for os in ObraSocial.objects.using(db_alias).all():
        clave = " ".join(os.nombre.lower().split())  # minúsculas + espacios normalizados
        grupos.setdefault(clave, []).append(os)

    for variantes in grupos.values():
        if len(variantes) < 2:
            continue
        # Se conserva la mejor escrita (con alguna mayúscula) y, a igualdad, la
        # más usada; el resto se fusiona en esa.
        def puntaje(os):
            usos = (
                Cliente.objects.using(db_alias).filter(obra_social=os).count()
                + Venta.objects.using(db_alias).filter(obra_social=os).count()
            )
            return (os.nombre != os.nombre.lower(), usos)

        canonica = max(variantes, key=puntaje)
        for otra in variantes:
            if otra.pk == canonica.pk:
                continue
            Cliente.objects.using(db_alias).filter(obra_social=otra).update(obra_social=canonica)
            Venta.objects.using(db_alias).filter(obra_social=otra).update(obra_social=canonica)
            otra.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0006_sembrar_obras_sociales"),
        # La reasignación toca Venta.obra_social, que existe desde esta migración.
        ("sales", "0017_venta_obra_social"),
    ]

    operations = [
        migrations.RunPython(fusionar, migrations.RunPython.noop),
    ]
