from django.db import models


class Tenant(models.Model):
    nombre = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    db_name = models.CharField(max_length=63)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre
