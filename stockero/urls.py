"""
URL configuration for stockero project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import TemplateView
from django.views.static import serve

urlpatterns = [
    path('admin-panel/', admin.site.urls),
    path('panel-gestion/', login_required(TemplateView.as_view(template_name="gestion.html")), name='gestion'),
    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('', login_required(TemplateView.as_view(template_name="home.html")), name='home'),
    # PWA: el service worker se sirve desde la raíz para que su alcance sea todo
    # el sitio (si se sirviera desde /static/ solo alcanzaría esa carpeta).
    path('sw.js', TemplateView.as_view(
        template_name="sw.js", content_type="application/javascript"), name='service_worker'),
    path('manifest.json', TemplateView.as_view(
        template_name="manifest.json", content_type="application/manifest+json"), name='manifest'),
    path('notificaciones/', include('notificaciones.urls')),
    # core trae sus rutas con el prefijo puesto (papelera/, configuracion/).
    path('', include('core.urls')),
    path('ventas/', include('sales.urls')),
    path('inventario/', include('inventory.urls')),
    path('clientes/', include('customers.urls')),
    path('recetas/', include('prescriptions.urls')),
    path('lentes-contacto/', include('contact_lenses.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # En producción servimos los archivos subidos (fotos de recetas) solo a
    # usuarios logueados. Para volúmenes chicos como este, alcanza y evita
    # exponer las recetas (datos de salud) públicamente.
    urlpatterns += [
        path(
            'media/<path:path>',
            login_required(serve),
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
