# translate-deck

Hub de traduções para o Steam Deck (Decky Loader). Descobre traduções de jogos
em um catálogo curado e as aplica nos arquivos do jogo com backup e rollback.
Na build sideload, também lista todos os jogos instalados e aceita arquivos de
tradução do próprio usuário (biblioteca local, `local/<id>`).

- `core/` — biblioteca Python + CLI `tdeck` (sem dependências externas)
- `plugin/` — plugin Decky (backend Python + painel QAM)
- catálogo — repositório separado, servido por GitHub Pages
  (`translate-deck-catalog`, em `C:\Projetos\translate-deck-catalog`)
- `docs/` — [legal](docs/legal.md), [catálogo](docs/catalog.md),
  [engine Godot](docs/engines/godot.md), [terceiros](docs/THIRD_PARTY.md),
  [submissão](docs/submission.md)

## Desenvolvimento

```bash
python -m venv .venv && .venv/Scripts/pip install -e core/ pytest
python -m pytest                 # 69 testes (+1 condicional ao GDRE real)
python tests/e2e/windows_e2e.py  # catálogo e biblioteca: apply -> verify -> revert byte-exato
tdeck doctor
```

Uso típico:

```bash
tdeck games list
tdeck pck list --file "Game.pck" --translations   # inspeciona um pack
tdeck catalog validate --catalog ../translate-deck-catalog
tdeck plan --appid 367520 --translation hk-ptbr
tdeck install --appid 367520 --translation hk-ptbr --apply
tdeck uninstall --appid 367520
```

Biblioteca local (sideload):

```bash
tdeck inspect "traducao.zip" --appid 367520
tdeck library add "traducao.zip" --appid 367520
tdeck library list --appid 367520
tdeck install --appid 367520 --translation local/pt-br-1a2b3c4d --apply
tdeck library remove 367520 local/pt-br-1a2b3c4d
```

Plugin:

```bash
cd plugin && npm install && npm run build
python scripts/build.py --edition store      # out/store.zip (sem fonte manual/biblioteca)
python scripts/build.py --edition sideload   # out/sideload.zip
bash tools/deck_smoke.sh sideload            # instala e reinicia o Decky no Deck
```

Nada aqui traduz texto: o projeto apenas instala traduções feitas pela
comunidade, com permissão registrada no catálogo. Jogos com anti-cheat ou
componente online são recusados. O catálogo começa vazio: entradas reais só
entram com `evidence_url` do autor e `sha256` do artefato.
