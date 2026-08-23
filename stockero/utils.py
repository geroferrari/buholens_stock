from django.utils import timezone


def formato_local(dt, fmt="%d/%m/%Y %H:%M"):
    """Formatea un datetime timezone-aware en el huso horario local
    (TIME_ZONE, ver settings). `dt.strftime(...)` a secas muestra la hora en
    UTC (como se guarda en la base), no la hora real: con TIME_ZONE en
    America/Argentina/Buenos_Aires (UTC-3) eso hace que todo se vea 3 horas
    "adelantado"."""
    return timezone.localtime(dt).strftime(fmt)
