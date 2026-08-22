# RELATÓRIO TÉCNICO — Rastreamento de Entregadores no REMO

**Data:** 22/08/2026
**Análise:** Auditoria do sistema de rastreamento em tempo real implementado no Portal do Cliente e Painel Admin

---

## 1. RESUMO EXECUTIVO

O sistema REMO possui rastreamento GPS de entregadores implementado, mas **sem ajuste à malha viária (snap-to-roads)**. O resultado visual é uma linha reta conectando pontos GPS sucessivos, que atravessa quarteirões e áreas não viáveis. Este relatório documenta a arquitetura atual, identifica as limitações e propõe a evolução para um rastreamento aderente às ruas (similar ao LEVA.AI).

---

## 2. ARQUITETURA ATUAL

### 2.1 Fluxo de dados — coleta de GPS

```
Celular do entregador (PWA)
    │
    │  navigator.geolocation.watchPosition()
    │  → callback a cada mudança de posição
    │
    ↓
POST /api/pwa/localizacao
    { lat, lng, precisao }
    │
    ↓
Backend (app/api/pwa.py:332)
    │
    ├── UPDATE usuarios SET localizacao_atual = ...
    │   (posição mais recente — sobrescreve a anterior)
    │
    └── INSERT INTO rastreamento (usuario_id, lat, lng, precisao)
        (histórico de posições — mantém últimas 200 por usuário)
```

**Arquivo:** `app/api/pwa.py`, linha 332-371

### 2.2 Coleta no PWA (frontend)

```javascript
// templates/index.html, linha 781-803
gpsWatchId = navigator.geolocation.watchPosition(async pos => {
    const lat = pos.coords.latitude;
    const lng = pos.coords.longitude;
    const precisao = pos.coords.accuracy;
    await api('/localizacao', {
        method: 'POST',
        body: JSON.stringify({ lat, lng, precisao }),
    });
}, err => { ... }, {
    enableHighAccuracy: true,
    maximumAge: 5000,    // aceita cache de até 5s
    timeout: 15000       // timeout de 15s
});
```

**Características:**
- Usa `watchPosition` do navegador — dispara callback a cada mudança detectada
- `enableHighAccuracy: true` — solicita GPS de alta precisão
- **Não há controle de frequência** — o navegador decide quando disparar
- **Não há envio em background** — se o PWA for minimizado, o GPS para
- **Não há filtro de precisão** — pontos com precisão ruim (e.g. 500m) são salvos igual aos bons

### 2.3 Armazenamento — tabela `rastreamento`

```sql
-- app/schema.sql, linha 234-242
CREATE TABLE IF NOT EXISTS rastreamento (
    id BIGSERIAL PRIMARY KEY,
    usuario_id BIGINT NOT NULL REFERENCES usuarios(id),
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    precisao DOUBLE PRECISION,
    criado_em TIMESTAMPTZ DEFAULT NOW()
);
```

**Características:**
- Guarda lat, lng, precisão e timestamp
- **Não guarda** velocidade, rumo (heading), nem ordem_id associada
- Limite de 200 posições por usuário (DELETE automático das mais antigas)
- **Não há vinculação com a ordem** — a trilha é do entregador, não da corrida

### 2.4 Consumo da trilha — Admin

```python
# app/api/admin.py, linha 246-258
for ent in entregadores:
    if ent.get("localizacao"):
        cur.execute("""
            SELECT lat, lng, criado_em
            FROM rastreamento
            WHERE usuario_id = %s
            ORDER BY criado_em DESC LIMIT 50
        """, (ent["id"],))
        trilha = [{"lat": float(t["lat"]), "lng": float(t["lng"])} for t in cur.fetchall()]
        trilha.reverse()  # ordem cronológica
        ent["trilha"] = trilha
```

**Características:**
- Busca as últimas 50 posições do entregador (independente de qual ordem)
- Retorna como array de `{lat, lng}` para o frontend

### 2.5 Consumo da trilha — Portal do Cliente

```python
# app/api/portal.py, linha 620-627
if r.get("entregador_id"):
    cur.execute("""
        SELECT lat, lng FROM rastreamento
        WHERE usuario_id = %s ORDER BY criado_em DESC LIMIT 50
    """, (r["entregador_id"],))
    trilha = [{"lat": float(t["lat"]), "lng": float(t["lng"])} for t in cur.fetchall()]
    trilha.reverse()
```

Mesma lógica do admin — últimas 50 posições do entregador.

### 2.6 Renderização no mapa — ambos os portais

```javascript
// Admin — templates/admin/index.html, linha 778-781
if (e.trilha && e.trilha.length > 1) {
    const points = e.trilha.map(t => [t.lat, t.lng]);
    L.polyline(points, { color: '#00d4aa', weight: 4, opacity: .8 }).addTo(routesLayer);
}

// Portal do Cliente — templates/portal/index.html, linha 686-688
if (o.trilha && o.trilha.length > 1) {
    const points = o.trilha.map(t => [t.lat, t.lng]);
    L.polyline(points, { color: '#00d4aa', weight: 4, opacity: .8 }).addTo(acomLayers);
}
```

**Características:**
- `L.polyline(points)` — conecta os pontos com segmentos retos
- **Sem snap-to-roads** — os pontos GPS brutos são conectados diretamente
- **Sem interpolação** — sem curvas suaves entre os pontos
- **Sem roteamento** — não consulta nenhuma API de rotas

### 2.7 Linha reta entre entregador e destino (Admin)

```javascript
// templates/admin/index.html, linha 767
L.polyline(
    [[ent.localizacao.lat, ent.localizacao.lng], coords],
    { color: '#3a86ff', weight: 3, opacity: .7, dashArray: '8,8' }
).addTo(routesLayer);
```

Esta é uma **linha tracejada azul** conectando a posição atual do entregador ao destino. É puramente visual — não representa uma rota real.

---

## 3. DIAGNÓSTICO — O QUE ESTÁ CAUSANDO A LINHA RETA

### 3.1 Causa raiz

O sistema atual faz:

```
GPS bruto (P1, P2, P3, P4, P5)
    ↓
Polyline([P1, P2, P3, P4, P5])
    ↓
Linha conectando os pontos com segmentos retos
```

**Não há nenhuma etapa de map matching ou snap-to-roads.** Os pontos GPS brutos contêm ruído (imprecisão de até 50m em condições ideais, mais em áreas urbanas densas) e não estão alinhados com a malha viária.

### 3.2 Problemas identificados

| # | Problema | Impacto | Arquivo |
|---|----------|---------|---------|
| 1 | **Sem snap-to-roads** | A linha atravessa quarteirões, parques, rios | `templates/admin/index.html:780`, `templates/portal/index.html:688` |
| 2 | **Sem roteamento entre origem e destino** | A linha tracejada azul é uma reta, não segue ruas | `templates/admin/index.html:767` |
| 3 | **Sem vínculo trilha ↔ ordem** | A trilha é do entregador, não da corrida específica | `app/api/admin.py:249`, `app/api/portal.py:621` |
| 4 | **Sem filtro de precisão GPS** | Pontos com precisão de 500m+ poluem a trilha | `app/api/pwa.py:346-358` |
| 5 | **Sem controle de frequência** | `watchPosition` dispara em frequência variável | `templates/index.html:785` |
| 6 | **GPS para em background** | PWA minimizado = sem rastreamento | `templates/index.html:785` (limitação do navegador) |
| 7 | **Limite de 200 posições** | Corridas longas perdem o início da trilha | `app/api/pwa.py:361-365` |
| 8 | **Sem distinção rota planejada vs trajeto realizado** | O sistema mistura os conceitos | N/A |

---

## 4. COMPARAÇÃO COM LEVA.AI

| Aspecto | REMO (atual) | LEVA.AI (observado) |
|---------|-------------|---------------------|
| Trajeto no mapa | Linha reta entre pontos GPS | Linha seguindo a malha viária |
| Snap-to-roads | ❌ Não | ✅ Sim (provável) |
| Roteamento | ❌ Não | ✅ Sim (provável) |
| Histórico GPS | ✅ Sim (200 pontos) | ✅ Sim (provável) |
| Map matching | ❌ Não | ✅ Sim (provável) |
| Rota planejada vs realizada | ❌ Misturados | ✅ Distintos (provável) |
| GPS em background | ❌ Não (PWA) | ✅ Sim (app nativo) |

---

## 5. PROPUESTA DE EVOLUÇÃO

### 5.1 Arquitetura proposta

```
APP DO ENTREGADOR (PWA)
    │
    │  GPS (watchPosition)
    │  → filtro de precisão (< 50m)
    │  → throttle (máx 1 envio a cada 3s)
    │  → envio só se movimentou > 10m
    │
    ↓
POST /api/pwa/localizacao
    { lat, lng, precisao, velocidade, heading, ordem_id }
    │
    ↓
REMO API
    │
    ├── UPDATE usuarios SET localizacao_atual = ...
    │
    └── INSERT INTO rastreamento
        (usuario_id, ordem_id, lat, lng, precisao, velocidade, heading)
    │
    ↓
HISTÓRICO GPS (vinculado à ordem)
    │
    ↓
MAP MATCHING / SNAP TO ROADS
    (OSRM ou Google Roads API)
    │
    ↓
TRAJETO REAL (pontos ajustados à via)
    │
    ↓
RENDERIZAÇÃO NO MAPA
    ├── Polyline do trajeto realizado (verde, seguindo ruas)
    ├── Marcador do entregador (posição atual)
    ├── Rota planejada (linha tracejada, opcional)
    └── Marcador de destino
```

### 5.2 Snap-to-Roads — opções de implementação

| Opção | API | Custo | Qualidade | Complexidade |
|-------|-----|-------|-----------|-------------|
| **A** | Google Roads API — Snap to Roads | $4 por 1000 snaps | Alta | Baixa |
| **B** | OSRM — map matching (self-hosted) | Grátis | Alta | Média (infra) |
| **C** | Valhalla — map matching (self-hosted) | Grátis | Alta | Média (infra) |
| **D** | GraphHopper — map matching (self-hosted) | Grátis | Alta | Média (infra) |
| **E** | Nominatim + OSRM público | Grátis (rate-limited) | Média | Baixa |

**Recomendação:** Começar com **OSRM self-hosted** (opção B) — é gratuito, open-source, e tem endpoint de map matching. Pode ser deployado no Railway como um serviço separado. Alternativamente, usar **Google Roads API** (opção A) se o orçamento permitir, pois é mais simples de integrar.

### 5.3 Roteamento (rota planejada)

Para a rota planejada (origem → destino seguindo ruas), usar:

| Opção | API | Custo |
|-------|-----|-------|
| **A** | OSRM — route | Grátis (self-hosted) |
| **B** | GraphHopper — route | Grátis (self-hosted) |
| **C** | Google Directions API | $5 por 1000 rotas |
| **D** | Mapbox Directions API | $1 por 1000 rotas |

**Recomendação:** OSRM (mesmo serviço do snap-to-roads) — um único deploy resolve ambos.

### 5.4 Melhorias no PWA (coleta de GPS)

```javascript
// Proposta de melhoria — templates/index.html
let ultimaEnvio = 0;
let ultimaPos = null;

gpsWatchId = navigator.geolocation.watchPosition(async pos => {
    const lat = pos.coords.latitude;
    const lng = pos.coords.longitude;
    const precisao = pos.coords.accuracy;
    const agora = Date.now();

    // Filtro 1: precisão mínima
    if (precisao > 50) return;  // ignora pontos imprecisos

    // Filtro 2: throttle — máx 1 envio a cada 3s
    if (agora - ultimaEnvio < 3000) return;

    // Filtro 3: só envia se movimentou > 10m
    if (ultimaPos) {
        const dist = haversine(ultimaPos, [lat, lng]);
        if (dist < 0.010) return;  // menos de 10m, ignora
    }

    ultimaEnvio = agora;
    ultimaPos = [lat, lng];

    await api('/localizacao', {
        method: 'POST',
        body: JSON.stringify({
            lat, lng, precisao,
            velocidade: pos.coords.speed,
            heading: pos.coords.heading,
            ordem_id: corridaAtualId,  // vincula à ordem
        }),
    });
}, ...);
```

### 5.5 Melhorias no schema

```sql
ALTER TABLE rastreamento
    ADD COLUMN ordem_id BIGINT REFERENCES ordens_servico(id),
    ADD COLUMN velocidade DOUBLE PRECISION,
    ADD COLUMN heading DOUBLE PRECISION,
    ADD COLUMN snapped_lat DOUBLE PRECISION,  -- coords após snap-to-roads
    ADD COLUMN snapped_lng DOUBLE PRECISION;

-- Índice para buscar trilha por ordem
CREATE INDEX IF NOT EXISTS idx_rastreamento_ordem ON rastreamento(ordem_id, criado_em DESC);
```

### 5.6 Distinção: rota planejada vs trajeto realizado

| Conceito | Cor no mapa | Estilo | Quando mostrar |
|----------|------------|--------|----------------|
| **Rota planejada** | Azul tracejado | `dashArray: '8,8'` | Quando ordem é ATRIBUIDA |
| **Trajeto realizado** | Verde sólido | `weight: 4` | Quando ordem é EM_ROTA, atualiza conforme GPS |
| **Entregador** | Azul (marcador) | Círculo com inicial | Sempre que tiver localização |
| **Destino** | Vermelho (marcador) | Pin | Sempre que tiver coords |
| **Origem** | Verde (marcador) | Casa | Sempre que tiver coords |

---

## 6. PRIORIZAÇÃO SUGERIDA

| Fase | Tarefa | Esforço | Impacto |
|------|--------|---------|---------|
| **1** | Filtro de precisão GPS + throttle + vínculo ordem_id | Baixo | Médio |
| **2** | Deploy OSRM no Railway + endpoint de snap-to-roads | Médio | Alto |
| **3** | Integrar snap-to-roads na renderização da trilha | Baixo | Alto |
| **4** | Rota planejada via OSRM (origem → destino) | Baixo | Médio |
| **5** | Aumentar limite de posições por corrida (200 → 1000) | Trivial | Baixo |
| **6** | Background GPS (PWA nativo ou app Android) | Alto | Alto |

---

## 7. CONCLUSÃO

O rastreamento atual do REMO tem a **coleta de dados correta** (GPS → backend → histórico → mapa), mas **falta a etapa de ajuste à malha viária**. A linha verde atual é uma `Polyline` conectando pontos GPS brutos, que naturalmente atravessa quarteirões.

Para chegar ao comportamento visual do LEVA.AI, é necessário adicionar **map matching (snap-to-roads)** entre o histórico GPS e a renderização no mapa. A solução mais custo-efetiva é deployar **OSRM** como serviço separado no Railway e chamar seu endpoint de map matching antes de retornar a trilha para o frontend.

A distinção entre **rota planejada** (calculada uma vez no início) e **trajeto realizado** (construído conforme o entregador se move) deve ser refletida visualmente com cores e estilos diferentes.
