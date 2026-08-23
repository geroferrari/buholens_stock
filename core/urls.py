from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Papelera: oculta a propósito para reducir complejidad por ahora. Lo
    # borrado se sigue archivando igual (soft-delete), solo no hay UI para
    # verlo/restaurarlo. Descomentar para reactivar (junto con las tarjetas
    # en home.html/gestion.html).
    # path("papelera/", views.papelera, name="papelera"),
    # path("papelera/<str:tipo>/<int:pk>/restaurar/", views.restaurar, name="restaurar"),
    # path("papelera/<str:tipo>/<int:pk>/eliminar/", views.eliminar_definitivo, name="eliminar_definitivo"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
