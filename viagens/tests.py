"""
Suíte de testes do app `viagens` — ESQUELETO PARA ESTUDO.

Como usar
---------
1. Rode `python manage.py test viagens`. Tudo aparece como **skipped**: um
   teste vazio que "passa" é pior que nenhum teste, então cada TODO chama
   `self.skipTest(...)` até você implementá-lo.
2. Implemente um método por vez, apagando o `self.skipTest`. O objetivo é
   sempre: **ver o teste falhar antes de vê-lo passar** (quebre o código de
   propósito e confirme que o teste acusa).
3. Dois testes já vêm implementados como referência de estilo — um de modelo
   (`test_km_final_menor_ou_igual_ao_inicial_e_rejeitada`) e um de view
   (`test_post_lanca_viagem_e_registra_lancada_por`). Copie a estrutura deles.

A lição que atravessa o arquivo inteiro
---------------------------------------
`Model.save()` NÃO valida. `Viagem.objects.create(km_final=1, km_inicial=999)`
grava sem reclamar. Quem dispara as regras é `full_clean()` — chamado pelos
formulários (via `_post_clean`) e pelo admin, nunca pelo ORM puro. Por isso:

- para testar REGRA DE NEGÓCIO  → use `viagem.full_clean()` ou o Form;
- para MONTAR CENÁRIO no banco  → use `Viagem.objects.create(...)` à vontade.

Referências: `viagens/services.py`, `viagens/models.py`, `viagens/forms.py`.
"""

from datetime import date, timedelta
from unittest import expectedFailure

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from colaboradores.models import CentroCusto, Funcionario

from .forms import LancamentoViagemForm
from .models import ReservaViagem, Veiculo, Viagem
from .services import montar_calendario


class BaseViagensTest(TestCase):
    """
    Fixtures compartilhadas.

    `setUpTestData` roda UMA vez por classe (dentro de uma transação que sofre
    rollback ao fim de cada teste) — bem mais rápido que `setUp`, que roda a
    cada método. Use `setUp` só quando cada teste precisar de objetos novos.
    """

    @classmethod
    def setUpTestData(cls):
        cls.cc_ti = CentroCusto.objects.create(codigo="1012201006", descricao="TI")
        cls.cc_projetos = CentroCusto.objects.create(
            codigo="1011105012", descricao="Projetos"
        )

        cls.portaria = Funcionario.objects.create(username="portaria", nome="PORTARIA")
        cls.funcionario = Funcionario.objects.create(
            username="adriano",
            nome="ADRIANO AMBROSIO BODNAR",
            centro_custo=cls.cc_projetos,
            ativo=True,
        )
        cls.funcionario_sem_cc = Funcionario.objects.create(
            username="sem.cc", nome="SEM CENTRO DE CUSTO", ativo=True
        )
        cls.funcionario_inativo = Funcionario.objects.create(
            username="inativo", nome="INATIVO", centro_custo=cls.cc_ti, ativo=False
        )

        cls.strada = Veiculo.objects.create(
            placa="RLN1J19", modelo="STRADA", marca="FIAT", km_atual=100000
        )
        cls.cronos = Veiculo.objects.create(
            placa="SXB9B09", modelo="CRONOS", marca="FIAT", km_atual=105000
        )

    # -- helpers -----------------------------------------------------------
    def nova_viagem(self, **kwargs) -> Viagem:
        """Instância NÃO salva, com defaults válidos. Sobrescreva o que importa."""
        dados = {
            "funcionario": self.funcionario,
            "veiculo": self.strada,
            "centro_custo": self.cc_projetos,
            "data": date(2026, 8, 3),
            "km_inicial": 100000,
            "km_final": 100005,
        }
        dados.update(kwargs)
        return Viagem(**dados)

    def criar_viagem(self, **kwargs) -> Viagem:
        """Grava direto no banco (sem validar) — para montar cenário."""
        viagem = self.nova_viagem(**kwargs)
        viagem.save()
        return viagem

    def dados_form(self, **kwargs) -> dict:
        """POST pronto para `LancamentoViagemForm` / a view de lançamento."""
        dados = {
            "funcionario": self.funcionario.pk,
            "veiculo": self.strada.pk,
            "data": "2026-08-03",
            "km_inicial": 100000,
            "km_final": 100005,
        }
        dados.update(kwargs)
        return dados


# =========================================================================
# 1. Regras de quilometragem — services.validar_quilometragem
# =========================================================================
class ValidacaoQuilometragemTest(BaseViagensTest):
    """Piso, teto e a regra básica km_final > km_inicial."""

    def test_km_final_menor_ou_igual_ao_inicial_e_rejeitada(self):
        """EXEMPLO IMPLEMENTADO — use como modelo para os demais."""
        viagem = self.nova_viagem(km_inicial=100000, km_final=100000)

        with self.assertRaises(ValidationError) as ctx:
            viagem.full_clean()

        # O erro tem que cair NO CAMPO certo, não como erro geral do form.
        self.assertIn("km_final", ctx.exception.message_dict)

    def test_km_inicial_abaixo_do_maior_km_registrado_e_rejeitada(self):
        """O bug original: viagem de 06/08 iniciando em 98.700 com 104.300 já rodados."""
        # TODO: crie viagens até 104300 e tente lançar uma posterior com km_inicial menor.
        #       Confirme que a mensagem cita o piso e que o erro está em "km_inicial".
        self.skipTest("TODO")

    def test_primeira_viagem_do_veiculo_usa_km_atual_como_piso(self):
        """Veículo sem viagens: o piso é o hodômetro do cadastro."""
        # TODO: self.strada tem km_atual=100000 e nenhuma viagem. Tente 99999 -> erro.
        self.skipTest("TODO")

    def test_viagem_retroativa_nao_pode_invadir_lancamento_posterior(self):
        """Regra do teto: km_final não passa do km_inicial da viagem seguinte."""
        # TODO: crie uma viagem em 06/08 iniciando em 104300 e tente lançar
        #       uma em 04/08 terminando em 108000.
        self.skipTest("TODO")

    def test_viagem_retroativa_dentro_da_folga_e_aceita(self):
        """Se sobra intervalo entre dois lançamentos, o retroativo cabe."""
        # TODO: viagens 03/08 (…->100005) e 05/08 (103000->…) deixam a folga
        #       100005..103000. Uma viagem em 04/08 dentro dela deve passar.
        self.skipTest("TODO")

    def test_veiculo_com_viagens_apenas_futuras_nao_usa_km_atual_como_piso(self):
        """Sem este cuidado, um lançamento retroativo legítimo seria barrado."""
        # TODO: cronos com uma viagem em 04/08; lance uma em 01/08 com km menor.
        self.skipTest("TODO")

    def test_edicao_nao_conflita_com_a_propria_viagem(self):
        """`viagem_id` existe para excluir a própria linha da comparação."""
        # TODO: crie, altere o km_final para mais e chame full_clean() de novo.
        self.skipTest("TODO")

# =========================================================================
# 2. Hodômetro do veículo — services.atualizar_km_veiculo + signal
# =========================================================================
class HodometroVeiculoTest(BaseViagensTest):
    """O `km_atual` acompanha as viagens para cima E para baixo."""

    def test_save_de_viagem_sobe_o_km_atual(self):
        # TODO: crie uma viagem terminando em 107000 e confira `refresh_from_db`.
        self.skipTest("TODO")

    def test_exclusao_da_maior_viagem_baixa_o_km_atual(self):
        """Sem o post_delete, o hodômetro ficaria inflado e barraria lançamentos."""
        # TODO: duas viagens; apague a maior; o km_atual volta para a menor.
        self.skipTest("TODO")

    def test_edicao_de_viagem_para_menos_baixa_o_km_atual(self):
        # TODO: por que um UPDATE condicional "só sobe" não resolveria este caso?
        self.skipTest("TODO")

    def test_exclusao_em_massa_tambem_recalcula(self):
        """`queryset.delete()` dispara post_delete por instância — confirme."""
        # TODO: use Viagem.objects.filter(...).delete().
        self.skipTest("TODO")

    def test_veiculo_sem_viagens_preserva_o_km_do_cadastro(self):
        """Apagar todas as viagens NÃO pode zerar o hodômetro informado no cadastro."""
        # TODO
        self.skipTest("TODO")


# =========================================================================
# 3. Formulário de lançamento
# =========================================================================
class LancamentoViagemFormTest(BaseViagensTest):
    def test_form_valido_congela_o_centro_de_custo_do_funcionario(self):
        # TODO: salve pelo form e confira viagem.centro_custo == cc do funcionário.
        #       Depois mude o cc do funcionário e confirme que a viagem NÃO muda.
        self.skipTest("TODO")

    def test_erro_de_regra_aparece_no_campo_e_nao_como_erro_geral(self):
        """A validação vem de Model.clean() via _post_clean — confirme o endereçamento."""
        # TODO: form inválido -> assertIn("km_inicial", form.errors)
        self.skipTest("TODO")

    def test_select_lista_apenas_colaboradores_ativos_e_com_centro_de_custo(self):
        # TODO: funcionario_inativo e funcionario_sem_cc não podem estar no queryset.
        self.skipTest("TODO")

    def test_veiculo_e_obrigatorio(self):
        """O campo é null=True no modelo, mas required=True no form. Por quê?"""
        # TODO
        self.skipTest("TODO")


# =========================================================================
# 4. Rateio — services.calcular_rateio
# =========================================================================
class CalcularRateioTest(BaseViagensTest):
    def test_soma_km_e_percentual_por_centro_de_custo(self):
        # TODO: 150 km no CC A e 250 km no CC B -> 37,50% e 62,50%.
        self.skipTest("TODO")

    def test_percentual_e_decimal_com_duas_casas(self):
        """Por que Decimal e não float? Veja _percentual em services.py."""
        # TODO: use assertEqual(linha["percentual"], Decimal("37.50")).
        self.skipTest("TODO")

    def test_viagem_fora_do_periodo_nao_entra(self):
        # TODO
        self.skipTest("TODO")

    def test_viagem_ja_fechada_nao_entra(self):
        """`fechamento IS NULL` é o que define "em aberto"."""
        # TODO
        self.skipTest("TODO")


# =========================================================================
# 5. Fechamento — services.confirmar_fechamento
# =========================================================================
class ConfirmarFechamentoTest(BaseViagensTest):
    def test_cria_snapshot_e_marca_as_viagens(self):
        # TODO: confira Fechamento.total_km, os FechamentoRateio criados e
        #       que toda viagem do período ficou com fechamento preenchido.
        self.skipTest("TODO")

    def test_segunda_passada_no_mesmo_periodo_retorna_none(self):
        """Garantia de "nunca contar duas vezes"."""
        # TODO
        self.skipTest("TODO")

    def test_periodo_sem_viagens_retorna_none(self):
        # TODO
        self.skipTest("TODO")

    def test_viagem_lancada_apos_o_fechamento_do_periodo(self):
        """
        CAÇA AOS BUGS nº 2: lance uma viagem de 03/08 DEPOIS de fechar 01–05/08.
        Documente com asserts o que acontece hoje com ela. É o comportamento
        desejado? Se não, o que você mudaria — e como avisaria o operador?
        """
        # TODO
        self.skipTest("TODO")


# =========================================================================
# 6. Views (test Client)
# =========================================================================
# Nos testes o Django força DEBUG=False, e aí o
# CompressedManifestStaticFilesStorage (WhiteNoise) exige o staticfiles.json
# gerado pelo `collectstatic` — sem ele, renderizar base.html estoura
# "Missing staticfiles manifest entry". Em teste não queremos depender de um
# passo de build, então trocamos pelo storage simples.
# `override_settings` na classe vale para todos os métodos dela e é revertido
# automaticamente ao fim — nunca altere settings "na mão" dentro de um teste.
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class ViagensViewsTest(BaseViagensTest):
    def test_post_lanca_viagem_e_registra_lancada_por(self):
        """EXEMPLO IMPLEMENTADO — modelo para os testes de view."""
        self.client.force_login(self.portaria)

        resposta = self.client.post(reverse("lancar_viagem"), self.dados_form())

        self.assertRedirects(resposta, reverse("lancar_viagem"))
        viagem = Viagem.objects.get()
        self.assertEqual(viagem.lancada_por, self.portaria)
        self.assertEqual(viagem.centro_custo, self.cc_projetos)
        self.assertEqual(viagem.km_percorrida, 5)

    def test_rotas_exigem_login(self):
        # TODO: sem login, cada rota do app deve redirecionar (302) para /login/.
        #       Dica: itere sobre uma lista de reverse(...) e use assertRedirects.
        self.skipTest("TODO")

    def test_post_invalido_nao_cria_viagem_e_reexibe_o_form(self):
        # TODO: status 200 (não redirect), Viagem.objects.count() == 0.
        self.skipTest("TODO")

    def test_exportacao_retorna_xlsx(self):
        # TODO: confira o Content-Type e o Content-Disposition (attachment).
        self.skipTest("TODO")

    def test_exportacao_de_fechamento_inexistente_retorna_404(self):
        # TODO
        self.skipTest("TODO")


# =========================================================================
# 7. Agenda / pré-cadastro (fases 1 e 2)
# =========================================================================
class ReservaViagemModelTest(BaseViagensTest):
    def test_descricao_usa_o_cadastro_quando_identificado(self):
        reserva = ReservaViagem.objects.create(
            funcionario=self.funcionario,
            solicitante_nome="ADRIANO A. BODNAR",
            veiculo=self.strada,
            data=timezone.localdate(),
        )

        self.assertEqual(reserva.descricao_solicitante, str(self.funcionario))

    def test_descricao_cai_no_texto_do_outlook_quando_nao_identificado(self):
        """O assunto do evento é texto livre e nem sempre casa com o cadastro."""
        reserva = ReservaViagem.objects.create(
            solicitante_nome="Tamara Suelen Köpp",
            veiculo=self.strada,
            data=timezone.localdate(),
        )

        self.assertIsNone(reserva.funcionario)
        self.assertEqual(reserva.descricao_solicitante, "Tamara Suelen Köpp")

    def test_reserva_pendente_com_data_passada_esta_atrasada(self):
        reserva = ReservaViagem.objects.create(
            veiculo=self.strada, data=timezone.localdate() - timedelta(days=1)
        )

        self.assertTrue(reserva.atrasada)

    def test_id_externo_repetido_na_mesma_origem_e_recusado(self):
        """Idempotência do sync: o mesmo evento não entra duas vezes."""
        dados = {
            "veiculo": self.strada,
            "data": timezone.localdate(),
            "origem": ReservaViagem.Origem.OUTLOOK,
            "id_externo": "AAMkAG-123",
        }
        ReservaViagem.objects.create(**dados)

        with self.assertRaises(IntegrityError):
            ReservaViagem.objects.create(**dados)

    def test_reservas_manuais_sem_id_externo_podem_repetir(self):
        """A constraint é parcial: só vale para quem tem id externo."""
        for _ in range(2):
            ReservaViagem.objects.create(
                veiculo=self.strada, data=timezone.localdate()
            )

        self.assertEqual(ReservaViagem.objects.count(), 2)


class MontarCalendarioTest(BaseViagensTest):
    def test_agrupa_reservas_por_dia_em_uma_unica_query(self):
        hoje = timezone.localdate()
        ReservaViagem.objects.create(veiculo=self.strada, data=hoje)
        ReservaViagem.objects.create(veiculo=self.cronos, data=hoje)

        with self.assertNumQueries(1):
            calendario = montar_calendario(hoje.year, hoje.month)

        dias = {dia: reservas for semana in calendario["semanas"] for dia, reservas in semana}
        self.assertEqual(len(dias[hoje]), 2)
        self.assertEqual(calendario["total_no_mes"], 2)

    def test_grade_cobre_semanas_inteiras(self):
        calendario = montar_calendario(2026, 8)

        self.assertTrue(all(len(semana) == 7 for semana in calendario["semanas"]))
        self.assertEqual(calendario["primeiro_dia"].weekday(), 0)   # segunda

    def test_reserva_cancelada_nao_aparece(self):
        hoje = timezone.localdate()
        ReservaViagem.objects.create(
            veiculo=self.strada, data=hoje, status=ReservaViagem.Status.CANCELADA
        )

        self.assertEqual(montar_calendario(hoje.year, hoje.month)["total_no_mes"], 0)


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class AgendaViewTest(BaseViagensTest):
    def test_exige_login(self):
        resposta = self.client.get(reverse("agenda"))

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login/", resposta["Location"])

    def test_abre_no_dia_de_hoje(self):
        self.client.force_login(self.portaria)
        hoje = timezone.localdate()
        ReservaViagem.objects.create(
            veiculo=self.strada, data=hoje, solicitante_nome="FULANO DE TAL"
        )

        resposta = self.client.get(reverse("agenda"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["dia_selecionado"], hoje)
        self.assertContains(resposta, "FULANO DE TAL")

    def test_parametros_invalidos_caem_no_padrao_sem_estourar(self):
        """`?dia=` e `?mes=` são entrada do usuário: nunca podem virar 500."""
        self.client.force_login(self.portaria)

        resposta = self.client.get(
            reverse("agenda"), {"dia": "ontem", "ano": "abc", "mes": "13"}
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["dia_selecionado"], timezone.localdate())

    def test_dia_selecionado_filtra_a_fila(self):
        self.client.force_login(self.portaria)
        amanha = timezone.localdate() + timedelta(days=1)
        ReservaViagem.objects.create(veiculo=self.strada, data=amanha)

        resposta = self.client.get(reverse("agenda"), {"dia": amanha.isoformat()})

        self.assertEqual(resposta.context["dia_selecionado"], amanha)
        self.assertEqual(len(resposta.context["reservas_do_dia"]), 1)


# =========================================================================
# 8. Lacunas conhecidas (caça aos bugs)
#
# `@expectedFailure` = "este teste descreve o comportamento CORRETO, que o
# código ainda não tem". A suíte segue verde, mas a dívida fica documentada
# em código executável — e no dia em que você corrigir o bug, o runner acusa
# "unexpected success" e te obriga a remover o decorador. Muito melhor que um
# TODO solto num comentário.
# =========================================================================
class LacunasConhecidasTest(BaseViagensTest):
    def test_viagem_com_data_futura_e_rejeitada(self):
        """Camada 2: a viagem é lançada depois de acontecer, nunca antes."""
        viagem = self.nova_viagem(data=timezone.localdate() + timedelta(days=1))

        with self.assertRaises(ValidationError) as ctx:
            viagem.full_clean()

        self.assertIn("data", ctx.exception.message_dict)

    def test_data_vazia_nao_estoura_a_regra_de_data_futura(self):
        """
        `clean()` roda com o objeto pela metade quando um campo falha na fase 1.
        Sem a guarda `is not None`, comparar `None > date` derruba o form com
        TypeError (erro 500) em vez de acusar "campo obrigatório".
        """
        form = LancamentoViagemForm(self.dados_form(data=""))

        self.assertFalse(form.is_valid())
        self.assertIn("data", form.errors)

    def test_form_sem_veiculo_acusa_campo_obrigatorio_e_nao_estoura(self):
        """
        Com FK obrigatória, `self.veiculo` levanta RelatedObjectDoesNotExist em
        vez de devolver None — por isso `clean()` consulta `veiculo_id` antes.
        """
        form = LancamentoViagemForm(self.dados_form(veiculo=""))

        self.assertFalse(form.is_valid())
        self.assertIn("veiculo", form.errors)

    def test_erros_de_data_e_de_km_aparecem_juntos(self):
        """Acumulação: o operador corrige tudo de uma vez, não um por envio."""
        form = LancamentoViagemForm(
            self.dados_form(
                data=(timezone.localdate() + timedelta(days=1)).isoformat(),
                km_inicial=500,
                km_final=100,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("data", form.errors)
        self.assertIn("km_final", form.errors)

    def test_banco_recusa_km_final_menor_que_inicial(self):
        """Camada 3: a CheckConstraint barra o que o ORM puro deixaria passar."""

        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            self.criar_viagem(km_inicial=100000, km_final=99000)

    @expectedFailure
    def test_fechamentos_com_periodos_sobrepostos_deveriam_ser_impedidos(self):
        """CAÇA AOS BUGS nº 3."""
        # TODO: crie dois Fechamento com períodos que se cruzam e assert que
        #       o segundo é recusado.
        self.fail("comportamento ainda não implementado")
