from django.contrib import admin

from .models import SuscripcionPush


@admin.register(SuscripcionPush)
class SuscripcionPushAdmin(admin.ModelAdmin):
    list_display = ("usuario", "dispositivo", "creado")
    search_fields = ("usuario__username", "dispositivo")
