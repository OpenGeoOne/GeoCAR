# -*- coding: utf-8 -*-
"""
Orquestrador da pré-análise do CAR.

Recebe os parâmetros do diálogo, executa validação, sobreposições, APP e RL,
cria as camadas de resultado e gera o relatório HTML.
"""

import os
from datetime import datetime

from qgis.core import QgsGeometry

from . import app as modulo_app
from .relatorio import gerar_relatorio_html
from .reserva_legal import calcular_rl
from .sobreposicao import analisar_sobreposicoes
from .utils import adicionar_feicao, area_ha, criar_camada_memoria, src_utm_sirgas, uniao
from .validacao import validar_perimetro, verificar_extrapolacao


def executar(p):
    """
    Executa a pré-análise.

    p (dict): perimetro, hidrografia, campo_largura, largura_padrao, nascentes,
    lagos, vegetacao, consolidada, restricoes, modulo_fiscal_ha, area_2008_ha,
    pct_rl, pasta_saida

    Retorna dict: {"camadas": [QgsVectorLayer], "relatorio": caminho, "resumo": dict}
    """
    camada_perimetro = p["perimetro"]
    if camada_perimetro is None:
        raise ValueError("Selecione a camada de perímetro do imóvel.")
    if p["modulo_fiscal_ha"] <= 0:
        raise ValueError("Informe o tamanho do módulo fiscal do município (ha).")

    # --- SRC de trabalho (UTM SIRGAS 2000 do centróide do imóvel) ---
    geoms_originais = [f.geometry() for f in camada_perimetro.getFeatures() if f.hasGeometry()]
    if not geoms_originais:
        raise ValueError("A camada de perímetro está vazia.")
    centro_ref = QgsGeometry.unaryUnion([g.makeValid() for g in geoms_originais])
    src = src_utm_sirgas(centro_ref, camada_perimetro.crs())

    # --- 1. Validação ---
    problemas, parcelas = validar_perimetro(camada_perimetro, src)
    perimetro = uniao([g.makeValid() for _fid, g in parcelas])
    area_imovel = area_ha(perimetro)

    area_2008 = p["area_2008_ha"] if p["area_2008_ha"] > 0 else area_imovel
    n_modulos = area_2008 / p["modulo_fiscal_ha"]

    vegetacao, prob_veg = verificar_extrapolacao(p["vegetacao"], "Vegetação nativa", perimetro, src)
    consolidada, prob_cons = verificar_extrapolacao(p["consolidada"], "Área consolidada",
                                                    perimetro, src)
    problemas += [x for x in (prob_veg, prob_cons) if x]

    # --- 2. Sobreposições ---
    sobreposicoes = analisar_sobreposicoes(perimetro, area_imovel, p["restricoes"], src)

    # --- 3. APP ---
    res_app = modulo_app.calcular_app(
        perimetro, src, n_modulos,
        hidrografia=p["hidrografia"],
        campo_largura=p["campo_largura"],
        largura_padrao=p["largura_padrao"],
        nascentes=p["nascentes"],
        lagos=p["lagos"],
        consolidada=consolidada,
        rios_poligono=p.get("rios_poligono"),
    )
    limite = modulo_app.limite_61b(n_modulos, area_imovel)
    area_recompor = area_ha(res_app["app_recompor"])
    if res_app["app_nao_consolidada"] is not None:
        area_recompor_total = area_recompor + area_ha(res_app["app_nao_consolidada"])
    else:
        area_recompor_total = area_recompor

    # --- 4. Reserva Legal ---
    res_rl = calcular_rl(area_imovel, p["pct_rl"], n_modulos, vegetacao, res_app["app_integral"])

    # --- 5. Camadas de resultado ---
    camadas = _criar_camadas(src, perimetro, area_imovel, n_modulos, problemas,
                             sobreposicoes, res_app)

    # --- 6. Relatório ---
    resumo = {
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "camada_perimetro": camada_perimetro.name(),
        "src": f"{src.authid()} — {src.description()}",
        "area_imovel_ha": area_imovel,
        "area_2008_ha": area_2008,
        "modulo_fiscal_ha": p["modulo_fiscal_ha"],
        "n_modulos": n_modulos,
        "n_parcelas": len(parcelas),
        "problemas": problemas,
        "sobreposicoes": sobreposicoes,
        "app": {
            "detalhes": res_app["detalhes"],
            "avisos": res_app["avisos"],
            "integral_ha": area_ha(res_app["app_integral"]),
            "faixa_consolidada_ha": area_ha(res_app["faixa_consolidada"]),
            "recompor_ha": area_recompor,
            "recompor_total_ha": area_recompor_total,
            "liberada_ha": area_ha(res_app["consolidada_liberada"]),
            "tem_consolidada": consolidada is not None and not consolidada.isEmpty(),
            "consolidada_ha": area_ha(consolidada),
            "limite_61b_ha": limite,
        },
        "rl": res_rl,
    }

    caminho = p.get("caminho_relatorio")
    if caminho:
        os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    else:
        pasta = p.get("pasta_saida") or os.path.expanduser("~")
        os.makedirs(pasta, exist_ok=True)
        nome_arq = f"relatorio_car_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        caminho = os.path.join(pasta, nome_arq)
    gerar_relatorio_html(resumo, caminho)

    return {"camadas": camadas, "relatorio": caminho, "resumo": resumo}


def _criar_camadas(src, perimetro, area_imovel, n_modulos, problemas, sobreposicoes, res_app):
    """Cria as camadas de memória com os resultados da análise."""
    camadas = []

    # Perímetro no SRC de trabalho
    c_per = criar_camada_memoria("Perímetro (UTM)", "MultiPolygon", src,
                                 [("area_ha", "double"), ("n_modulos", "double")])
    adicionar_feicao(c_per, perimetro, [round(area_imovel, 4), round(n_modulos, 2)])
    camadas.append(c_per)

    # Problemas de validação
    if problemas:
        c_prob = criar_camada_memoria("Problemas de validação", "Point", src,
                                      [("feicao", "string"), ("tipo", "string"),
                                       ("descricao", "string")])
        for prob in problemas:
            adicionar_feicao(c_prob, QgsGeometry.fromPointXY(prob["ponto"]),
                             [str(prob["feicao"]), prob["tipo"], prob["descricao"]])
        camadas.append(c_prob)

    # Sobreposições
    if sobreposicoes:
        c_sob = criar_camada_memoria("Sobreposições", "MultiPolygon", src,
                                     [("camada", "string"), ("identific", "string"),
                                      ("area_ha", "double"), ("perc", "double")])
        for s in sobreposicoes:
            adicionar_feicao(c_sob, s["geometria"],
                             [s["camada"], s["identificador"], round(s["area_ha"], 4),
                              round(s["percentual"], 2)])
        camadas.append(c_sob)

    # APPs
    temas = [
        ("APP integral (art. 4º)", res_app["app_integral"]),
        ("Faixa escadinha (art. 61-A)", res_app["faixa_consolidada"]),
        ("APP a recompor em área consolidada", res_app["app_recompor"]
         if res_app["consolidada_liberada"] is not None else None),
        ("Uso consolidado mantido em APP", res_app["consolidada_liberada"]),
        ("APP fora de área consolidada", res_app["app_nao_consolidada"]),
    ]
    for nome, geom in temas:
        if geom is None or geom.isEmpty():
            continue
        c = criar_camada_memoria(nome, "MultiPolygon", src, [("area_ha", "double")])
        adicionar_feicao(c, geom, [round(area_ha(geom), 4)])
        if c.featureCount():
            camadas.append(c)

    return camadas
