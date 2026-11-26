# translate-deck (plugin Decky)

Backend fino sobre `tdeck_core`; nada de regra de negócio aqui.

## Build

```bash
cd plugin
npm install
npm run build            # gera dist/
python scripts/build.py --edition store    # out/store.zip (sem fonte manual)
python scripts/build.py --edition sideload # out/sideload.zip (com fonte manual)
```

`py_modules/tdeck_core` é copiado de `core/src` no empacotamento e não é
commitado. O zip da loja não contém `sources/manual.py` nem `manual_wiring.py`.

## Settings

`INDEX_SHA256` em `main.py` precisa apontar para o SHA do `index.json`
publicado antes de gerar a build.
