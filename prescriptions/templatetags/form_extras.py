from decimal import Decimal

from django import template

register = template.Library()

# Campos de esférico/cilíndrico/adición, donde el signo (+/-) es significativo
# y se quiere mostrar explícito. Se reusa tanto en la vista de solo lectura
# como en el formulario de carga (para marcar el input con el "+" al tipear).
CAMPOS_CON_SIGNO = {
    "lejos_od_esfera", "lejos_od_cilindro", "lejos_od_adicion",
    "lejos_oi_esfera", "lejos_oi_cilindro", "lejos_oi_adicion",
    "cerca_od_esfera", "cerca_od_cilindro",
    "cerca_oi_esfera", "cerca_oi_cilindro",
}


@register.filter
def es_campo_con_signo(nombre_campo):
    return nombre_campo in CAMPOS_CON_SIGNO


@register.filter
def signo(valor):
    """Antepone '+' a los valores positivos (esfera/cilindro/adición), para
    que quede explícito igual que en una receta oftalmológica real."""
    if valor in (None, ""):
        return valor
    numero = Decimal(valor) if isinstance(valor, str) else valor
    return f"{numero:+.2f}" if numero > 0 else str(numero)


@register.filter
def clase_signo(valor):
    """Clase CSS para pintar en verde/rojo un valor ya formateado con signo
    (ej: '+1.25' o '-1.25'), en la vista de solo lectura de la receta."""
    valor = str(valor)
    if valor.startswith("+"):
        return "signo-positivo"
    if valor.startswith("-"):
        return "signo-negativo"
    return ""


@register.filter
def split(value, sep=","):
    return value.split(sep)


@register.filter(name="field")
def get_field(form, name):
    return form[name]


@register.filter
def field_label(form, name):
    return form[name].label


@register.filter
def field_errors(form, name):
    return form[name].errors
