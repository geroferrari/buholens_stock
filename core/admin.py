from django.contrib import admin


def _solo_superusers(request):
    return bool(request.user.is_active and request.user.is_superuser)


admin.site.has_permission = _solo_superusers
