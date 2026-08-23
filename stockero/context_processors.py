from core.models import Configuracion

from .permissions import es_administrador


def rol_usuario(request):
    user = getattr(request, "user", None)
    return {"es_admin": es_administrador(user)}


def configuracion(request):
    """Deja los datos de la óptica (nombre, logo, color, contacto) disponibles en
    TODAS las plantillas como `optica`. Es lo que hace que la app no tenga ningún
    nombre de óptica escrito en el código."""
    return {"optica": Configuracion.actual()}
