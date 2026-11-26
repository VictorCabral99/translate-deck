# Submissão ao Decky Plugin Store

Status em 2026-11-26: **não submetido**. Catálogo publicado e índice fixado
(etapas 1–2 concluídas); restam teste no Deck, repositório de release e o PR.
As etapas abaixo estão na ordem em que precisam acontecer; as marcadas com
"bloqueio" dependem de ações fora do repositório (Deck físico, conta GitHub).

## Requisitos verificados na wiki oficial

Fonte: `wiki.deckbrew.xyz/en/plugin-dev/submitting-plugins`
(consultado em 2026-11-26) e README do `decky-plugin-database`.

- Submissão = PR no `SteamDeckHomebrew/decky-plugin-database` adicionando um
  **submódulo git** em `plugins/<nome>` apontando para o commit exato a publicar.
- O repositório do submódulo precisa ter `plugin.json`, `package.json`, `main.py`,
  `dist/` e `py_modules/` **na raiz** — a loja usa o próprio repositório, não um
  zip de release.
- Licença obrigatória na raiz (`LICENSE`); sem repositório privado, sem binário
  "caixa-preta", sem código ofuscado.
- Plugin com código LLM é rejeitado; backend Python próprio é permitido, mas
  precisa de teste em SteamOS (Beta/Preview quando aplicável).
- Atualização = novo commit no submódulo + bump de versão no `package.json`.

Consequência para este projeto: o monorepo (`core/`, `plugin/`, `tests/`) **não**
serve como submódulo, porque o plugin está em `plugin/`. É preciso um repositório
de release separado com a build da loja na raiz.

## Etapas

1. **Catálogo publicado** (bloqueio: conta GitHub).
   `translate-deck-catalog` precisa existir em GitHub Pages; o CI gera
   `index.json` + `index.sha256` e publica. Sem catálogo o plugin instala, mas
   não lista nada.

2. **Fixar o índice** em `plugin/main.py`.
   `INDEX_SHA256` = conteúdo de `index.sha256` (64 hex, sem newline). Enquanto
   estiver vazio, `refresh_catalog` recusa por design. O valor muda a cada
   publicação do catálogo, então pine só depois que o catálogo estabilizar.

3. **Repositório de release** (bloqueio: criar repo público).
   Sugestão de nome: `translate-deck-plugin`. Conteúdo da raiz = saída de
   `python plugin/scripts/build.py --edition store` (flat, já inclui `LICENSE`,
   `plugin.json`, `package.json`, `main.py`, `dist/`, `py_modules/`).
   O `package.json` precisa de `version` própria do plugin (bump a cada release);
   o repo de release não tem histórico de build, então o commit enviado é o que
   a loja vai instalar.

   ```bash
   python plugin/scripts/build.py --edition store
   mkdir -p ../translate-deck-plugin && unzip -o out/store.zip -d ../translate-deck-plugin
   # revisar, commitar e publicar ../translate-deck-plugin
   unzip -l out/store.zip | grep -i manual   # deve sair vazio: exit 1
   ```

4. **Teste no Deck** (bloqueio: Deck físico, branches Stable + Beta).
   Instalar a build sideload, abrir o QAM, atualizar catálogo, instalar e
   reverter um jogo real; `journalctl -u plugin_loader` sem traceback.

   Observação sobre a build da loja: o backend da fonte manual
   (`sources/manual.py` + `manual_wiring.py`) e o chunk `dist/ManualSource-*`
   (import dinâmico da UI) não existem no zip. O `index.js` mantém a referência
   ao chunk, mas o import só é executado quando `manual_source_available`
   responde `true`, o que nunca acontece na build da loja.

5. **PR no decky-plugin-database**.
   Fork → `git submodule add <url do repo de release> plugins/translate-deck` com
   o commit testado → PR. No texto do PR: o plugin não traduz nada, não inclui
   assets de jogo, só aplica patch assinado por sha256 com backup e revert
   byte-exato; catálogo default-deny; fonte manual ausente da build da loja.

## Checklist antes do PR

- [ ] `python -m pytest` verde (core).
- [ ] `tdeck catalog validate` e `build_index.py --check` verdes.
- [ ] `out/store.zip` sem `manual_wiring.py`/`sources/manual.py` (grep acima).
- [ ] `INDEX_SHA256` preenchido e igual ao `index.sha256` publicado.
- [ ] `package.json` com versão nova e `plugin.json` com descrição/tags atuais.
- [ ] Repositório de release público com `LICENSE` (MIT) na raiz.
- [ ] Teste em Deck: instalar, verificar, desinstalar com hash original.
- [ ] `docs/legal.md` linkado no README do repo de release.
