# Política legal e de segurança

O translate-deck **não traduz nada**. Ele aplica patches de tradução feitos por
terceiros, com permissão registrada, e restaura o original byte a byte.

## O que o projeto faz e não faz

- Faz: baixar o artefato do tradutor, conferir SHA-256, inserir a tradução no
  `.pck` do jogo com backup e manifest, reverter quando pedido.
- Não faz: tradução automática/IA, OCR, overlay, editor de texto, contorno de
  DRM, alteração de executável, injeção de código, patch em jogo com anti-cheat.

## Base jurídica (por que o desenho é conservador)

- O Contrato de Assinatura da Steam (§2.G) lista "translate" e "create
  derivative works" entre os atos restritos; tradução é obra derivada também
  sob 17 USC §101. Por isso:
  - o catálogo distribui **apenas metadados + URL canônica do autor**;
  - nenhum asset do jogo e nenhum arquivo de tradução é hospedado aqui;
  - só entram entradas com permissão explícita documentada.
- O §4.B e as regras de conduta proíbem trapaça/adulteração em jogos online.
  Jogos com anti-cheat (EAC, BattlEye, VAC, Denuvo) ou componente online são
  **recusados**, não apenas avisados.
- Nada aqui contorna proteção técnica (DMCA §1201). Se o patch exigir quebrar
  DRM, a entrada é rejeitada.

## Permissão no catálogo (default-deny)

| status    | instala? | requisito                                      |
|-----------|----------|------------------------------------------------|
| `granted` | sim      | `evidence_url` https + `checked_at`            |
| `implied` | não      | revisão manual caso a caso                     |
| `unknown` | não      | aguardando contato com o tradutor              |
| `denied`  | nunca    | bloqueado permanentemente                      |

Autores que liberam cópia/modificação (ex.: termos da GameVicio) entram como
`granted` com o trecho e a data. Sem evidência, a tradução aparece na lista
como bloqueada e não instala.

## Remoção (takedown)

1. Autor ou titular abre issue no repositório do catálogo.
2. A entrada é removida em até **24 h**, `index.json` é regenerado e o SHA muda.
3. Como o plugin confere o SHA fixado do índice, a tradução deixa de ser
   oferecida na próxima atualização — sem depender de release do plugin.

## Anti-cheat e integridade

- Varredura por arquivos/pastas (`EasyAntiCheat`, `EasyAntiCheat_EOS`,
  `BattlEye`, `start_protected_game`, `*_EAC.exe`, `*_BE.exe`) antes de qualquer
  escrita; presença ⇒ aborta.
- Catálogo tem `risk.anticheat` e `risk.online`; qualquer um bloqueia.
- "Verificar integridade" da Steam deve voltar a baixar zero bytes após
  reverter, prova de que o original foi restaurado.

## Limites conhecidos

- O plugin **modifica arquivos do jogo** (repack do `.pck` Godot). Isso pode
  violar termos de uso individuais; a decisão de instalar é do usuário e a
  reversão é sempre possível enquanto o manifest existir.
- Atualização do jogo pode quebrar o patch: o `verify` detecta (`revalidated`)
  e oferece reaplicação.
- Build da loja não inclui fonte manual nem biblioteca local; sideload inclui, e
  é de responsabilidade de quem instala. Arquivos adicionados à biblioteca
  (`local/<id>`) não são hospedados nem distribuídos pelo projeto: ficam apenas
  no aparelho do usuário, com hash conferido a cada aplicação.
