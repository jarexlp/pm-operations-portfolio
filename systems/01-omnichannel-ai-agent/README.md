# Omnichannel AI Sales & Support Agent (`Caminos 1524` · Contabo VPS)

Production **FastAPI** orchestration backend deploying a multimodal **Gemini 2.5 Flash** prospect/support agent across **WhatsApp Business Cloud**, **Evolution API (dual WhatsApp instances)**, **Facebook Messenger**, **Chatwoot**, and **Google Sheets CRM**—hosted on a Contabo Linux VPS.

> All private API keys, webhook secrets, staff phone numbers, and server filepaths have been parameterized cleanly via environment variables (see [`../../.env.example`](../../.env.example)).

---

## System Architecture

```mermaid
flowchart LR
    subgraph CHANNELS["Customer Channels & Ad Traffic"]
        WA_CLOUD["WhatsApp Business Cloud\n(Meta Graph API v21.0)"]
        WA_EVO["WhatsApp Dual Instances\n(Evolution API)"]
        FB_MSG["Facebook Messenger / IG Ads\n(Meta Webhooks + Referrals)"]
    end

    subgraph VPS["Contabo VPS · FastAPI Backend (main.py)"]
        INGEST["Webhook Router\n(/webhook & /evolution)"]
        BRIDGE["Chatwoot Bridge\n(Contact/Conv Sync + Attachments)"]
        GUARD["Human Takeover Guard\n(is_echo / fromMe / Labels / History)"]
        AI["Gemini 2.5 Flash\n(Multimodal Audio/Image + Prompt Brain)"]
        AD_ATTR["Ad Context Resolver\n(ad_id -> anuncios.json)"]
    end

    subgraph OPS["CRM, Human Agents & Reporting"]
        CW["Chatwoot Shared Inbox\n(Live Dashboard & Macros)"]
        REP["Sales Advisor\n(Instant WhatsApp Alert on Handoff)"]
        SHEETS["Google Sheets CRM Webhook\n(Lead & Status Logging)"]
    end

    CHANNELS --> INGEST --> AD_ATTR --> BRIDGE --> GUARD
    BRIDGE <--> CW
    GUARD -->|"Human active"| CW
    GUARD -->|"AI handles"| AI
    AI -->|"[ASESOR] handoff token"| REP
    AI -->|"Direct reply + media"| CHANNELS
    INGEST --> SHEETS
    CW -->|"/chatwoot agent replies"| BRIDGE --> CHANNELS
```

---

## Key Engineering Highlights

1. **Zero-Collision Human Takeover Detection (`GUARD`):**
   - Automatically silences the AI bot whenever a human rep replies from **Chatwoot** (`humano_intervino`), **Meta Business Suite** (`is_echo` webhook detection outside bot hashes), or **mobile WhatsApp** (`fromMe`), preventing bot-vs-human double-messaging.
2. **Multimodal Customer Ingestion (Audio & Images):**
   - Downloads incoming voice notes (`audio/ogg`) and product screenshots (`image/jpeg`) directly from Meta Graph API v21.0 and passes them natively to Gemini via `types.Part.from_bytes`.
3. **Structured AI-to-Human Escalation (`[ASESOR]` Token):**
   - Prompted for consultative pre-qualification (never pushy): once buying intent, sizing confirmation, or payment questions appear, Gemini emits `[ASESOR]`, triggering:
     - Clean customer handoff message
     - Chatwoot label (`requiere_asesor`) + conversation sync
     - Real-time WhatsApp alert to the assigned advisor
     - Google Sheets lead classification sync
4. **Click-to-WhatsApp / Messenger Ad Attribution:**
   - Captures Meta `referral.source_id` / `externalAdReply` payloads, resolves ad names against `anuncios.json`, and injects exact campaign context into Gemini's hidden turn context.
5. **Modular Knowledge Brain & Agent Macros:**
   - Dynamically loads modular Markdown/text instructions (`01_personalidad.txt`, `02_catalogo.txt`, `03_inventario.txt`, `04_escenarios.txt`) so business operators can update catalog stock without redeploying Python code.
   - Paired with standardized Chatwoot closer macros ([`chatwoot_macros_guide.md`](./chatwoot_macros_guide.md)).

---

## Files

- [`main.py`](./main.py) — Sanitized production FastAPI application (webhooks, Chatwoot bridge, Meta/Evolution dispatchers, Gemini multimodal agent).
- [`chatwoot_macros_guide.md`](./chatwoot_macros_guide.md) — Standardized operational Chatwoot macros (Payment Closing, Delivery Logistics Form, Sizing Calibration, Inventory Urgency).
