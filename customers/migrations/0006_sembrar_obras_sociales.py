from django.db import migrations

# Lista estándar de obras sociales / prepagas usadas en Argentina, para que el
# desplegable de la venta tenga de dónde elegir desde el arranque. Se pueden
# editar / desactivar / borrar / agregar desde Gestión → Obras sociales.
OBRAS_SOCIALES = [
    "OSDE",
    "Swiss Medical",
    "Galeno",
    "Medicus",
    "OMINT",
    "Medifé",
    "Avalian",
    "Sancor Salud",
    "Prevención Salud",
    "PAMI",
    "IOMA",
    "OSECAC",
    "Unión Personal",
    "Jerárquicos Salud",
    "Federada Salud",
    "OSPRERA",
    "OSPE",
    "Accord Salud",
    "Hospital Italiano",
    "Particular",
]


def sembrar(apps, schema_editor):
    ObraSocial = apps.get_model("customers", "ObraSocial")
    for nombre in OBRAS_SOCIALES:
        # get_or_create para no pisar nada si alguna ya existía (idempotente).
        ObraSocial.objects.using(schema_editor.connection.alias).get_or_create(nombre=nombre, defaults={"activa": True})


def revertir(apps, schema_editor):
    # Solo borra las que sembramos y que no estén en uso por ninguna venta/cliente.
    ObraSocial = apps.get_model("customers", "ObraSocial")
    for nombre in OBRAS_SOCIALES:
        obra = ObraSocial.objects.using(schema_editor.connection.alias).filter(nombre=nombre).first()
        if obra and not obra.clientes.exists() and not obra.ventas.exists():
            obra.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0005_obra_social"),
        # La reversa toca ObraSocial.ventas, que existe recién con la FK de la venta.
        ("sales", "0017_venta_obra_social"),
    ]

    operations = [
        migrations.RunPython(sembrar, revertir),
    ]
