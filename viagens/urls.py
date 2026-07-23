from django.urls import path

from .views import (
    FechamentoExportarView,
    FechamentoView,
    HistoricoFechamentosView,
    LancarViagemView,
)

urlpatterns = [
    path("lancar/", LancarViagemView.as_view(), name="lancar_viagem"),
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
