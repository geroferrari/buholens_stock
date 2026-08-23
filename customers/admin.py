from django.contrib import admin

from .models import Cliente, ObraSocial


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "dni", "telefono", "email", "obra_social")
    search_fields = ("nombre", "apellido", "dni", "telefono", "email")


@admin.register(ObraSocial)
class ObraSocialAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa")
    search_fields = ("nombre",)
