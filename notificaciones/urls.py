from django.urls import path

from . import views

app_name = "notificaciones"

urlpatterns = [
    path("estado/", views.estado_push, name="estado_push"),
    path("suscribir/", views.suscribir, name="suscribir"),
    path("desuscribir/", views.desuscribir, name="desuscribir"),
    path("probar/", views.probar, name="probar"),
]
