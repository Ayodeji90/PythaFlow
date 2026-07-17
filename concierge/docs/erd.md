# Concierge — Entity-Relationship Diagram (Day 2)

`Tenant` is the root of isolation; **every other table carries `tenant_id`**
(omitted from the diagram bodies for readability — it's on all of them except
`tenants`). Enums are stored as VARCHAR + CHECK; primary keys are UUIDs.

```mermaid
erDiagram
    TENANT ||--o{ USER : "employs"
    TENANT ||--o{ CHANNEL : "owns"
    TENANT ||--o{ GUEST : "serves"
    TENANT ||--o{ CONVERSATION : "scopes"
    TENANT ||--o{ RESERVATION : "scopes"
    TENANT ||--o{ KNOWLEDGE_CHUNK : "scopes"

    GUEST ||--o{ CONVERSATION : "talks in"
    CHANNEL ||--o{ CONVERSATION : "carries"
    CONVERSATION ||--o{ MESSAGE : "contains"
    CONVERSATION ||--o{ RESERVATION : "produces"
    CONVERSATION ||--o{ ACTION : "logs"

    ACTION ||--o| APPROVAL : "gated by"
    RESERVATION ||--o| APPROVAL : "gated by"
    USER ||--o{ APPROVAL : "decides"

    TENANT {
        uuid id PK
        string slug UK
        string name
        text brand_voice
        jsonb languages
        string timezone
        jsonb hours
        jsonb config
    }
    USER {
        uuid id PK
        string email
        string name
        enum role "owner|manager|staff"
        string auth_ref
    }
    CHANNEL {
        uuid id PK
        enum type "webchat|whatsapp|sms|voice|instagram|email"
        string external_id
        jsonb config
        bool active
    }
    GUEST {
        uuid id PK
        string display_name
        string phone
        jsonb handles
        jsonb preferences
        jsonb consent
        datetime last_seen_at
    }
    CONVERSATION {
        uuid id PK
        uuid guest_id FK
        uuid channel_id FK
        enum channel_type
        string external_thread_id
        string language
        enum status "active|human|closed"
        jsonb state
    }
    MESSAGE {
        uuid id PK
        uuid conversation_id FK
        enum role "guest|assistant|staff|system|tool"
        text content
        string content_type
        jsonb meta
    }
    RESERVATION {
        uuid id PK
        uuid guest_id FK
        uuid conversation_id FK
        int party_size
        date date
        time time
        string area
        text notes
        enum status "pending|approved|confirmed|cancelled|rejected"
        enum source_channel
        string external_ref
        string idempotency_key "UNIQUE per tenant"
    }
    ACTION {
        uuid id PK
        uuid conversation_id FK
        string type "tool name"
        jsonb input
        jsonb output
        enum status "proposed|executed|failed"
    }
    APPROVAL {
        uuid id PK
        uuid action_id FK
        uuid reservation_id FK
        enum status "pending|approved|rejected"
        uuid decided_by FK
        datetime decided_at
    }
    KNOWLEDGE_CHUNK {
        uuid id PK
        string source
        string title
        text content
        vector embedding "1024-dim, HNSW cosine index"
        jsonb meta
    }
```
