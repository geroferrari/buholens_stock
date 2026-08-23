from django.urls import path

from . import views

app_name = "contact_lenses"

urlpatterns = [
    path("", views.agenda, name="agenda"),
    path("nueva/", views.PruebaCreateView.as_view(), name="prueba_nueva"),
    path("<int:pk>/", views.prueba_detalle, name="prueba_detalle"),
    path("<int:pk>/iniciar-venta/", views.iniciar_venta, name="iniciar_venta"),
    path("<int:pk>/realizada-sin-venta/", views.marcar_realizada_sin_venta, name="marcar_realizada_sin_venta"),
    path("<int:pk>/reprogramar/", views.reprogramar, name="reprogramar"),
    path("<int:pk>/cancelar/", views.marcar_cancelada, name="marcar_cancelada"),
    path("<int:pk>/editar/", views.PruebaUpdateView.as_view(), name="prueba_editar"),
    path("<int:pk>/eliminar/", views.PruebaDeleteView.as_view(), name="prueba_eliminar"),
]
