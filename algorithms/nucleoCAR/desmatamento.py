# -*- coding: utf-8 -*-
"""
Desmatamento detectado pelo PRODES (INPE) e o marco de 22/07/2008 do Código Florestal.

- consultarProdes: polígonos de desmatamento anual dos seis biomas (TerraBrasilis, WFS aberto) na extensão da ATI;
- analisar_desmatamento: o que foi desmatado depois de 22/07/2008 dentro da ATI e o que disso está declarado como
  área consolidada (não pode), em APP ou em Reserva Legal (recomposição obrigatória).

O PRODES mapeia desmatamentos a partir de cerca de 1 ha, com imagens Landsat (30 m): a ausência de polígono não
prova que não houve supressão.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import date

from qgis.PyQt.QtCore import QDate, QMetaType
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsJsonUtils, QgsVectorLayer

from .utils import area_ha, feicoes_no_src, recortar, uniao

ARQUIVO_FONTES = os.path.join(os.path.dirname(__file__), 'fontes_restricoes.json')
NOME_PRODES = 'Desmatamento_PRODES'
MARCO = date(2008, 7, 22)
AREA_MINIMA_HA = 0.01          # 100 m²: abaixo disso é ruído de borda entre o PRODES e a ATI
POR_PAGINA = 1000

APOS = 'Após 22/07/2008'
A_CONFIRMAR = 'A confirmar (detectado em 2008)'
ANTES = 'Antes de 22/07/2008'

DESMATE_ATI = 'Desmatamento após 22/07/2008 na ATI'
DESMATE_CONFIRMAR = 'Desmatamento a confirmar (2008) na ATI'
CONSOLIDADA_POS = 'Área consolidada sobre desmatamento após 2008'
APP_POS = 'APP desmatada após 2008'
RL_POS = 'Reserva Legal desmatada após 2008'

CAMPOS = [('bioma', QMetaType.Type.QString), ('ano', QMetaType.Type.Int), ('data_imagem', QMetaType.Type.QString),
          ('periodo', QMetaType.Type.QString), ('area_ha', QMetaType.Type.Double), ('fonte', QMetaType.Type.QString),
          ('consulta', QMetaType.Type.QString)]


def _definicao():
    with open(ARQUIVO_FONTES, encoding='utf-8') as arquivo:
        return json.load(arquivo).get('prodes')


def periodo(ano, data):
    """Classifica o desmatamento em relação a 22/07/2008, pela data da imagem que o detectou (ou pelo ano)."""
    if data is not None and data > MARCO:
        return APOS if (ano or data.year) >= 2009 else A_CONFIRMAR
    if data is None and ano:
        return APOS if ano >= 2009 else (A_CONFIRMAR if ano == 2008 else ANTES)
    return ANTES


def _data(valor):
    if isinstance(valor, QDate) and valor.isValid():
        return date(valor.year(), valor.month(), valor.day())
    texto = str(valor or '')[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def consultarProdes(extensao, feedback):
    """
    Desmatamento anual do PRODES (todos os biomas) na extensão (QgsRectangle em graus, SIRGAS 2000/WGS 84),
    numa camada de memória. None se o serviço estiver indisponível.
    """
    definicao = _definicao()
    if not definicao:
        return None
    memoria = QgsVectorLayer('MultiPolygon?crs=EPSG:4674', NOME_PRODES, 'memory')
    memoria.dataProvider().addAttributes([QgsField(n, t) for n, t in CAMPOS])
    memoria.updateFields()
    hoje = date.today().strftime('%d/%m/%Y')
    caixa = (f'{extensao.yMinimum()},{extensao.xMinimum()},{extensao.yMaximum()},{extensao.xMaximum()},'
             f'urn:ogc:def:crs:EPSG::4326')
    respondeu = False
    novas = []
    for bioma, camada in definicao['camadas'].items():
        inicio = 0
        while True:
            if feedback is not None and feedback.isCanceled():
                return None
            parametros = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': camada,
                          'outputFormat': 'application/json', 'srsName': 'EPSG:4326', 'bbox': caixa,
                          'count': POR_PAGINA, 'startIndex': inicio}
            try:
                texto = urllib.request.urlopen(definicao['url'] + '?' + urllib.parse.urlencode(parametros),
                                               timeout=definicao.get('timeout', 30)).read().decode('utf-8')
            except Exception as erro:
                if feedback is not None:
                    feedback.reportError(f'PRODES {bioma}: serviço indisponível ({erro}).', fatalError=False)
                break
            respondeu = True
            campos = QgsJsonUtils.stringToFields(texto)
            feicoes = QgsJsonUtils.stringToFeatureList(texto, campos)
            for f in feicoes:
                geometria = QgsGeometry(f.geometry())
                if geometria.isNull():
                    continue
                geometria.convertToMultiType()
                ano = int(f['year']) if campos.indexFromName('year') >= 0 and f['year'] not in (None, '') else None
                data = _data(f['image_date']) if campos.indexFromName('image_date') >= 0 else None
                area = float(f['area_km']) * 100.0 if campos.indexFromName('area_km') >= 0 and f['area_km'] else None
                nova = QgsFeature(memoria.fields())
                nova.setGeometry(geometria)
                nova.setAttributes([bioma, ano, data.strftime('%d/%m/%Y') if data else '', periodo(ano, data),
                                    round(area, 4) if area is not None else None, definicao['fonte'], hoje])
                novas.append(nova)
            if len(feicoes) < POR_PAGINA:
                break
            inicio += POR_PAGINA
    if not respondeu:
        return None
    memoria.dataProvider().addFeatures(novas)
    if feedback is not None:
        apos = sum(1 for f in novas if f['periodo'] != ANTES)
        feedback.pushInfo(f'PRODES: {len(novas)} polígono(s) de desmatamento na área ({apos} depois de 22/07/2008 '
                          f'ou a confirmar)')
    return memoria


def _uniao_camadas(camadas, src, busca):
    geometrias = [g.makeValid() for c in camadas or [] if c is not None
                  for _f, _a, g in feicoes_no_src(c, src, busca) if g is not None and not g.isEmpty()]
    return uniao(geometrias) if geometrias else None


def _area(geometria, outra):
    if outra is None or outra.isEmpty():
        return 0.0, None
    comum = recortar(geometria, outra)
    if comum is None or comum.isEmpty():
        return 0.0, None
    return area_ha(comum), comum


def analisar_desmatamento(perimetro, src, camadas_prodes, consolidada=None, app=None, reservas=(), vegetacao=None):
    """
    Desmatamento do PRODES depois de 22/07/2008 (e os de 2008 a confirmar) dentro da ATI.
    consolidada, app, vegetacao: geometrias no SRC de trabalho (ou None); reservas: camadas de RL.
    Retorna None se o PRODES não foi consultado; senão dict com poligonos, itens (camada de resultado),
    totais e anos.
    """
    camadas_prodes = [c for c in camadas_prodes or [] if c is not None]
    if not camadas_prodes:
        return None
    busca = perimetro.boundingBox()
    reserva = _uniao_camadas(reservas, src, busca)
    poligonos, itens = [], []
    antes_ha = 0.0
    for camada in camadas_prodes:
        nomes = {n.lower(): n for n in camada.fields().names()}
        for _fid, atributos, geom in feicoes_no_src(camada, src, busca):
            if geom is None or geom.isEmpty():
                continue
            dentro = recortar(geom.makeValid(), perimetro)
            area = area_ha(dentro)
            if area < AREA_MINIMA_HA:
                continue
            valor = lambda n: atributos.get(nomes.get(n, ''), None)
            per = str(valor('periodo') or '')
            if per == ANTES or not per:
                antes_ha += area
                continue
            ano = valor('ano')
            ano = int(ano) if ano not in (None, '') and str(ano) != 'NULL' else None
            data = str(valor('data_imagem') or '')
            cons_ha, cons_g = _area(dentro, consolidada)
            app_ha, app_g = _area(dentro, app)
            rl_ha, rl_g = _area(dentro, reserva)
            veg_ha, _ = _area(dentro, vegetacao)
            poligonos.append({'ano': ano, 'data': data, 'periodo': per, 'bioma': str(valor('bioma') or ''),
                              'area_ha': area, 'consolidada_ha': cons_ha, 'app_ha': app_ha, 'rl_ha': rl_ha,
                              'vegetacao_ha': veg_ha})
            itens.append({'tipo': DESMATE_ATI if per == APOS else DESMATE_CONFIRMAR, 'ano': ano, 'data': data,
                          'area_ha': area, 'geometria': dentro})
            for tipo, a, g in ((CONSOLIDADA_POS, cons_ha, cons_g), (APP_POS, app_ha, app_g), (RL_POS, rl_ha, rl_g)):
                if a >= AREA_MINIMA_HA:
                    itens.append({'tipo': tipo, 'ano': ano, 'data': data, 'area_ha': a, 'geometria': g})
    poligonos.sort(key=lambda p: (p['ano'] or 0, -p['area_ha']))
    soma = lambda chave, so_apos=False: sum(p[chave] for p in poligonos if not so_apos or p['periodo'] == APOS)
    return {
        'poligonos': poligonos,
        'itens': itens,
        'apos_ha': soma('area_ha', True),
        'confirmar_ha': sum(p['area_ha'] for p in poligonos if p['periodo'] != APOS),
        'antes_ha': antes_ha,
        'consolidada_ha': soma('consolidada_ha'),
        'app_ha': soma('app_ha'),
        'rl_ha': soma('rl_ha'),
        'vegetacao_ha': soma('vegetacao_ha'),
        'anos': sorted({p['ano'] for p in poligonos if p['ano']}),
        'biomas': sorted({p['bioma'] for p in poligonos if p['bioma']}),
    }
