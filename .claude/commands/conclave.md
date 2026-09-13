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

## Fluxo obrigatório

1. **Base factual.** Invoque o subagente `iris` (Task tool — ou a adaptação da Nota de compatibilidade acima) com a demanda.
   Peça fatos separados de inferência, fonte e incerteza de cada um. Use a
   saída dela como contexto para todos os passos seguintes.

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

9. **Consolide** você mesmo (o orquestrador) o resultado final — não peça a
   um dos agentes para consolidar pelos outros.

## Formato final obrigatório

```
[CONCLAVE | plano estratégico — ciclo X]

Demanda analisada:
...

Dados principais:
...

Decisões consolidadas:
1. ...
   responsável:
   prazo:
   evidência:
   status: aguardando aprovação humana

Conflitos identificados:
...

Como foram resolvidos:
...

Riscos sinalizados por Dicio:
...

Riscos sinalizados por Marie:
...

Impacto financeiro — Standard:
...

Capacidade operacional — Rua:
...

Dados e incerteza — Iris:
...

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
