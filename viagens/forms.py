from django import forms

from colaboradores.models import Funcionario

from .models import Viagem, Veiculo


class LancamentoViagemForm(forms.ModelForm):
    class Meta:
        model = Viagem
        fields = ["funcionario", "veiculo", "data", "km_inicial", "km_final"]
        widgets = {
            "funcionario": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "data": forms.DateInput(
                attrs={"class": "input input-bordered w-full", "type": "date"},
                format="%Y-%m-%d",
            ),
            "veiculo": forms.Select(
                attrs={"class": "select select-bordered w-full"}
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
            "veiculo" :"Veiculo Utilizado",
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

        self.fields["veiculo"].queryset = Veiculo.objects.filter(ativo=True).order_by("placa")
        self.fields["veiculo"].empty_label = "Selecione um veículo"

    # A validação de quilometragem vive em Viagem.clean() e é executada pelo
    # _post_clean() do ModelForm — assim vale também para o admin e para
    # qualquer full_clean(). Os erros já vêm endereçados a km_inicial/km_final.


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
