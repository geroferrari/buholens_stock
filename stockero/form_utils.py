from django import forms


class BootstrapFormMixin:
    """Agrega clases de Bootstrap a los widgets automáticamente, sin tener que
    declararlas a mano en cada Meta.widgets de cada formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault("class", "form-control")
            else:
                widget.attrs.setdefault("class", "form-control")


class BootstrapModelForm(BootstrapFormMixin, forms.ModelForm):
    pass
