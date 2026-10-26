# -*- coding: utf-8 -*-
"""
Comparação da ATI com as parcelas certificadas no SIGEF (INCRA).

Classifica cada parcela que toca a ATI:
- "Parcela do imóvel": ao menos metade da parcela está dentro da ATI;
- "Parcela de terceiro dentro da ATI": a ATI avança sobre um imóvel certificado de outro;
- "Ajuste de divisa com parcela certificada": faixa estreita ao longo do limite.
E mede o que a ATI tem sem certificação e o que as parcelas do imóvel têm fora da ATI.
"""

from .sobreposicao import LARGURA_DIVISA_PADRAO, PERC_DIVISA_PADRAO, largura_media
from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

PARCELA_IMOVEL = "Parcela do imóvel"
PARCELA_TERCEIRO = "Parcela de terceiro dentro da ATI"
PARCELA_DIVISA = "Ajuste de divisa com parcela certificada"
SEM_CERTIFICACAO = "ATI sem parcela certificada"
FORA_ATI = "Parcela do imóvel fora da ATI"

AREA_MINIMA_HA = 0.0001       # 1 m²
FRACAO_DO_IMOVEL = 0.5        # parcela com ao menos metade dentro da ATI = parcela do próprio imóvel


def _valor(atributos, nome):
    chaves = {k.lower(): k for k in atributos}
    valor = atributos.get(chaves.get(nome, ""), "")
    return "" if valor in (None, "NULL") else str(valor)


def comparar_sigef(perimetro, area_imovel_ha, src, camadas):
    """
    camadas: camadas de parcelas certificadas (ex.: Parcelas_SIGEF da ferramenta 1c).
    Retorna None se nenhuma camada foi informada; senão um dict com
    parcelas (lista), sem_certificacao_ha, fora_ati_ha, matriculas, itens (para a camada de divergências).
    """
    camadas = [c for c in camadas or [] if c is not None]
    if not camadas:
        return None
    parcelas, vizinhas, geoms_todas, geoms_imovel = [], [], [], []
    for camada in camadas:
        for _fid, atributos, geom in feicoes_no_src(camada, src):
            if geom is None or geom.isEmpty():
                continue
            geom = geom.makeValid()
            dentro = recortar(geom, perimetro)
            area_dentro = area_ha(dentro)
            if area_dentro <= AREA_MINIMA_HA:
                # Imóvel certificado vizinho (confrontante ou próximo), que não toca a ATI
                vizinhas.append({"codigo": _valor(atributos, "codigo_imovel") or _valor(atributos, "parcela"),
                                 "nome": _valor(atributos, "nome_area"), "matricula": _valor(atributos, "matricula"),
                                 "area_parcela_ha": area_ha(geom), "distancia_m": geom.distance(perimetro)})
                continue
            area_parcela = area_ha(geom)
            fracao = area_dentro / area_parcela if area_parcela else 0.0
            if fracao >= FRACAO_DO_IMOVEL:
                classe = PARCELA_IMOVEL
                geoms_imovel.append(geom)
            elif (largura_media(dentro) <= LARGURA_DIVISA_PADRAO
                  and area_dentro / area_imovel_ha * 100.0 <= PERC_DIVISA_PADRAO):
                classe = PARCELA_DIVISA
            else:
                classe = PARCELA_TERCEIRO
            geoms_todas.append(geom)
            parcelas.append({
                "codigo": _valor(atributos, "codigo_imovel") or _valor(atributos, "parcela"),
                "nome": _valor(atributos, "nome_area"),
                "matricula": _valor(atributos, "matricula"),
                "situacao": _valor(atributos, "situacao"),
                "area_parcela_ha": area_parcela,
                "area_na_ati_ha": area_dentro,
                "perc_parcela": fracao * 100.0,
                "classe": classe,
                "geometria": dentro,
            })

    ordem = {PARCELA_IMOVEL: 0, PARCELA_TERCEIRO: 1, PARCELA_DIVISA: 2}
    parcelas.sort(key=lambda p: (ordem[p["classe"]], -p["area_na_ati_ha"]))

    sem_certificacao = subtrair(perimetro, uniao(geoms_todas)) if geoms_todas else perimetro
    fora_ati = subtrair(uniao(geoms_imovel), perimetro) if geoms_imovel else None

    itens = []
    for p in parcelas:
        if p["classe"] != PARCELA_IMOVEL:
            itens.append({"tipo": p["classe"], "codigo": p["codigo"], "matricula": p["matricula"],
                          "area_ha": p["area_na_ati_ha"], "geometria": p["geometria"]})
    if area_ha(sem_certificacao) > AREA_MINIMA_HA:
        itens.append({"tipo": SEM_CERTIFICACAO, "codigo": "", "matricula": "",
                      "area_ha": area_ha(sem_certificacao), "geometria": sem_certificacao})
    if fora_ati is not None and area_ha(fora_ati) > AREA_MINIMA_HA:
        itens.append({"tipo": FORA_ATI, "codigo": "", "matricula": "",
                      "area_ha": area_ha(fora_ati), "geometria": fora_ati})

    matriculas = sorted({p["matricula"] or p["codigo"] for p in parcelas if p["classe"] == PARCELA_IMOVEL})
    return {
        "parcelas": parcelas,
        "sem_certificacao_ha": area_ha(sem_certificacao),
        "fora_ati_ha": area_ha(fora_ati) if fora_ati is not None else 0.0,
        "matriculas": matriculas,
        "vizinhas": sorted(vizinhas, key=lambda v: v["distancia_m"]),
        "itens": itens,
    }
