from django.urls import path

from .views import (
    AgendaView,
    FechamentoExportarViagensView,
    FechamentoExportarView,
    FechamentoView,
    HistoricoFechamentosView,
    LancarReservaView,
    LancarViagemView,
    NovaReservaView,
    RegistrarChegadaView,
    SincronizarReservasView,
)

urlpatterns = [
    path("agenda/", AgendaView.as_view(), name="agenda"),
    path("lancar/", LancarViagemView.as_view(), name="lancar_viagem"),
    path("reservas/nova/", NovaReservaView.as_view(), name="nova_reserva"),
    path(
        "reservas/sincronizar/",
        SincronizarReservasView.as_view(),
        name="sincronizar_reservas",
    ),
    path(
        "reservas/<int:pk>/lancar/",
        LancarReservaView.as_view(),
        name="lancar_reserva",
    ),
    path(
        "chegada/<int:pk>/",
        RegistrarChegadaView.as_view(),
        name="registrar_chegada",
    ),
    path("fechamento/", FechamentoView.as_view(), name="fechamento"),
    path(
        "fechamentos/",
        HistoricoFechamentosView.as_view(),
        name="historico_fechamentos",
    ),
    path(
        "fechamentos/<int:pk>/exportar/",
        FechamentoExportarView.as_view(),
        name="fechamento_exportar",
    ),
    path(
        "fechamentos/<int:pk>/exportar/viagens/",
        FechamentoExportarViagensView.as_view(),
        name="fechamento_exportar_viagens",
    ),
]
