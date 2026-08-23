from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("papelera/", views.papelera, name="papelera"),
    path("papelera/<str:tipo>/<int:pk>/restaurar/", views.restaurar, name="restaurar"),
    path("papelera/<str:tipo>/<int:pk>/eliminar/", views.eliminar_definitivo, name="eliminar_definitivo"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
