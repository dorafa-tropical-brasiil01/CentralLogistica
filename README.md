# Central Logística (REMO)

Plataforma web/PWA para gestão de entregas e logística.

## Estrutura

```
CentralLogistica/
├── app/
│   ├── core/             # config, db, ids
│   ├── repositories/     # acesso a dados (um por entidade)
│   ├── services/         # regras de negócio
│   ├── pix/              # adapter, mock, serviço e webhook
│   ├── caixa/            # módulo de caixa físico
│   ├── api/              # rotas REST
│   ├── migracoes/        # schema
│   ├── schema.sql        # DDL
│   └── factory.py        # factory Flask
├── tests/
├── main.py               # entrypoint Railway
├── requirements.txt
└── runtime.txt
```

## Variáveis de ambiente

- `DATABASE_URL`: PostgreSQL
- `SECRET_KEY`
- `CENTRAL_LOGISTICA_API_KEY`
- `PIX_PROVIDER`: `mock` ou `pagbank`
- `PIX_TOKEN`
- `PIX_WEBHOOK_SECRET`
- `REMO_PIX_ONLINE_ENABLED`

## Boas práticas

- Arquivos pequenos e com responsabilidade única.
- Separação entre repositórios, serviços e adapters.
- Operações financeiras sempre dentro de transações.
- `SELECT ... FOR UPDATE` em toda alteração de saldo.
- Imutabilidade das movimentações confirmadas.
