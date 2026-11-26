# Catálogo

Dois repositórios:

- código: `VictorCabral99/translate-deck` (este);
- dados: `VictorCabral99/translate-deck-catalog`, servido em GitHub Pages
  (`https://victorcabral99.github.io/translate-deck-catalog/index.json`).

## Formato

`schema/game.schema.json` e `schema/translation.schema.json` (JSON Schema
2020-12, `additionalProperties: false`, enums fechados). O validador de runtime
é `core/src/tdeck_core/catalog.py` — schema e validador precisam concordar.

Chaves proibidas em `install.params`: `script`, `command`, `cmd`, `exec`,
`preinstall`, `postinstall`. Não existe método de instalação que execute código.

Artefatos aceitos: `godot_translation` (`.translation` pronto) e `po`. CSV não
é aceito — o GDRE v2.7.x não converte CSV sem o projeto/import original.

`install.params` do Godot: `pck` (nome do `.pck`, opcional se houver um só),
`insert[{pck_path, artifact}]`, `project_settings` (gera `override.cfg`) e,
opcionalmente, `tool: "gdre"` + `gdre{path, key}` para aplicar via
`gdre_tools --pck-patch` em vez do escritor próprio.

## Fluxo de curadoria

1. Localize o tópico oficial do tradutor (GameVicio, GitHub, fórum do jogo).
2. Registre `source.author` + `source.origin_url` (página canônica).
3. Registre a permissão: `granted` exige `evidence_url` https e `checked_at`;
   sem isso fica `unknown` e não instala.
4. Calcule `sha256` do artefato e o tamanho em bytes.
5. Defina `install.params.insert` (paths `res://...` dentro do `.pck`) e, se o
   jogo ignorar o locale do sistema, `project_settings`.
6. `python scripts/build_index.py`, abra PR. CI valida e regenera
   `index.json` + `index.sha256`.

## Índice e pinagem

- `index.json` é determinístico (sem timestamp, chaves ordenadas).
- O plugin baixa `index.json`, confere o SHA-256 contra `INDEX_SHA256` embutido
  em `plugin/main.py` e só então valida/exibe.
- Publicou catálogo novo? Atualize `INDEX_SHA256` (e a build do plugin).
- `validate_index()` rejeita `schema_version` desconhecido e appid duplicado.

## Fonte manual (sideload)

O descritor manual usa o mesmo validador (`source.type = "manual"`). O CLI
`tdeck install --manual caminho.json --allow-unpermitted` mostra o plano, o
hash esperado e exige `--apply`. Na build da loja, `sources/manual.py` e
`plugin/manual_wiring.py` não existem: `manual_source_available()` responde
`false` e o QAM esconde a opção.

## Estado atual

O catálogo está vazio. O spike do M0 validou leitura, extração e repack em
packs reais (Godot 4.7/4.8, inclusive 30+ `.po` de tradução) e a semântica do
GDRE (`--pck-patch`).

As primeiras entradas reais (2–3 jogos Godot) seguem sem candidato: buscas no
GameVicio e no GitHub (2026-11-26) não retornaram tradução de jogo Godot com
página do autor estável + artefato baixável sem login. Critério para entrar:
`source.author` + `origin_url` verificáveis, `permission.granted` com
`evidence_url` https, `sha256` calculado do arquivo real. Não invente URL nem
hash; enquanto não houver candidato, a build da loja lista jogos sem tradução.
