# -*- coding: utf-8 -*-
"""
Cálculo de Áreas de Preservação Permanente (APP) hídricas.

1) APP integral — art. 4º da Lei 12.651/2012
2) Faixa mínima de recomposição em área rural consolidada — art. 61-A
   ("escadinha"), em função do número de módulos fiscais em 22/07/2008
3) Limite de recomposição do art. 61-B (imóveis de até 4 módulos fiscais)

Observações de modelagem:
- A hidrografia linear é tratada como eixo do curso d'água. A faixa é medida
  a partir da borda da calha do leito regular, por isso o buffer aplicado é
  (faixa + largura / 2).
- Rios largos representados como polígono devem ser incluídos na camada de
  massas d'água ou convertidos previamente.
- A "escadinha" só se aplica DENTRO da área rural consolidada. Fora dela vale
  a APP integral.
- Normas estaduais podem ser mais restritivas. Confira a legislação local.
"""

from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

SEGMENTOS_BUFFER = 16


# ---------------------------------------------------------------------------
# Regras legais
# ---------------------------------------------------------------------------
def faixa_rio_integral(largura_m):
    """Art. 4º, I — faixa marginal de cursos d'água naturais (m)."""
    if largura_m < 10:
        return 30.0
    if largura_m <= 50:
        return 50.0
    if largura_m <= 200:
        return 100.0
    if largura_m <= 600:
        return 200.0
    return 500.0


def faixa_lago_integral(superficie_ha):
    """Art. 4º, II, a — lagos e lagoas naturais em zona rural (m)."""
    return 50.0 if superficie_ha <= 20 else 100.0


RAIO_NASCENTE_INTEGRAL = 50.0   # art. 4º, IV


def faixa_rio_consolidada(n_modulos, largura_m):
    """Art. 61-A, §§1º a 4º — faixa mínima de recomposição em rio (m)."""
    if n_modulos <= 1:
        return 5.0
    if n_modulos <= 2:
        return 8.0
    if n_modulos <= 4:
        return 15.0
    if n_modulos <= 10 and largura_m <= 10:
        return 20.0
    # Demais casos: metade da largura, mínimo 30 m e máximo 100 m
    return max(30.0, min(100.0, largura_m / 2.0))


def faixa_lago_consolidada(n_modulos):
    """Art. 61-A, §6º — lagos e lagoas naturais (m)."""
    if n_modulos <= 1:
        return 5.0
    if n_modulos <= 2:
        return 8.0
    if n_modulos <= 4:
        return 15.0
    return 30.0


RAIO_NASCENTE_CONSOLIDADA = 15.0   # art. 61-A, §5º


def limite_61b(n_modulos, area_imovel_ha):
    """
    Art. 61-B — limite da área total de APP a recompor:
    até 2 MF: 10% da área do imóvel; de 2 a 4 MF: 20%.
    Retorna o limite em ha ou None quando não se aplica.
    """
    if n_modulos <= 2:
        return area_imovel_ha * 0.10
    if n_modulos <= 4:
        return area_imovel_ha * 0.20
    return None


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------
def _largura(atributos, campo, padrao):
    """Lê a largura do curso d'água; usa o padrão se vazio ou inválido."""
    if not campo:
        return padrao, True
    try:
        valor = float(atributos.get(campo))
        if valor > 0:
            return valor, False
    except (TypeError, ValueError):
        pass
    return padrao, True


def calcular_app(perimetro, src_trabalho, n_modulos, hidrografia=None,
                 campo_largura=None, largura_padrao=5.0, nascentes=None,
                 lagos=None, consolidada=None):
    """
    Calcula as APPs hídricas dentro do perímetro.

    Retorna dict com geometrias e estatísticas:
    - app_integral, faixa_consolidada, app_recompor, consolidada_liberada
    - detalhes: lista de dicts por tema (tipo, faixa_integral, faixa_consolidada, area_ha)
    - avisos: lista de mensagens
    """
    # Margem de busca: maior faixa possível (500 m) + folga
    busca = perimetro.boundingBox()
    busca.grow(700.0)

    integral, escadinha, detalhes, avisos = [], [], [], []
    canais = []  # leitos regulares dos cursos d'água (não são APP)

    # --- Cursos d'água (linhas) ---
    if hidrografia is not None:
        sem_largura = 0
        geoms_i, geoms_c = [], []
        for _fid, atrib, geom in feicoes_no_src(hidrografia, src_trabalho, busca):
            largura, usou_padrao = _largura(atrib, campo_largura, largura_padrao)
            sem_largura += int(usou_padrao)
            meia = largura / 2.0
            fi = faixa_rio_integral(largura)
            fc = faixa_rio_consolidada(n_modulos, largura)
            geoms_i.append(geom.buffer(fi + meia, SEGMENTOS_BUFFER))
            geoms_c.append(geom.buffer(fc + meia, SEGMENTOS_BUFFER))
            canais.append(geom.buffer(meia, SEGMENTOS_BUFFER))  # leito regular
            detalhes.append({"tipo": f"Curso d'água ({largura:g} m)",
                             "faixa_integral": fi, "faixa_consolidada": fc})
        integral += geoms_i
        escadinha += geoms_c
        if sem_largura:
            avisos.append(f"{sem_largura} trecho(s) de hidrografia sem largura informada: "
                          f"adotado {largura_padrao:g} m.")

    # --- Nascentes (pontos) ---
    if nascentes is not None:
        n = 0
        for _fid, _a, geom in feicoes_no_src(nascentes, src_trabalho, busca):
            integral.append(geom.buffer(RAIO_NASCENTE_INTEGRAL, SEGMENTOS_BUFFER))
            escadinha.append(geom.buffer(RAIO_NASCENTE_CONSOLIDADA, SEGMENTOS_BUFFER))
            n += 1
        if n:
            detalhes.append({"tipo": f"Nascentes ({n})",
                             "faixa_integral": RAIO_NASCENTE_INTEGRAL,
                             "faixa_consolidada": RAIO_NASCENTE_CONSOLIDADA})

    # --- Lagos e lagoas naturais (polígonos) ---
    espelhos = []
    if lagos is not None:
        for _fid, _a, geom in feicoes_no_src(lagos, src_trabalho, busca):
            geom = geom.makeValid()
            superficie = area_ha(geom)
            fi = faixa_lago_integral(superficie)
            fc = faixa_lago_consolidada(n_modulos)
            integral.append(geom.buffer(fi, SEGMENTOS_BUFFER))
            escadinha.append(geom.buffer(fc, SEGMENTOS_BUFFER))
            espelhos.append(geom)
            detalhes.append({"tipo": f"Lago/lagoa ({superficie:.2f} ha)",
                             "faixa_integral": fi, "faixa_consolidada": fc})

    # O próprio leito e o espelho d'água não são APP
    agua = uniao(espelhos + canais)
    app_integral = recortar(subtrair(uniao(integral), agua), perimetro)
    faixa_consolidada = recortar(subtrair(uniao(escadinha), agua), perimetro)

    # Aplicação da "escadinha" somente na área consolidada
    if consolidada is not None and not consolidada.isEmpty():
        consolidada_em_app = recortar(app_integral, consolidada)
        app_recompor = recortar(faixa_consolidada, consolidada)
        consolidada_liberada = subtrair(consolidada_em_app, faixa_consolidada)
        # Fora da área consolidada, toda a APP integral deve ser preservada/recomposta
        app_nao_consolidada = subtrair(app_integral, consolidada)
    else:
        app_recompor = faixa_consolidada
        consolidada_liberada = None
        app_nao_consolidada = None
        if integral:
            avisos.append("Camada de área consolidada não informada: a faixa da 'escadinha' é "
                          "apresentada apenas como referência.")

    if not integral:
        avisos.append("Nenhuma feição hídrica informada ou encontrada próxima ao imóvel.")

    return {
        "app_integral": app_integral,
        "faixa_consolidada": faixa_consolidada,
        "app_recompor": app_recompor,
        "consolidada_liberada": consolidada_liberada,
        "app_nao_consolidada": app_nao_consolidada,
        "detalhes": detalhes,
        "avisos": avisos,
    }
