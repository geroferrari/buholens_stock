import re
from urllib.parse import quote

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from core.models import Configuracion

solo_digitos = RegexValidator(r"^\d*$", "Ingresá solo números.")


class ObraSocial(models.Model):
    nombre = models.CharField(max_length=100)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            # No dos obras sociales con el mismo nombre ignorando mayúsculas, así
            # no se cuela un duplicado tipo "Particular" / "particular". Las
            # variantes reales (ej: "OSDE 210" vs "OSDE 410") sí conviven porque
            # tienen nombres distintos.
            models.UniqueConstraint(Lower("nombre"), name="obrasocial_nombre_ci_unique"),
        ]

    def __str__(self):
        return self.nombre


class Cliente(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    dni = models.CharField(max_length=20, blank=True, unique=False, validators=[solo_digitos])
    telefono = models.CharField(max_length=40, blank=True, validators=[solo_digitos])
    email = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    obra_social = models.ForeignKey(
        ObraSocial, on_delete=models.SET_NULL, null=True, blank=True, related_name="clientes",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre", "apellido"]

    def save(self, *args, **kwargs):
        # Los números locales se suelen anotar sin la característica (ej
        # "511801"): se completan con la que esté configurada en Gestión →
        # Configuración, para que el link de WhatsApp (ver whatsapp_url) salga
        # bien armado. Si no hay ninguna configurada, el teléfono queda igual.
        self.telefono = Configuracion.actual().completar_telefono(self.telefono)
        super().save(*args, **kwargs)

    @classmethod
    def crear_rapido(cls, **datos):
        """Alta rápida (ningún campo es obligatorio) usada desde los popups
        de otras pantallas (punto de venta, receta): si vino todo vacío no
        crea nada, para no dejar clientes en blanco solo por haber tocado
        "guardar" sin cargar ningún dato."""
        if not any(str(v).strip() for v in datos.values() if v):
            return None
        return cls.objects.create(**datos)

    @classmethod
    def buscar(cls, q):
        """Búsqueda por nombre/apellido/dni/email para los autocompletar de
        cliente. Se busca palabra por palabra (cada una debe aparecer en
        nombre, apellido, dni o email) para que "Juan Perez" encuentre al
        cliente aunque "Juan Perez" completo no esté en un solo campo."""
        query = models.Q()
        for palabra in q.split():
            query &= (
                models.Q(nombre__icontains=palabra) | models.Q(apellido__icontains=palabra)
                | models.Q(dni__icontains=palabra) | models.Q(email__icontains=palabra)
            )
        return cls.objects.filter(query)

    @property
    def nombre_completo(self):
        return " ".join(p for p in [self.nombre, self.apellido] if p)

    def whatsapp_url(self, mensaje=""):
        """Link a wa.me con el teléfono normalizado (best-effort: los datos
        vienen de sistemas viejos con formatos re variados). Si no se puede
        armar un número razonable, devuelve None."""
        digitos = re.sub(r"\D", "", self.telefono or "")
        if len(digitos) < 6:
            return None
        digitos = Configuracion.actual().telefono_internacional(digitos)
        url = f"https://wa.me/{digitos}"
        if mensaje:
            url += f"?text={quote(mensaje)}"
        return url

    @property
    def whatsapp_url_anteojo_listo(self):
        saludo = f"Hola {self.nombre_completo}" if self.nombre_completo else "Hola"
        return self.whatsapp_url(f"{saludo} su anteojo ya esta en la optica listo para retirar")

    def __str__(self):
        if self.nombre_completo:
            return self.nombre_completo + (f" (DNI {self.dni})" if self.dni else "")
        if self.email:
            return self.email
        if self.dni:
            return f"DNI {self.dni}"
        return f"Cliente #{self.pk}"
