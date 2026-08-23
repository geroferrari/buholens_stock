from django.urls import path

from . import views

app_name = "prescriptions"

urlpatterns = [
    path("", views.RecetaListView.as_view(), name="receta_lista"),
    path("historial-carga/", views.receta_historial, name="receta_historial"),
    path("nueva/", views.RecetaCreateView.as_view(), name="receta_nueva"),
    path("medicos/buscar/", views.buscar_medicos_json, name="buscar_medicos_json"),
    path("medicos/nuevo-rapido/", views.medico_nuevo_rapido_json, name="medico_nuevo_rapido_json"),
    path("info-cliente/", views.info_receta_cliente_json, name="info_receta_cliente_json"),
    path("<int:pk>/", views.receta_detalle, name="receta_detalle"),
    path("<int:pk>/editar/", views.RecetaUpdateView.as_view(), name="receta_editar"),
    path("<int:pk>/eliminar/", views.RecetaDeleteView.as_view(), name="receta_eliminar"),

    path("laboratorio/", views.OrdenLaboratorioListView.as_view(), name="orden_laboratorio_lista"),
    path("laboratorio/nueva/", views.orden_laboratorio_nueva, name="orden_laboratorio_nueva"),
    path("laboratorio/recetas-de-cliente/", views.recetas_de_cliente_json, name="recetas_de_cliente_json"),
    path("laboratorio/armazones/buscar/", views.buscar_armazones_json, name="buscar_armazones_json"),
    path("laboratorio/<int:pk>/", views.orden_laboratorio_imprimir, name="orden_laboratorio_imprimir"),
    path("laboratorio/<int:pk>/eliminar/", views.OrdenLaboratorioDeleteView.as_view(), name="orden_laboratorio_eliminar"),
]
