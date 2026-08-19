-- Schema da Central Logística (REMO)
-- Fase 1 — Financeiro Operacional / Carteira Pré-paga

CREATE TABLE IF NOT EXISTS empresas (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    cnpj TEXT,
    telefone TEXT,
    email TEXT,
    endereco JSONB,
    config JSONB,
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS usuarios (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE,
    nome TEXT,
    telefone TEXT,
    perfil TEXT NOT NULL,
    empresa_id TEXT REFERENCES empresas(id),
    ativo BOOLEAN DEFAULT TRUE,
    senha_hash TEXT,
    senha_salt TEXT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS carteiras (
    id BIGSERIAL PRIMARY KEY,
    empresa_id TEXT UNIQUE NOT NULL REFERENCES empresas(id),
    saldo_atual NUMERIC(12,2) NOT NULL DEFAULT 0,
    ativo BOOLEAN DEFAULT TRUE,
    bloqueada_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS caixas (
    id BIGSERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'FECHADO',
    operador_abertura_id BIGINT REFERENCES usuarios(id),
    aberto_em TIMESTAMPTZ,
    saldo_esperado NUMERIC(12,2) DEFAULT 0,
    ativo BOOLEAN DEFAULT TRUE,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS abastecimentos (
    id BIGSERIAL PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    empresa_id TEXT NOT NULL REFERENCES empresas(id),
    carteira_id BIGINT NOT NULL REFERENCES carteiras(id),
    valor NUMERIC(12,2) NOT NULL,
    metodo TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    pix_payload JSONB,
    pix_txid TEXT,
    pix_linha_digitavel TEXT,
    pix_qr_code TEXT,
    transacao_externa_id TEXT,
    confirmado_em TIMESTAMPTZ,
    expira_em TIMESTAMPTZ,
    operador_id BIGINT REFERENCES usuarios(id),
    caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id),
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (empresa_id, transacao_externa_id)
);

CREATE TABLE IF NOT EXISTS movimentacoes_carteira (
    id BIGSERIAL PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    carteira_id BIGINT NOT NULL REFERENCES carteiras(id),
    abastecimento_id BIGINT REFERENCES abastecimentos(id),
    caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id),
    ordem_id BIGINT,
    tipo TEXT NOT NULL,
    descricao TEXT,
    valor NUMERIC(12,2) NOT NULL,
    saldo_anterior NUMERIC(12,2) NOT NULL,
    saldo_final NUMERIC(12,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'CONCLUIDO',
    idempotency_key TEXT UNIQUE,
    referencia_externa TEXT,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS caixa_operacoes (
    id BIGSERIAL PRIMARY KEY,
    caixa_id BIGINT NOT NULL REFERENCES caixas(id),
    operador_id BIGINT NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL,
    valor NUMERIC(12,2),
    saldo_inicial NUMERIC(12,2),
    saldo_final_sistema NUMERIC(12,2),
    saldo_contado NUMERIC(12,2),
    diferenca NUMERIC(12,2),
    motivo TEXT,
    abastecimento_id BIGINT REFERENCES abastecimentos(id),
    movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id),
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ordens_servico (
    id BIGSERIAL PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    solicitacao_id TEXT,
    empresa_id TEXT NOT NULL REFERENCES empresas(id),
    movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id),
    entregador_id BIGINT REFERENCES usuarios(id),
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    protocolo TEXT UNIQUE,
    payload_json JSONB,
    taxa NUMERIC(12,2),
    atribuido_em TIMESTAMPTZ,
    em_rota_em TIMESTAMPTZ,
    entregue_em TIMESTAMPTZ,
    cancelado_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (empresa_id, solicitacao_id)
);

CREATE TABLE IF NOT EXISTS webhooks_recebidos (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    abastecimento_id BIGINT REFERENCES abastecimentos(id),
    origem TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    processado BOOLEAN DEFAULT FALSE,
    recebido_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS webhooks_enviados (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    ordem_id BIGINT REFERENCES ordens_servico(id),
    url TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    resposta_json JSONB,
    status_code INTEGER,
    enviado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditoria_financeira (
    id BIGSERIAL PRIMARY KEY,
    carteira_id BIGINT NOT NULL REFERENCES carteiras(id),
    movimentacao_id BIGINT REFERENCES movimentacoes_carteira(id),
    abastecimento_id BIGINT REFERENCES abastecimentos(id),
    caixa_operacao_id BIGINT REFERENCES caixa_operacoes(id),
    tipo TEXT NOT NULL,
    referencia TEXT,
    dados_json JSONB,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_abastec_empresa ON abastecimentos(empresa_id);
CREATE INDEX IF NOT EXISTS idx_abastec_status ON abastecimentos(status);
CREATE INDEX IF NOT EXISTS idx_abastec_uuid ON abastecimentos(uuid);
CREATE INDEX IF NOT EXISTS idx_abastec_transacao ON abastecimentos(empresa_id, transacao_externa_id);
CREATE INDEX IF NOT EXISTS idx_mov_carteira ON movimentacoes_carteira(carteira_id);
CREATE INDEX IF NOT EXISTS idx_mov_tipo ON movimentacoes_carteira(tipo);
CREATE INDEX IF NOT EXISTS idx_caixa_operacoes_caixa ON caixa_operacoes(caixa_id);
CREATE INDEX IF NOT EXISTS idx_caixa_operacoes_tipo ON caixa_operacoes(tipo);
CREATE INDEX IF NOT EXISTS idx_webhooks_recebidos_key ON webhooks_recebidos(idempotency_key);
