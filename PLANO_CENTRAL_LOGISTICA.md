# Plano de Implementação — Central Logística (REMO)

> **Status:** rascunho de planejamento para outro desenvolvedor.
> **Local:** `C:\Users\RAFAEL\Desktop\App_DoRafa\CentralLogistica`
> **Inspiração visual:** capturas de tela da plataforma `parceiro.leveai.com.br` disponíveis em `..\SISTEMA_LOGISTICO`.
> **Princípio financeiro central:** `sem crédito, sem entrega`.

---

## 1. Resumo da decisão

A Central Logística será uma **plataforma online (web/PWA)**, desenvolvida em projeto **separado** do Cardápio, usando o mesmo fluxo de deploy do Cardápio:

- Repositório Git próprio (`CentralLogistica`)
- Deploy automático via Railway (`publicar_central_logistica.ps1`)
- Banco de dados PostgreSQL próprio
- Python + Flask no backend (mesma stack do Cardápio)
- HTML/CSS/JS no frontend, com PWA para instalação em celulares

A plataforma deve se comunicar com o Cardápio **exclusivamente por HTTP**:

- **Cardápio envia pedidos para a Central** via `POST` no endpoint da Central.
- **Central devolve status (ATRIBUIDO, EM_ROTA, ENTREGUE)** para o Cardápio via `POST /api/external/logistica/status`.

A ordem de construção foi invertida em relação ao plano original: **o módulo financeiro/carteira pré-paga é a Fase 1**. Nenhuma Ordem de Serviço logística pode ser criada sem saldo suficiente na carteira da empresa.

---

## 2. Por que online e não software local

- Os entregadores e despachadores usam celulares/tablets — web/PWA não exige instalação.
- Um deploy atualiza todos os usuários simultaneamente.
- A plataforma pode acessar GPS, notificações e câmera do celular via PWA.
- Facilita rastreamento em tempo real no painel da Central.
- Mantém o mesmo padrão de deploy do Cardápio (Railway + Git).

---

## 3. Fases de implementação

A construção obedece a ordem abaixo. Cada fase deve estar funcional antes da próxima.

| Fase | Nome | Objetivo |
|------|------|----------|
| **1** | Financeiro Operacional / Carteira Pré-paga | Empresa, carteira, abastecimento via PIX, crédito, débito, estorno, extrato, fechamento. |
| **2** | Autenticação e Usuários | Login, perfis, permissões, vinculação de usuários a empresas. |
| **3** | Ordens de Serviço | Criação, status e lifecycle da OS consumindo crédito. |
| **4** | Entregadores | Cadastro, atribuição, PWA básico. |
| **5** | Mapa / Despacho | Mapa, localização, acompanhamento de corridas. |
| **6** | Integração Cardápio | APIs de envio e retorno com idempotência. |
| **7** | Relatórios | Métricas, gráficos, extratos e fechamentos. |

**O módulo financeiro precisa nascer antes da logística.** Sem crédito na carteira, não há entrega.

---

## 4. Princípio financeiro da REMO

> **A REMO opera em modelo pré-pago no MVP. O crédito da empresa pode ser abastecido por PIX online ou por recebimento presencial em dinheiro no escritório da Central, desde que o recebimento presencial ocorra dentro de um caixa aberto e seja registrado por operador autorizado. Uma empresa somente poderá solicitar serviços logísticos quando possuir crédito disponível suficiente em sua carteira. Sem crédito, sem entrega.**

Isso é mais do que uma funcionalidade: é uma regra estrutural do negócio.

### Separação absoluta entre carteira, caixa e recebimentos

A carteira da empresa é o **destino do crédito**. Os recebimentos (PIX ou dinheiro) são as **origens financeiras**. O caixa é o controle do **dinheiro físico**. Os três conceitos nunca devem ser misturados.

```text
           PAGAMENTO DA EMPRESA
                    │
        ┌───────────┴───────────┐
        │                       │
       PIX                   DINHEIRO
        │                       │
        ▼                       ▼
 PROVEDOR PIX               CAIXA ABERTO
        │                       │
        ▼                       ▼
 ABASTECIMENTO          OPERAÇÃO DE CAIXA
        │                       │
        └───────────┬───────────┘
                    ▼
            CRÉDITO NA CARTEIRA
                    │
                    ▼
            SALDO DA EMPRESA
                    │
                    ▼
                 LOGÍSTICA
```

- **PIX** é uma origem financeira (eletrônica).
- **Dinheiro** é outra origem financeira (física).
- **Carteira** é o destino do crédito.
- **Caixa** controla o dinheiro físico.

A REMO **não será um ERP financeiro**. Ela será uma plataforma logística com uma carteira financeira pré-paga necessária para controlar o uso do serviço.

---

## 5. Conceito central: carteira pré-paga

A loja terá uma carteira de crédito dentro da REMO.

### Exemplo

**LOJA A**

Saldo disponível: `R$ 150,00`

A loja solicita abastecimento:

- Valor: `R$ 100,00`
- Método: `PIX`

A REMO gera a cobrança PIX. Depois da confirmação:

```text
Saldo anterior:  R$ 150,00
Crédito PIX:     + R$ 100,00
────────────────────────────
Novo saldo:      R$ 250,00
```

Somente então a loja poderá utilizar a logística.

---

## 6. Regra de segurança financeira

### Regra obrigatória

> **Nenhuma Ordem de Serviço logística pode consumir crédito inexistente.**

**Exemplo de rejeição:**

```text
Saldo disponível: R$ 5,00
Taxa da entrega:  R$ 8,00

Resultado: SOLICITAÇÃO RECUSADA (saldo_insuficiente)
```

Mesmo que o Cardápio envie a solicitação corretamente, a REMO deve responder `saldo_insuficiente` se não houver saldo suficiente.

Isso protege a REMO contra crédito negativo e elimina a necessidade de cobrança posterior.

### Fluxo de validação

```text
Cardápio envia entrega com taxa = R$ 8,00
                ↓
         REMO verifica saldo
                ↓
     Saldo ≥ R$ 8,00?
       │
       ├── NÃO → rejeita (saldo_insuficiente)
       │
       └── SIM → reserva/debita e cria OS
```

A REMO não precisa saber inicialmente como a taxa foi calculada. Ela recebe apenas o campo `taxa` e valida o saldo.

> **Atualização (2026-08-20):** A REMO agora tem **seu próprio cálculo de frete independente**. Ver seção 21 abaixo.

---

## 21. Cálculo de frete independente da REMO

### 21.1 Problema identificado

Originalmente, a REMO apenas recebia a `taxa` calculada pelo Cardápio e debitava esse valor da carteira. Isso criava um buraco financeiro:

```
PDV configura "frete grátis" → Cardápio calcula taxa = 0 → KDS envia 0 → REMO debita 0
```

O entregador continua fazendo a entrega, mas a REMO não recebe nada.

### 21.2 Solução: configuração independente

A REMO agora tem **sua própria configuração de frete** por empresa, separada da configuração do Cardápio/PDV. O cálculo usa o mesmo mecanismo (haversine), mas com regras próprias.

### 21.3 Dois conceitos separados

| Conceito | Quem paga | Exemplo |
|---|---|---|
| **Taxa que o cliente paga** | Cliente → Restaurante | "Frete grátis" = cliente não paga |
| **Custo da entrega** | Restaurante → REMO | O entregador precisa ser pago |

### 21.4 Cenários

| Situação | REMO cobra | Cliente paga | Resultado |
|---|---|---|---|
| Frete normal | R$ 8,00 | R$ 8,00 | Restaurante repassa |
| Frete grátis (promo) | R$ 8,00 | R$ 0,00 | Restaurante absorve R$ 8,00 |
| Frete com markup | R$ 8,00 | R$ 12,00 | Restaurante lucra R$ 4,00 |

### 21.5 Implementação

**Tabela `frete_config`:**

```sql
CREATE TABLE IF NOT EXISTS frete_config (
    id BIGSERIAL PRIMARY KEY,
    empresa_id TEXT UNIQUE NOT NULL REFERENCES empresas(id),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    origin_maps_url TEXT,
    base NUMERIC(12,2) DEFAULT 0,
    per_km NUMERIC(12,2) DEFAULT 0,
    min_v NUMERIC(12,2),
    max_v NUMERIC(12,2),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ DEFAULT NOW()
);
```

**Endpoints:**

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/v1/frete/<empresa_id>` | Obtém configuração atual |
| `POST` | `/api/v1/frete/<empresa_id>` | Salva configuração |
| `POST` | `/api/v1/frete/<empresa_id>/habilitar` | Habilita frete |
| `POST` | `/api/v1/frete/<empresa_id>/desabilitar` | Desabilita frete |
| `POST` | `/api/v1/frete/<empresa_id>/preview` | Calcula frete com base em coordenadas |

**Fluxo de cálculo:**

```
1. PDV configura regras do cliente (Cardápio) e regras da REMO (separadas)
2. Cliente faz pedido → Cardápio calcula frete do cliente
3. KDS sinal_entregar → envia coordenadas + taxa_cliente para REMO
4. REMO calcula frete real com SUAS regras (haversine)
5. REMO debita frete real da carteira
6. REMO registra: taxa_cliente (info) vs taxa_real (debitado)
```

**Fallback:** Se a REMO não tiver configuração de frete habilitada, usa a `taxa_cliente` enviada pelo Cardápio como fallback (compatibilidade retroativa).

**Arquivos:**

- `app/core/frete.py` — cálculo haversine (espelha Cardápio)
- `app/repositories/frete.py` — repositório de configuração
- `app/api/frete.py` — endpoints REST
- `app/services/ordens.py` — integração do cálculo na criação de ordem

**Payload enviado pelo Cardápio (atualizado):**

```json
{
  "empresa_id": "empresa-teste-001",
  "solicitacao_id": "PEDIDO-001",
  "taxa": 8.0,
  "origin_maps_url": "https://maps.google.com/?q=-16.7547,-48.5049",
  "client_maps_url": "https://maps.google.com/?q=-16.8000,-48.5500",
  "payload": {
    "cliente_nome": "Ana Souza",
    "cliente_whatsapp": "11988887777",
    "tipo_entrega": "DELIVERY",
    "taxa_cliente": 8.0,
    "total": 68.5,
    "origin_maps_url": "https://maps.google.com/?q=-16.7547,-48.5049",
    "client_maps_url": "https://maps.google.com/?q=-16.8000,-48.5500"
  }
}
```

**Resposta da REMO (atualizada):**

A ordem criada inclui `payload_json` com `taxa_cliente` e `taxa_real` para auditoria.

---

## 7. Controle de concorrência no consumo do saldo

A operação de débito deve ser **transacional e protegida contra condições de corrida**.

### Problema

```text
Saldo = R$ 10

Pedido A → R$ 8
Pedido B → R$ 8
```

Se duas requisições chegarem simultaneamente, ambas podem enxergar `Saldo = R$ 10` e tentar gastar `R$ 8`. Isso causaria saldo negativo.

### Solução

Toda operação de consumo deve seguir o padrão:

```text
BEGIN;

-- 1. Bloqueia a carteira (FOR UPDATE) para evitar leituras simultâneas
SELECT saldo_atual FROM carteiras WHERE empresa_id = 'X' FOR UPDATE;

-- 2. Verifica saldo
IF saldo_atual < taxa THEN
    ROLLBACK;
    RETURN saldo_insuficiente;
END IF;

-- 3. Cria movimentação de débito
INSERT INTO movimentacoes_carteira (...);

-- 4. Atualiza saldo materializado
UPDATE carteiras SET saldo_atual = saldo_atual - taxa WHERE empresa_id = 'X';

-- 5. Cria OS vinculada à movimentação
INSERT INTO ordens_servico (..., movimentacao_id, ...) VALUES (...);

COMMIT;
```

O `SELECT ... FOR UPDATE` garante que apenas uma transação por vez consiga reservar/debitar o saldo.

---

## 8. Regra de estorno e cancelamento

A política de estorno precisa ser definida antes da implementação das Ordens de Serviço.

### Cenários

| Status da OS no cancelamento | Regra de estorno sugerida | Observação |
|------------------------------|---------------------------|------------|
| `PENDENTE` | Estorna 100% da taxa. | OS ainda não foi atribuída. |
| `ATRIBUIDA` | Estorno parcial ou regra comercial. | Pode haver custo de logística. |
| `EM_ROTA` | Geralmente sem estorno. | Entrega já foi iniciada. |
| `ENTREGUE` | Sem estorno. | Serviço foi concluído. |

A movimentação de estorno deve gerar uma linha em `movimentacoes_carteira` com `tipo = 'ESTORNO'`, vinculada à movimentação original de débito.

### Imutabilidade das movimentações financeiras

Nenhuma movimentação financeira confirmada pode ser editada ou excluída. Correções devem gerar uma nova movimentação `AJUSTE` vinculada à operação original.

Exemplo:

```text
ENTRADA
+ R$ 100
   ↓
Erro de lançamento.

Errado:
   editar R$ 100 → R$ 80

Certo:
   ENTRADA
   + R$ 100

   AJUSTE
   - R$ 20
   referencia_movimentacao = 123
   motivo = "Correção de lançamento"
```

A política exata de estorno pode ser parametrizada por empresa no futuro. No MVP, define-se uma regra padrão e documenta-se.

---

## 9. Separação entre dinheiro da carteira e dinheiro da venda

Isso precisa ficar muito explícito.

A loja pode ter `R$ 500,00` de crédito logístico, e isso **não** significa que a REMO recebeu `R$ 500,00` referentes às vendas da loja. É um saldo **pré-pago para utilização do serviço logístico**.

### Fluxo financeiro da REMO

```text
LOJA
  │
  │ PIX
  ▼
REMO
  │
  │ crédito
  ▼
CARTEIRA DA LOJA
  │
  │ consumo
  ▼
ENTREGAS
```

### Fluxo de pagamento da venda (independente)

```text
CLIENTE
  │
  │ pagamento da venda
  ▼
PROVEDOR / LOJA
```

Essa separação mantém a arquitetura limpa e evita misturar caixa da venda com caixa da logística.

---

## 10. Métodos de abastecimento no MVP

Apenas **PIX** e **dinheiro presencial** no escopo inicial.

| Método | MVP | Observação |
|--------|-----|------------|
| **PIX** | ✅ Sim | Abastecimento online, automático. |
| **Dinheiro** | ✅ Sim | Abastecimento presencial, exige caixa aberto + operador. |
| Cartão | ❌ Não | Fora do escopo. |
| Boleto | ❌ Não | Fora do escopo. |
| Transferência manual | ❌ Não | Fora do escopo. |
| Faturamento | ❌ Não | Fora do escopo. |
| Pós-pago | ❌ Não | Fora do escopo. |
| Fiado | ❌ Não | Fora do escopo. |

Isso reduz drasticamente o número de cenários a testar.

---

## 11. Fase 1 — Financeiro Operacional / Carteira Pré-paga

### Objetivo

Criar a infraestrutura financeira mínima necessária para que uma empresa utilize os serviços da REMO somente mediante crédito antecipadamente abastecido, seja por **PIX online** ou por **dinheiro presencial no escritório**.

### Sequência da Fase 1

```text
1. Fundação financeira
   ├── Empresa
   ├── Carteira
   ├── Livro-razão
   └── Auditoria

2. PIX
   ├── Abastecimento
   ├── PaymentProviderAdapter / PagBankAdapter
   ├── QR Code
   ├── Webhook
   ├── Idempotência
   └── Crédito automático

3. Caixa físico
   ├── Caixa
   ├── Operador
   ├── Abertura
   ├── Entrada
   ├── Saída
   ├── Suprimento
   ├── Sangria
   ├── Abastecimento em dinheiro
   └── Fechamento

4. Conciliação
   ├── Carteira
   ├── PIX
   ├── Caixa
   └── Auditoria

5. Testes
   ├── PIX
   ├── Dinheiro
   ├── Concorrência
   ├── Idempotência
   └── Recuperação
```

A autenticação completa (login, perfis, permissões) fica para a **Fase 2**.

### Escopo

- Cadastro da empresa.
- Criação da carteira vinculada à empresa.
- Carteira financeira da empresa.
- Livro-razão (`movimentacoes_carteira`).
- Saldo disponível materializado, auditado e consistente.
- Histórico de movimentações e auditoria financeira.
- Abastecimento por **PIX online** (automático, sem operador).
- Abastecimento por **dinheiro presencial** (exige caixa aberto + operador).
- Geração da cobrança PIX (QR Code + copia e cola).
- Confirmação de pagamento via webhook.
- Crédito automático na carteira.
- Proteção contra processamento duplicado.
- **Motor de débito da carteira** (com `FOR UPDATE`), implementado e testado de forma isolada.
- Bloqueio por saldo insuficiente.
- Caixa físico com abertura, fechamento, operações e contagem.
- Regra de caixa aberto para recebimento em dinheiro.
- Regra de um caixa aberto por vez.
- Imutabilidade das movimentações financeiras confirmadas.
- Estorno básico.
- Extrato.
- Fechamento financeiro básico.

### Motor de débito na Fase 1

Na Fase 1, o mecanismo de débito será implementado e testado de forma isolada, sem vinculação a uma Ordem de Serviço real.

Exemplo de teste interno:

```text
Carteira R$ 100
    ↓
Débito simulado R$ 8
    ↓
Saldo R$ 92
```

O débito produtivo associado à criação de uma Ordem de Serviço somente será habilitado na **Fase 3**, quando a entidade `ordens_servico` estiver operacional.

Nesse momento, o serviço de OS utilizará o mesmo motor financeiro dentro de uma transação atômica:

```text
POST pedido logístico
       ↓
TRANSAÇÃO
       ↓
bloqueia carteira
       ↓
verifica saldo
       ↓
cria débito
       ↓
cria OS
       ↓
COMMIT
```

### Regra principal

> **Nenhuma entrega poderá ser autorizada sem saldo disponível suficiente na carteira da empresa.**

### Fora do escopo inicial

- Cartão, boleto.
- Faturamento, pós-pago, fiado.
- Múltiplos meios de pagamento online.
- ERP contábil.
- Emissão fiscal.
- Contas a pagar/receber empresarial.
- Domínio completo de Ordens de Serviço (Fase 3).

### Demonstração mínima da Fase 1

```text
Teste 1
  Empresa criada
  Carteira criada
  Saldo = R$ 0,00

Teste 2
  Empresa solicita R$ 100,00
  Abastecimento criado
  PIX gerado (QR + copia e cola)

Teste 3
  PIX pago
  Webhook/consulta confirma pagamento
  Abastecimento = APROVADO
  + R$ 100,00 na carteira

Teste 4
  Consumo simula entrega de R$ 8,00
  - R$ 8,00 (débito atômico)
  Saldo = R$ 92,00

Teste 5
  Consumo simula entrega de R$ 100,00
  Saldo = R$ 92,00
  RECUSADA (saldo_insuficiente)

Teste 6
  Consumo anterior cancelado (PENDENTE)
  + R$ 8,00 estornado
  Saldo = R$ 100,00
```

Se essa cadeia estiver funcionando, a fundação financeira da REMO está pronta.

---

## 12. Três grandes áreas do módulo financeiro

### 12.1 Carteira

- Saldo atual.
- Adicionar crédito.
- Extrato.
- Créditos pendentes.
- Créditos confirmados.
- Débitos de entregas.
- Ajustes.
- Estornos.

### 12.2 Abastecimento

- Novo abastecimento.
- Valor.
- PIX (QR Code e copia e cola).
- Status.
- Data.
- ID da transação.

### 12.3 Fechamento

- Período.
- Créditos recebidos.
- Consumo logístico.
- Estornos.
- Ajustes.
- Saldo inicial.
- Saldo final.

---

## 13. Separação entre "pedido PIX" e "crédito"

Tecnicamente importante: quando a loja pede `R$ 100,00`, a REMO **não deve** imediatamente adicionar `R$ 100,00` à carteira.

Primeiro existe uma intenção de pagamento:

```text
ABASTECIMENTO
R$ 100,00
STATUS = PENDENTE
```

Depois:

```text
PIX CONFIRMADO
        ↓
    CRÉDITO
        ↓
   CARTEIRA
```

Portanto:

```text
PENDENTE
   ↓
APROVADO
   ↓
CRÉDITO GERADO
```

Isso evita crédito fantasma.

### Identificador interno do abastecimento

O `abastecimento.uuid` é o **identificador interno da operação de abastecimento**. Ele é gerado pela REMO e não muda.

Os identificadores fornecidos pelo PSP (`transacao_externa_id`, `pix_txid` etc.) são utilizados para **conciliação externa** e nunca substituem o identificador interno.

Isso garante independência do formato específico do PagBank, Asaas, Mercado Pago ou qualquer outro provedor.

---

## 14. Idempotência no financeiro

Assim como no pagamento do PDV, a REMO precisa impedir que uma confirmação PIX seja processada duas vezes.

```text
Webhook PIX
   ↓
REMO recebe
   ↓
+ R$ 100

Se o mesmo webhook chegar novamente:

Webhook repetido
   ↓
REMO reconhece transação já processada
   ↓
NÃO adiciona R$ 100 novamente
```

Indispensável para evitar saldo duplicado.

### Um abastecimento gera uma única movimentação de crédito

Um abastecimento somente pode gerar uma única movimentação de crédito na carteira.

```text
ABASTECIMENTO
      │
      ├── PENDENTE
      │
      ▼
PIX CONFIRMADO
      │
      ▼
TRANSACÃO
      │
      ├── verifica idempotência
      │
      ├── verifica se abastecimento já está APROVADO
      │
      ├── cria CREDITO
      │
      ├── atualiza carteira
      │
      └── marca abastecimento APROVADO

PIX CONFIRMADO novamente
        ↓
abastecimento já APROVADO
        ↓
NÃO criar nova movimentação
```

Esse é um teste obrigatório.

---

## 15. Modelo de dados atualizado

### 15.1 Tabelas essenciais

```sql
empresas
  id TEXT PRIMARY KEY
  nome TEXT NOT NULL
  cnpj TEXT
  ativo BOOLEAN DEFAULT TRUE
  endereco JSONB
  config JSONB
  criado_em TIMESTAMPTZ DEFAULT NOW()

carteiras
  id BIGSERIAL PRIMARY KEY
  empresa_id TEXT UNIQUE NOT NULL REFERENCES empresas(id)
  saldo_atual NUMERIC(12,2) NOT NULL DEFAULT 0
  ativo BOOLEAN DEFAULT TRUE
  criado_em TIMESTAMPTZ DEFAULT NOW()

usuarios
  id BIGSERIAL PRIMARY KEY
  username TEXT UNIQUE
  nome TEXT
  telefone TEXT
  perfil TEXT NOT NULL  -- ADMIN, CENTRAL, ENTREGADOR, OPERADOR
  empresa_id TEXT REFERENCES empresas(id)
  ativo BOOLEAN DEFAULT TRUE
  senha_hash TEXT
  senha_salt TEXT
  localizacao_atual JSONB
  ultima_localizacao_em TIMESTAMPTZ
  criado_em TIMESTAMPTZ DEFAULT NOW()

abastecimentos
  id BIGSERIAL PRIMARY KEY
  uuid TEXT UNIQUE
  empresa_id TEXT NOT NULL REFERENCES empresas(id)
  carteira_id BIGINT NOT NULL REFERENCES carteiras(id)
  valor NUMERIC(12,2) NOT NULL
  metodo TEXT NOT NULL  -- PIX, DINHEIRO
  status TEXT NOT NULL DEFAULT 'PENDENTE'  -- PENDENTE, APROVADO, CANCELADO, EXPIRADO
  pix_payload JSONB
  pix_txid TEXT
  pix_linha_digitavel TEXT
  pix_qr_code TEXT
  transacao_externa_id TEXT
  confirmado_em TIMESTAMPTZ
  expira_em TIMESTAMPTZ
  operador_id BIGINT REFERENCES usuarios(id)  -- obrigatório para DINHEIRO
  caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id)  -- obrigatório para DINHEIRO
  criado_em TIMESTAMPTZ DEFAULT NOW()
  UNIQUE (empresa_id, transacao_externa_id)

movimentacoes_carteira
  id BIGSERIAL PRIMARY KEY
  uuid TEXT UNIQUE
  carteira_id BIGINT NOT NULL REFERENCES carteiras(id)
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id)
  ordem_id BIGINT  -- preenchido futuramente na Fase 3
  tipo TEXT NOT NULL  -- CREDITO, DEBITO, ESTORNO, AJUSTE
  descricao TEXT
  valor NUMERIC(12,2) NOT NULL
  saldo_anterior NUMERIC(12,2) NOT NULL
  saldo_final NUMERIC(12,2) NOT NULL
  status TEXT NOT NULL DEFAULT 'CONCLUIDO'  -- PENDENTE, CONCLUIDO, CANCELADO
  idempotency_key TEXT UNIQUE
  referencia_externa TEXT
  criado_em TIMESTAMPTZ DEFAULT NOW()

ordens_servico
  id BIGSERIAL PRIMARY KEY
  uuid TEXT UNIQUE
  solicitacao_id TEXT
  empresa_id TEXT NOT NULL REFERENCES empresas(id)
  movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id)
  entregador_id BIGINT REFERENCES usuarios(id)
  status TEXT NOT NULL  -- PENDENTE, AGENDADA, ATRIBUIDA, EM_ROTA, ENTREGUE, CANCELADA, DEVOLVIDA
  protocolo TEXT UNIQUE
  payload_json JSONB
  taxa NUMERIC(12,2)
  atribuido_em TIMESTAMPTZ
  em_rota_em TIMESTAMPTZ
  entregue_em TIMESTAMPTZ
  cancelado_em TIMESTAMPTZ
  criado_em TIMESTAMPTZ DEFAULT NOW()
  UNIQUE (empresa_id, solicitacao_id)

webhooks_recebidos
  id BIGSERIAL PRIMARY KEY
  idempotency_key TEXT UNIQUE
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  origem TEXT NOT NULL  -- PAGBANK, etc.
  payload_json JSONB NOT NULL
  processado BOOLEAN DEFAULT FALSE
  recebido_em TIMESTAMPTZ DEFAULT NOW()

webhooks_enviados
  id BIGSERIAL PRIMARY KEY
  idempotency_key TEXT UNIQUE
  ordem_id BIGINT REFERENCES ordens_servico(id)
  url TEXT NOT NULL
  payload_json JSONB NOT NULL
  resposta_json JSONB
  status_code INTEGER
  enviado_em TIMESTAMPTZ DEFAULT NOW()

areas_cobertura
  id BIGSERIAL PRIMARY KEY
  empresa_id TEXT REFERENCES empresas(id)
  cidade TEXT NOT NULL
  bairro TEXT NOT NULL
  taxa_entrega NUMERIC(12,2)
  ativo BOOLEAN DEFAULT TRUE
  UNIQUE (empresa_id, cidade, bairro)

localizacoes
  id BIGSERIAL PRIMARY KEY
  ordem_id BIGINT REFERENCES ordens_servico(id)
  entregador_id BIGINT REFERENCES usuarios(id)
  latitude NUMERIC
  longitude NUMERIC
  precisao NUMERIC
  recebido_em TIMESTAMPTZ DEFAULT NOW()

caixas
  id BIGSERIAL PRIMARY KEY
  nome TEXT NOT NULL
  status TEXT NOT NULL DEFAULT 'FECHADO'  -- FECHADO, ABERTO
  operador_abertura_id BIGINT REFERENCES usuarios(id)
  aberto_em TIMESTAMPTZ
  saldo_esperado NUMERIC(12,2) DEFAULT 0
  ativo BOOLEAN DEFAULT TRUE
  criado_em TIMESTAMPTZ DEFAULT NOW()

caixa_operacoes
  id BIGSERIAL PRIMARY KEY
  caixa_id BIGINT NOT NULL REFERENCES caixas(id)
  operador_id BIGINT NOT NULL REFERENCES usuarios(id)
  tipo TEXT NOT NULL
    -- Operacao de controle: ABERTURA, FECHAMENTO
    -- Operacao de dinheiro fisico: ENTRADA, SAIDA, SUPRIMENTO, SANGRIA, AJUSTE
  valor NUMERIC(12,2)
  saldo_inicial NUMERIC(12,2)
  saldo_final_sistema NUMERIC(12,2)
  saldo_contado NUMERIC(12,2)
  diferenca NUMERIC(12,2)
  motivo TEXT
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id)
  criado_em TIMESTAMPTZ DEFAULT NOW()

auditoria_financeira
  id BIGSERIAL PRIMARY KEY
  carteira_id BIGINT NOT NULL REFERENCES carteiras(id)
  movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id)
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id)
  tipo TEXT NOT NULL
  referencia TEXT
  dados_json JSONB
  criado_em TIMESTAMPTZ DEFAULT NOW()
```

### 15.2 Notas

- `carteiras` é a entidade financeira vinculada a uma `empresas`. Cada empresa tem exatamente uma carteira.
- `carteiras.saldo_atual` é um **saldo materializado** derivado do livro-razão e utilizado para operações transacionais. Ele deve ser fortemente consistente com `movimentacoes_carteira`.
- `movimentacoes_carteira` é o **livro-razão financeiro** da carteira. É a fonte de verdade financeira. Cada crédito, débito, estorno ou ajuste gera uma movimentação.
- Toda alteração deve atualizar tanto `movimentacoes_carteira` quanto `carteiras.saldo_atual` dentro da mesma transação PostgreSQL.
- Em caso de divergência, o saldo deve ser reconstruído a partir das movimentações.
- Toda alteração no saldo deve passar por uma única rotina transacional que:
  1. Bloqueia a carteira (`SELECT ... FOR UPDATE`).
  2. Verifica saldo.
  3. Insere movimentação.
  4. Atualiza `carteiras.saldo_atual`.
  5. Commit.
- `abastecimentos` armazena a intenção de abastecimento da carteira. Método pode ser `PIX` ou `DINHEIRO`. Só gera crédito após confirmação.
- Regras por método:
  - `PIX`: `transacao_externa_id` obrigatória; `operador_id` e `caixa_operacao_id` devem ser NULL.
  - `DINHEIRO`: `operador_id` e `caixa_operacao_id` obrigatórios; `transacao_externa_id` deve ser NULL.
- `webhooks_recebidos` persiste todos os webhooks recebidos do PSP, garantindo idempotência e auditabilidade.
- `movimentacoes_carteira` nunca são editadas ou excluídas. Correções geram uma nova movimentação `AJUSTE` vinculada à movimentação original.
- `idempotency_key` evita processamento duplicado de confirmações PIX e débitos.
- `ordens_servico.movimentacao_id` liga a OS ao débito correspondente, garantindo atomicidade.
- `caixas.status` indica `FECHADO` ou `ABERTO`. Apenas um caixa pode estar aberto por vez. Não é possível receber dinheiro se o caixa não estiver aberto.
- `caixa_operacoes.tipo` divide-se em:
  - Operações de **controle**: `ABERTURA`, `FECHAMENTO`.
  - Operações de **dinheiro físico**: `ENTRADA`, `SAIDA`, `SUPRIMENTO`, `SANGRIA`, `AJUSTE`.
- `auditoria_financeira` registra eventos relevantes do financeiro para rastreabilidade. Permite responder perguntas como "por que o saldo desta empresa mudou de R$ 100 para R$ 92?".
- Regra rígida de `movimentacoes_carteira.tipo`:
  - `CREDITO` → soma ao saldo.
  - `DEBITO` → subtrai do saldo.
  - `ESTORNO` → soma ao saldo (estorna um débito anterior).
  - `AJUSTE` → depende da natureza descrita no registro.
- `RESERVA` fica fora do MVP. Só deve ser introduzida quando houver necessidade concreta.

---

## 16. Contrato de integração com o Cardápio

### 16.1 Cardápio envia pedido para a Central

A Central deve expor um endpoint que o Cardápio chama quando o pedido é sinalizado (botão "Sinal para entregar").

**Endpoint esperado na Central:**

```http
POST /api/v1/pedidos
Content-Type: application/json
Authorization: Bearer <CENTRAL_LOGISTICA_API_KEY>
X-Idempotency-Key: <empresa_id>:<solicitacao_id>:SINALIZADO
```

**Payload mínimo:**

```json
{
  "empresa_id": "EMPRESA01",
  "solicitacao_id": "SOL-001",
  "origem": "DoRafa_KDS",
  "evento": "SINALIZADO",
  "sinalizado_em": "2026-08-19T15:00:00",
  "cliente": {
    "nome": "Ana Souza",
    "whatsapp": "11988887777"
  },
  "entrega": {
    "tipo": "DELIVERY",
    "endereco": {
      "rua": "Rua das Palmeiras",
      "numero": "450",
      "bairro": "Jardim",
      "cidade": "São Paulo",
      "referencia": "Portão azul",
      "maps_url": ""
    },
    "taxa": 8.0
  },
  "pedido": {
    "itens": [
      {"nome": "Xis Bacon", "qty": 2, "preco": 28.0},
      {"nome": "Batata Frita M", "qty": 1, "preco": 12.5}
    ],
    "total": 68.5,
    "observacoes": "Sem cebola."
  }
}
```

**Respostas possíveis:**

- Sucesso:

```json
{
  "ok": true,
  "protocolo": "REM-20260819-001"
}
```

- Saldo insuficiente:

```json
{
  "ok": false,
  "error": "saldo_insuficiente",
  "saldo_atual": 5.00,
  "taxa_solicitada": 8.00
}
```

### 16.2 Central devolve status para o Cardápio

A Central chama o webhook do Cardápio sempre que houver mudança de status logístico.

**Endpoint no Cardápio:**

```http
POST https://<cardapio>/api/external/logistica/status
Content-Type: application/json
Authorization: Bearer <CENTRAL_LOGISTICA_API_KEY>
X-Idempotency-Key: <empresa_id>:<solicitacao_id>:<STATUS>
```

**Payload:**

```json
{
  "empresa_id": "EMPRESA01",
  "solicitacao_id": "SOL-001",
  "status": "ENTREGUE",
  "evento": "ENTREGUE",
  "protocolo": "REM-20260819-001",
  "entregador": {
    "id": "ENT-01",
    "nome": "João Gregório"
  },
  "nota": "Entregue ao cliente",
  "timestamp": "2026-08-19T15:45:00"
}
```

**Status permitidos:** `ATRIBUIDO`, `EM_ROTA`, `ENTREGUE`.

---

## 17. Remuneração do entregador (estrutura futura)

Uma porcentagem da taxa pode ser destinada ao entregador. Na Fase 1, basta preparar a estrutura para que o consumo possa posteriormente gerar uma obrigação para o entregador.

### Modelos futuros

**Modelo A — percentual por entrega:**

```text
Entrega:      R$ 10,00
Remuneração:  60%
Valor devido: R$ 6,00
```

**Modelo B — valor fixo por entrega:**

```text
Entrega:      R$ 10,00
Fixo:         R$ 10,00
Valor devido: R$ 10,00
```

**Modelo C — salário fixo:**

Remuneração mensal fixa, independente do número de entregas.

### Separação importante

- A **carteira da loja** controla: quanto a loja gasta para utilizar a logística.
- O **módulo de remuneração** controla: quanto a REMO deve pagar ao entregador.

São duas coisas diferentes. O salário fixo do entregador não deve ser confundido com o débito da carteira da loja.

A Fase 1 não implementa remuneração, mas o modelo de dados deve permitir adicioná-la sem quebrar a estrutura.

---

## 18. Estrutura de pastas sugerida

A estrutura segue o princípio da **responsabilidade única e arquivos pequenos**. Cada módulo deve ter no máximo uma função clara.

```
CentralLogistica/
├── .git
├── .gitignore
├── README.md
├── PLANO_CENTRAL_LOGISTICA.md
├── requirements.txt
├── runtime.txt
├── main.py                      # entrypoint do Railway
├── publicar_central_logistica.ps1
├── app/
│   ├── __init__.py
│   ├── schema.sql               # DDL único do banco
│   ├── factory.py               # criação da app Flask
│   ├── core/                    # configuração, conexão, ids
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── ids.py
│   │   └── security.py
│   ├── repositories/            # um arquivo por entidade (acesso a dados)
│   │   ├── empresas.py
│   │   ├── usuarios.py
│   │   ├── carteiras.py
│   │   ├── abastecimentos.py
│   │   ├── movimentacoes_carteira.py
│   │   ├── caixas.py
│   │   ├── caixa_operacoes.py
│   │   ├── webhooks_recebidos.py
│   │   └── auditoria_financeira.py
│   ├── services/                # regras de negócio
│   │   ├── abastecimento.py
│   │   ├── caixa.py
│   │   ├── movimentacoes.py
│   │   └── ordens.py
│   ├── pix/                     # adapter pattern para PIX
│   │   ├── adapter_contract.py
│   │   ├── mock_adapter.py
│   │   ├── pagbank_adapter.py
│   │   ├── service.py
│   │   └── webhook.py
│   ├── caixa/                   # módulo próprio de caixa físico
│   │   └── (se necessário, UI/pages)
│   ├── api/                     # rotas REST
│   │   ├── __init__.py
│   │   ├── financeiro.py
│   │   ├── pedidos.py
│   │   └── webhooks.py
│   ├── migracoes/
│   │   └── runner.py
│   ├── auth/                    # login, perfis (Fase 2)
│   ├── central/                 # PWA da central (Fase 4+)
│   └── entregador/              # PWA do entregador (Fase 4+)
├── static/
│   ├── css/
│   ├── js/
│   └── assets/
│       └── logo.png
└── tests/
    ├── test_carteira.py
    ├── test_caixa.py
    ├── test_pix.py
    └── test_concorrencia.py
```

---

## 19. Variáveis de ambiente

| Variável | Descrição |
|----------|-----------|
| `DATABASE_URL` | PostgreSQL criado automaticamente pelo Railway. |
| `SECRET_KEY` | Chave de sessão do Flask. |
| `CENTRAL_LOGISTICA_API_KEY` | Token usado pelo Cardápio e pela Central. |
| `CARDAPIO_WEBHOOK_URL` | URL do Cardápio para enviar status (`https://.../api/external/logistica/status`). |
| `CARDAPIO_EMPRESA_ID` | Identificador da empresa no Cardápio (`EMPRESA01`). |
| `PUBLIC_BASE_URL` | URL pública da Central Logística. |
| `PIX_PROVIDER` | Provedor de PIX: `pagbank`, `mercadopago`, `asaas`, `mock`. |
| `PIX_TOKEN` | Token do provedor de PIX. |
| `PIX_WEBHOOK_SECRET` | Segredo para validar webhooks do provedor de PIX. |
| `TELEGRAM_BOT_TOKEN` | Opcional: notificar entregadores. |
| `GOOGLE_MAPS_API_KEY` | Opcional: rotas e geocoding. |

---

## 20. Fluxo completo (MVP)

### 20.1 Abastecimento por PIX

```text
EMPRESA
   │
   │ solicita R$ 100
   ▼
ABASTECIMENTO
PENDENTE
   │
   ▼
PAGBANK
   │
   │ PIX pago
   ▼
WEBHOOK
   │
   ▼
ABASTECIMENTO APROVADO
   │
   ├── MOVIMENTAÇÃO CREDITO +100
   │
   ├── CARTEIRA +100
   │
   └── AUDITORIA
```

### 20.2 Abastecimento por dinheiro

```text
EMPRESA
   │
   │ entrega R$ 100
   ▼
OPERADOR
   │
   ▼
CAIXA ABERTO?
   │
   ├── NÃO → REJEITA
   │
   └── SIM
        │
        ▼
ABASTECIMENTO APROVADO
        │
        ├── ENTRADA CAIXA +100
        │
        ├── CRÉDITO CARTEIRA +100
        │
        └── AUDITORIA
```

### 20.3 Utilização logística

```text
PEDIDO
   │
   ▼
REMO
   │
   ▼
CARTEIRA
   │
   ├── saldo suficiente?
   │
   ├── NÃO → saldo_insuficiente
   │
   └── SIM
        │
        ▼
   DÉBITO -R$ 8
        │
        ▼
      OS
```

### 20.4 Fluxo macro

1. Empresa é criada na REMO com saldo `R$ 0,00`.
2. Empresa abastece via **PIX** (automático) ou **dinheiro** (caixa aberto + operador).
3. REMO confirma abastecimento e credita na carteira (idempotente).
4. Pedido é pago no Cardápio e chega ao KDS como `NOVO`.
5. Cozinha aceita, prepara e sinaliza para entregar.
6. Cardápio chama `POST /api/v1/pedidos` na Central com `taxa = 8.0`.
7. REMO bloqueia carteira, verifica saldo. Se suficiente, debita e cria OS. Se não, responde `saldo_insuficiente`.
8. Despachador atribui entregador.
9. Entregador inicia rota (PWA).
10. Entregador confirma entrega.
11. REMO envia webhook `ENTREGUE` para o Cardápio.

---

## 19. Boas práticas de programação

### Modularidade

- Cada arquivo deve ter **uma responsabilidade única**.
- Repositórios, serviços, adapters e rotas devem viver em módulos separados.
- Arquivos grandes (>500 linhas) devem ser divididos.
- O nome do arquivo deve indicar exatamente o que ele faz.

### Camadas

| Camada | Onde vive | Regra |
|--------|-----------|-------|
| `repositories` | SQL/CRUD | Apenas acesso a dados. Nenhuma regra de negócio. |
| `services` | Regras de negócio | Orquestra repositórios, transações e validações. |
| `api` | Rotas Flask | Recebe request, chama serviço, devolve response. |
| `pix` | Adapter pattern | Isola a lógica do PSP. |
| `core` | Config/db/util | Sem regra de domínio. |

### Transações

- Toda alteração de saldo, caixa ou abastecimento ocorre dentro de uma transação.
- `SELECT ... FOR UPDATE` obrigatório para carteira.
- Nunca fazer commit parcial de operação financeira.

### Idempotência

- PIX: chave `idempotency_key` em `webhooks_recebidos` e `movimentacoes_carteira`.
- Dinheiro: chave gerada pelo cliente (`idempotency_key`).
- Débito: `idempotency_key` obrigatória para evitar duplo débito.

### Imutabilidade

- `movimentacoes_carteira` nunca são editadas ou excluídas.
- Correções geram movimentação `AJUSTE` vinculada à original.
- Operações de caixa nunca são apagadas.

### Testes

- Cada serviço e repositório deve ter teste próprio.
- Testes de concorrência obrigatórios para débito.
- Mocks para PSP em testes.

### Logging

- Nunca logar valores sensíveis (tokens, senhas, `encrypted_value`).
- Logar eventos financeiros com referência (UUID), nunca dados pessoais em excesso.

### Segurança

- Credenciais via variáveis de ambiente.
- Tokens e chaves nunca commitados no Git.
- Validação de assinatura de webhooks do PSP.

---

## 21. Checklist de implementação

### FASE 1 — FINANCEIRO OPERACIONAL / CARTEIRA PRÉ-PAGA

- [ ] Criar repositório Git para `CentralLogistica`.
- [ ] Inicializar projeto Flask com `main.py`, `requirements.txt`, `runtime.txt`.
- [ ] Criar schema PostgreSQL (`empresas`, `carteiras`, `usuarios`, `abastecimentos`, `movimentacoes_carteira`, `auditoria_financeira`, `ordens_servico` somente estrutura, `webhooks_recebidos`, `webhooks_enviados`, `caixas`, `caixa_operacoes`).
- [ ] Criar cadastro de empresas.
- [ ] Criar carteira vinculada à empresa.
- [ ] Criar abastecimento via PIX.
- [ ] Gerar cobrança PIX (QR Code + copia e cola).
- [ ] Receber e confirmar pagamento via webhook do provedor PIX.
- [ ] Creditar carteira automaticamente.
- [ ] Implementar idempotência no abastecimento (tabela `webhooks_recebidos`).
- [ ] Implementar débito de carteira com `SELECT ... FOR UPDATE`.
- [ ] Implementar bloqueio por saldo insuficiente.
- [ ] Implementar estorno básico.
- [ ] Implementar imutabilidade das movimentações financeiras.
- [ ] Criar caixa (`caixas`).
- [ ] Implementar abertura e fechamento de caixa.
- [ ] Implementar regra de um caixa aberto por vez.
- [ ] Implementar operações de caixa (entrada, saída, suprimento, sangria, ajuste).
- [ ] Implementar abastecimento em dinheiro vinculado a caixa aberto e operador.
- [ ] Implementar auditoria financeira.
- [ ] Implementar extrato e fechamento básico.

### FASE 2 — AUTENTICAÇÃO E USUÁRIOS

- [ ] Login de administrador.
- [ ] Gerenciamento de empresas.
- [ ] Gerenciamento de usuários e perfis.
- [ ] Vincular usuários a empresas.

### FASE 3 — ORDENS DE SERVIÇO

- [ ] Criar OS com status.
- [ ] Lifecycle da OS (`PENDENTE` → `ATRIBUIDA` → `EM_ROTA` → `ENTREGUE`).
- [ ] Cancelamento e devolução com estorno segundo política.
- [ ] Vincular OS à movimentação de débito.

### FASE 4 — ENTREGADORES

- [ ] Cadastro de entregadores.
- [ ] Atribuição de OS a entregador.
- [ ] PWA básico do entregador (aceitar, entregar, finalizar).

### FASE 5 — MAPA / DESPACHO

- [ ] Mapa com localização de entregadores.
- [ ] Acompanhamento de corridas.
- [ ] Painel do despachador.

### FASE 6 — INTEGRAÇÃO CARDÁPIO

- [ ] Implementar `POST /api/v1/pedidos` (receber do Cardápio).
- [ ] Implementar envio de webhooks para o Cardápio.
- [ ] Garantir idempotência nas duas pontas.
- [ ] Testar fluxo ponta a ponta.

### FASE 7 — RELATÓRIOS

- [ ] Tela de relatórios com métricas.
- [ ] Gráficos de distribuição.
- [ ] Exportar PDF.

---

## 22. Referências visuais

As imagens em `..\SISTEMA_LOGISTICO` mostram a plataforma `parceiro.leveai.com.br` e servem de referência para:

- Layout escuro com verde/laranja.
- Menu superior fixo: Mapa, Ordens, Relatórios, Carteira, Financeiro, Configurações.
- Uso de cards, badges de status verdes e tabelas.
- Mapa com rotas e ícone de moto.
- Tela de ordens com filtros e ações.
- Relatórios com cards de métricas e gráficos simples.
- Carteira e financeiro com saldo, extrato e fechamento.

A logo do projeto (DoRafa Tropical Brasil / REMO) deve estar em `static/assets/logo.png`.

---

## 23. Notas para o desenvolvedor

- Manter o projeto **separado** do Cardápio. Não importar código de `..\Cardapio`.
- Toda comunicação com o Cardápio é por HTTP. Nenhuma dependência direta de banco.
- Usar `X-Idempotency-Key` em todas as chamadas para evitar duplicidade.
- O Cardápio já expõe o endpoint `/api/external/logistica/status` para receber status da Central.
- A Fase 1 (financeiro) é crítica. Sem ela, a Fase 3 (OS) não pode existir.
- O princípio `sem crédito, sem entrega` deve ser uma regra de negócio inquebrável.
- PIX é o único método de abastecimento no MVP.
- Crédito só é gerado após confirmação do pagamento, nunca antes.
- Cada crédito, débito, estorno ou ajuste deve gerar uma linha em `movimentacoes_carteira`.
- `movimentacoes_carteira` é o livro-razão financeiro e a fonte de verdade financeira. `carteiras.saldo_atual` é o saldo materializado utilizado em operações transacionais.
- Toda alteração deve atualizar o livro-razão e o saldo materializado na mesma transação PostgreSQL. Em caso de divergência, o saldo deve ser reconstruído a partir das movimentações.
- Toda operação de débito deve usar `SELECT ... FOR UPDATE` para evitar condições de corrida.
- O débito e a criação da OS devem ocorrer na mesma transação atômica.
- O `abastecimento.uuid` é o identificador interno da operação de abastecimento. Os identificadores do PSP (`transacao_externa_id`, `pix_txid`) são para conciliação externa e nunca substituem o identificador interno.
- Um abastecimento somente pode gerar uma única movimentação de crédito.
- A política de estorno deve ser definida antes da implementação das OS.
- A princípio, o entregador não precisa de app nativo. PWA com geolocação é suficiente.
- Para geolocalização em tempo real, usar WebSocket ou envio periódico de coordenadas (a cada 10-30s).
- Para rotas, usar Google Maps ou OpenStreetMap (Leaflet + OSRM) com fallback manual.
