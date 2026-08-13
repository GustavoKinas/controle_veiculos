from django.urls import path

from .views import (
    AgendaView,
    FechamentoExportarView,
    FechamentoView,
    HistoricoFechamentosView,
    LancarReservaView,
    LancarViagemView,
    RegistrarChegadaView,
)

urlpatterns = [
    path("agenda/", AgendaView.as_view(), name="agenda"),
    path("lancar/", LancarViagemView.as_view(), name="lancar_viagem"),
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
]
