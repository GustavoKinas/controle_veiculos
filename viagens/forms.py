from django import forms

from colaboradores.models import Funcionario

from .models import ReservaViagem, Viagem, Veiculo


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
            # Opcional desde a fase 3: em branco registra a saída e deixa a
            # viagem em andamento (o `required` vem do modelo, que agora
            # aceita km_final nulo).
            "km_final": forms.NumberInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "min": 0,
                    "placeholder": "Em branco = veículo ainda na rua",
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


class ReservaManualForm(forms.ModelForm):
    """
    Cadastro de reserva direto no painel, sem passar pelo Outlook.

    Existe porque nem toda reserva nasce numa agenda: alguém liga para a
    portaria, o carro é pedido na hora, ou a caixa de recurso está fora do ar.
    O campo `origem` fica em `MANUAL` (o padrão do modelo) e `id_externo`
    segue vazio — é isso que impede o sync de tratar esta reserva como um
    evento que "sumiu do Outlook" e cancelá-la na rodada seguinte.

    `funcionario` é obrigatório aqui, ao contrário do modelo: quem cadastra na
    mão sabe para quem é. O campo é opcional no banco por causa do Outlook,
    que às vezes não permite identificar o solicitante.
    """

    class Meta:
        model = ReservaViagem
        fields = ["funcionario", "veiculo", "data", "hora_inicio", "hora_fim", "destino"]
        widgets = {
            "funcionario": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "veiculo": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "data": forms.DateInput(
                attrs={"class": "input input-bordered w-full", "type": "date"},
                format="%Y-%m-%d",
            ),
            "hora_inicio": forms.TimeInput(
                attrs={"class": "input input-bordered w-full", "type": "time"},
                format="%H:%M",
            ),
            "hora_fim": forms.TimeInput(
                attrs={"class": "input input-bordered w-full", "type": "time"},
                format="%H:%M",
            ),
            "destino": forms.TextInput(
                attrs={
                    "class": "input input-bordered w-full",
                    "placeholder": "Ex.: Visita a cliente",
                }
            ),
        }
        labels = {
            "funcionario": "Colaborador",
            "veiculo": "Veículo",
            "data": "Data da reserva",
            "hora_inicio": "Horário de início",
            "hora_fim": "Horário de fim",
            "destino": "Destino",
        }
        help_texts = {
            "hora_inicio": "Deixe as duas horas em branco para reserva de dia inteiro.",
            "destino": "Opcional.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data"].input_formats = ["%Y-%m-%d"]
        self.fields["hora_inicio"].input_formats = ["%H:%M"]
        self.fields["hora_fim"].input_formats = ["%H:%M"]

        # Mesma regra do lançamento: só viaja quem está ativo e tem centro de
        # custo, porque é o centro de custo que recebe o rateio depois.
        self.fields["funcionario"].queryset = (
            Funcionario.objects.filter(ativo=True, centro_custo__isnull=False)
            .select_related("centro_custo")
            .order_by("nome")
        )
        self.fields["funcionario"].required = True
        self.fields["funcionario"].empty_label = "Selecione um colaborador"

        self.fields["veiculo"].queryset = Veiculo.objects.filter(ativo=True).order_by(
            "placa"
        )
        self.fields["veiculo"].empty_label = "Selecione um veículo"

    def clean(self):
        cleaned = super().clean()
        hora_inicio = cleaned.get("hora_inicio")
        hora_fim = cleaned.get("hora_fim")

        # Uma hora só é ambíguo: não dá para dizer se é dia inteiro ou se
        # faltou preencher. O modelo não barra isso (o Outlook manda eventos
        # com as duas nulas), então a exigência é do formulário.
        if bool(hora_inicio) != bool(hora_fim):
            self.add_error(
                "hora_fim" if hora_inicio else "hora_inicio",
                "Informe os dois horários ou deixe ambos em branco (dia inteiro).",
            )

        return cleaned

    # A coerência entre os horários e o veículo inativo ficam em
    # `ReservaViagem.clean()`, executado pelo `_post_clean()` do ModelForm —
    # assim valem também para o admin e para qualquer full_clean().


class LancamentoDeReservaForm(forms.Form):
    """
    Conclusão de uma reserva. **Não é ModelForm de propósito.**

    Colaborador, veículo e data vêm da reserva, lidos no servidor. Se fossem
    campos do formulário — mesmo `hidden` ou `disabled` — bastaria editar o
    HTML para lançar viagem em nome de outra pessoa, em outro carro. O usuário
    só contribui com a quilometragem.

    A única exceção é `funcionario`, e só quando a reserva veio do Outlook sem
    colaborador identificado: aí a informação não existe no sistema e quem
    sabe é o operador.

    `km_final` é opcional — é o que faz um formulário só atender os dois
    fluxos: preenchido = viagem concluída (Fluxo B); vazio = saída registrada,
    viagem em andamento (Fluxo A).
    """

    km_inicial = forms.IntegerField(
        label="Quilometragem inicial",
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "placeholder": "Ex.: 120340"}
        ),
    )
    km_final = forms.IntegerField(
        label="Quilometragem final",
        min_value=0,
        required=False,
        help_text="Deixe em branco se o veículo ainda não retornou.",
        widget=forms.NumberInput(
            attrs={"class": "input input-bordered w-full", "placeholder": "Opcional"}
        ),
    )
    funcionario = forms.ModelChoiceField(
        queryset=Funcionario.objects.none(),
        label="Colaborador",
        required=False,
        empty_label="Selecione um colaborador",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, *args, reserva=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reserva = reserva

        # Reserva com colaborador identificado: o campo não deve nem existir,
        # para que não haja o que adulterar. Reserva sem: vira obrigatório.
        if reserva is not None and reserva.funcionario_id:
            del self.fields["funcionario"]
        else:
            self.fields["funcionario"].required = True
            self.fields["funcionario"].queryset = (
                Funcionario.objects.filter(ativo=True, centro_custo__isnull=False)
                .select_related("centro_custo")
                .order_by("nome")
            )

    def clean(self):
        cleaned = super().clean()
        km_inicial = cleaned.get("km_inicial")
        km_final = cleaned.get("km_final")

        # Comparação barata que evita ida ao banco; as regras de piso e teto
        # ficam no modelo, que é o único caminho por onde todos passam.
        if km_inicial is not None and km_final is not None and km_final <= km_inicial:
            self.add_error(
                "km_final", "A quilometragem final deve ser maior que a inicial."
            )
        return cleaned


class RegistrarChegadaForm(forms.Form):
    """Segunda etapa do Fluxo A: só a quilometragem de retorno."""

    km_final = forms.IntegerField(
        label="Quilometragem final",
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                "class": "input input-bordered w-full",
                "placeholder": "KM do painel na chegada",
                "autofocus": "autofocus",
            }
        ),
    )


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
