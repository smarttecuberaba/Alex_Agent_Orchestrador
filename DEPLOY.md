# Deploy — Agente 2W Pneus na VPS Hostinger + Coolify

Interface WhatsApp: **Chatwoot** (https://chatwoot.smarttecsolutions.com.br) via conector **Baileys**

## Estrutura de arquivos

```
/
├── Dockerfile              # Imagem de producao (Python 3.11-slim)
├── docker-compose.yml      # Lido pelo Coolify
├── requirements.txt        # Dependencias Python
├── .env.example            # Template de variaveis de ambiente
├── agente_2w/              # Codigo do agente (copiar do projeto local)
├── api/
│   ├── server.py           # FastAPI + webhook Chatwoot
│   ├── chatwoot.py         # Envia respostas via API do Chatwoot
│   └── sessao_manager.py   # Gerencia sessoes por numero de telefone
└── scripts/
    ├── start.sh            # Entrypoint com validacao de vars
    └── healthcheck.sh      # Health check do Docker
```

---

## Fluxo completo de uma mensagem

```
Cliente WhatsApp
    │
    ▼  (envia mensagem)
Baileys (conector no Chatwoot)
    │
    ▼  (cria/atualiza conversa)
Chatwoot  https://chatwoot.smarttecsolutions.com.br
    │
    ▼  POST /webhook?secret=XXX  (event: message_created)
FastAPI  api/server.py
    │  filtra: message_type=incoming, content_type=text
    │  extrai: telefone, conversation_id, texto
    │  dispara background_task
    │
    ▼  (background)
sessao_manager.py
    │  busca sessao ativa pelo telefone ou cria nova
    │
    ▼
agente_2w/engine/orquestrador.processar_turno()
    │  chama OpenAI GPT-4o
    │  salva contexto no Supabase
    │  retorna mensagem em linguagem natural
    │
    ▼
api/chatwoot.py
    │  POST /api/v1/accounts/{id}/conversations/{id}/messages
    │
    ▼
Chatwoot → Baileys → Cliente WhatsApp
```

---

## Passos para deploy

### 1. Preparar o repositorio Git

O Coolify faz deploy a partir de um repositorio (GitHub, GitLab ou Gitea).

```
repo/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── agente_2w/          ← copiar do projeto local
└── api/
    ├── __init__.py
    ├── server.py
    ├── chatwoot.py
    └── sessao_manager.py
```

Commit e push para o repositorio privado.

### 2. Configurar o Coolify

1. Acesse o painel Coolify da VPS Hostinger
2. **New Resource → Application → Docker Compose**
3. Conecte o repositorio GitHub
4. Branch: `main` | Build Path: `/` | Docker Compose File: `docker-compose.yml`

### 3. Variaveis de ambiente no Coolify

Em **Environment Variables**, adicione:

| Variavel | Valor |
|---|---|
| `SUPABASE_URL` | `https://vyxdquwxmgibpkoswxut.supabase.co` |
| `SUPABASE_KEY` | service_role key do Supabase (nao a anon key) |
| `OPENAI_API_KEY` | sua chave OpenAI |
| `OPENAI_MODEL` | `gpt-4o` |
| `CHATWOOT_URL` | `https://chatwoot.smarttecsolutions.com.br` |
| `CHATWOOT_API_TOKEN` | API Access Token do Chatwoot (ver abaixo) |
| `CHATWOOT_ACCOUNT_ID` | ID da conta no Chatwoot (normalmente `1`) |
| `WEBHOOK_SECRET` | string aleatoria longa (ex: `openssl rand -hex 32`) |
| `LOG_LEVEL` | `info` |

### 4. Dominio e HTTPS no Coolify

1. Em **Domains**, adicione o subdominio (ex: `agente.2wpneus.com.br`)
2. Coolify provisiona SSL via Let's Encrypt automaticamente
3. Porta exposta: `8000` — Coolify faz o proxy

### 5. Obter o API Access Token do Chatwoot

1. Acesse https://chatwoot.smarttecsolutions.com.br
2. Perfil (canto inferior esquerdo) → **Profile Settings**
3. Seção **Access Token** → copie o token
4. Cole em `CHATWOOT_API_TOKEN` no Coolify

> Use o token de um usuario **Agente** ou crie um usuario dedicado para o bot.

### 6. Descobrir o CHATWOOT_ACCOUNT_ID

Na URL do Chatwoot ao estar logado:
```
https://chatwoot.smarttecsolutions.com.br/app/accounts/1/...
                                                        ^
                                                   account_id
```

### 7. Configurar o Webhook no Chatwoot

1. Acesse: **Settings → Integrations → Webhooks → Add new webhook**
2. URL:
   ```
   https://agente.2wpneus.com.br/webhook?secret=SEU_WEBHOOK_SECRET
   ```
3. Marque apenas o evento: **Message Created**
4. Salve

> O `?secret=` na URL e a forma de validacao. O Chatwoot nao suporta headers customizados no webhook nativamente.

---

## Comandos uteis pos-deploy

```bash
# Ver logs em tempo real (no servidor via SSH)
docker logs -f agente-2w

# Verificar saude
curl https://agente.2wpneus.com.br/health

# Testar webhook manualmente (simula mensagem do cliente)
curl -X POST "https://agente.2wpneus.com.br/webhook?secret=SEU_SEGREDO" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "id": 1,
    "content": "oi, preciso de um pneu",
    "message_type": "incoming",
    "content_type": "text",
    "conversation": {
      "id": 123,
      "meta": {
        "sender": {
          "name": "Teste",
          "phone_number": "+5521999999999"
        }
      }
    },
    "account": {"id": 1}
  }'
```

---

## Troubleshooting

| Problema | Causa provavel | Solucao |
|---|---|---|
| Webhook retorna 401 | `WEBHOOK_SECRET` errado na URL | Verificar o valor em `?secret=` |
| Mensagem nao chega no WhatsApp | `CHATWOOT_API_TOKEN` invalido ou expirado | Gerar novo token no perfil |
| `sem_telefone` nos logs | Baileys nao preencheu `phone_number` | Verificar se o conector Baileys esta ativo |
| Agente nao responde | Erro no OpenAI ou Supabase | Checar logs: `docker logs agente-2w` |
| `conversation_id` ausente | Evento nao e `message_created` | Normal — ignorado automaticamente |

---

## Observacoes

- **SUPABASE_KEY**: use a `service_role` key — o agente precisa de acesso total ao banco
- **Sessoes**: cada numero de telefone tem uma sessao ativa. Quando a sessao fecha (pedido confirmado), a proxima mensagem inicia uma nova conversa
- **Mensagens de audio/imagem**: ignoradas por ora — o agente processa apenas texto
- **Grupos WhatsApp**: ignorados automaticamente (Chatwoot filtra no conector Baileys)
