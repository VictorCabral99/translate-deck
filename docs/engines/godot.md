# Engine Godot

## Formato do pack (GDPC)

Leitura/escrita própria em `core/src/tdeck_core/pck.py`, sem dependências.

```
magic "GDPC" | u32 format_version | u32 major, minor, patch
V1 (Godot 3.x): 16 x u32 reservado | u32 count | tabela após o header
   entrada: u32 path_len | utf8 | u64 offset | u64 size | md5[16]
   offset absoluto no arquivo
V2 (Godot 4.0-4.3): u32 pack_flags | u64 file_base | 16 x u32 reservado |
   u32 count | tabela após o header
   entrada: u32 path_len | utf8 | u64 offset | u64 size | md5[16] | u32 flags
   offset relativo a file_base (file_base absoluto, ou relativo ao início do
   pack quando PACK_REL_FILEBASE)
V3/V4 (Godot 4.4+): u32 pack_flags | u64 file_base | u64 dir_offset
   file_base e dir_offset são relativos ao início do pack; a tabela fica na
   posição dir_offset (normalmente no fim do arquivo) e começa com u32 count
   dados alinhados em 16 bytes
```

Observado em packs reais (4.8.0, 4.7.1): `pack_flags=2` (REL_FILEBASE),
`file_base=112`, tabela no fim. Caminhos podem vir com NULs de padding dentro
do `path_len`; o leitor descarta esses NULs.

- `read_pack()` valida magic, versão, `dir_offset`, contagem e limites de cada
  entrada (offsets dentro do arquivo, paths únicos e sem caracteres de controle).
- `rewrite_pack()` copia todas as entradas, substitui só as pedidas, recalcula
  offsets/tabela e grava no mesmo layout do original. Recusa pack com diretório
  criptografado, sparse bundle, pack embutido, ou entradas com flags
  (criptografada/removida/delta).
- A troca é atômica: grava em `<pack>.tdeck-new`, reabre e valida com
  `read_pack()` e só então `os.replace`.
- Pack embutido no executável: detectado pelo trailer `GDPC | u64 tamanho do
  pack | GDPC` no fim do `.exe` (validado com um exe real gerado pelo GDRE,
  Godot 4.7.1) ou pelo magic anexado; `tdeck pck list` lê para diagnóstico, mas
  a escrita continua **recusada**.

Validação feita no M0 (Windows, packs públicos, extração com MD5 e repack):

| Pack | Godot | Layout | Entradas | Resultado |
|---|---|---|---|---|
| Pixelorama 0.9.2 | 3.4.2 | V1 | 536 | leitura + repack, 0 MD5 divergentes |
| Pixelorama 1.0.1 | 4.2.2 | V2 | 846 | leitura + repack, 0 MD5 divergentes |
| Pixelorama 1.2.4 | 4.7.1 | V4 | 1281 | troca de `Translations/pt_BR.po` + `.po` novo, 1282 entradas, 0 divergências |
| GDRE Tools 2.7.4 | 4.8.0 | V4 | 94 | leitura + extração com MD5 |

V3 (formato intermediário do 4.4) não apareceu em nenhum pack público testado;
é lido com o mesmo caminho do V4 e o escritor gera V4.

## Instalação

1. Resolve a instalação Steam (`libraryfolders.vdf` + `appmanifest`).
2. `detect()` recusa anti-cheat, engine divergente, jogo em execução e falta de
   espaço (repack precisa ~2×).
3. Resolve o `.pck` (`install.params.pck` ou único `*.pck`).
4. `insert` mapeia artefato → path `res://...`; se o path existe, substitui; se
   não, adiciona.
5. Backup byte-exato em `<estado>/backups/<appid>/<buildid>/` + manifest com
   SHA-256 antes/depois.
6. `override.cfg` (`[internationalization] locale/fallback`) é **experimental**:
   só usar quando o jogo ignorar o locale do sistema; entra em `files_touched`
   e é removido no revert.

## Pack inteiro: `godot_pack_replace`

Traduções distribuídas como `.pck` já traduzido (sem `.translation` separado)
usam o método `godot_pck_replace` (`patch.kind = godot_pack_replace`,
artefato `pck`):

1. Exige pack-alvo não embutido; pack embutido no `.exe` continua recusado.
2. Valida o artefato com `read_pack()` antes de qualquer escrita.
3. Backup byte-exato do `.pck` original, cópia para `<pack>.tdeck-new`,
   revalidação e `os.replace`.
4. Manifest guarda hash antes/depois; `uninstall` restaura o original.
5. Não cria `override.cfg` — o pack já contém o locale.

Fonte do artefato: biblioteca local (sideload) ou catálogo. É o único método
que aceita pacote de terceiro sem saber o caminho interno da tradução; por
isso avisa sobre buildid divergente e exige confirmação na inspeção.

## Ferramenta alternativa: GDRE Tools

O escritor próprio é o padrão: artefatos `godot_translation` e `po` são
inseridos direto no `.pck`, sem binário externo.

O GDRE Tools (GPLv3, não vendorizado) pode ser usado como alternativa via
`install.params.tool = "gdre"`; ele faz o mesmo patch com `--pck-patch`:

```bash
gdre_tools.exe --headless --pck-patch=<Game.pck> --output=<Game.pck.tdeck-new> \
  --patch-file=<arquivo local>=res://caminho/no/pack
```

- Binário: `TDECK_GDRE_PATH`, `install.params.gdre.path` ou `gdre_tools` no PATH.
- Spike no M0 (GDRE v2.7.4): a saída é um **arquivo novo** (o `.pck` original não
  é tocado), com todas as entradas preservadas e o arquivo adicionado presente;
  por isso o fluxo grava em `.tdeck-new` e usa `os.replace`, igual ao writer.
- `--patch-translations` (CSV) foi testado e **não serve** para packs de
  terceiros: exige o layout de importação do projeto (`failed to get import
  info`). Por isso o catálogo não aceita artefato CSV: só `.translation`/`.po`
  prontos (`godot_translation`/`po`).
- Packs criptografados precisam de `install.params.gdre.key` (64 hex).

## Limite de escopo

O método `godot_pck_translations` cobre traduções embarcadas no `.pck`. Jogos
que leem traduções de uma pasta `i18n/` fora do pack (ex.: Pathway) exigem um
método de "arquivos soltos" com backup por arquivo, ainda não implementado.
Quando só existe um `.pck` já traduzido, use `godot_pack_replace` (com backup
do pack inteiro).

## Verificação

- `tdeck plan ...` (dry-run) lista escritas e bytes necessários.
- `tdeck install ... --apply` grava; `tdeck verify --appid N` reporta
  `installed` / `revalidated` / `missing`.
- `tdeck uninstall --appid N` restaura o backup; o SHA do `.pck` volta ao
  original (o E2E `tests/e2e/windows_e2e.py` prova isso a cada execução, nos
  dois métodos: insert e pack inteiro).
- Teste de aceitação no Deck: aplicar, abrir o jogo em PT-BR, reverter e rodar
  "verificar integridade" sem download.
