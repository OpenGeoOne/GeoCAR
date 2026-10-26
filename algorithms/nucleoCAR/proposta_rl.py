# -*- coding: utf-8 -*-
"""
Rascunho de Reserva Legal (ferramenta 4e).

Escolhe, sobre a vegetação nativa, a área que falta para a RL exigida (art. 12), descontada a RL já declarada:
1. vegetação nativa fora de APP, servidão e RL declarada;
2. se faltar e o cômputo for permitido, APP com vegetação nativa (art. 15).
Quando há mais vegetação que o necessário, a RL cresce a partir da APP e da RL já declarada (ou, sem elas, a partir
da divisa do imóvel), para ficar contínua e formar corredor com a APP e com os vizinhos.
Todas as geometrias no SRC métrico do imóvel (UTM).
"""

from qgis.core import QgsGeometry

AREA_MINIMA_M2 = 1.0
PARTE_MINIMA_M2 = 500.0   # fragmentos de vegetação menores que isso não entram no rascunho
SEGMENTOS = 8
ITERACOES = 40

ORIGEM_VEGETACAO = "Vegetação nativa fora de APP"
ORIGEM_APP = "APP com vegetação nativa (art. 15)"


def _vazia(g):
    return g is None or g.isEmpty() or g.area() < AREA_MINIMA_M2


def _menos(a, b):
    return QgsGeometry(a) if _vazia(b) else a.difference(b)


def _limpar(g, minimo=AREA_MINIMA_M2):
    """Só as partes com área de ao menos 'minimo' m²."""
    if _vazia(g):
        return QgsGeometry()
    partes = [p for p in g.asGeometryCollection() if p.area() >= minimo]
    return QgsGeometry.unaryUnion(partes) if partes else QgsGeometry()


def _buscar(disponivel, sementes, meta_m2):
    """A menor faixa em volta das sementes cuja interseção com o disponível alcança a meta (busca binária)."""
    caixa = disponivel.boundingBox()
    caixa.combineExtentWith(sementes.boundingBox())
    baixo, alto = 0.0, (caixa.width() ** 2 + caixa.height() ** 2) ** 0.5
    melhor = QgsGeometry(disponivel)
    for _ in range(ITERACOES):
        meio = (baixo + alto) / 2.0
        escolha = disponivel.intersection(sementes.buffer(meio, SEGMENTOS))
        if escolha.area() >= meta_m2:
            melhor, alto = escolha, meio
        else:
            baixo = meio
        if alto - baixo < 0.05:
            break
    return melhor


def crescer(disponivel, sementes, meta_m2, minimo=PARTE_MINIMA_M2):
    """
    Parte da área disponível com a meta (m²), crescendo a partir das sementes. Fragmentos menores que 'minimo'
    não entram (não servem como RL); a área que eles deixariam de fora é compensada crescendo um pouco mais.
    """
    disponivel = _limpar(disponivel, minimo)
    if _vazia(disponivel) or meta_m2 <= 0:
        return QgsGeometry()
    if disponivel.area() <= meta_m2:
        return disponivel
    if sementes is None or sementes.isEmpty():
        sementes = disponivel.centroid()
    alvo, escolha = meta_m2, QgsGeometry()
    for _ in range(6):
        bruta = _buscar(disponivel, sementes, alvo)
        escolha = _limpar(bruta, minimo)
        if escolha.area() >= meta_m2 - AREA_MINIMA_M2 or bruta.area() >= disponivel.area() - AREA_MINIMA_M2:
            break
        alvo += meta_m2 - escolha.area()
    return escolha


def propor_rl(ati, percentual, vegetacao, app=None, reserva_declarada=None, servidao=None, computar_app=True):
    """
    Retorna dict com exigida_ha, declarada_ha, falta_ha, partes (lista de (origem, geometria)), proposta_ha,
    deficit_ha (o que nem a vegetação cobre) e avisos.
    """
    avisos = []
    exigida = ati.area() * percentual / 100.0
    declarada = QgsGeometry() if _vazia(reserva_declarada) else reserva_declarada.intersection(ati)
    declarada_m2 = 0.0 if _vazia(declarada) else declarada.area()
    falta = exigida - declarada_m2
    resultado = {"exigida_ha": exigida / 1e4, "declarada_ha": declarada_m2 / 1e4, "falta_ha": max(falta, 0) / 1e4,
                 "partes": [], "proposta_ha": 0.0, "deficit_ha": 0.0, "avisos": avisos}
    if falta <= AREA_MINIMA_M2:
        avisos.append("A Reserva Legal declarada já alcança a exigida: nada a propor.")
        return resultado
    if _vazia(vegetacao):
        avisos.append("Sem vegetação nativa na ATI: a RL terá de ser recomposta ou compensada (art. 66).")
        resultado["deficit_ha"] = falta / 1e4
        return resultado

    ocupado = [g for g in (servidao, declarada) if not _vazia(g)]
    ocupado = QgsGeometry.unaryUnion(ocupado) if ocupado else QgsGeometry()
    vegetacaoNaAti = _menos(vegetacao.intersection(ati), ocupado)
    if _vazia(app):
        avisos.append("APP não informada (camada APP_Integral vazia): rode a pré-análise do grupo 3 antes, ou o "
                      "rascunho pode incluir APP.")
        foraApp, naApp = vegetacaoNaAti, QgsGeometry()
    else:
        foraApp, naApp = _menos(vegetacaoNaAti, app), vegetacaoNaAti.intersection(app)

    # Sementes: APP e RL declarada; sem elas, a divisa do imóvel (encosta nos vizinhos)
    sementes = [g for g in (app, declarada) if not _vazia(g)]
    sementes = QgsGeometry.unaryUnion(sementes) if sementes else QgsGeometry(ati.constGet().boundary())

    escolha = crescer(_limpar(foraApp), sementes, falta)
    if not _vazia(escolha):
        resultado["partes"].append((ORIGEM_VEGETACAO, escolha))
        falta -= escolha.area()
    if falta > AREA_MINIMA_M2 and computar_app and not _vazia(naApp):
        semente = escolha if not _vazia(escolha) else sementes
        escolhaApp = crescer(_limpar(naApp), semente, falta)
        if not _vazia(escolhaApp):
            resultado["partes"].append((ORIGEM_APP, escolhaApp))
            falta -= escolhaApp.area()
            avisos.append("Parte da RL proposta está em APP (art. 15): só vale se não houver nova supressão de "
                          "vegetação e a APP estiver conservada ou em recuperação.")
    resultado["proposta_ha"] = sum(g.area() for _o, g in resultado["partes"]) / 1e4
    if falta > AREA_MINIMA_M2:
        resultado["deficit_ha"] = falta / 1e4
        avisos.append(f"Faltam {falta / 1e4:.4f} ha sem vegetação nativa disponível: recompor, regenerar ou compensar "
                      f"(art. 66). Imóvel com até 4 módulos fiscais em 22/07/2008 pode ficar com a vegetação "
                      f"existente naquela data (art. 67).")
    return resultado
