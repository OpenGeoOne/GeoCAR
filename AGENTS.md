# AGENTS.md — GeoCAR / PyQGIS

## Contexto do projeto

Este projeto contém rotinas Python e um plugin para QGIS, com foco em geoprocessamento, cadastro ambiental rural e planejamento de voo com drones.

## Ambiente

- Sistema operacional: macOS.
- QGIS: 3.44.
- Python: 3.12, integrado ao QGIS.
- Execução habitual: Console Python ou Editor de Scripts do QGIS.

## Estilo de código

- Escrever código linear, de cima para baixo.
- Não usar `if __name__ == "__main__"`.
- Usar nomes de variáveis em camelCase.
- Escrever comentários e docstrings em português do Brasil.
- Colocar imports no topo e importar somente o necessário.
- Nunca usar `from qgis.core import *`.
- Incluir em toda rotina o cabeçalho:

  ```python
  # Descrição do que faz
  # nomeArquivo.py
  ```

- `print()` é permitido, pois as rotinas são executadas no Console do QGIS.
- Usar caminhos completos quando a rotina for destinada ao uso local.

## CRS e cálculos métricos

- EPSG:4326: WGS 84 geográfico.
- EPSG:4674: SIRGAS 2000 geográfico.
- EPSG:31983: SIRGAS 2000 / UTM 23S, usual para SP, RJ, MG, PR e GO.
- EPSG:31982: SIRGAS 2000 / UTM 22S.
- EPSG:31984: SIRGAS 2000 / UTM 24S.
- EPSG:3857: Web Mercator, somente para visualização.

Para distância, área, buffer e outras operações métricas, usar CRS projetado em UTM. Nunca calcular distância ou área diretamente em graus.

## Regras PyQGIS

- Chamar `camada.updateExtents()` depois de adicionar feições.
- Usar `QgsVectorFileWriter.writeAsVectorFormatV3` para exportação vetorial.
- Verificar o CRS e o tipo de geometria antes de processar uma camada.
- Validar a existência das camadas e dos campos usados pela rotina.
- Não acessar `QgsProject` ou `QgsVectorLayer` dentro de `QgsTask.run()`, para evitar crashes.

## Skill especializada

Para tarefas específicas de PyQGIS, consultar:

`skills/pyqgis/SKILL.md`

O manual de referência do PyQGIS 3.44 está indicado dentro dessa skill.

## Segurança e manutenção

- Preservar alterações existentes no projeto.
- Não apagar arquivos ou executar comandos destrutivos sem autorização explícita.
- Verificar as alterações e testar a rotina em proporção ao risco antes de concluir.
