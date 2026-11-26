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

Artefatos aceitos: `godot_translation` (`.translation` pronto), `po` e `pck`
(pack inteiro já traduzido). CSV não é aceito — o GDRE v2.7.x não converte CSV
sem o projeto/import original. Métodos: `godot_pck_translations` (insert de
entradas, kind `godot_translation`) e `godot_pck_replace` (substitui o pack
inteiro, kind `godot_pack_replace`, `params.replace_pack = true`).

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

## Biblioteca local (sideload)

O usuário adiciona arquivos que encontrou por conta própria; o plugin copia
para uma pasta gerenciada e aplica como qualquer tradução do catálogo.
Só existe na build sideload (`library.py` + seção do QAM).

```
<TDECK_HOME>/library/<appid>/<id>/
├─ descriptor.json   # metadados: locale, kind, sha256, targets, origem, data
└─ files/            # cópia do artefato (.translation/.po/.pck ou .json)
```

- Tipos aceitos: `.translation`, `.po`, `.pck` (pack inteiro), `.json`
  (descritor) e `.zip`/pasta com um desses arquivos.
- `id = <locale>-<sha256[:8]>` do artefato; mesmo conteúdo = mesma entrada.
- Exposto como `local/<id>`, sem colidir com IDs do catálogo.
- Destino no pack: `basename` igual ou entrada única; se houver mais de uma,
  a inspeção lista os caminhos e exige escolha (QAM/CLI).
- Zip: recusa caminho absoluto, `..`, symlink, mais de 2000 entradas ou 500 MB
  descompactado.
- Remover exige a tradução revertida (`manifest_revert` antes).
- Descritor `.json` aceita artefatos remotos https; o hash continua conferido
  no download.

```bash
tdeck inspect "traducao.zip" --appid 367520
tdeck library add "traducao.zip" --appid 367520
tdeck library list --appid 367520
tdeck install --appid 367520 --translation local/pt-br-1a2b3c4d --apply
tdeck uninstall --appid 367520
tdeck library remove 367520 local/pt-br-1a2b3c4d
```

O QAM mostra todos os jogos instalados com engine detectada; jogos Godot
aparecem na seção "Minhas traducoes (sideload)" com inspeção, adição e
ações Aplicar/Verificar/Reverter/Remover.

## Estado atual

O catálogo está vazio e **publicado** desde 2026-11-26 em
`https://victorcabral99.github.io/translate-deck-catalog/` (CI valida, regenera
`index.json` + `index.sha256` e publica Pages). O plugin fixa o digest atual
(`INDEX_SHA256` em `plugin/main.py`); publicar catálogo novo exige atualizar o
pin e a build. O spike do M0 validou leitura, extração e repack em packs reais
(Godot 4.7/4.8, inclusive 30+ `.po` de tradução) e a semântica do GDRE
(`--pck-patch`).

As primeiras entradas reais (2–3 jogos Godot) seguem sem candidato: buscas no
GameVicio e no GitHub (2026-11-26) não retornaram tradução de jogo Godot com
página do autor estável + artefato baixável sem login. Critério para entrar:
`source.author` + `origin_url` verificáveis, `permission.granted` com
`evidence_url` https, `sha256` calculado do arquivo real. Não invente URL nem
hash; enquanto não houver candidato, a build da loja lista jogos sem tradução.
