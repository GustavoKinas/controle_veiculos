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

import csv
import io
from datetime import date, time, timedelta
from unittest import expectedFailure, mock

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from django.contrib.auth.models import Group, Permission

from colaboradores.models import CentroCusto, Funcionario
from colaboradores.permissoes import (
    GRUPO_FINANCEIRO,
    GRUPO_PORTARIA,
    PERMISSOES_POR_PERFIL,
    criar_usuario_de_perfil,
    sincronizar_perfis,
)

from .exports import (
    CABECALHO_RATEIO,
    exportar_rateio_csv,
    exportar_viagens_csv,
    montar_csv_rateio,
    montar_csv_viagens,
)
from .forms import LancamentoViagemForm, ReservaManualForm
from .integracoes.microsoft_graph import normalizar_evento
from .models import (
    Fechamento,
    ReservaViagem,
    Veiculo,
    Viagem,
    periodos_se_sobrepoem,
)
from .sincronizacao import (
    GraphIndisponivel,
    ResultadoSincronizacao,
    SemCaixasCadastradas,
)
from .services import (
    ReservaIndisponivel,
    ViagemNaoEstaEmAndamento,
    calcular_rateio,
    confirmar_fechamento,
    lancar_viagem_da_reserva,
    montar_calendario,
    registrar_chegada,
    sincronizar_reservas,
)


# Nos testes o Django força DEBUG=False, e aí o
# CompressedManifestStaticFilesStorage (WhiteNoise) exige o staticfiles.json
# gerado pelo `collectstatic` — sem ele, renderizar base.html estoura
# "Missing staticfiles manifest entry". Teste não deve depender de build.
STORAGES_DE_TESTE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


class BaseViagensTest(TestCase):
    """
    Fixtures compartilhadas.

    `setUpTestData` roda UMA vez por classe (dentro de uma transação que sofre
    rollback ao fim de cada teste) — bem mais rápido que `setUp`, que roda a
    cada método. Use `setUp` só quando cada teste precisar de objetos novos.
    """

    @classmethod
    def setUpTestData(cls):
        # Os grupos de acesso precisam existir antes dos usuários: desde que as
        # views passaram a exigir permissão, um `portaria` sem perfil não
        # conseguiria abrir tela nenhuma, e todo teste de view falharia por
        # 403 em vez de testar o que se propõe.
        sincronizar_perfis()

        cls.cc_ti = CentroCusto.objects.create(codigo="1012201006", descricao="TI")
        cls.cc_projetos = CentroCusto.objects.create(
            codigo="1011105012", descricao="Projetos"
        )

        cls.portaria = Funcionario.objects.create(username="portaria", nome="PORTARIA")
        cls.portaria.groups.add(Group.objects.get(name=GRUPO_PORTARIA))

        cls.financeiro = Funcionario.objects.create(
            username="financeiro", nome="FINANCEIRO"
        )
        cls.financeiro.groups.add(Group.objects.get(name=GRUPO_FINANCEIRO))
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
@override_settings(STORAGES=STORAGES_DE_TESTE)
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

    def test_exportacao_retorna_csv(self):
        # TODO: confira o Content-Type e o Content-Disposition (attachment).
        #       Já existe cobertura real na seção 11 — este aqui é para você
        #       escrever do zero, chegando na mesma conclusão por outro caminho.
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


@override_settings(STORAGES=STORAGES_DE_TESTE)
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

    def test_reserva_futura_nao_oferece_o_botao_de_lancar(self):
        """
        Lançar viagem que ainda não aconteceu sempre falharia na validação de
        data futura — melhor não oferecer a ação. O bloqueio é de tela; quem
        garante a regra continua sendo o `Viagem.clean()`.
        """
        self.client.force_login(self.portaria)
        amanha = timezone.localdate() + timedelta(days=1)
        reserva = ReservaViagem.objects.create(veiculo=self.strada, data=amanha)

        resposta = self.client.get(reverse("agenda"), {"dia": amanha.isoformat()})

        self.assertContains(resposta, "Aguardando a data")
        self.assertNotContains(resposta, reverse("lancar_reserva", args=[reserva.pk]))

    def test_reserva_de_hoje_oferece_o_botao_de_lancar(self):
        self.client.force_login(self.portaria)
        hoje = timezone.localdate()
        reserva = ReservaViagem.objects.create(veiculo=self.strada, data=hoje)

        resposta = self.client.get(reverse("agenda"), {"dia": hoje.isoformat()})

        self.assertContains(resposta, reverse("lancar_reserva", args=[reserva.pk]))

    def test_dia_selecionado_filtra_a_fila(self):
        self.client.force_login(self.portaria)
        amanha = timezone.localdate() + timedelta(days=1)
        ReservaViagem.objects.create(veiculo=self.strada, data=amanha)

        resposta = self.client.get(reverse("agenda"), {"dia": amanha.isoformat()})

        self.assertEqual(resposta.context["dia_selecionado"], amanha)
        self.assertEqual(len(resposta.context["reservas_do_dia"]), 1)


# =========================================================================
# 7.1 Sincronização com o Outlook (fase 4)
#
# Nenhum teste aqui toca a rede: a borda (`integracoes.microsoft_graph`) já
# traduziu o evento para o formato normalizado, e é esse dicionário que o
# serviço recebe. Testar o tradutor e o gravador separadamente é o que torna
# a integração testável sem mock de HTTP.
# =========================================================================
class NormalizarEventoTest(TestCase):
    """Tradução do evento cru do Graph para o formato do sync."""

    def evento(self, **kwargs) -> dict:
        bruto = {
            "id": "AAMkAG-123",
            "subject": "Jacson Roberto de Maia ",
            "isAllDay": False,
            "isCancelled": False,
            "start": {"dateTime": "2026-08-13T11:00:00.0000000"},
            "end": {"dateTime": "2026-08-13T12:00:00.0000000"},
            "organizer": {
                "emailAddress": {
                    "name": "Jacson Roberto de Maia",
                    "address": "Jacson.Maia@GrupoFlexivel.com.br",
                }
            },
        }
        bruto.update(kwargs)
        return bruto

    def test_normaliza_campos_e_baixa_a_caixa_dos_emails(self):
        """
        E-mails vão para minúsculo dos dois lados da junção — o `IN` do
        Postgres é case-sensitive e o AD devolve a grafia que quiser.
        """
        dados = normalizar_evento(self.evento(), "Autenticidade@GrupoFlexivel.com.BR")

        self.assertEqual(dados["id_externo"], "AAMkAG-123")
        self.assertEqual(dados["email_recurso"], "autenticidade@grupoflexivel.com.br")
        self.assertEqual(dados["solicitante_email"], "jacson.maia@grupoflexivel.com.br")
        self.assertEqual(dados["data"], date(2026, 8, 13))
        self.assertEqual(dados["hora_inicio"], time(11, 0))
        self.assertEqual(dados["hora_fim"], time(12, 0))
        self.assertFalse(dados["cancelado"])

    def test_remove_espaco_sobrando_do_nome(self):
        """Todo assunto vindo da API real tem espaço no fim."""
        dados = normalizar_evento(self.evento(organizer={}), "sala@x.com")

        self.assertEqual(dados["solicitante_nome"], "Jacson Roberto de Maia")

    def test_dia_inteiro_grava_horario_nulo(self):
        """
        `hora_inicio=None` e não `00:00`: "sem horário definido" e "sai à
        meia-noite" são coisas diferentes na agenda do operador.
        """
        dados = normalizar_evento(
            self.evento(
                isAllDay=True,
                start={"dateTime": "2026-08-13T00:00:00.0000000"},
                end={"dateTime": "2026-08-14T00:00:00.0000000"},
            ),
            "sala@x.com",
        )

        self.assertEqual(dados["data"], date(2026, 8, 13))
        self.assertIsNone(dados["hora_inicio"])
        self.assertIsNone(dados["hora_fim"])

    def test_evento_sem_id_ou_sem_data_e_descartado(self):
        """Um evento inaproveitável não pode derrubar o lote inteiro."""
        self.assertIsNone(normalizar_evento(self.evento(id=None), "sala@x.com"))
        self.assertIsNone(normalizar_evento(self.evento(start=None), "sala@x.com"))


class SincronizarReservasTest(BaseViagensTest):
    """Regras de estado e idempotência do upsert."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.strada.email_recurso = "sala.a@empresa.com"
        cls.strada.save(update_fields=["email_recurso"])
        cls.cronos.email_recurso = "sala.b@empresa.com"
        cls.cronos.save(update_fields=["email_recurso"])
        cls.funcionario.email = "adriano@empresa.com"
        cls.funcionario.save(update_fields=["email"])

    def evento(self, **kwargs) -> dict:
        dados = {
            "id_externo": "evt-1",
            "email_recurso": "sala.a@empresa.com",
            "solicitante_email": "adriano@empresa.com",
            "solicitante_nome": "ADRIANO AMBROSIO BODNAR",
            "data": timezone.localdate(),
            "hora_inicio": time(8, 0),
            "hora_fim": time(9, 0),
            "cancelado": False,
        }
        dados.update(kwargs)
        return dados

    def sincronizar(self, eventos, caixas=None, dias=30):
        hoje = timezone.localdate()
        return sincronizar_reservas(
            eventos=eventos,
            caixas_consultadas=caixas
            if caixas is not None
            else {"sala.a@empresa.com", "sala.b@empresa.com"},
            data_inicio=hoje,
            data_fim=hoje + timedelta(days=dias),
        )

    def test_cria_reserva_e_casa_o_colaborador_por_email(self):
        resumo = self.sincronizar([self.evento()])

        self.assertEqual(resumo["criadas"], 1)
        reserva = ReservaViagem.objects.get()
        self.assertEqual(reserva.funcionario, self.funcionario)
        self.assertEqual(reserva.veiculo, self.strada)
        self.assertEqual(reserva.status, ReservaViagem.Status.PENDENTE)

    def test_rodar_duas_vezes_nao_duplica(self):
        """Idempotência: a chave é o id_externo."""
        self.sincronizar([self.evento()])
        resumo = self.sincronizar([self.evento()])

        self.assertEqual(resumo["criadas"], 0)
        self.assertEqual(resumo["atualizadas"], 1)
        self.assertEqual(ReservaViagem.objects.count(), 1)

    def test_evento_remarcado_atualiza_em_vez_de_duplicar(self):
        """
        O caso que a chave natural (veículo+solicitante+período) quebraria:
        o horário muda, o id não.
        """
        self.sincronizar([self.evento()])

        self.sincronizar([self.evento(hora_inicio=time(14, 0), hora_fim=time(15, 0))])

        reserva = ReservaViagem.objects.get()
        self.assertEqual(reserva.hora_inicio, time(14, 0))

    def test_solicitante_sem_cadastro_fica_sem_colaborador(self):
        self.sincronizar(
            [self.evento(solicitante_email="ninguem@empresa.com", solicitante_nome="Fulano")]
        )

        reserva = ReservaViagem.objects.get()
        self.assertIsNone(reserva.funcionario)
        self.assertEqual(reserva.solicitante_nome, "Fulano")
        # O e-mail fica guardado: é a chave para reconciliar depois.
        self.assertEqual(reserva.solicitante_email, "ninguem@empresa.com")

    def test_caixa_sem_veiculo_cadastrado_e_ignorada(self):
        resumo = self.sincronizar([self.evento(email_recurso="sala.z@empresa.com")])

        self.assertEqual(resumo["ignoradas_sem_veiculo"], 1)
        self.assertEqual(ReservaViagem.objects.count(), 0)

    def test_evento_cancelado_no_outlook_cancela_a_reserva(self):
        self.sincronizar([self.evento()])

        resumo = self.sincronizar([self.evento(cancelado=True)])

        self.assertEqual(resumo["canceladas"], 1)
        self.assertEqual(
            ReservaViagem.objects.get().status, ReservaViagem.Status.CANCELADA
        )

    def test_evento_excluido_do_outlook_some_e_e_cancelado(self):
        """
        Evento EXCLUÍDO não vem marcado — ele simplesmente não está no payload.
        A varredura de ausentes é a única forma de detectá-lo.
        """
        self.sincronizar([self.evento()])

        resumo = self.sincronizar([])

        self.assertEqual(resumo["canceladas"], 1)
        self.assertEqual(
            ReservaViagem.objects.get().status, ReservaViagem.Status.CANCELADA
        )

    def test_caixa_que_falhou_nao_tem_reservas_canceladas(self):
        """
        A proteção mais importante do sync: um 403 numa sala faz seus eventos
        sumirem do payload. Sem `caixas_consultadas`, isso seria lido como
        "tudo foi excluído no Outlook" e cancelaria reservas legítimas.
        """
        self.sincronizar([self.evento()])

        # A caixa da reserva não foi consultada nesta rodada (falhou).
        resumo = self.sincronizar([], caixas={"sala.b@empresa.com"})

        self.assertEqual(resumo["canceladas"], 0)
        self.assertEqual(
            ReservaViagem.objects.get().status, ReservaViagem.Status.PENDENTE
        )

    def test_reserva_lancada_e_intocavel(self):
        """A viagem aconteceu e tem quilometragem — o passado não se reescreve."""
        self.sincronizar([self.evento()])
        reserva = ReservaViagem.objects.get()
        reserva.status = ReservaViagem.Status.LANCADA
        reserva.save(update_fields=["status"])

        resumo = self.sincronizar([self.evento(cancelado=True)])

        reserva.refresh_from_db()
        self.assertEqual(resumo["intocadas_lancadas"], 1)
        self.assertEqual(reserva.status, ReservaViagem.Status.LANCADA)

    def test_evento_que_reaparece_volta_para_pendente(self):
        self.sincronizar([self.evento()])
        self.sincronizar([self.evento(cancelado=True)])

        resumo = self.sincronizar([self.evento()])

        self.assertEqual(resumo["reabertas"], 1)
        self.assertEqual(
            ReservaViagem.objects.get().status, ReservaViagem.Status.PENDENTE
        )

    def test_nenhuma_caixa_consultada_nao_cancela_nada(self):
        """Sync que falhou por inteiro não pode ter efeito destrutivo."""
        self.sincronizar([self.evento()])

        resumo = self.sincronizar([], caixas=set())

        self.assertEqual(resumo["canceladas"], 0)
        self.assertEqual(
            ReservaViagem.objects.get().status, ReservaViagem.Status.PENDENTE
        )


class FuncionarioEmailTest(TestCase):
    """O `email` é a chave de junção — precisa ser normalizado e único."""

    def test_email_e_normalizado_em_minusculo_no_save(self):
        funcionario = Funcionario.objects.create(
            username="sara", nome="SARA", email="  Sara.Bruch@GrupoFlexivel.com.BR "
        )

        self.assertEqual(funcionario.email, "sara.bruch@grupoflexivel.com.br")

    def test_email_repetido_e_recusado(self):
        Funcionario.objects.create(username="a", nome="A", email="x@empresa.com")

        with self.assertRaises(IntegrityError):
            Funcionario.objects.create(username="b", nome="B", email="X@Empresa.com")

    def test_varios_colaboradores_podem_ficar_sem_email(self):
        """A constraint é parcial: hoje a maioria do cadastro não tem e-mail."""
        for i in range(3):
            Funcionario.objects.create(username=f"sem{i}", nome=f"SEM {i}")

        self.assertEqual(Funcionario.objects.filter(email="").count(), 3)


# =========================================================================
# 8. Fase 3 — lançamento a partir da reserva (fluxos A e B)
# =========================================================================
class ViagemEmAndamentoTest(BaseViagensTest):
    """`km_final` nulo = veículo na rua. O que isso muda no resto do sistema."""

    def test_viagem_sem_km_final_esta_em_andamento_e_nao_soma_km(self):
        viagem = self.criar_viagem(km_final=None)

        self.assertTrue(viagem.em_andamento)
        self.assertEqual(viagem.km_percorrida, 0)

    def test_viagem_em_andamento_nao_entra_no_rateio(self):
        """Prévia do fechamento não pode contar quilômetro que não existe."""
        hoje = timezone.localdate()
        self.criar_viagem(data=hoje, km_final=None)

        rateio = calcular_rateio(hoje, hoje)

        self.assertEqual(rateio["quantidade_viagens"], 0)
        self.assertEqual(rateio["total_km"], 0)

    def test_fechamento_nao_consome_viagem_em_andamento(self):
        """
        O teste mais importante desta fase.

        O fechamento é irreversível: se engolisse a viagem aberta, ela seria
        marcada como fechada com 0 km e os quilômetros reais nunca entrariam
        em rateio nenhum.
        """
        hoje = timezone.localdate()
        aberta = self.criar_viagem(data=hoje, km_final=None)
        concluida = self.criar_viagem(
            data=hoje, km_inicial=100005, km_final=100200, veiculo=self.cronos
        )

        fechamento = confirmar_fechamento(hoje, hoje, usuario=self.portaria)

        aberta.refresh_from_db()
        concluida.refresh_from_db()
        self.assertIsNone(aberta.fechamento_id)          # intocada
        self.assertEqual(concluida.fechamento_id, fechamento.pk)
        self.assertEqual(fechamento.total_km, 195)

    def test_previa_informa_quantas_viagens_ficam_de_fora(self):
        """
        O operador precisa saber, ANTES de confirmar, que há viagens do
        período que não entrarão — o fechamento é irreversível.
        """
        hoje = timezone.localdate()
        self.criar_viagem(data=hoje, km_final=None)
        self.criar_viagem(data=hoje, veiculo=self.cronos, km_inicial=105000, km_final=105100)

        rateio = calcular_rateio(hoje, hoje)

        self.assertEqual(rateio["quantidade_viagens"], 1)
        self.assertEqual(rateio["quantidade_em_andamento"], 1)

    @override_settings(STORAGES=STORAGES_DE_TESTE)
    def test_aviso_aparece_no_modal_de_confirmacao(self):
        hoje = timezone.localdate()
        self.criar_viagem(data=hoje, km_final=None)
        self.criar_viagem(data=hoje, veiculo=self.cronos, km_inicial=105000, km_final=105100)
        self.client.force_login(self.portaria)

        resposta = self.client.get(
            reverse("fechamento"),
            {"data_inicio": hoje.isoformat(), "data_fim": hoje.isoformat()},
        )

        self.assertContains(resposta, "viagem(ns) em andamento neste período")

    def test_hodometro_considera_viagem_aberta(self):
        """
        O carro saiu com 107.000 e não voltou: o hodômetro tem que refletir
        isso, senão a próxima viagem poderia começar abaixo disso.
        """
        self.criar_viagem(km_inicial=107000, km_final=None)

        self.strada.refresh_from_db()
        self.assertEqual(self.strada.km_atual, 107000)

    def test_piso_considera_viagem_aberta(self):
        self.criar_viagem(data=date(2026, 8, 3), km_inicial=107000, km_final=None)

        viagem = self.nova_viagem(data=date(2026, 8, 4), km_inicial=106000, km_final=106500)

        with self.assertRaises(ValidationError) as ctx:
            viagem.full_clean()
        self.assertIn("km_inicial", ctx.exception.message_dict)


class LancarReservaServiceTest(BaseViagensTest):
    def setUp(self):
        self.reserva = ReservaViagem.objects.create(
            funcionario=self.funcionario,
            veiculo=self.strada,
            data=timezone.localdate(),
        )

    def test_fluxo_b_lanca_viagem_completa_e_marca_a_reserva(self):
        viagem = lancar_viagem_da_reserva(
            reserva_pk=self.reserva.pk,
            km_inicial=100000,
            km_final=100150,
            usuario=self.portaria,
        )

        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, ReservaViagem.Status.LANCADA)
        self.assertEqual(self.reserva.viagem_id, viagem.pk)
        self.assertTrue(viagem.concluida)
        self.assertEqual(viagem.km_percorrida, 150)
        self.assertEqual(viagem.lancada_por, self.portaria)

    def test_fluxo_a_registra_saida_e_depois_chegada(self):
        viagem = lancar_viagem_da_reserva(
            reserva_pk=self.reserva.pk, km_inicial=100000, usuario=self.portaria
        )
        self.assertTrue(viagem.em_andamento)

        viagem = registrar_chegada(viagem_pk=viagem.pk, km_final=100340)

        self.assertTrue(viagem.concluida)
        self.assertEqual(viagem.km_percorrida, 340)

    def test_viagem_usa_os_dados_da_reserva_e_nao_os_recebidos(self):
        """Colaborador e veículo vêm da reserva mesmo se alguém mandar outros."""
        viagem = lancar_viagem_da_reserva(
            reserva_pk=self.reserva.pk,
            km_inicial=100000,
            km_final=100100,
            funcionario=self.funcionario_inativo,   # tentativa de sobrescrever
        )

        self.assertEqual(viagem.funcionario, self.funcionario)
        self.assertEqual(viagem.veiculo, self.strada)
        self.assertEqual(viagem.data, self.reserva.data)

    def test_reserva_ja_lancada_nao_gera_segunda_viagem(self):
        """Regra 1:1 — clique duplo, duas abas, dois operadores."""
        lancar_viagem_da_reserva(
            reserva_pk=self.reserva.pk, km_inicial=100000, km_final=100100
        )

        with self.assertRaises(ReservaIndisponivel):
            lancar_viagem_da_reserva(
                reserva_pk=self.reserva.pk, km_inicial=100100, km_final=100200
            )

        self.assertEqual(Viagem.objects.count(), 1)

    def test_veiculo_ja_na_rua_bloqueia_nova_saida(self):
        lancar_viagem_da_reserva(reserva_pk=self.reserva.pk, km_inicial=100000)
        outra = ReservaViagem.objects.create(
            funcionario=self.funcionario, veiculo=self.strada, data=timezone.localdate()
        )

        with self.assertRaises(ValidationError):
            lancar_viagem_da_reserva(reserva_pk=outra.pk, km_inicial=100500)

    def test_reserva_sem_colaborador_exige_que_o_operador_informe(self):
        sem_colaborador = ReservaViagem.objects.create(
            solicitante_nome="Tamara Suelen Köpp",
            veiculo=self.cronos,
            data=timezone.localdate(),
        )

        with self.assertRaises(ValidationError):
            lancar_viagem_da_reserva(reserva_pk=sem_colaborador.pk, km_inicial=105000)

        viagem = lancar_viagem_da_reserva(
            reserva_pk=sem_colaborador.pk,
            km_inicial=105000,
            funcionario=self.funcionario,
        )
        self.assertEqual(viagem.funcionario, self.funcionario)

    def test_km_invalido_nao_marca_a_reserva_como_lancada(self):
        """A transação reverte tudo: sem viagem, sem mudança de status."""
        with self.assertRaises(ValidationError):
            lancar_viagem_da_reserva(
                reserva_pk=self.reserva.pk, km_inicial=100000, km_final=99000
            )

        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, ReservaViagem.Status.PENDENTE)
        self.assertEqual(Viagem.objects.count(), 0)

    def test_chegada_em_viagem_ja_concluida_e_recusada(self):
        viagem = lancar_viagem_da_reserva(
            reserva_pk=self.reserva.pk, km_inicial=100000, km_final=100100
        )

        with self.assertRaises(ViagemNaoEstaEmAndamento):
            registrar_chegada(viagem_pk=viagem.pk, km_final=100999)


@override_settings(STORAGES=STORAGES_DE_TESTE)
class LancarReservaViewTest(BaseViagensTest):
    def setUp(self):
        self.client.force_login(self.portaria)
        self.reserva = ReservaViagem.objects.create(
            funcionario=self.funcionario,
            veiculo=self.strada,
            data=timezone.localdate(),
        )

    def test_get_mostra_os_dados_da_reserva_sem_campos_editaveis(self):
        resposta = self.client.get(reverse("lancar_reserva", args=[self.reserva.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.strada.placa)
        # Colaborador/veículo/data não podem ser inputs — nem hidden. Editar o
        # HTML não pode permitir lançar viagem em nome de outra pessoa.
        self.assertNotContains(resposta, 'name="veiculo"')
        self.assertNotContains(resposta, 'name="data"')
        self.assertNotContains(resposta, 'name="funcionario"')

    def test_post_completo_cria_a_viagem_e_volta_para_a_agenda(self):
        resposta = self.client.post(
            reverse("lancar_reserva", args=[self.reserva.pk]),
            {"km_inicial": 100000, "km_final": 100150},
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("agenda"), resposta["Location"])
        self.assertEqual(Viagem.objects.count(), 1)

    def test_post_sem_km_final_deixa_a_viagem_em_andamento(self):
        self.client.post(
            reverse("lancar_reserva", args=[self.reserva.pk]), {"km_inicial": 100000}
        )

        self.assertTrue(Viagem.objects.get().em_andamento)

    def test_reserva_ja_lancada_da_404(self):
        self.reserva.status = ReservaViagem.Status.LANCADA
        self.reserva.save(update_fields=["status"])

        resposta = self.client.get(reverse("lancar_reserva", args=[self.reserva.pk]))

        self.assertEqual(resposta.status_code, 404)

    def test_erro_em_campo_inexistente_no_form_vira_erro_geral(self):
        """
        Regressão: a data vem da reserva e NÃO é campo do formulário, então o
        erro de "data futura" não tem onde ser exibido. Antes, o
        `add_error("data", ...)` estourava ValueError e derrubava a tela com
        um 500 em vez de mostrar a mensagem ao operador.
        """
        reserva_futura = ReservaViagem.objects.create(
            funcionario=self.funcionario,
            veiculo=self.cronos,
            data=timezone.localdate() + timedelta(days=1),
        )

        resposta = self.client.post(
            reverse("lancar_reserva", args=[reserva_futura.pk]),
            {"km_inicial": 105000, "km_final": 105100},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "não pode ser maior que a data atual")
        self.assertEqual(Viagem.objects.count(), 0)

    def test_erro_de_regra_reexibe_o_form_sem_criar_viagem(self):
        resposta = self.client.post(
            reverse("lancar_reserva", args=[self.reserva.pk]),
            {"km_inicial": 10, "km_final": 20},      # abaixo do hodômetro
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Viagem.objects.count(), 0)

    def test_chegada_conclui_a_viagem(self):
        self.client.post(
            reverse("lancar_reserva", args=[self.reserva.pk]), {"km_inicial": 100000}
        )
        viagem = Viagem.objects.get()

        resposta = self.client.post(
            reverse("registrar_chegada", args=[viagem.pk]), {"km_final": 100480}
        )

        self.assertEqual(resposta.status_code, 302)
        viagem.refresh_from_db()
        self.assertEqual(viagem.km_percorrida, 480)

    def test_get_da_chegada_renderiza_com_o_km_de_saida(self):
        """
        Também garante que `registrar_chegada.html` é renderizado ao menos uma
        vez pela suíte — sem isso, um erro de template só apareceria em
        produção (teste de POST que redireciona não renderiza nada).
        """
        self.client.post(
            reverse("lancar_reserva", args=[self.reserva.pk]), {"km_inicial": 100000}
        )
        viagem = Viagem.objects.get()

        resposta = self.client.get(reverse("registrar_chegada", args=[viagem.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "100000")
        self.assertContains(resposta, self.strada.placa)

    def test_chegada_em_viagem_concluida_da_404(self):
        viagem = self.criar_viagem(veiculo=self.cronos, km_inicial=105000, km_final=105100)

        resposta = self.client.get(reverse("registrar_chegada", args=[viagem.pk]))

        self.assertEqual(resposta.status_code, 404)


# =========================================================================
# 9. Lacunas conhecidas (caça aos bugs)
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


# =========================================================================
# 10. Perfis de acesso, reserva manual e sync pela tela
#
# O controle de acesso é testado pela porta da frente (`self.client`), nunca
# só pelo `has_perm`: o que interessa não é o usuário ter a permissão, é a URL
# recusar quem não tem. Um mixin esquecido numa view passa despercebido por
# qualquer teste que só olhe o objeto de usuário.
# =========================================================================
@override_settings(STORAGES=STORAGES_DE_TESTE)
class PerfilFinanceiroTest(BaseViagensTest):
    """O financeiro fecha períodos e mais nada."""

    ROTAS_PERMITIDAS = ["fechamento", "historico_fechamentos"]
    ROTAS_NEGADAS = [
        "agenda",
        "lancar_viagem",
        "nova_reserva",
        "funcionarios",
        "funcionarios_cadastrados",
    ]

    def setUp(self):
        self.client.force_login(self.financeiro)

    def test_acessa_fechamento_e_historico(self):
        for nome in self.ROTAS_PERMITIDAS:
            with self.subTest(rota=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 200)

    def test_nao_acessa_as_telas_da_portaria(self):
        for nome in self.ROTAS_NEGADAS:
            with self.subTest(rota=nome):
                resposta = self.client.get(reverse(nome))
                # Redireciona para a página inicial do perfil dele, não entrega 200.
                self.assertEqual(resposta.status_code, 302)
                self.assertNotIn(reverse(nome), resposta["Location"])

    def test_nao_dispara_a_sincronizacao(self):
        """Sem `gerenciar_reservas`, o POST é recusado antes de tocar a API."""
        resposta = self.client.post(reverse("sincronizar_reservas"), {"dia": ""})

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(ReservaViagem.objects.count(), 0)

    def test_consegue_confirmar_um_fechamento(self):
        """A permissão não é decorativa: ele precisa conseguir fechar."""
        self.criar_viagem(data=date(2026, 8, 3))

        resposta = self.client.post(
            reverse("fechamento"),
            {"data_inicio": "2026-08-01", "data_fim": "2026-08-31"},
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Fechamento.objects.count(), 1)

    def test_pagina_inicial_leva_ao_fechamento(self):
        """Sem isto, o login do financeiro cairia num 403 de boas-vindas."""
        self.assertRedirects(self.client.get("/"), reverse("fechamento"))


@override_settings(STORAGES=STORAGES_DE_TESTE)
class PerfilPortariaTest(BaseViagensTest):
    """A portaria opera o dia a dia e nunca entra no /admin."""

    def setUp(self):
        self.client.force_login(self.portaria)

    def test_acessa_as_telas_de_operacao(self):
        for nome in ["agenda", "lancar_viagem", "nova_reserva"]:
            with self.subTest(rota=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 200)

    def test_usuario_de_perfil_nasce_sem_acesso_ao_admin(self):
        criar_usuario_de_perfil(
            username="portaria2", senha="x", nome="Portaria 2", grupo=GRUPO_PORTARIA
        )

        usuario = Funcionario.objects.get(username="portaria2")
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)

    def test_recriar_rebaixa_quem_ja_era_superusuario(self):
        """
        O comando não só cria: conserta. Rodá-lo sobre um usuário que ganhou
        /admin em algum momento tem que tirar o acesso, sem depender de alguém
        lembrar de desmarcar a caixa.
        """
        Funcionario.objects.filter(pk=self.portaria.pk).update(
            is_staff=True, is_superuser=True
        )

        criar_usuario_de_perfil(
            username="portaria", senha="nova", nome="PORTARIA", grupo=GRUPO_PORTARIA
        )

        self.portaria.refresh_from_db()
        self.assertFalse(self.portaria.is_staff)
        self.assertFalse(self.portaria.is_superuser)

    def test_admin_recusa_a_portaria_mesmo_com_is_staff(self):
        """
        A garantia de "sob nenhuma hipótese": mesmo com `is_staff` marcado na
        mão, o AdminSite recusa quem está num perfil operacional.
        """
        Funcionario.objects.filter(pk=self.portaria.pk).update(is_staff=True)

        resposta = self.client.get("/admin/", follow=True)

        # Em vez do painel, o admin devolve o próprio formulário de login.
        self.assertNotContains(resposta, "Administração do sistema")

    def test_admin_recusa_o_financeiro_mesmo_com_is_staff(self):
        Funcionario.objects.filter(pk=self.financeiro.pk).update(is_staff=True)
        self.client.force_login(self.financeiro)

        resposta = self.client.get("/admin/", follow=True)

        self.assertNotContains(resposta, "Administração do sistema")

    def test_superusuario_continua_entrando_no_admin(self):
        """A trava é para perfil operacional, não para o administrador."""
        admin = Funcionario.objects.create_superuser(
            username="administrador", password="x"
        )
        self.client.force_login(admin)

        resposta = self.client.get("/admin/")

        self.assertEqual(resposta.status_code, 200)


class PerfisConfiguradosTest(TestCase):
    """A política declarada em permissoes.py precisa chegar ao banco."""

    def test_sincronizar_perfis_e_idempotente(self):
        sincronizar_perfis()
        sincronizar_perfis()

        for nome, rotulos in PERMISSOES_POR_PERFIL.items():
            with self.subTest(perfil=nome):
                grupo = Group.objects.get(name=nome)
                self.assertEqual(grupo.permissions.count(), len(rotulos))

    def test_financeiro_nao_recebe_permissao_de_operacao(self):
        sincronizar_perfis()

        codenames = set(
            Group.objects.get(name=GRUPO_FINANCEIRO)
            .permissions.values_list("codename", flat=True)
        )

        self.assertIn("realizar_fechamento", codenames)
        self.assertNotIn("lancar_viagem", codenames)
        self.assertNotIn("gerenciar_reservas", codenames)

    def test_tirar_permissao_da_politica_tira_de_quem_ja_tinha(self):
        """
        `set()` e não `add()`: se o comando só acrescentasse, a política do
        arquivo e a do banco divergiriam em silêncio — e a do banco é a que
        vale na hora de negar acesso.
        """
        sincronizar_perfis()
        grupo = Group.objects.get(name=GRUPO_FINANCEIRO)
        grupo.permissions.add(Permission.objects.get(codename="lancar_viagem"))

        sincronizar_perfis()

        self.assertNotIn(
            "lancar_viagem",
            set(grupo.permissions.values_list("codename", flat=True)),
        )


@override_settings(STORAGES=STORAGES_DE_TESTE)
class ReservaManualTest(BaseViagensTest):
    """Cadastro de reserva pelo painel."""

    def setUp(self):
        self.client.force_login(self.portaria)

    def dados_reserva(self, **kwargs) -> dict:
        dados = {
            "funcionario": self.funcionario.pk,
            "veiculo": self.strada.pk,
            "data": "2026-08-20",
            "hora_inicio": "08:00",
            "hora_fim": "12:00",
            "destino": "Visita a cliente",
        }
        dados.update(kwargs)
        return dados

    def test_cria_reserva_e_volta_para_o_dia_dela(self):
        resposta = self.client.post(reverse("nova_reserva"), self.dados_reserva())

        reserva = ReservaViagem.objects.get()
        self.assertEqual(reserva.funcionario, self.funcionario)
        self.assertEqual(reserva.status, ReservaViagem.Status.PENDENTE)
        # Volta para o dia da reserva criada, não para hoje.
        self.assertRedirects(
            resposta,
            f"{reverse('agenda')}?dia=2026-08-20",
            fetch_redirect_response=False,
        )

    def test_reserva_manual_nasce_sem_id_externo(self):
        """
        É o que a protege do sync: `id_externo` vazio significa que ela não
        veio do Outlook, e por isso a rodada seguinte não a cancela por ter
        "sumido da agenda".
        """
        self.client.post(reverse("nova_reserva"), self.dados_reserva())

        reserva = ReservaViagem.objects.get()
        self.assertEqual(reserva.origem, ReservaViagem.Origem.MANUAL)
        self.assertEqual(reserva.id_externo, "")

    def test_sync_nao_cancela_reserva_manual(self):
        """Regressão do risco acima, exercitando o serviço de verdade."""
        self.strada.email_recurso = "stradarln1j19@puflexivel.com.br"
        self.strada.save()
        self.client.post(reverse("nova_reserva"), self.dados_reserva())
        reserva = ReservaViagem.objects.get()

        # Rodada em que o Outlook não devolveu evento nenhum para a caixa.
        sincronizar_reservas(
            eventos=[],
            caixas_consultadas={self.strada.email_recurso},
            data_inicio=date(2026, 8, 1),
            data_fim=date(2026, 8, 31),
        )

        reserva.refresh_from_db()
        self.assertEqual(reserva.status, ReservaViagem.Status.PENDENTE)

    def test_hora_fim_anterior_a_inicio_e_recusada(self):
        form = ReservaManualForm(
            self.dados_reserva(hora_inicio="14:00", hora_fim="09:00")
        )

        self.assertFalse(form.is_valid())
        self.assertIn("hora_fim", form.errors)

    def test_uma_hora_so_e_recusada(self):
        """Ambíguo: não dá para saber se é dia inteiro ou campo esquecido."""
        form = ReservaManualForm(self.dados_reserva(hora_fim=""))

        self.assertFalse(form.is_valid())
        self.assertIn("hora_fim", form.errors)

    def test_reserva_de_dia_inteiro_e_valida(self):
        form = ReservaManualForm(self.dados_reserva(hora_inicio="", hora_fim=""))

        self.assertTrue(form.is_valid(), form.errors)

    def test_veiculo_inativo_e_recusado(self):
        self.strada.ativo = False
        self.strada.save()

        form = ReservaManualForm(self.dados_reserva())

        self.assertFalse(form.is_valid())

    def test_post_invalido_nao_cria_reserva(self):
        resposta = self.client.post(
            reverse("nova_reserva"), self.dados_reserva(data="")
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(ReservaViagem.objects.count(), 0)


@override_settings(STORAGES=STORAGES_DE_TESTE)
class SincronizarPelaTelaTest(BaseViagensTest):
    """O botão da agenda, sem tocar a rede."""

    def setUp(self):
        self.client.force_login(self.portaria)

    def test_get_nao_e_aceito(self):
        """
        Sincronizar grava no banco. Se respondesse a GET, um prefetch do
        navegador ou um robô dispararia a importação sozinho.
        """
        self.assertEqual(
            self.client.get(reverse("sincronizar_reservas")).status_code, 405
        )

    def test_erro_de_credencial_vira_mensagem_e_nao_500(self):
        with mock.patch(
            "viagens.views.executar_sincronizacao",
            side_effect=GraphIndisponivel("credencial ausente"),
        ):
            resposta = self.client.post(
                reverse("sincronizar_reservas"), {"dia": "2026-08-13"}, follow=True
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não foi possível falar com o Outlook")

    def test_sem_caixa_cadastrada_avisa_o_operador(self):
        with mock.patch(
            "viagens.views.executar_sincronizacao",
            side_effect=SemCaixasCadastradas("Nenhum veículo ativo com caixa"),
        ):
            resposta = self.client.post(
                reverse("sincronizar_reservas"), {"dia": ""}, follow=True
            )

        self.assertContains(resposta, "Nenhum veículo ativo com caixa")

    def test_falha_parcial_nao_e_anunciada_como_sucesso(self):
        """
        Caixa que não respondeu significa agenda incompleta. Dizer
        "sincronizado" faria o operador confiar numa lista que pode estar
        faltando reserva.
        """
        resultado = ResultadoSincronizacao(
            resumo={"criadas": 2, "atualizadas": 0, "canceladas": 0},
            erros={"cronossxk9g85@puflexivel.com.br": "403"},
        )

        with mock.patch("viagens.views.executar_sincronizacao", return_value=resultado):
            resposta = self.client.post(
                reverse("sincronizar_reservas"), {"dia": ""}, follow=True
            )

        self.assertContains(resposta, "Sincronização parcial")
        self.assertContains(resposta, "cronossxk9g85@puflexivel.com.br")

    def test_sucesso_volta_para_o_dia_que_estava_aberto(self):
        resultado = ResultadoSincronizacao(
            resumo={"criadas": 1, "atualizadas": 0, "canceladas": 0}
        )

        with mock.patch("viagens.views.executar_sincronizacao", return_value=resultado):
            resposta = self.client.post(
                reverse("sincronizar_reservas"), {"dia": "2026-08-20"}
            )

        self.assertRedirects(
            resposta,
            f"{reverse('agenda')}?dia=2026-08-20",
            fetch_redirect_response=False,
        )

# =========================================================================
# 11. Exportação em CSV — rateio e viagens, arquivos separados
#
# O rateio é importado no ERP, então o teste central é o de forma: uma
# tabela e nada mais. Título de seção, linha em branco ou linha de total
# viram registro fantasma na importação, e nenhum deles aparece num "abri
# aqui e estava bonito".
#
# Os outros três protegem a leitura no Excel pt-BR: separador, BOM e decimal
# com vírgula. O `;` só quebra em quem tem Excel em português, e o BOM
# ausente só destrói acento em quem tem ANSI diferente — não dá para
# descobrir por inspeção casual.
# =========================================================================
class ExportarRateioCsvTest(BaseViagensTest):
    """O arquivo que vai para o ERP."""

    def setUp(self):
        # Dois centros de custo, para o rateio ter mais de uma linha e o
        # percentual não ser trivialmente 100.
        self.criar_viagem(data=date(2026, 8, 3), km_inicial=100000, km_final=100100)
        self.criar_viagem(
            funcionario=self.funcionario_inativo,
            centro_custo=self.cc_ti,
            veiculo=self.cronos,
            data=date(2026, 8, 4),
            km_inicial=105000,
            km_final=105300,
        )
        self.fechamento = confirmar_fechamento(
            date(2026, 8, 1), date(2026, 8, 31), usuario=self.portaria
        )

    def linhas(self) -> list[list[str]]:
        texto = montar_csv_rateio(self.fechamento)
        return list(csv.reader(io.StringIO(texto), delimiter=";"))

    # -- forma: é uma tabela, e só ---------------------------------------
    def test_e_uma_tabela_pura(self):
        """
        Cabeçalho + uma linha por centro de custo. Nada mais.

        Cada elemento a mais (título, linha em branco, total) entraria no ERP
        como se fosse um centro de custo.
        """
        linhas = self.linhas()

        self.assertEqual(len(linhas), 1 + self.fechamento.rateios.count())

    def test_nao_tem_linha_em_branco(self):
        texto = montar_csv_rateio(self.fechamento)

        self.assertNotIn("\r\n\r\n", texto)

    def test_nao_tem_titulo_nem_linha_de_total(self):
        texto = montar_csv_rateio(self.fechamento)

        self.assertNotIn("Fechamento de", texto)
        self.assertNotIn("Resumo do Rateio", texto)
        self.assertNotIn("Total", texto)

    def test_todas_as_linhas_tem_a_mesma_quantidade_de_colunas(self):
        """Coluna com significado fixo é o que a importação exige."""
        linhas = self.linhas()

        larguras = {len(linha) for linha in linhas}
        self.assertEqual(larguras, {len(CABECALHO_RATEIO)})

    def test_o_periodo_vem_em_coluna_e_nao_em_titulo(self):
        """
        A data do fechamento estava num título no topo do arquivo. Como
        título não é dado tabular, ela virou coluna — e aí cada linha se
        basta sozinha na importação.
        """
        cabecalho, primeira, *_ = self.linhas()

        self.assertEqual(cabecalho[:2], ["Data Inicio", "Data Fim"])
        self.assertEqual(primeira[:2], ["01/08/2026", "31/08/2026"])

    def test_codigo_do_centro_de_custo_vem_sozinho_na_coluna(self):
        """Código e descrição em colunas diferentes: uma informação cada."""
        _, primeira, *_ = self.linhas()

        self.assertEqual(primeira[2], self.cc_ti.codigo)
        self.assertEqual(primeira[3], self.cc_ti.descricao)

    # -- leitura no Excel pt-BR ------------------------------------------
    def test_usa_ponto_e_virgula_como_separador(self):
        texto = montar_csv_rateio(self.fechamento)

        self.assertIn("Data Inicio;Data Fim;Centro de Custo", texto)

    def test_percentual_sai_com_virgula_decimal(self):
        """`25.00` com separador `;` seria lido como texto e não somaria."""
        texto = montar_csv_rateio(self.fechamento)

        self.assertIn("25,00", texto)   # 100 km de 400
        self.assertNotIn("25.00", texto)

    def test_linhas_terminam_em_crlf(self):
        """RFC 4180 — e é o que o Excel espera."""
        self.assertIn("\r\n", montar_csv_rateio(self.fechamento))

    def test_resposta_tem_bom_para_o_excel_ler_utf8(self):
        """
        Sem o BOM o Excel assume ANSI e "Descrição" vira "DescriÃ§Ã£o". Ele
        não consulta o charset declarado no cabeçalho HTTP.
        """
        resposta = exportar_rateio_csv(self.fechamento)

        self.assertTrue(resposta.content.startswith(b"\xef\xbb\xbf"))

    def test_acentos_sobrevivem_a_ida_e_volta(self):
        cc = CentroCusto.objects.create(codigo="1099999999", descricao="Manutenção")
        self.criar_viagem(
            funcionario=self.funcionario_sem_cc,
            centro_custo=cc,
            veiculo=self.strada,
            data=date(2026, 9, 2),
            km_inicial=200000,
            km_final=200050,
        )
        fechamento = confirmar_fechamento(date(2026, 9, 1), date(2026, 9, 30))

        conteudo = exportar_rateio_csv(fechamento).content.decode("utf-8-sig")

        self.assertIn("Manutenção", conteudo)

    def test_content_type_e_nome_do_arquivo(self):
        resposta = exportar_rateio_csv(self.fechamento)

        self.assertEqual(resposta["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", resposta["Content-Disposition"])
        self.assertIn(
            'filename="rateio_20260801_20260831.csv"',
            resposta["Content-Disposition"],
        )


class ExportarViagensCsvTest(BaseViagensTest):
    """O detalhamento, agora em arquivo próprio."""

    def setUp(self):
        self.criar_viagem(data=date(2026, 8, 3), km_inicial=100000, km_final=100100)
        self.criar_viagem(
            funcionario=self.funcionario_inativo,
            centro_custo=self.cc_ti,
            veiculo=self.cronos,
            data=date(2026, 8, 4),
            km_inicial=105000,
            km_final=105300,
        )
        self.fechamento = confirmar_fechamento(
            date(2026, 8, 1), date(2026, 8, 31), usuario=self.portaria
        )

    def test_lista_todas_as_viagens_do_fechamento(self):
        linhas = list(
            csv.reader(io.StringIO(montar_csv_viagens(self.fechamento)), delimiter=";")
        )

        self.assertEqual(len(linhas) - 1, self.fechamento.viagens.count())

    def test_as_viagens_sairam_do_arquivo_de_rateio(self):
        """
        Era o mesmo arquivo até agora. Ter as duas tabelas empilhadas é o que
        impedia a importação no ERP.
        """
        rateio = montar_csv_rateio(self.fechamento)

        self.assertNotIn("KM Inicial", rateio)
        self.assertNotIn(str(self.funcionario), rateio)

    def test_traz_a_placa_do_veiculo(self):
        conteudo = montar_csv_viagens(self.fechamento)

        self.assertIn(self.strada.placa, conteudo)
        self.assertIn(self.cronos.placa, conteudo)

    def test_data_em_formato_brasileiro(self):
        conteudo = montar_csv_viagens(self.fechamento)

        self.assertIn("03/08/2026", conteudo)
        self.assertIn("04/08/2026", conteudo)

    def test_content_type_e_nome_do_arquivo(self):
        resposta = exportar_viagens_csv(self.fechamento)

        self.assertEqual(resposta["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn(
            'filename="viagens_20260801_20260831.csv"',
            resposta["Content-Disposition"],
        )


@override_settings(STORAGES=STORAGES_DE_TESTE)
class ExportacaoPelaUrlTest(BaseViagensTest):
    def setUp(self):
        self.criar_viagem(data=date(2026, 8, 3), km_inicial=100000, km_final=100100)
        self.fechamento = confirmar_fechamento(
            date(2026, 8, 1), date(2026, 8, 31), usuario=self.portaria
        )

    def test_as_duas_rotas_baixam_csv(self):
        self.client.force_login(self.financeiro)

        for rota in ["fechamento_exportar", "fechamento_exportar_viagens"]:
            with self.subTest(rota=rota):
                resposta = self.client.get(reverse(rota, args=[self.fechamento.pk]))

                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta["Content-Type"], "text/csv; charset=utf-8")

    def test_as_duas_rotas_exigem_permissao_de_fechamento(self):
        self.client.force_login(Funcionario.objects.create(username="joao.sem.perfil"))

        for rota in ["fechamento_exportar", "fechamento_exportar_viagens"]:
            with self.subTest(rota=rota):
                resposta = self.client.get(reverse(rota, args=[self.fechamento.pk]))

                self.assertNotEqual(resposta.status_code, 200)

    def test_fechamento_inexistente_da_404(self):
        self.client.force_login(self.financeiro)

        resposta = self.client.get(reverse("fechamento_exportar_viagens", args=[9999]))

        self.assertEqual(resposta.status_code, 404)


# =========================================================================
# 12. Veículo já reservado (BUG corrigido em 08/2026)
#
# A tela de reserva manual aceitava reservar um veículo que já tinha reserva
# pendente no mesmo horário — duas pessoas saíam com o mesmo carro. A regra
# vive em `ReservaViagem.clean()`, e não no formulário, para valer também no
# admin e em qualquer `full_clean()`.
# =========================================================================
class PeriodosSeSobrepoemTest(TestCase):
    """A regra de sobreposição, isolada de banco e de modelo."""

    def sobrepoe(self, a_ini, a_fim, b_ini, b_fim) -> bool:
        return periodos_se_sobrepoem(
            time.fromisoformat(a_ini) if a_ini else None,
            time.fromisoformat(a_fim) if a_fim else None,
            time.fromisoformat(b_ini) if b_ini else None,
            time.fromisoformat(b_fim) if b_fim else None,
        )

    def test_um_dentro_do_outro(self):
        self.assertTrue(self.sobrepoe("09:00", "11:00", "08:00", "12:00"))

    def test_invade_o_inicio(self):
        self.assertTrue(self.sobrepoe("07:00", "09:00", "08:00", "12:00"))

    def test_invade_o_fim(self):
        self.assertTrue(self.sobrepoe("11:00", "14:00", "08:00", "12:00"))

    def test_identicos(self):
        self.assertTrue(self.sobrepoe("08:00", "12:00", "08:00", "12:00"))

    def test_encostados_nao_sobrepoem(self):
        """
        08:00–12:00 e 12:00–14:00 se tocam mas não disputam o carro. Recusar
        isso engessaria o uso normal da frota: o veículo volta e sai de novo.
        """
        self.assertFalse(self.sobrepoe("12:00", "14:00", "08:00", "12:00"))

    def test_separados(self):
        self.assertFalse(self.sobrepoe("14:00", "16:00", "08:00", "12:00"))

    def test_dia_inteiro_conflita_com_qualquer_horario(self):
        self.assertTrue(self.sobrepoe(None, None, "08:00", "12:00"))
        self.assertTrue(self.sobrepoe("08:00", "12:00", None, None))

    def test_dois_dias_inteiros_conflitam(self):
        self.assertTrue(self.sobrepoe(None, None, None, None))


@override_settings(STORAGES=STORAGES_DE_TESTE)
class VeiculoJaReservadoTest(BaseViagensTest):
    """A regra pela porta da frente: formulário e tela."""

    DATA = "2026-08-20"

    def setUp(self):
        self.client.force_login(self.portaria)
        self.existente = ReservaViagem.objects.create(
            funcionario=self.funcionario,
            veiculo=self.strada,
            data=date(2026, 8, 20),
            hora_inicio=time(8, 0),
            hora_fim=time(12, 0),
        )

    def dados(self, **kwargs) -> dict:
        base = {
            # Precisa ter centro de custo: o formulário só lista quem pode viajar.
            "funcionario": self.funcionario.pk,
            "veiculo": self.strada.pk,
            "data": self.DATA,
            "hora_inicio": "09:00",
            "hora_fim": "11:00",
            "destino": "Visita",
        }
        base.update(kwargs)
        return base

    def test_horario_sobreposto_e_recusado(self):
        form = ReservaManualForm(self.dados())

        self.assertFalse(form.is_valid())
        self.assertIn("veiculo", form.errors)

    def test_a_mensagem_diz_qual_o_conflito(self):
        """O operador precisa saber o horário ocupado para escolher outro."""
        form = ReservaManualForm(self.dados())
        form.is_valid()

        mensagem = " ".join(form.errors["veiculo"])
        self.assertIn(self.strada.placa, mensagem)
        self.assertIn("08:00", mensagem)
        self.assertIn("12:00", mensagem)

    def test_horario_encostado_e_aceito(self):
        form = ReservaManualForm(self.dados(hora_inicio="12:00", hora_fim="14:00"))

        self.assertTrue(form.is_valid(), form.errors)

    def test_horario_livre_e_aceito(self):
        form = ReservaManualForm(self.dados(hora_inicio="14:00", hora_fim="16:00"))

        self.assertTrue(form.is_valid(), form.errors)

    def test_outro_veiculo_no_mesmo_horario_e_aceito(self):
        form = ReservaManualForm(self.dados(veiculo=self.cronos.pk))

        self.assertTrue(form.is_valid(), form.errors)

    def test_outro_dia_no_mesmo_horario_e_aceito(self):
        form = ReservaManualForm(self.dados(data="2026-08-21"))

        self.assertTrue(form.is_valid(), form.errors)

    def test_dia_inteiro_conflita_com_reserva_existente(self):
        form = ReservaManualForm(self.dados(hora_inicio="", hora_fim=""))

        self.assertFalse(form.is_valid())
        self.assertIn("veiculo", form.errors)

    def test_reserva_cancelada_libera_o_horario(self):
        """Só reserva pendente ocupa o veículo."""
        self.existente.status = ReservaViagem.Status.CANCELADA
        self.existente.save()

        form = ReservaManualForm(self.dados())

        self.assertTrue(form.is_valid(), form.errors)

    def test_reserva_lancada_libera_o_horario(self):
        """Lançada já virou viagem — o horário não está mais reservado."""
        self.existente.status = ReservaViagem.Status.LANCADA
        self.existente.save()

        form = ReservaManualForm(self.dados())

        self.assertTrue(form.is_valid(), form.errors)

    def test_a_tela_nao_cria_a_reserva_duplicada(self):
        """Regressão do bug, pela view."""
        resposta = self.client.post(reverse("nova_reserva"), self.dados())

        self.assertEqual(resposta.status_code, 200)   # reexibe o form
        self.assertEqual(ReservaViagem.objects.count(), 1)

    def test_a_regra_vale_no_full_clean_e_nao_so_no_formulario(self):
        """
        Vive em `Model.clean()` de propósito: assim o admin e qualquer
        script que chame `full_clean()` também são barrados.
        """
        reserva = ReservaViagem(
            funcionario=self.funcionario_sem_cc,
            veiculo=self.strada,
            data=date(2026, 8, 20),
            hora_inicio=time(9, 0),
            hora_fim=time(11, 0),
        )

        with self.assertRaises(ValidationError) as ctx:
            reserva.full_clean()

        self.assertIn("veiculo", ctx.exception.message_dict)

    def test_editar_a_propria_reserva_nao_conflita_consigo_mesma(self):
        self.existente.destino = "Novo destino"

        self.existente.full_clean()   # não deve levantar

    def test_o_sync_nao_e_barrado_pela_regra(self):
        """
        A importação usa `update_or_create` e não chama `full_clean()` — de
        propósito. O Outlook é a fonte da verdade do que veio dele, e a
        própria caixa de recurso já recusa reserva sobreposta na origem.
        """
        self.strada.email_recurso = "stradarln1j19@puflexivel.com.br"
        self.strada.save()

        resumo = sincronizar_reservas(
            eventos=[
                {
                    "id_externo": "evento-sobreposto",
                    "email_recurso": self.strada.email_recurso,
                    "solicitante_nome": "Fulano",
                    "solicitante_email": "fulano@grupoflexivel.com.br",
                    "data": date(2026, 8, 20),
                    "hora_inicio": time(9, 0),
                    "hora_fim": time(11, 0),
                    "cancelado": False,
                }
            ],
            caixas_consultadas={self.strada.email_recurso},
            data_inicio=date(2026, 8, 1),
            data_fim=date(2026, 8, 31),
        )

        self.assertEqual(resumo["criadas"], 1)
