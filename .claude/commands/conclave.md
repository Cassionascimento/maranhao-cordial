---
description: Convoca o Conclave completo do Conselho de Agentes (Pirret, Standard, Zilda, Leonard, Marie, Rua, Dicio, Iris) sobre uma demanda. Nenhuma ação externa é executada.
argument-hint: [demanda a analisar — se omitido, use a pendência mais relevante do Modo Diretor/mi_decisao]
---

Você está orquestrando um **Conclave** do Conselho de Agentes da Maranhão
Cordial. Isto NÃO é uma etapa de código — é uma sessão de análise. **Não
edite arquivos da aplicação, não faça commit, não execute nada externo.**

## Nota de compatibilidade desta interface
Em algumas superfícies (ex.: Claude Code no app desktop), `Agent(subagent_type="<nome-do-agente>")` não reconhece os subagentes de projeto — só um roster fixo do runtime. Teste isso antes de seguir; se falhar, use `mi_conselho_orquestrador.py` para adaptar o mesmo fluxo abaixo sem duplicá-lo: `classificar_especialistas(demanda)` decide quem convocar, `carregar_persona(agente)` lê o `.md` original, `formatar_contexto_factual(snapshot)` prepara o dado somente-leitura (ou o marcador de dado indisponível, se não houver `snapshot`), e `montar_prompt(...)` monta o texto final — que você então passa como `prompt` para `Agent(subagent_type="general-purpose", ...)`. O fluxo, os passos e o formato final continuam sendo exatamente os desta especificação.

Demanda a analisar: $ARGUMENTS

Se nenhuma demanda foi passada, identifique a pendência mais relevante hoje
(leia `mi_decisao.py`/`mi_diretor.py`/o estado mais recente conhecido nesta
conversa; se não houver nada real e específico, diga isso e pare — **não
invente uma demanda só para ter o que analisar**).

## Regra central
Não aceite oito monólogos isolados. Os agentes precisam realmente reagir uns
aos outros quando divergem, com evidência — não apenas "concordo".

## Regras que valem para toda a sessão (não só para um passo)
- **Não recomende de novo o que já está em andamento.** Antes de montar o
  pacote de estado (passo 0), confira o que `mi_decisao.py`/`mi_diretor.py`
  já mostram como em andamento/concluído/bloqueado para esta demanda. Se um
  agente propuser uma ação que já está em curso ou já foi concluída, ela
  não vira "recomendação nova" — vira só uma confirmação do status
  existente. Julgue por EQUIVALÊNCIA DE INTENÇÃO, não por semelhança
  textual (duas frases diferentes podem descrever a mesma ação; frases
  parecidas podem descrever ações diferentes) — na dúvida, pergunte, não
  presuma nenhum dos dois lados.
- **Todo número que pesa numa decisão precisa de proveniência.** Valor,
  unidade, origem (FONTE_INTERNA | FORNECEDOR | POLITICA | CALCULO |
  ESTIMATIVA), fonte e confiança. Um número sem essa tag nunca é
  apresentado como fato ou política — no máximo como ESTIMATIVA, marcada
  como tal, e isso por si só é motivo para "Precisa do Diretor: SIM".
- **Divergência só existe entre posições realmente incompatíveis sobre a
  MESMA decisão atual.** Um dado ausente é lacuna, não divergência. Um
  risco apontado é risco, não divergência. Uma condicional ("se Standard
  não aprovar, então...") é hipótese, não divergência. Dois agentes
  analisando dimensões diferentes do mesmo problema, sem conclusões
  incompatíveis, não divergem. Classifique cada caso antes de escrever
  "Divergências" no formato final — não escreva "agentes divergem" quando,
  na prática, só falta um dado.
- **"Precisa do Diretor" sempre vem com motivo concreto — nunca genérico.**
  Ausência de informação ou uma divergência aparente (que na checagem
  acima não era divergência real) não escalam sozinhas para o Diretor. Só
  escalam: veto, divergência real não resolvida, ou dado ausente que
  bloqueia uma decisão iminente/irreversível — e o motivo escrito precisa
  nomear qual desses é.

## Fluxo obrigatório

0. **Pacote de estado.** Antes de convocar qualquer especialista, monte (ou
   peça à Iris que monte, já que ela lê `mi_sinais`/`mi_decisao`/
   `mi_calendario`) um resumo curto com: estado atual, ações já
   concluídas, ações já em andamento, evidências disponíveis, bloqueios,
   dependências, prazos e restrições conhecidas. Todo agente convocado
   recebe esse resumo junto com a demanda — nenhum agente analisa "no
   vácuo".

1. **Base factual.** Invoque o subagente `iris` (Task tool — ou a adaptação da Nota de compatibilidade acima) com a demanda e o pacote de estado do passo 0.
   Peça fatos separados de inferência, fonte e incerteza de cada um, e
   peça explicitamente as LACUNAS (o que falta confirmar — preço, MOQ,
   estoque, lead time etc.) — nunca aceite "ver especialista pertinente"
   como resposta de Iris; se algo falta, o nome do que falta é a resposta.
   Use a saída dela (fatos + lacunas) como contexto para todos os passos
   seguintes.

2. **Análise por especialidade.** Com base na demanda + na base factual da
   Iris, decida **quais** especialistas são realmente pertinentes (nem
   sempre são os 8 — mas em `/conclave` a expectativa é cobertura completa,
   então só deixe de convocar um agente se ele for genuinamente irrelevante
   à demanda, e diga explicitamente por quê). Invoque cada um (Task tool —
   ou a adaptação da Nota de compatibilidade) em paralelo quando não houver
   dependência entre eles, passando a base
   factual da Iris. Cada agente deve responder **apenas dentro da sua
   especialidade**, no formato de recomendação definido no próprio arquivo
   do agente (`.claude/agents/<nome>.md`).

3. **Identificar conflitos.** Compare as conclusões. Um conflito existe
   quando dois agentes chegam a recomendações incompatíveis, ou quando um
   dado usado por um contradiz o dado usado por outro.

4. **Confronto entre agentes conflitantes.** Para cada conflito, invoque de
   novo (Task tool) os agentes envolvidos, agora incluindo explicitamente a
   posição e a evidência do outro lado, e peça uma réplica com evidência —
   não uma concessão automática. Repita até a divergência ficar clara e
   registrada (ela não precisa ser "resolvida" com um dos dois cedendo; pode
   permanecer como divergência registrada para o Diretor decidir).

5. **Standard** quantifica o impacto econômico sempre que a demanda
   envolver custo, receita, margem ou investimento — mesmo que nenhum
   conflito o exija diretamente.

6. **Marie** valida risco técnico/de produto sempre que a demanda tocar
   fórmula, embalagem, processo ou claim.

7. **Dicio** valida risco jurídico sempre que a demanda tocar claim,
   contrato, campanha pública, dado de cliente (LGPD) ou pessoal. Se Dicio
   emitir **veto**, ele é definitivo para esta rodada: a recomendação
   correspondente não pode ser apresentada como "pronta para aprovação" —
   só como "bloqueada por veto jurídico, aguardando revisão humana".

8. **Rua** valida executabilidade operacional sempre que a demanda envolver
   produção, prazo, estoque ou capacidade de entrega.

9. **Caminho crítico.** Quando a demanda tiver prazo ou objetivo, não trate
   a lista de ações como se todas tivessem a mesma prioridade. Identifique:
   a próxima etapa real, a condição necessária para ela, o bloqueador
   (se houver) e a ação específica que o desbloqueia. Isso vira "Próxima
   ação" no formato final — nunca uma lista genérica de tarefas.

10. **Consolide** você mesmo (o orquestrador) o resultado final — não peça a
    um dos agentes para consolidar pelos outros.

## Formato final obrigatório

```
[CONCLAVE | plano estratégico — ciclo X]

Demanda analisada:
...

O que sabemos:
... (fatos confirmados, com fonte de cada um)

O que não sabemos:
... (lacunas explícitas — vindas de Iris e de qualquer agente que sinalizou dado ausente)

Convergências:
... (onde os agentes concordaram, e por quê)

Divergências:
... (onde os agentes discordaram, com a evidência de cada lado — nunca "resolvida" só para parecer consenso)

Riscos:
... (por agente: Dicio/jurídico, Marie/técnico, Standard/financeiro, Rua/operacional, conforme pertinente)

Bloqueios:
... (inclui veto, se houver, e o que falta para desbloquear)

Decisão possível agora:
... (o que já pode ser decidido com a evidência atual, separado do que ainda depende de dado ausente)

Próxima ação:
...
responsável:
prazo:
evidência necessária (se ainda faltar algo antes de executar):

Precisa do Diretor:
SIM/NÃO
Motivo:
...
```

"ciclo X" é um número sequencial simples (pergunte ao usuário se não souber
o último ciclo registrado, ou use 1 se for o primeiro desta conversa).

## Depois de apresentar o resultado

Pergunte ao usuário se deseja registrar esta Ata no Maranhão Intelligence
(`mi_conselho.registrar_registro`, tipo `conclave`) — **isso só deve
acontecer com autorização explícita**, nunca automaticamente, e mesmo assim
é só uma gravação local/testada (nenhum envio externo, nenhum deploy,
nenhuma migration é executada por este comando).

## Restrições absolutas desta sessão de Conclave
- Nenhuma ação externa: nenhum envio, publicação, pagamento, contratação,
  desligamento, mudança de fórmula em produção ou alteração contratual.
- Nenhum arquivo da aplicação é editado por este comando.
- Nenhum deploy, push ou migration é executado.
- WhatsApp/Meta não são tocados.
