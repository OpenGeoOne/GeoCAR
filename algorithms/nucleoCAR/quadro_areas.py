# -*- coding: utf-8 -*-
"""
Quadro de áreas do imóvel, para preencher e conferir o SICAR.

Todas as áreas no SRC métrico do imóvel (UTM SIRGAS 2000), recortadas pela ATI. Sai no relatório da
pré-análise (seção 1) e numa planilha CSV (Pre-Analise/GeoCAR_Quadro_de_Areas_<data>.csv).
"""

import csv

from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

# Camadas declaradas de APP de relevo, vereda, manguezal e uso restrito (nomes das RAIZ)
CHAVES_USO_RESTRITO = ('uso_restrito', 'declividade_25_45', 'inclinacao_25')
CHAVES_APP_DECLARADA = ('decliv', 'encosta', 'altitude', 'topo_morro', 'borda', 'vereda', 'manguezal', 'mangue')


def classificar_camada(nome):
    """'uso_restrito', 'app' ou None, pelo nome da camada da RAIZ."""
    n = nome.lower()
    if any(c in n for c in CHAVES_USO_RESTRITO):
        return 'uso_restrito'
    if any(c in n for c in CHAVES_APP_DECLARADA):
        return 'app'
    return None


def _uniao_camada(camada, src, perimetro):
    geometrias = [g.makeValid() for _f, _a, g in feicoes_no_src(camada, src, perimetro.boundingBox())
                  if g is not None and not g.isEmpty()]
    if not geometrias:
        return None
    return recortar(uniao(geometrias), perimetro)


def calcular_quadro(perimetro, src, area_imovel, n_modulos, modulo_fiscal, vegetacao, coberturas, servidoes,
                    reservas, outras, res_app, res_rl, recompor_real):
    """
    Linhas do quadro: lista de dicts {grupo, item, area_ha, obs}. 'vegetacao' é geometria (ou None);
    coberturas, servidoes, reservas e outras são camadas.
    """
    linhas = []

    def linha(grupo, item, area, obs=''):
        linhas.append({'grupo': grupo, 'item': item, 'area_ha': area, 'obs': obs})

    # Imóvel
    servidao = uniao([g for g in (_uniao_camada(c, src, perimetro) for c in servidoes or []) if g is not None]) \
        if servidoes else None
    servidao_ha = area_ha(servidao) if servidao is not None and not servidao.isEmpty() else 0.0
    linha('Imóvel', 'Área total do imóvel (ATI)', area_imovel)
    linha('Imóvel', 'Servidão administrativa', servidao_ha, ', '.join(c.name() for c in servidoes or []
                                                                      if c.featureCount()))
    linha('Imóvel', 'Área líquida (ATI menos servidão administrativa)', area_imovel - servidao_ha)
    linha('Imóvel', 'Módulos fiscais', None, f'{n_modulos:.2f} MF (módulo de {modulo_fiscal:g} ha)'.replace('.', ','))

    # Cobertura do solo
    ocupado = []
    if vegetacao is not None and not vegetacao.isEmpty():
        linha('Cobertura do solo', 'Remanescente de vegetação nativa', area_ha(vegetacao))
        ocupado.append(vegetacao)
    for camada in coberturas or []:
        g = _uniao_camada(camada, src, perimetro)
        if g is not None and not g.isEmpty():
            linha('Cobertura do solo', camada.name(), area_ha(g))
            ocupado.append(g)
    if servidao is not None and not servidao.isEmpty():
        ocupado.append(servidao)
    if ocupado:
        linha('Cobertura do solo', 'Área sem cobertura declarada', area_ha(subtrair(perimetro, uniao(ocupado))),
              'deve ser zero: classifique ou use a 4e')

    # APP hídrica calculada pela pré-análise
    integral = res_app.get('app_integral')
    if integral is not None and not integral.isEmpty():
        linha('APP hídrica (calculada)', 'APP integral (art. 4º)', area_ha(integral))
        if vegetacao is not None and not vegetacao.isEmpty():
            linha('APP hídrica (calculada)', 'APP com vegetação nativa', area_ha(recortar(integral, vegetacao)))
        liberada = res_app.get('consolidada_liberada')
        if liberada is not None and not liberada.isEmpty():
            linha('APP hídrica (calculada)', 'Uso consolidado mantido em APP (art. 61-A)', area_ha(liberada))
        linha('APP hídrica (calculada)', 'APP a recompor', recompor_real)

    # APP de relevo, vereda, manguezal e uso restrito declarados nas camadas da RAIZ
    for camada in sorted(outras or [], key=lambda c: (classificar_camada(c.name()) != 'app', c.name())):
        tipo = classificar_camada(camada.name())
        g = _uniao_camada(camada, src, perimetro) if tipo else None
        if g is not None and not g.isEmpty():
            grupo = 'Uso restrito (art. 11)' if tipo == 'uso_restrito' else 'APP declarada (relevo, vereda, manguezal)'
            linha(grupo, camada.name(), area_ha(g))

    # Reserva Legal
    linha('Reserva Legal', f'RL exigida ({res_rl["percentual"]:g}% da ATI)', res_rl['exigida_ha'])
    if servidao_ha > 0:
        linha('Reserva Legal', f'RL sobre a área líquida ({res_rl["percentual"]:g}%)',
              (area_imovel - servidao_ha) * res_rl['percentual'] / 100.0, 'referência: servidão fora da base')
    total = []
    for camada in reservas or []:
        g = _uniao_camada(camada, src, perimetro)
        if g is not None and not g.isEmpty():
            linha('Reserva Legal', camada.name(), area_ha(g))
            total.append(g)
    linha('Reserva Legal', 'RL declarada (total)', area_ha(uniao(total)) if total else 0.0)
    linha('Reserva Legal', 'Vegetação nativa fora de APP', res_rl['vegetacao_fora_app_ha'],
          'disponível para a RL sem cômputo da APP')
    return linhas


def gravar_csv(linhas, caminho, cabecalho_extra=None):
    """Planilha para o Excel em português: separador ';' e vírgula decimal."""
    with open(caminho, 'w', newline='', encoding='utf-8-sig') as arquivo:
        escritor = csv.writer(arquivo, delimiter=';')
        for rotulo, valor in (cabecalho_extra or []):
            escritor.writerow([rotulo, valor])
        if cabecalho_extra:
            escritor.writerow([])
        escritor.writerow(['Grupo', 'Item', 'Área (ha)', 'Observação'])
        for l in linhas:
            area = '' if l['area_ha'] is None else f"{l['area_ha']:.4f}".replace('.', ',')
            escritor.writerow([l['grupo'], l['item'], area, l['obs']])
    return caminho
