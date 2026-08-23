from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("", views.ClienteListView.as_view(), name="cliente_lista"),
    path("nuevo/", views.ClienteCreateView.as_view(), name="cliente_nuevo"),
    path("nuevo-rapido/", views.cliente_nuevo_rapido_json, name="cliente_nuevo_rapido_json"),
    path("buscar/", views.buscar_clientes_json, name="buscar_clientes_json"),
    path("<int:pk>/", views.cliente_detalle, name="cliente_detalle"),
    path("<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="cliente_editar"),
    path("<int:pk>/eliminar/", views.ClienteDeleteView.as_view(), name="cliente_eliminar"),

    path("obras-sociales/buscar/", views.buscar_obras_sociales_json, name="buscar_obras_sociales_json"),
    path("obras-sociales/nueva-rapida/", views.obra_social_nueva_rapida_json, name="obra_social_nueva_rapida_json"),
    path("obras-sociales/", views.ObraSocialListView.as_view(), name="obra_social_lista"),
    path("obras-sociales/nueva/", views.ObraSocialCreateView.as_view(), name="obra_social_nueva"),
    path("obras-sociales/<int:pk>/editar/", views.ObraSocialUpdateView.as_view(), name="obra_social_editar"),
    path("obras-sociales/<int:pk>/eliminar/", views.ObraSocialDeleteView.as_view(), name="obra_social_eliminar"),
]
