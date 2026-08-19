# Auditoria Técnica — Módulo Financeiro da Central Logística (REMO)

> **Data:** 19/08/2026
> **Auditor:** Devin CLI
> **Escopo:** módulo financeiro da REMO, com auditoria prévia do pagamento existente no Cardápio.
> **Objetivo:** extrair padrões reutilizáveis, identificar riscos e definir a arquitetura financeira mínima, segura e consistente para a REMO.

---

## Sumário executivo

A arquitetura de pagamentos do Cardápio está **bem estruturada, testada e pode ser reproduzida conceitualmente na REMO**. Ela segue uma separação clara em três níveis:

1. **Domínio** (`PaymentService`) — regras canônicas, estados, idempotência, não-regressão.
2. **Contrato** (`PaymentProviderAdapter`) — interface comum para qualquer PSP.
3. **Implementação** (`PagBankAdapter`) — tradução específica do PagBank.

A REMO deve reutilizar esse padrão para o fluxo **PIX online**, mas com adaptações obrigatórias:

- O pagamento do Cardápio é **pela venda** (cliente paga o restaurante). Na REMO, o pagamento é **de abastecimento** (empresa pré-paga a própria carteira).
- O Cardápio não tem carteira pré-paga, caixa físico nem controle de operador. Isso é **desenvolvimento do zero** na REMO.
- O conceito de `external_payments` se transforma em `abastecimentos` (PIX) na REMO.
- O crédito da carteira só existe **depois da confirmação** do abastecimento.
- O débito da carteira só ocorre **no ato da criação da OS**, transacionalmente.

**Decisão final:** a REMO pode reaproveitar a arquitetura em camadas (domínio/adapter/provider) do Cardápio, mas deve implementar um novo domínio financeiro com carteira, livro-razão, caixa físico e controle de operador.

### Separação absoluta: carteira, caixa e recebimentos

A carteira da empresa é o **destino do crédito**. Os recebimentos (PIX ou dinheiro) são as **origens financeiras**. O caixa é o controle do **dinheiro físico**.

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

- **PIX** é uma origem financeira (eletrônica), sem operador, sem caixa.
- **Dinheiro** é outra origem financeira (física), exige operador e caixa aberto.
- **Carteira** é o destino do crédito.
- **Caixa** controla o dinheiro físico.

---

## A. O que já existe no Cardápio

### A.1 Componentes identificados

| Camada | Arquivo | Papel |
|--------|---------|-------|
| Domínio | `cardapio_app/payments/domain.py` | `PaymentService`, `PaymentStatus`, `ExternalPayment`. Regras canônicas de pagamento. |
| Contrato | `cardapio_app/payments/adapter_contract.py` | `PaymentProviderAdapter` (ABC), `PaymentMethod`, `ProviderPaymentStatus`, `CreatePaymentRequest`, `CreatePaymentResult`, `PaymentStatusResult`, `PaymentEvent`, `QRCodeData`. |
| Implementação | `cardapio_app/payments/pagbank_adapter.py` | `PagBankAdapter`. Integração concreta com a API Order do PagBank. |
| Orquestração | `cardapio_app/pagamento_online/service.py` | Liga `PaymentService` ao ciclo de vida da solicitação, KDS e notificações. |
| Domínio puro | `cardapio_app/pagamento_online/domain.py` | Regras de apresentação, estados derivados, cálculo de subtotal, tolerância monetária. |
| Banco | `pg_store.py` | Schema, CRUD, idempotência e transações do PostgreSQL. |
| Rotas | `cardapio_app/routes.py` | Endpoints REST `/api/payments/*` e webhook. |
| PDV espelho | `PDV/app/payments/` | Cópia idêntica da arquitetura para o PDV. |

O projeto possui **duas cópias espelhadas** da arquitetura de pagamentos: uma no `Cardapio/` e outra no `PDV/`. Isso valida a portabilidade do padrão.

### A.2 Fluxo de pagamento online no Cardápio

```text
1. CRIAÇÃO
   Cliente/PDV solicita cobrança
   ↓
   PaymentService.iniciar_pagamento()
   ↓
   gera external_payment_id (UUID)
   ↓
   PagBankAdapter.create_payment()
   ↓
   POST /orders no PagBank
   ↓
   retorna provider_transaction_id + QR Code
   ↓
   grava em external_payments (status PENDENTE)

2. COBRANÇA
   external_payments armazena payload, image_url, expires_at
   ↓
   cliente vê QR Code / copia e cola

3. PAGAMENTO
   cliente paga o PIX

4. WEBHOOK
   PagBank chama POST /api/payments/webhook
   ↓
   PagBankAdapter.validate_webhook()
   ↓
   verifica assinatura (x-authenticity-token)
   ↓
   normaliza payload → PaymentEvent
   ↓
   PaymentService.processar_webhook()

5. CONFIRMAÇÃO
   busca external_payment por provider_transaction_id
   ↓
   verifica idempotência (last_event_id)
   ↓
   verifica não-regressão de estados terminais
   ↓
   atualiza status (PENDENTE → APROVADO)

6. PERSISTÊNCIA
   pg_store.update_external_payment_status()
   ↓
   atualiza status, last_event_id, last_event_at, updated_at

7. APLICAÇÃO
   orquestrador (pagamento_online/service.py)
   ↓
   verifica unicidade financeira
   ↓
   vincula pagamento à solicitação
   ↓
   avança status para PENDENTE (cozinha)
   ↓
   notifica KDS / Telegram

8. FINALIZAÇÃO
   PDV faz claim + apply do pagamento
   ↓
   registra applied_sale_id / applied_sale_payment_id
```

### A.3 Banco de dados

#### Tabela `external_payments`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | `TEXT PRIMARY KEY` | UUID interno do pagamento. Identificador principal da aplicação. |
| `provider_id` | `TEXT NOT NULL` | PSP (ex: PAGBANK). |
| `provider_transaction_id` | `TEXT NOT NULL` | ID da transação no PSP (ex: ORDE_...). Para conciliação externa. |
| `payment_method` | `TEXT NOT NULL` | PIX, CARTAO_CREDITO, CARTAO_DEBITO, VOUCHER. |
| `amount` | `REAL NOT NULL` | Valor em reais. |
| `currency` | `TEXT DEFAULT 'BRL'` | Moeda. |
| `status` | `TEXT DEFAULT 'PENDENTE'` | PENDENTE, APROVADO, RECUSADO, EXPIRADO, CANCELADO. |
| `reference_id` | `TEXT` | Vínculo com solicitação/sale_id. |
| `qr_code_payload` | `TEXT` | Cópia e cola do PIX. |
| `qr_code_image_base64` | `TEXT` | Imagem base64 do QR. |
| `qr_code_image_url` | `TEXT` | URL da imagem do QR. |
| `expires_at` | `TIMESTAMPTZ` | Expiração da cobrança. |
| `last_event_id` | `TEXT` | SHA-256 do último webhook processado. |
| `last_event_at` | `TIMESTAMPTZ` | Timestamp do último evento. |
| `claimed_by_pdv_id` | `TEXT` | PDV que reivindicou. |
| `claimed_at` | `TIMESTAMPTZ` | Data do claim. |
| `applied_sale_id` | `INTEGER` | Venda onde foi aplicado. |
| `applied_sale_payment_id` | `INTEGER` | ID do pagamento dentro da venda. |
| `applied_at` | `TIMESTAMPTZ` | Data da aplicação. |
| `metadata` | `JSONB` | Dados extras. |
| `created_at` | `TIMESTAMPTZ DEFAULT NOW()` | Criação. |
| `updated_at` | `TIMESTAMPTZ DEFAULT NOW()` | Última atualização. |

#### Tabela `payment_provider_settings`

Configurações não-secretas do PSP.

| Campo | Descrição |
|-------|-----------|
| `provider_id` | Identificador do PSP. |
| `display_name` | Nome amigável. |
| `base_url` | URL base da API. |
| `environment` | SANDBOX/PRODUCTION. |
| `default_expires_in_seconds` | Expiração padrão. |
| `webhook_url` | URL para notificações. |
| `config_json` | Configurações extras. |
| `is_active` | Ativo? |

#### Tabela `payment_provider_credentials`

Credenciais secretas criptografadas.

| Campo | Descrição |
|-------|-----------|
| `provider_id` | PSP. |
| `credential_key` | Nome do segredo (PAGBANK_TOKEN, PAGBANK_WEBHOOK_TOKEN). |
| `encrypted_value` | Valor criptografado com Fernet. |
| `hint` | Dica não sensível. |

#### Índices

- `idx_external_payments_status`
- `idx_external_payments_provider_tx` (provider_id, provider_transaction_id)
- `idx_external_payments_reference`
- `idx_external_payments_claimed`
- `idx_provider_credentials_provider`

### A.4 Estados do pagamento

```
PENDENTE  → APROVADO
          → RECUSADO
          → CANCELADO
          → EXPIRADO

EXPIRADO  → APROVADO  (permitido: PIX pago após expiração)

APROVADO  → (terminal, não regredir)
RECUSADO  → (terminal)
CANCELADO → (terminal)
```

### A.5 Idempotência no Cardápio

O Cardápio implementa idempotência em **múltiplas camadas**:

1. **Nível do PSP:**
   - `last_event_id` (SHA-256 do body do webhook) evita processar o mesmo evento duas vezes.
   - `PaymentService.processar_webhook()` compara `last_event_id` com `event.event_id`.

2. **Nível de domínio:**
   - Estados terminais (`APROVADO`, `RECUSADO`, `CANCELADO`) não são sobrescritos.
   - Exceção: `EXPIRADO → APROVADO` é permitida.

3. **Nível de aplicação:**
   - `claim_external_payment` e `apply_external_payment` são idempotentes via condições `IS NULL OR = valor`.

4. **Nível de pedido público:**
   - Tabela `public_pedidos_idempotency` evita duplicar a criação de pedido.

### A.6 Testes que comprovam o funcionamento

| Teste | Local | O que valida |
|-------|-------|--------------|
| `test_pix_contract.py` | `PDV/tests/` | Contrato, criação, webhook, idempotência, estados, expiração. |
| `test_pagamento_online_fase1a.py` | `PDV/tests/` | Fluxo online completo, orquestração, retentativa. |
| `teste_integracao_real.py` | `PDV/tests/` | Integração real com sandbox/produção. |
| `test_payment_provider_config.py` | `PDV/tests/` | Configuração de provedores. |
| `test_salao_fora_da_fase1a.py` | `PDV/tests/` | Pedidos presenciais fora do escopo online. |

---

## B. O que pode ser reutilizado conceitualmente

| Conceito | Como reutilizar na REMO |
|----------|-------------------------|
| Arquitetura em 3 níveis (domínio/adapter/provider) | Criar `AbastecimentoService`, `PaymentProviderAdapter` e `PagBankAdapter` específicos para abastecimento. |
| Contrato do adapter | Reaproveitar `PaymentMethod`, `ProviderPaymentStatus`, `QRCodeData`, `CreatePaymentRequest`, `CreatePaymentResult`, `PaymentEvent`. |
| Normalização de status | Mapear WAITING/PAID → PENDING/APPROVED. |
| Webhook com assinatura | Usar `x-authenticity-token` e SHA-256(token + body). |
| Idempotência via `last_event_id` | `abastecimento.last_event_id` = SHA-256(body do webhook). |
| Estados terminais e não-regressão | `PENDENTE → APROVADO/CANCELADO/EXPIRADO`; `APROVADO` terminal. |
| Expiração local | Job que expira abastecimentos PENDENTE com `expires_at < NOW()`. |
| Conversão centavos/reais | `_reais_to_centavos` e `_centavos_to_reais`. |
| Tolerância monetária | `AMOUNT_TOLERANCE = 0.01`. |
| Separação settings/credentials | `payment_provider_settings` e `payment_provider_credentials` (ou equivalente). |
| Feature flag | `CARDAPIO_PIX_ONLINE_ENABLED` → `REMO_PIX_ONLINE_ENABLED`. |

---

## C. O que precisa ser adaptado

| Item | Cardápio | REMO | Adaptação |
|------|----------|------|-----------|
| Propósito do pagamento | Cliente paga pedido | Empresa abastece carteira | Aprovação gera **crédito na carteira**, não liberação de pedido. |
| Entidade de pagamento | `external_payments` | `abastecimentos` | Renomear e adicionar `carteira_id`, `movimentacao_id`. |
| reference_id | `solicitacao_id` | `empresa_id` + abastecimento interno | Vínculo com empresa, não pedido. |
| Aplicação do pagamento | `applied_sale_id` | `movimentacao_id` na carteira | O crédito vira movimentação financeira. |
| Orquestração | Liga pagamento ao KDS | Liga abastecimento à carteira | Nova orquestração financeira. |
| QR Code | Exibido ao cliente | Exibido à empresa/admin | Interface de abastecimento. |
| Webhook | Dispara KDS | Dispara crédito na carteira | Atomicidade: abastecimento APROVADO + movimentação CREDITO + saldo. |

---

## D. O que precisa ser desenvolvido do zero

1. **Entidade `carteiras`**
   - Uma por empresa.
   - `saldo_atual` materializado.
   - Livro-razão em `movimentacoes_carteira`.

2. **Livro-razão `movimentacoes_carteira`**
   - Tipos: `CREDITO`, `DEBITO`, `ESTORNO`, `AJUSTE`.
   - Campos: `saldo_anterior`, `saldo_final`, `idempotency_key`, `abastecimento_id`, `ordem_id`.

3. **Entidade `abastecimentos`**
   - PIX e dinheiro presencial.
   - Estados: `PENDENTE`, `APROVADO`, `CANCELADO`, `EXPIRADO`.
   - Não confundir com `external_payments`: aqui o foco é abastecimento de carteira.

4. **Caixa físico (`caixas`, `caixa_operacoes`)**
   - Abertura, fechamento, suprimento, sangria, entrada, saída, ajuste.
   - Vinculação a operador.
   - Contagem física vs saldo do sistema.

5. **Auditoria financeira (`auditoria_financeira`)**
   - Rastreabilidade de toda alteração de saldo.

6. **Motor de débito com `FOR UPDATE`**
   - Bloqueio de carteira.
   - Verificação atômica de saldo.
   - Criação de débito + eventual criação de OS na mesma transação.

7. **Idempotência dupla**
   - Abastecimento PIX (webhook duplicado).
   - Abastecimento em dinheiro (requisição duplicada).
   - Débito da carteira (requisição duplicada).

8. **Regras de negócio novas**
   - `sem crédito, sem entrega`.
   - Caixa fechado impede abastecimento em dinheiro.
   - Operador obrigatório para caixa.
   - Estorno por cancelamento de OS segundo política.

---

## E. Modelo financeiro recomendado

### Entidades principais

```
empresas
  └── carteiras (1:1)
        ├── saldo_atual (materializado)
        └── movimentacoes_carteira (livro-razão)

abastecimentos
  ├── PIX
  │     └── vira movimentacao CREDITO quando APROVADO
  └── DINHEIRO
        └── caixa_operacao + movimentacao CREDITO

caixas
  └── caixa_operacoes
        ├── ENTRADA
        ├── SAIDA
        ├── SUPRIMENTO
        ├── SANGRIA
        └── AJUSTE

ordens_servico
  └── movimentacao DEBITO vinculada

auditoria_financeira
  └── registra eventos de alteração de saldo
```

### Princípios

1. **Carteira pré-paga:** a empresa precisa ter saldo antes de usar logística.
2. **Livro-razão:** `movimentacoes_carteira` é a fonte de verdade.
3. **Saldo materializado:** `carteiras.saldo_atual` é usado para operações, mas deve ser sempre consistente com o livro-razão.
4. **Atomicidade:** crédito, débito e OS ocorrem dentro da mesma transação.
5. **Concorrência:** `SELECT ... FOR UPDATE` em toda operação de saldo.
6. **Idempotência:** nenhuma confirmação gera duplo crédito; nenhum débito é duplicado.
7. **Separação:** caixa físico ≠ carteira da empresa ≠ recebimentos PIX.

---

## F. Modelo de dados recomendado

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
  operador_id BIGINT REFERENCES usuarios(id)  -- para DINHEIRO
  caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id)  -- para DINHEIRO
  criado_em TIMESTAMPTZ DEFAULT NOW()
  UNIQUE (empresa_id, transacao_externa_id)

movimentacoes_carteira
  id BIGSERIAL PRIMARY KEY
  uuid TEXT UNIQUE
  carteira_id BIGINT NOT NULL REFERENCES carteiras(id)
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  ordem_id BIGINT
  tipo TEXT NOT NULL  -- CREDITO, DEBITO, ESTORNO, AJUSTE
  descricao TEXT
  valor NUMERIC(12,2) NOT NULL
  saldo_anterior NUMERIC(12,2) NOT NULL
  saldo_final NUMERIC(12,2) NOT NULL
  status TEXT NOT NULL DEFAULT 'CONCLUIDO'
  idempotency_key TEXT UNIQUE
  referencia_externa TEXT
  criado_em TIMESTAMPTZ DEFAULT NOW()

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

ordens_servico
  id BIGSERIAL PRIMARY KEY
  uuid TEXT UNIQUE
  solicitacao_id TEXT
  empresa_id TEXT NOT NULL REFERENCES empresas(id)
  movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id)
  entregador_id BIGINT REFERENCES usuarios(id)
  status TEXT NOT NULL
  protocolo TEXT UNIQUE
  payload_json JSONB
  taxa NUMERIC(12,2)
  criado_em TIMESTAMPTZ DEFAULT NOW()

auditoria_financeira
  id BIGSERIAL PRIMARY KEY
  carteira_id BIGINT NOT NULL REFERENCES carteiras(id)
  movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id)
  abastecimento_id BIGINT REFERENCES abastecimentos(id)
  tipo TEXT NOT NULL
  referencia TEXT
  dados_json JSONB
  criado_em TIMESTAMPTZ DEFAULT NOW()
```

---

## G. Fluxo PIX na REMO

```text
1. Empresa/admin solicita abastecimento de R$ 100 via PIX
   ↓
2. Sistema cria abastecimento PENDENTE
   ↓
3. AbastecimentoService.iniciar_abastecimento_pix()
   ↓
4. PagBankAdapter.create_payment()
   ↓
5. Grava abastecimento com QR Code
   ↓
6. Empresa vê QR Code / copia e cola
   ↓
7. PIX pago
   ↓
8. PSP envia webhook
   ↓
9. PagBankAdapter.validate_webhook()
   ↓
10. PaymentService.processar_webhook() / AbastecimentoService
   ↓
11. Verifica idempotência (last_event_id)
   ↓
12. Verifica não-regressão
   ↓
13. Transação atômica:
       - abastecimento → APROVADO
       - cria movimentacao CREDITO
       - atualiza carteiras.saldo_atual
       - registra auditoria_financeira
       - COMMIT
   ↓
14. Carteira com R$ 100 de crédito
```

### Regra de idempotência do PIX

```text
Webhook 1
   ↓
APROVADO
   ↓
+ R$ 100

Webhook 1 novamente
   ↓
abastecimento já APROVADO
   ↓
NÃO cria nova movimentação
   ↓
Saldo continua R$ 100
```

---

## H. Fluxo dinheiro presencial na REMO

```text
1. Operador abre caixa
   Caixa: CAIXA-01
   Saldo inicial: R$ 200,00

2. Empresa entrega R$ 100 em dinheiro

3. Operador autorizado registra abastecimento em dinheiro
   - Valor: R$ 100,00
   - Empresa: EMPRESA01
   - Caixa: CAIXA-01 (ABERTO)
   - Operador: JOAO

4. Validação:
   - Caixa está ABERTO?
   - Operador está autorizado?
   - Valor > 0?

5. Transação atômica:
   - cria abastecimento APROVADO
   - cria caixa_operacao ENTRADA + R$ 100
   - cria movimentacao CREDITO + R$ 100 na carteira
   - atualiza carteiras.saldo_atual
   - atualiza saldo do caixa
   - registra auditoria_financeira
   - COMMIT

6. Carteira: + R$ 100
   Caixa: + R$ 100
```

### Regra de segurança

```text
CAIXA FECHADO
   ↓
ABASTECIMENTO EM DINHEIRO → NEGADO

CAIXA ABERTO
+
OPERADOR AUTORIZADO
+
VALOR
+
EMPRESA
+
CONFIRMAÇÃO
   ↓
ABASTECIMENTO APROVADO
```

---

## I. Fluxo de abertura/fechamento de caixa

### Abertura

```text
Operador: João
Data: 19/08/2026 08:00
Caixa: CAIXA-01
Saldo inicial contado: R$ 200,00

Cria caixa_operacao tipo ABERTURA
  caixa_id = 1
  operador_id = 1
  saldo_inicial = 200.00
  status_caixa = ABERTO
```

### Durante o expediente

```text
ENTRADA     + R$ 100  (abastecimento dinheiro)
SAÍDA       - R$ 20   (ex: despesas do caixa)
SUPRIMENTO  + R$ 50   (reforço)
SANGRIA     - R$ 30   (retirada)
AJUSTE      ± R$ X    (correção com motivo)
```

### Fechamento

```text
Saldo inicial sistema:    R$ 200
Entradas:                 R$ 300
Saídas:                   R$ 50
--------------------------
Saldo esperado:           R$ 450

Dinheiro contado:         R$ 450
Diferença:                R$ 0

Cria caixa_operacao tipo FECHAMENTO
  saldo_final_sistema = 450.00
  saldo_contado = 450.00
  diferenca = 0.00
  operador_id = JOAO
  status_caixa = FECHADO
```

### Divergência

```text
Saldo esperado:      R$ 450
Dinheiro contado:    R$ 440
Diferença:           - R$ 10

Registra FECHAMENTO com diferenca = -10.00
NUNCA apagar ou corrigir silenciosamente a operação original.
```

---

## J. Regras de negócio

### J.1 Regras gerais

1. `sem crédito, sem entrega`.
2. Carteira pré-paga por empresa.
3. PIX é o único meio online no MVP.
4. Dinheiro presencial requer caixa aberto e operador autorizado.
5. Regras de origem por método:
   - `PIX`: `transacao_externa_id` obrigatória; `operador_id` e `caixa_operacao_id` NULL.
   - `DINHEIRO`: `operador_id` e `caixa_operacao_id` obrigatórios; `transacao_externa_id` NULL.
6. Cada alteração de saldo gera movimentação no livro-razão.
7. Toda operação de saldo usa `SELECT ... FOR UPDATE`.
8. Débito e criação de OS são atômicos.
9. Um abastecimento gera no máximo uma movimentação de crédito.
10. Não confundir `abastecimento` com `ajuste`.
11. Crédito só é gerado após confirmação.
12. Nenhuma movimentação financeira confirmada pode ser editada ou excluída. Correções geram movimentação `AJUSTE` vinculada à original.

### J.2 Regras de estorno

| Status da OS | Estorno |
|--------------|---------|
| `PENDENTE` | 100% da taxa |
| `ATRIBUIDA` | Política comercial (parcial ou total) |
| `EM_ROTA` | Sem estorno |
| `ENTREGUE` | Sem estorno |

### J.3 Regras de caixa

- Não é possível receber dinheiro sem caixa aberto.
- Apenas um caixa pode estar aberto por vez.
- Cada operação de caixa exige operador identificado.
- Fechamento exige contagem física.
- Diferenças são registradas, nunca apagadas.
- Operações de controle (`ABERTURA`, `FECHAMENTO`) e operações de dinheiro físico (`ENTRADA`, `SAIDA`, `SUPRIMENTO`, `SANGRIA`, `AJUSTE`) devem ser separadas.

---

## K. Riscos encontrados

### K.1 Riscos herdados do Cardápio

| Risco | Descrição | Mitigação na REMO |
|-------|-----------|-------------------|
| R1 — `amount REAL` | O Cardápio usa `REAL` para valor monetário, o que pode causar imprecisão. | Usar `NUMERIC(12,2)` na REMO. |
| R2 — Sem carteira | O Cardápio não tem controle de saldo pré-pago. | Criar `carteiras` e `movimentacoes_carteira`. |
| R3 — Caixa inexistente | Não há controle de caixa físico. | Criar `caixas` e `caixa_operacoes`. |
| R4 — `last_event_id` como idempotência | O Cardápio usa `last_event_id`, mas não há tabela de idempotência persistente de webhooks. | Criar `webhooks_recebidos` com `idempotency_key` UNIQUE. |
| R5 — Conciliação manual | Pagamentos excedentes geram ocorrências para tratamento manual. | Implementar bloqueios automáticos e auditoria. |
| R6 — Estado não atômico | O Cardápio separa status de pagamento e status do pedido. | Na REMO, crédito e saldo devem ser atômicos. |

### K.2 Riscos novos da REMO

| Risco | Descrição | Mitigação |
|-------|-----------|-----------|
| R7 — Saldo negativo | Concorrência pode levar a débito sem saldo. | `SELECT ... FOR UPDATE` + verificação antes do débito. |
| R8 — Crédito duplicado | Webhook duplicado pode gerar saldo extra. | `idempotency_key` UNIQUE em `movimentacoes_carteira` e status `APROVADO` do abastecimento. |
| R9 — Dinheiro sem registro | Operador pode tentar crédito sem movimentação de caixa. | Exigir `caixa_operacao_id` em todo abastecimento em dinheiro. |
| R10 — Caixa fechado | Recebimento fora do expediente sem controle. | Validar status do caixa antes de qualquer operação. |
| R11 — Divergência não registrada | Fechamento pode esconder diferenças. | Sempre gravar `diferenca` no fechamento. |
| R12 — Sem separação carteira/caixa | Misturar saldo da empresa com dinheiro físico. | Entidades separadas e rastreáveis. |

---

## L. Falhas ou inconsistências do plano atual

O plano `PLANO_CENTRAL_LOGISTICA.md` foi revisado e está **consistente na estratégia**, mas apresenta alguns pontos que precisam de atenção:

1. **Saldo materializado:** a versão final do plano já corrige a contradição, mas a implementação deve garantir que `carteiras.saldo_atual` e `movimentacoes_carteira` sejam atualizados na **mesma transação**.

2. **Ausência de tabela de webhooks recebidos:** o plano menciona `webhooks_enviados` (da REMO para o Cardápio), mas não cria `webhooks_recebidos` (do PSP para a REMO). Recomendo adicionar.

3. **Caixa físico subespecificado:** o plano cita caixa, mas não detalha `caixas` e `caixa_operacoes`. Necessário detalhar.

4. **Operador não modelado:** `usuarios.perfil` precisa incluir `OPERADOR` e vincular `caixa_operacoes.operador_id`.

5. **Auditoria financeira:** a tabela foi adicionada, mas os gatilhos de escrita ainda precisam ser definidos.

6. **Testes de concorrência:** o plano menciona `FOR UPDATE`, mas não exige testes automatizados de concorrência. Recomendo testes com threads/forks simulando requisições simultâneas.

7. **Feature flag:** o plano não menciona feature flag para PIX online. Recomendo `REMO_PIX_ONLINE_ENABLED`.

8. **Separação carteira/caixa:** o plano deve deixar explícito que a carteira é o destino do crédito e o caixa é o controle do dinheiro físico; nunca confundir os saldos.

---

## M. Testes necessários

### M.1 PIX

- [ ] Criar abastecimento PIX.
- [ ] Gerar cobrança com QR Code.
- [ ] Pagamento confirmado.
- [ ] Webhook processado.
- [ ] Webhook duplicado (idempotência).
- [ ] Pagamento expirado.
- [ ] Pagamento recusado.
- [ ] Crédito automático na carteira.
- [ ] Transação externa duplicada.
- [ ] Confirmação após expiração (`EXPIRADO → APROVADO`).

### M.2 Dinheiro

- [ ] Caixa fechado impede abastecimento.
- [ ] Caixa aberto permite abastecimento.
- [ ] Operador autorizado.
- [ ] Recebimento físico.
- [ ] Crédito na carteira.
- [ ] Entrada no caixa.
- [ ] Operação duplicada (idempotência).

### M.3 Caixa

- [ ] Abertura.
- [ ] Saldo inicial.
- [ ] Entrada.
- [ ] Saída.
- [ ] Suprimento.
- [ ] Sangria.
- [ ] Fechamento.
- [ ] Diferença positiva.
- [ ] Diferença negativa.
- [ ] Fechamento sem diferença.

### M.4 Carteira

- [ ] Crédito.
- [ ] Débito.
- [ ] Estorno.
- [ ] Saldo insuficiente.
- [ ] Concorrência (dois débitos simultâneos).
- [ ] Reconstrução do saldo a partir do livro-razão.
- [ ] Auditoria de alterações.

### M.5 Integração Cardápio

- [ ] Cardápio envia OS para REMO.
- [ ] REMO rejeita por saldo insuficiente.
- [ ] REMO aceita e cria OS.
- [ ] REMO envia status de volta.
- [ ] Idempotência nas duas pontas.

---

## N. Plano de implementação recomendado

### Fase 1.1 — Estrutura base (sem PSP)

1. Criar repositório Git e projeto Flask.
2. Configurar PostgreSQL.
3. Criar tabelas: `empresas`, `carteiras`, `usuarios`, `movimentacoes_carteira`, `auditoria_financeira`.
4. Implementar cadastro de empresas e carteiras.
5. Implementar crédito manual/teste (sem integração real).
6. Implementar débito isolado com `FOR UPDATE`.
7. Implementar extrato e saldo.

### Fase 1.2 — PIX online

1. Criar tabela `abastecimentos`.
2. Reproduzir arquitetura `AbastecimentoService` + `PaymentProviderAdapter` + `PagBankAdapter`.
3. Implementar geração de cobrança PIX.
4. Implementar webhook do PagBank.
5. Implementar idempotência via `last_event_id` e `webhooks_recebidos`.
6. Implementar crédito atômico na carteira após confirmação.

### Fase 1.3 — Caixa físico

1. Criar tabelas `caixas` e `caixa_operacoes`.
2. Implementar abertura/fechamento.
3. Implementar entrada/saída/suprimento/sangria.
4. Implementar abastecimento em dinheiro vinculado a caixa aberto.

### Fase 1.4 — Integração e testes

1. Implementar endpoints para testes isolados.
2. Criar suite de testes de concorrência.
3. Validar idempotência de PIX e dinheiro.
4. Simular integração com Cardápio (mock).

### Fase 2 — Autenticação e usuários

1. Login, perfis, permissões.
2. Vincular operadores a caixas.

### Fase 3 — Ordens de Serviço

1. Criar OS.
2. Vincular débito atômico à OS.
3. Regras de estorno.

---

## Conclusão

A REMO pode e deve aproveitar a **arquitetura em camadas** do Cardápio para pagamentos PIX online. O padrão `PaymentService → Adapter → Provider` está validado, testado e é portável.

No entanto, o domínio financeiro da REMO é **mais complexo** que o do Cardápio por incluir:

- carteira pré-paga;
- livro-razão;
- abastecimento (não venda);
- caixa físico;
- operadores;
- débito vinculado a OS.

A arquitetura financeira mínima, segura e consistente exige:

1. Reproduzir a camada de pagamento PIX.
2. Criar domínio de carteira com livro-razão.
3. Criar domínio de caixa físico.
4. Garantir atomicidade e concorrência com `FOR UPDATE`.
5. Garantir idempotência em todas as operações.
6. Manter auditoria completa.

A implementação deve seguir a ordem proposta: estrutura base → PIX → caixa → integração → OS. Não começar pela OS sem a carteira funcionando.
