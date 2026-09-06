from core.models import Configuracion
from tenants.db_router import tenant_has_feature

from .permissions import es_administrador


def rol_usuario(request):
    user = getattr(request, "user", None)
    return {"es_admin": es_administrador(user)}


def features(request):
    """Deja `tenant_has_feature` disponible en todas las plantillas para
    activar/desactivar cosas de UI por óptica: {% if tenant_has_feature("x") %}."""
    return {"tenant_has_feature": tenant_has_feature}


def configuracion(request):
    """Deja los datos de la óptica (nombre, color, contacto) disponibles en
    TODAS las plantillas como `optica`. Es lo que hace que la app no tenga ningún
    nombre de óptica escrito en el código."""
    return {"optica": Configuracion.actual()}
