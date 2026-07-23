from django import forms

from colaboradores.models import Funcionario

from .models import Viagem


class LancamentoViagemForm(forms.ModelForm):
    class Meta:
        model = Viagem
        fields = ["funcionario", "data", "km_inicial", "km_final"]
        widgets = {
            "funcionario": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "data": forms.DateInput(
                attrs={"class": "input input-bordered w-full", "type": "date"},
                format="%Y-%m-%d",
            ),
            "km_inicial": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": 0,
                    "placeholder": "Ex.: 120340",
                }
            ),
            "km_final": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": 0,
                    "placeholder": "Ex.: 120512",
                }
            ),
        }
        labels = {
            "funcionario": "Colaborador",
            "data": "Data da viagem",
            "km_inicial": "Quilometragem inicial",
            "km_final": "Quilometragem final",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data"].input_formats = ["%Y-%m-%d"]
        # Só colaboradores ativos e vinculados a um centro de custo podem viajar.
        self.fields["funcionario"].queryset = (
            Funcionario.objects.filter(ativo=True, centro_custo__isnull=False)
            .select_related("centro_custo")
            .order_by("nome")
        )
        self.fields["funcionario"].empty_label = "Selecione um colaborador"

    def clean(self):
        cleaned = super().clean()
        km_inicial = cleaned.get("km_inicial")
        km_final = cleaned.get("km_final")

        if km_inicial is not None and km_final is not None and km_final < km_inicial:
            self.add_error(
                "km_final",
                "A quilometragem final não pode ser menor que a inicial.",
            )
        return cleaned


class FechamentoFiltroForm(forms.Form):
    data_inicio = forms.DateField(
        label="Data de início",
        widget=forms.DateInput(
            attrs={"class": "input input-bordered w-full", "type": "date"},
            format="%Y-%m-%d",
        ),
        input_formats=["%Y-%m-%d"],
    )
    data_fim = forms.DateField(
        label="Data de fim",
        widget=forms.DateInput(
            attrs={"class": "input input-bordered w-full", "type": "date"},
            format="%Y-%m-%d",
        ),
        input_formats=["%Y-%m-%d"],
    )

    def clean(self):
        cleaned = super().clean()
        data_inicio = cleaned.get("data_inicio")
        data_fim = cleaned.get("data_fim")

        if data_inicio and data_fim and data_fim < data_inicio:
            raise forms.ValidationError(
                "A data de fim não pode ser anterior à data de início."
            )
        return cleaned
