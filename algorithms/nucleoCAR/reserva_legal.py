# -*- coding: utf-8 -*-
"""
Estimativa de Reserva Legal (RL) — arts. 12, 15, 66 e 67 da Lei 12.651/2012.

Percentuais (art. 12):
- Amazônia Legal: 80% (floresta), 35% (cerrado), 20% (campos gerais)
- Demais regiões: 20%
"""

from .utils import area_ha, subtrair

OPCOES_PERCENTUAL = [
    (20.0, "20% — Demais regiões / campos gerais na Amazônia Legal"),
    (35.0, "35% — Cerrado na Amazônia Legal"),
    (80.0, "80% — Floresta na Amazônia Legal"),
]


def calcular_rl(area_imovel_ha, percentual, n_modulos, vegetacao=None, app_integral=None):
    """
    Retorna dict com:
    exigida_ha, vegetacao_ha, vegetacao_fora_app_ha, deficit_com_app_ha,
    deficit_sem_app_ha, observacoes (lista)
    """
    exigida = area_imovel_ha * percentual / 100.0
    observacoes = []

    if vegetacao is None or vegetacao.isEmpty():
        veg_ha = 0.0
        veg_fora_app = 0.0
        observacoes.append("Camada de vegetação nativa não informada: o déficit considera "
                           "vegetação existente igual a zero.")
    else:
        veg_ha = area_ha(vegetacao)
        veg_fora_app = area_ha(subtrair(vegetacao, app_integral))

    deficit_com_app = max(0.0, exigida - veg_ha)        # cômputo da APP na RL (art. 15)
    deficit_sem_app = max(0.0, exigida - veg_fora_app)  # sem cômputo da APP

    observacoes.append("O cômputo da APP na RL (art. 15) exige que não implique nova supressão "
                       "de vegetação e que a APP esteja conservada ou em recuperação.")

    if n_modulos <= 4:
        observacoes.append("Imóvel com até 4 módulos fiscais em 22/07/2008: pelo art. 67, a RL "
                           "pode ser constituída pela vegetação nativa existente naquela data, "
                           "sem obrigação de completar o percentual.")
    elif deficit_com_app > 0:
        observacoes.append("Há déficit de RL: regularização por recomposição, regeneração "
                           "natural ou compensação (art. 66), via PRA quando cabível.")

    return {
        "percentual": percentual,
        "exigida_ha": exigida,
        "vegetacao_ha": veg_ha,
        "vegetacao_fora_app_ha": veg_fora_app,
        "deficit_com_app_ha": deficit_com_app,
        "deficit_sem_app_ha": deficit_sem_app,
        "observacoes": observacoes,
    }
