# Javier Reyes Ruiz — AI Automations, System Integrations & Operations Engineering

[![Live Web Portfolio](https://img.shields.io/badge/Web_Portfolio-Live_View-10B981?style=for-the-badge)](https://jarexlp.github.io/pm-operations-portfolio/)
[![Zeller CRM Repo](https://img.shields.io/badge/GitHub-Zeller_E--Commerce_CRM-0EA5E9?style=for-the-badge)](https://github.com/jarexlp/zeller-crm)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Javier_Reyes_Ruiz-0A66C2?style=for-the-badge)](https://www.linkedin.com/in/javierreyesruiz)
[![English C2](https://img.shields.io/badge/English-C2_Fluent-38BDF8?style=for-the-badge)](#)

> **Engineering & Operations Profile:** Operations & Automation Builder with **12+ years of U.S.-aligned experience (2012–Present)** turning manual multi-department bottlenecks into production **AI agents, system integrations, cloud automations, and live BI reporting pipelines**. Backed by a **Magna Cum Laude Law Degree (LL.B.)**, **Google Data Analytics**, **DOMO BI**, and **Power BI Certified Developer** certifications.

---

## Verified Impact Across Production Systems

| System | Core Stack | Documented Outcome |
| :--- | :--- | :--- |
| **[01 · Omnichannel AI Sales & Support Agent](./systems/01-omnichannel-ai-agent/)** *(Caminos 1524 · Contabo VPS)* | Python, FastAPI, `google-genai` (Gemini 2.5), Chatwoot, Meta Graph API v21.0, Evolution API, Google Sheets | Multimodal WhatsApp / Messenger automation with ad attribution, voice/image parsing, and zero-collision human takeover detection |
| **[02 · Live Enterprise Compliance Hub & Copilot Agent](./systems/02-ilt-operations-hub-automation/)** *(Global BPO Partner LATAM)* | Python, SharePoint, Power Automate Cloud (`PA01–PA06`), Microsoft Graph Teams API, M365 Copilot Studio | **9–12 automated workflows** across **9,098 leaders in 10 countries** · **`1,314 hrs/yr` saved** (`11.4x` first-year ROI on `115` build hrs) |
| **[03 · Automated BI & Headless RPA Pipelines](./systems/03-bi-rpa-reporting-pipelines/)** *(DOMO / Workday / Power BI)* | Python, Playwright / Chromium, Pandas, Windows Scheduler, Power Query (`M`), DAX | Unattended extraction of `143k+` LMS rows & `31k+` HR records feeding a 4-view Star Schema · **`424 hrs/yr` saved** |
| **[04 · Distributed AI Job-Matching & Automation Worker](./systems/04-ai-job-matching-worker/)** | Next.js, Supabase Postgres (RLS), Docker, Python, Playwright, Gemini Pydantic Structured Outputs | Decoupled worker polling 8 API/ATS sources with multimodal resume evaluation & human-in-the-loop review gates |
| **[Zeller E-Commerce CRM](https://github.com/jarexlp/zeller-crm)** *(Separate Public Repo)* | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Supabase Auth & Postgres | Real-time inventory deduction, tiered commission calculation, logistics dispatch queue, and daily closeout receipts |

*(Combined verified savings across the Enterprise Hub + BI/RPA Reporting suite: **`1,738 hours/year`** reclaimed from repetitive manual workflows; consulting reporting automations cut weekly client prep by **`80%`**.)*

---

## Production Code Showcases (`./systems/`)

### 1. [Omnichannel AI Sales & Support Agent (`FastAPI + Gemini 2.5 + Chatwoot`)](./systems/01-omnichannel-ai-agent/)
Built and deployed on a **Contabo Linux VPS** for e-commerce operations (**Caminos 1524**):
- **Ingests:** Meta WhatsApp Cloud webhooks, dual WhatsApp instances via Evolution API, and Facebook Messenger / Click-to-Chat Ad referrals.
- **Multimodal Gemini Agent:** Processes customer text, voice notes (`audio/ogg`), and photos (`image/jpeg`) with a modular multi-file prompt brain (`personality`, `catalog`, `live inventory`, `scenarios`).
- **Human-in-the-Loop Safety:** Automatically pauses AI responses when an advisor replies from Chatwoot, Meta Business Suite (`is_echo`), or WhatsApp Web/Mobile (`fromMe`), and escalates warm leads via `[ASESOR]` with instant advisor WhatsApp alerts and Google Sheets CRM updates.

```
[WhatsApp / Messenger / Ads] ──▶ [FastAPI (/webhook, /evolution)] ──▶ [Human Override Check]
                                        │                                      │
                                        ▼ (Sync History & Labels)              ▼ (AI Active)
                                 [Chatwoot Inbox] ◀──── [Gemini 2.5 Multimodal + Sheets CRM]
```

### 2. [Enterprise Compliance Hub & M365 Copilot Control Tower](./systems/02-ilt-operations-hub-automation/)
Live compliance engine orchestrating **9–12 workflows** (identifying target leaders → tracking required COPC & internal certifications → delivering live team completion telemetry up to C-level operations leaders):
- **Master Python Sync ([`sync_operations_hub.py`](./systems/02-ilt-operations-hub-automation/sync_operations_hub.py)):** Purges exempt/terminated IDs, runs cascade stage unlocking (`SPO -> F1 -> F2 -> F3`), flags sessions at risk of under-enrollment (`RED <= 7d & <20`), and emits executive KPI workbooks.
- **Zero-Touch Cloud Attendance ([`teams_attendance_flow.json`](./systems/02-ilt-operations-hub-automation/teams_attendance_flow.json)):** Event-driven Logic Apps / Power Automate flow triggered on Teams call completion (`>= 75%` duration verification, `O365` ID resolution, automated `No-Show` reversal).
- **M365 Copilot Control Tower Agent:** `6,916`-character deterministic prompt governing Dual RBAC, Anti-Leak privacy guardrails, and `1–2s` lookup performance.

### 3. [Automated BI & Headless Playwright RPA Pipelines](./systems/03-bi-rpa-reporting-pipelines/)
Replaces slow manual portal exports and fragile VLOOKUP chains:
- **Headless Portal Extractor ([`domo_playwright_rpa.py`](./systems/03-bi-rpa-reporting-pipelines/domo_playwright_rpa.py)):** Persistent SSO context, automated date-control filtering (`All Time`), modal card verification before download, banner stripping, and chained Power BI build triggers.
- **Live Power Query Star Schema ([`power_query_star_schema.m`](./systems/03-bi-rpa-reporting-pipelines/power_query_star_schema.m)):** Direct SharePoint v2.0 connectors feeding Executive, Quorum Calendar, Risk Management, and Manager Backlog views.

### 4. [Distributed AI Job-Matching & Playwright Worker](./systems/04-ai-job-matching-worker/)
Decoupled SaaS architecture connecting a Next.js UI and **Supabase Postgres** queue with a Dockerized Playwright worker:
- **Structured Output AI Evaluator ([`matching_engine.py`](./systems/04-ai-job-matching-worker/matching_engine.py)):** Evaluates PDF resumes using `Pydantic`-enforced Gemini schemas, strict remote geo-filtering rules, and near-miss transparency.
- **Human-Approved Automation ([`supabase_schema_excerpt.sql`](./systems/04-ai-job-matching-worker/supabase_schema_excerpt.sql)):** Tiered ToS-compliant source catalog + `ready_for_review -> confirm_application() -> submitting` optimistic locking with screenshot evidence.

---

## Privacy & Sanitization Standards

- All enterprise client identifiers, tenant SharePoint/DOMO URLs, internal email addresses, advisor phone numbers, and API credentials are anonymized or injected strictly via environment variables (see [`.env.example`](./.env.example)).
- Companion repository: **[`jarexlp/zeller-crm`](https://github.com/jarexlp/zeller-crm)** (Next.js 16 + Supabase e-commerce CRM) · **[Interactive Web Portfolio](https://jarexlp.github.io/pm-operations-portfolio/)** · **[Executive Case Study PDF](./Portfolio_Executive_Deck_Javier_Reyes.pdf)**
