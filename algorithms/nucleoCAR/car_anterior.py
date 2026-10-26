# -*- coding: utf-8 -*-
"""
Comparação da ATI com o CAR atual do imóvel (retificação).

Com o código do CAR atual informado, esse cadastro deixa de ser tratado como sobreposição com vizinho e a
pré-análise mostra o que a nova ATI acrescenta e retira. Sem o código, um CAR que coincide quase todo com a
ATI (nos dois sentidos) é apontado como provável retificação ou CAR duplicado.
"""

from .utils import area_ha, feicoes_no_src, recortar, subtrair

CLASSE_PROPRIO = 'CAR do próprio imóvel (retificação)'
ACRESCIDA = 'Acrescida na retificação'
RETIRADA = 'Retirada na retificação'
COINCIDENCIA_MINIMA = 0.8      # fração da ATI e do CAR em comum para "provável CAR do próprio imóvel"
AREA_MINIMA_HA = 0.0001
STATUS = {'AT': 'Ativo', 'PE': 'Pendente', 'SU': 'Suspenso', 'CA': 'Cancelado'}


def _valor(atributos, nome):
    chaves = {k.lower(): k for k in atributos}
    valor = atributos.get(chaves.get(nome, ''), '')
    if valor is None or str(valor) == 'NULL':
        return ''
    if hasattr(valor, 'toString'):
        return valor.toString('dd/MM/yyyy')
    return str(valor)


def comparar_car_anterior(perimetro, src, camadas, codigo=''):
    """
    camadas: camadas com o campo cod_imovel (CARs do SICAR). Retorna None se não há CAR tocando a ATI e
    nenhum código foi informado; senão dict com codigo, encontrado, confirmado (código informado e achado),
    provavel, status, condicao, criacao, area_declarada, area_car_ha, area_ati_ha, comum_ha, perc_ati,
    perc_car, acrescida_ha, retirada_ha e itens (geometrias para a camada de resultado).
    """
    codigo = (codigo or '').strip().upper()
    area_ati = area_ha(perimetro)
    candidatos = []
    for camada in camadas or []:
        if camada is None or camada.fields().indexFromName('cod_imovel') < 0:
            continue
        for _fid, atributos, geom in feicoes_no_src(camada, src, perimetro.boundingBox()):
            if geom is None or geom.isEmpty():
                continue
            geom = geom.makeValid()
            cod = _valor(atributos, 'cod_imovel').strip().upper()
            comum = area_ha(recortar(perimetro, geom))
            if comum <= AREA_MINIMA_HA and cod != codigo:
                continue
            area_car = area_ha(geom)
            candidatos.append({'codigo': cod, 'atributos': atributos, 'geometria': geom, 'comum_ha': comum,
                               'area_car_ha': area_car,
                               'perc_ati': comum / area_ati * 100.0 if area_ati else 0.0,
                               'perc_car': comum / area_car * 100.0 if area_car else 0.0})
    if codigo:
        escolhido = next((c for c in candidatos if c['codigo'] == codigo), None)
        if escolhido is None:
            return {'codigo': codigo, 'encontrado': False, 'confirmado': False, 'provavel': False}
        confirmado, provavel = True, False
    else:
        provaveis = [c for c in candidatos
                     if min(c['perc_ati'], c['perc_car']) >= COINCIDENCIA_MINIMA * 100.0]
        if not provaveis:
            return None
        escolhido = max(provaveis, key=lambda c: c['comum_ha'])
        confirmado, provavel = False, True

    geom = escolhido['geometria']
    acrescida = subtrair(perimetro, geom)
    retirada = subtrair(geom, perimetro)
    itens = []
    if confirmado:
        for tipo, g in ((ACRESCIDA, acrescida), (RETIRADA, retirada)):
            if g is not None and area_ha(g) > AREA_MINIMA_HA:
                itens.append({'tipo': tipo, 'area_ha': area_ha(g), 'geometria': g})
    atributos = escolhido['atributos']
    status = _valor(atributos, 'status_imovel')
    area_declarada = _valor(atributos, 'area')
    try:
        area_declarada = float(area_declarada) if area_declarada else None
    except ValueError:
        area_declarada = None
    return {
        'codigo': escolhido['codigo'],
        'encontrado': True,
        'confirmado': confirmado,
        'provavel': provavel,
        'status': STATUS.get(status, status),
        'condicao': _valor(atributos, 'condicao'),
        'criacao': _valor(atributos, 'dat_criacao'),
        'area_declarada': area_declarada,
        'area_car_ha': escolhido['area_car_ha'],
        'area_ati_ha': area_ati,
        'comum_ha': escolhido['comum_ha'],
        'perc_ati': escolhido['perc_ati'],
        'perc_car': escolhido['perc_car'],
        'acrescida_ha': area_ha(acrescida) if acrescida is not None else 0.0,
        'retirada_ha': area_ha(retirada) if retirada is not None else 0.0,
        'itens': itens,
    }
