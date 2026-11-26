# Componentes de terceiros

## GDRE Tools

- Projeto: Godot RE Tools (GDRETools), licença **GPLv3**.
- Não é vendorizado neste repositório nem embutido no zip do plugin.
- Uso opcional (`install.params.tool = "gdre"`) para aplicar `.translation`/`.po`
  no pack via `--pck-patch` quando o escritor próprio não servir; o padrão não
  precisa de binário externo.
- Distribuição prevista via `remote_binary` do Decky (`package.json` com URL +
  `sha256hash`, conferidos pelo loader) ou apontando `TDECK_GDRE_PATH` para uma
  instalação local. Redistribuição, se houver, será do binário **sem
  modificação**, com link para o código-fonte; ver a licença do projeto.
- Nenhuma alteração de código GPL é feita aqui; o acionamento é por subprocesso.

## Godot Engine

- Formato de pack documentado publicamente; implementação em Python é
  interoperabilidade de formato, não código derivado do Godot (MIT).

## Decky Loader

- Plugin segue a API pública do loader; sem binários remotos hoje
  (`remote_binary` vazio).
