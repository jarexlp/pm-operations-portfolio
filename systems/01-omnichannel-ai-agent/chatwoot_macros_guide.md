# Standardized Chatwoot Closing & Triage Macros (E-Commerce Operations)

Configured inside Chatwoot (`Settings -> Macros`) so human sales reps respond in one click after the Gemini AI agent hands off qualified leads (`[ASESOR]`).

---

## 1. Payment Deposit Closing (`Cierre - Datos de Pago`)
- **Automated Actions:**
  1. Send standardized deposit message
  2. Add label: `Venta_Cerrada`
  3. Set conversation status: `Resolved`
- **Outcome:** Synchronizes automatically via `/chatwoot` `conversation_updated` webhook to log closed revenue in Google Sheets CRM.

## 2. Delivery & Dispatch Intake (`Logistica - Datos de Envío`)
- **Automated Action:** Prompts customer for exact address, landmark reference, backup mobile number, and recipient name to pass cleanly into `Zeller CRM` (`/logistica`).

## 3. Sizing & Fit Calibration (`Fricción - Tallas y CM`)
- **Automated Action:** Resolves sizing uncertainty (centimeter-to-EU/US mapping) before dispatch to minimize exchanges and return shipping losses.

## 4. Scarcity / Inventory Follow-Up (`Seguimiento - Urgencia Inventario`)
- **Automated Action:** Structured follow-up prompt for stalled warm leads before inventory allocation shifts.
