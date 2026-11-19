"""
Omnichannel AI Sales & Support Agent (FastAPI + Gemini + Chatwoot + Meta / Evolution API)

Deployed on a Contabo Linux VPS to handle inbound customer inquiries across:
- WhatsApp Business Cloud API (Meta Graph v21.0)
- Dual WhatsApp instances via Evolution API
- Facebook Messenger & Click-to-Chat Ad referrals
- Chatwoot shared inbox synchronization & human-in-the-loop escalation
- Google Sheets lead attribution & stage logging

Sanitized portfolio edition: all credentials, webhook secrets, filepaths, and
advisor phone numbers are loaded from environment variables.
"""

import base64
import json
import os
import subprocess
from datetime import datetime

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from google import genai
from google.genai import types

load_dotenv()
app = FastAPI(title="Omnichannel AI Sales & Support Agent")

# --- Environment Configuration ---
CW_URL = os.getenv("CHATWOOT_URL", "").rstrip("/")
CW_KEY = os.getenv("CHATWOOT_API_KEY", "")
CW_ACC = os.getenv("CHATWOOT_ACCOUNT_ID", "1")
CW_INBOX = os.getenv("CHATWOOT_INBOX_ID", "1")

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")
SHEETS_WEBHOOK = os.getenv("SHEETS_WEBHOOK_URL", "")
PAGE_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "")
WA_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")

EVO_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080").rstrip("/")
EVO_KEY = os.getenv("EVOLUTION_API_KEY", "")
PROMPTS_DIR = os.getenv("PROMPTS_DIR", "./prompts")
ADS_CATALOG_PATH = os.getenv("ADS_CATALOG_PATH", "./anuncios.json")
EXPORT_REPORT_PATH = os.getenv("EXPORT_REPORT_PATH", "./entrenamiento_ventas.txt")
EXPORT_EXTRACTOR_SCRIPT = os.getenv("EXPORT_EXTRACTOR_SCRIPT", "./extraer_datos.py")

# Dual-instance routing loaded from JSON env config (no hardcoded phone numbers)
# Example: {"store_a": {"rep_name": "Advisor A", "inbox_id": 6, "alert_phone": ""}}
try:
    CONFIG_WHATSAPP: dict = json.loads(os.getenv("WHATSAPP_INSTANCES_JSON", "{}") or "{}")
except json.JSONDecodeError:
    CONFIG_WHATSAPP = {}

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

mensajes_procesados: dict[str, bool] = {}
clientes_silenciados: dict[str, bool] = {}
mensajes_enviados_bot: dict[int, datetime] = {}


def log_debug(msg: str) -> None:
    print(f"DEBUG: {msg}", flush=True)


def cargar_anuncios() -> dict:
    """Load Click-to-Chat ad_id -> campaign name lookup map."""
    try:
        with open(ADS_CATALOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log_debug(f"Could not read ads catalog ({ADS_CATALOG_PATH}): {exc}")
        return {}


def cargar_cerebro() -> str:
    """Assemble modular prompt files (persona, catalog, live inventory, scenarios)."""
    archivos = [
        "01_personalidad.txt",
        "02_catalogo.txt",
        "03_inventario.txt",
        "04_escenarios.txt",
    ]
    cerebro_completo = ""
    for archivo in archivos:
        try:
            with open(os.path.join(PROMPTS_DIR, archivo), "r", encoding="utf-8") as f:
                cerebro_completo += f.read() + "\n\n"
        except Exception as exc:
            log_debug(f"Error loading prompt module {archivo}: {exc}")
    return cerebro_completo


def obtener_historial_chatwoot(conv_id: int | str) -> tuple[str, bool]:
    """Fetch recent conversation turns and detect if a human agent already replied."""
    if not CW_URL or not CW_KEY:
        return "", False
    headers = {"api-access-token": CW_KEY}
    url = f"{CW_URL}/api/v1/accounts/{CW_ACC}/conversations/{conv_id}/messages"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            mensajes = res.json().get("payload", [])
            historial = []
            humano_intervino = False
            for m in mensajes:
                if m.get("private"):
                    continue
                msg_type = m.get("message_type")
                if msg_type in [1, "outgoing"] and not m.get("content_attributes", {}).get("bot_reply"):
                    humano_intervino = True
            for m in mensajes[-6:]:
                if m.get("private"):
                    continue
                msg_type = m.get("message_type")
                rol = "Asistente" if msg_type in [1, "outgoing"] else "Cliente"
                contenido = m.get("content", "")
                if contenido:
                    historial.append(f"{rol}: {contenido}")
            return "\n".join(historial), humano_intervino
    except Exception:
        pass
    return "", False


def descargar_media_wa(media_id: str) -> bytes | None:
    """Download incoming image or voice note bytes from WhatsApp Cloud API."""
    if not WA_TOKEN:
        return None
    url_info = f"https://graph.facebook.com/v21.0/{media_id}"
    headers = {"Authorization": f"Bearer {WA_TOKEN}"}
    try:
        res_info = requests.get(url_info, headers=headers, timeout=5)
        if res_info.status_code == 200:
            media_url = res_info.json().get("url")
            res_media = requests.get(media_url, headers=headers, timeout=10)
            if res_media.status_code == 200:
                return res_media.content
    except Exception:
        pass
    return None


def obtener_nombre_messenger(sender_id: str) -> str | None:
    """Resolve display name from Meta Graph API for Messenger leads."""
    if not PAGE_TOKEN:
        log_debug("PAGE_ACCESS_TOKEN not configured.")
        return None
    try:
        url = f"https://graph.facebook.com/v21.0/{sender_id}?fields=first_name,last_name&access_token={PAGE_TOKEN}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            nombre = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            return nombre or None
    except Exception:
        pass
    return None


def registrar_lead_sheets(
    telefono: str,
    nombre: str | None = None,
    mensaje: str | None = None,
    ad_info: str | None = None,
    estado: str | None = None,
    agente: str | None = None,
    clasificacion: str | None = None,
) -> None:
    """Push new lead & lifecycle updates to Google Sheets webhook."""
    if not SHEETS_WEBHOOK:
        return
    data = {"telefono": telefono, "fecha": str(datetime.now())}
    if nombre:
        data["nombre"] = nombre
    if mensaje:
        data["mensaje"] = mensaje
    if ad_info:
        data["anuncio"] = ad_info
    if estado:
        data["estado"] = estado
    if agente:
        data["agente"] = agente
    if clasificacion:
        data["clasificacion"] = clasificacion
    try:
        requests.post(SHEETS_WEBHOOK, json=data, timeout=5)
    except Exception:
        pass


def enviar_mensaje_cliente(
    sender_id: str,
    texto: str,
    plataforma: str,
    url_adjunto: str | None = None,
    instancia: str | None = None,
) -> None:
    """Dispatch text or image replies across Evolution API, Meta WA Cloud, or Messenger."""
    log_debug(f"Dispatching message to {sender_id} via {plataforma} (attachment={url_adjunto is not None})")
    if len(mensajes_enviados_bot) > 1000:
        mensajes_enviados_bot.clear()
    if texto:
        mensajes_enviados_bot[hash(texto)] = datetime.now()

    try:
        media_bytes = None
        if url_adjunto:
            try:
                if url_adjunto.startswith("/") and CW_URL:
                    url_adjunto = f"{CW_URL}{url_adjunto}"
                r_img = requests.get(url_adjunto, headers={"api-access-token": CW_KEY}, timeout=15)
                if r_img.status_code == 200:
                    media_bytes = r_img.content
            except Exception as exc:
                log_debug(f"Failed downloading Chatwoot attachment: {exc}")

        # --- Route 1: WhatsApp via Evolution API ---
        if plataforma == "whatsapp" and instancia in CONFIG_WHATSAPP:
            headers_evo = {"apikey": EVO_KEY, "Content-Type": "application/json"}
            destino = str(sender_id)
            # Reconstruct @lid domain required for Meta Click-to-WhatsApp Ad leads
            if len(destino) >= 14 and "@" not in destino:
                destino = f"{destino}@lid"

            if media_bytes:
                b64 = base64.b64encode(media_bytes).decode("utf-8")
                payload = {
                    "number": destino,
                    "options": {"checkNumber": False},
                    "mediaMessage": {
                        "mediatype": "image",
                        "caption": str(texto) if texto else "",
                        "media": f"data:image/jpeg;base64,{b64}",
                    },
                }
                requests.post(f"{EVO_URL}/message/sendMedia/{instancia}", json=payload, headers=headers_evo, timeout=10)
            elif texto:
                payload = {
                    "number": destino,
                    "options": {"checkNumber": False},
                    "textMessage": {"text": str(texto)},
                }
                requests.post(f"{EVO_URL}/message/sendText/{instancia}", json=payload, headers=headers_evo, timeout=10)

        # --- Route 2: Meta WhatsApp Cloud API ---
        elif plataforma == "whatsapp":
            if not WA_PHONE_ID or not WA_TOKEN:
                return
            url = f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages"
            media_id = None
            if media_bytes:
                url_up = f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/media"
                res_up = requests.post(
                    url_up,
                    headers={"Authorization": f"Bearer {WA_TOKEN}"},
                    data={"messaging_product": "whatsapp", "type": "image/jpeg"},
                    files={"file": ("foto.jpg", media_bytes, "image/jpeg")},
                    timeout=15,
                )
                if res_up.status_code == 200:
                    media_id = res_up.json().get("id")

            headers_json = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
            if media_id:
                payload = {"messaging_product": "whatsapp", "to": sender_id, "type": "image", "image": {"id": media_id}}
                if texto:
                    payload["image"]["caption"] = str(texto)
                requests.post(url, json=payload, headers=headers_json, timeout=10)
            elif texto:
                payload = {"messaging_product": "whatsapp", "to": sender_id, "type": "text", "text": {"body": str(texto)}}
                requests.post(url, json=payload, headers=headers_json, timeout=10)

        # --- Route 3: Facebook Messenger ---
        elif plataforma in ["messenger", "page"]:
            if not PAGE_TOKEN:
                return
            url = f"https://graph.facebook.com/v21.0/me/messages?access_token={PAGE_TOKEN}"
            if media_bytes:
                data = {
                    "recipient": json.dumps({"id": sender_id}),
                    "message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}}),
                }
                requests.post(url, data=data, files={"filedata": ("foto.jpg", media_bytes, "image/jpeg")}, timeout=15)
                if texto:
                    requests.post(url, json={"recipient": {"id": sender_id}, "message": {"text": str(texto)}}, timeout=10)
            elif texto:
                requests.post(url, json={"recipient": {"id": sender_id}, "message": {"text": str(texto)}}, timeout=10)

    except Exception as exc:
        log_debug(f"Dispatch error: {exc}")


def puente_chatwoot(
    sender_id: str,
    texto: str,
    plataforma: str,
    wa_name: str | None = None,
    media_bytes: bytes | None = None,
    mime_type: str | None = None,
    instancia: str | None = None,
) -> tuple[int | None, bool, bool]:
    """Upsert Contact + Open Conversation in Chatwoot and log inbound message."""
    if not CW_URL or not CW_KEY:
        return None, False, False

    target_inbox = CW_INBOX
    if plataforma == "whatsapp" and instancia in CONFIG_WHATSAPP:
        target_inbox = CONFIG_WHATSAPP[instancia]["inbox_id"]

    headers = {"api-access-token": CW_KEY, "Content-Type": "application/json"}
    base_url = f"{CW_URL}/api/v1/accounts/{CW_ACC}"
    try:
        id_unico = f"cw_{plataforma}_{sender_id}"
        contact_id = None
        search_res = requests.get(f"{base_url}/contacts/search?q={id_unico}", headers=headers, timeout=5)
        search_data = search_res.json()

        if search_data.get("payload"):
            contact_info = search_data["payload"][0]
            contact_id = contact_info["id"]
            nombre_actual = contact_info.get("name", "")
            if wa_name and wa_name.strip() and (nombre_actual.startswith("Cliente") or not nombre_actual or nombre_actual != wa_name):
                requests.put(f"{base_url}/contacts/{contact_id}", json={"name": wa_name}, headers=headers, timeout=5)

        if not contact_id:
            nombre_final = wa_name or f"Cliente {plataforma.capitalize()} {sender_id[-4:]}"
            contact_data = {"name": nombre_final, "identifier": id_unico}
            if plataforma == "whatsapp":
                contact_data["phone_number"] = f"+{sender_id}"
            c_res = requests.post(f"{base_url}/contacts", json=contact_data, headers=headers, timeout=5)
            if c_res.status_code < 400:
                contact_id = c_res.json().get("payload", {}).get("contact", {}).get("id") or c_res.json().get("id")

        if not contact_id:
            return None, False, False

        conv_id = None
        asignado_a_humano = False
        convs_res = requests.get(f"{base_url}/contacts/{contact_id}/conversations", headers=headers, timeout=5)
        if convs_res.status_code == 200:
            for c in convs_res.json().get("payload", []):
                if str(c.get("inbox_id")) == str(target_inbox) and c.get("status") == "open":
                    conv_id = c["id"]
                    if "requiere_asesor" in c.get("labels", []):
                        asignado_a_humano = True
                    break

        es_nueva = False
        if not conv_id:
            conv_data = {"source_id": id_unico, "inbox_id": target_inbox, "contact_id": contact_id}
            new_conv_res = requests.post(f"{base_url}/conversations", json=conv_data, headers=headers, timeout=5)
            if new_conv_res.status_code < 400:
                conv_id = new_conv_res.json().get("id")
                es_nueva = True

        if conv_id:
            if media_bytes:
                ext = "archivo.jpg" if "image" in (mime_type or "") else "audio.ogg"
                files = {"attachments[]": (ext, media_bytes, mime_type or "image/jpeg")}
                texto_seguro = texto.strip() if (texto and texto.strip()) else "[Media attachment]"
                requests.post(
                    f"{base_url}/conversations/{conv_id}/messages",
                    data={"content": texto_seguro, "message_type": "incoming"},
                    files=files,
                    headers={"api-access-token": CW_KEY},
                    timeout=10,
                )
            else:
                texto_seguro = texto.strip() if (texto and texto.strip()) else "[Unsupported message]"
                requests.post(
                    f"{base_url}/conversations/{conv_id}/messages",
                    json={"content": texto_seguro, "message_type": "incoming"},
                    headers=headers,
                    timeout=5,
                )
            return conv_id, es_nueva, asignado_a_humano
    except Exception:
        pass
    return None, False, False


def asignar_a_humano(conv_id: int | str, agente_id: int | None = None) -> None:
    """Tag conversation with requiere_asesor and optionally assign an advisor."""
    if not CW_URL or not CW_KEY:
        return
    headers = {"api-access-token": CW_KEY, "Content-Type": "application/json"}
    base_url = f"{CW_URL}/api/v1/accounts/{CW_ACC}"
    requests.post(f"{base_url}/conversations/{conv_id}/labels", json={"labels": ["requiere_asesor"]}, headers=headers, timeout=5)
    if agente_id:
        try:
            requests.post(f"{base_url}/conversations/{conv_id}/assignments", json={"assignee_id": agente_id}, headers=headers, timeout=5)
        except Exception as exc:
            log_debug(f"Agent assignment failed: {exc}")


async def procesar_mensaje(
    sender_id: str,
    texto: str,
    plataforma: str,
    mid: str,
    wa_name: str | None = None,
    ad_title: str | None = None,
    media_id: str | None = None,
    tipo_media: str = "text",
    media_url: str | None = None,
    ad_id: str | None = None,
    instancia: str | None = None,
) -> None:
    """Process inbound event, sync Chatwoot, check human override, invoke Gemini & dispatch."""
    if mid in mensajes_procesados:
        return
    if len(mensajes_procesados) > 1000:
        mensajes_procesados.clear()
    mensajes_procesados[mid] = True

    if plataforma in ["messenger", "page"] and not wa_name:
        wa_name = obtener_nombre_messenger(sender_id)

    media_bytes, mime = None, None
    if plataforma == "whatsapp" and media_id:
        media_bytes = descargar_media_wa(media_id)
        if media_bytes:
            mime = "audio/ogg" if tipo_media == "audio" else "image/jpeg"
    elif plataforma in ["messenger", "page"] and media_url:
        try:
            r_media = requests.get(media_url, timeout=10)
            if r_media.status_code == 200:
                media_bytes = r_media.content
                mime = "image/jpeg" if tipo_media == "image" else "audio/ogg"
        except Exception as exc:
            log_debug(f"Failed downloading Messenger attachment: {exc}")

    conv_id, es_nueva, asignado_a_humano = puente_chatwoot(sender_id, texto, plataforma, wa_name, media_bytes, mime, instancia)

    if es_nueva:
        registrar_lead_sheets(sender_id, wa_name, texto, ad_title, estado="Nuevo")

    if not client:
        log_debug("GEMINI_API_KEY not configured; logged message to Chatwoot only.")
        return

    try:
        instrucciones_dinamicas = cargar_cerebro()
        hora_actual = datetime.now().strftime("%I:%M %p")

        historial_chat = ""
        if conv_id:
            historial_chat, intervenido_por_humano = obtener_historial_chatwoot(conv_id)
            if intervenido_por_humano or asignado_a_humano:
                log_debug(f"Human agent active in conversation {conv_id}; AI bot muted.")
                return

        config = CONFIG_WHATSAPP.get(instancia, {"rep_name": "Sales Team"})
        nombre_vendedora = config.get("rep_name", "Sales Team")

        contexto_oculto = (
            f"[SYSTEM: Customer: {wa_name or 'Unknown'}. Current time: {hora_actual}. "
            f"ROLE: Consultative sales assistant supporting {nombre_vendedora}. "
            "Share catalog and sizing details cleanly without pushy closing. "
            "RULE: As soon as the customer shows buying intent, requests payment details, "
            "or wants to reserve/think it over, end your reply with [ASESOR] to trigger human handoff. "
        )
        if ad_title:
            contexto_oculto += f"Came from Ad Campaign: '{ad_title}'. "
        contexto_oculto += f"Use chat history so greetings are never repeated.]\n\n=== HISTORY ===\n{historial_chat}\n\n"

        contenidos_gemini = [contexto_oculto + "Respond to the latest customer message."]
        if media_bytes:
            contenidos_gemini.append(types.Part.from_bytes(data=media_bytes, mime_type=mime))

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contenidos_gemini,
            config={"system_instruction": instrucciones_dinamicas},
        )
        respuesta_ia = response.text or ""

        if "[ASESOR]" in respuesta_ia:
            texto_gemini = respuesta_ia.split("[ASESOR]")[0].strip()
            mensaje_transferencia = f"Perfect! Give me a moment—I'm connecting you with {nombre_vendedora} to finalize the details."
            respuesta_ia = f"{texto_gemini}\n\n{mensaje_transferencia}" if texto_gemini else mensaje_transferencia

            if conv_id:
                requests.post(
                    f"{CW_URL}/api/v1/accounts/{CW_ACC}/conversations/{conv_id}/messages",
                    json={"content": respuesta_ia, "message_type": "outgoing", "content_attributes": {"bot_reply": True}},
                    headers={"api-access-token": CW_KEY, "Content-Type": "application/json"},
                    timeout=5,
                )
            enviar_mensaje_cliente(sender_id, respuesta_ia, plataforma, instancia=instancia)

            if conv_id:
                asignar_a_humano(conv_id)
                registrar_lead_sheets(sender_id, wa_name, texto, ad_title, estado="Transferido a Humano")
                alert_phone = config.get("alert_phone")
                if instancia and alert_phone and EVO_KEY:
                    payload_alerta = {
                        "number": alert_phone,
                        "options": {"checkNumber": False},
                        "textMessage": {"text": f"*QUALIFIED LEAD ({nombre_vendedora})*\n\nCustomer: +{sender_id}\nOpen Chatwoot to close."},
                    }
                    requests.post(
                        f"{EVO_URL}/message/sendText/{instancia}",
                        json=payload_alerta,
                        headers={"apikey": EVO_KEY, "Content-Type": "application/json"},
                        timeout=5,
                    )
        else:
            if conv_id:
                requests.post(
                    f"{CW_URL}/api/v1/accounts/{CW_ACC}/conversations/{conv_id}/messages",
                    json={"content": respuesta_ia, "message_type": "outgoing", "content_attributes": {"bot_reply": True}},
                    headers={"api-access-token": CW_KEY, "Content-Type": "application/json"},
                    timeout=5,
                )
            enviar_mensaje_cliente(sender_id, respuesta_ia, plataforma, instancia=instancia)

    except Exception as exc:
        log_debug(f"Gemini processing error: {exc}")


@app.post("/evolution")
async def recibir_evolution(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive dual-WhatsApp Evolution API events & ignore self-sent/group messages."""
    payload = await request.json()
    instancia = payload.get("instance")
    if not instancia or payload.get("event") != "messages.upsert":
        return {"status": "ok"}

    data = payload.get("data", {})
    key = data.get("key", {})
    remote_jid = key.get("remoteJid", "")
    sender_id = remote_jid.split("@")[0]

    if "status@broadcast" in remote_jid or "g.us" in remote_jid:
        return {"status": "ok"}

    msg = data.get("message", {})
    texto = msg.get("conversation") or msg.get("extendedTextMessage", {}).get("text") or ""

    ad_id = None
    referral = msg.get("extendedTextMessage", {}).get("contextInfo", {}).get("externalAdReply", {})
    if referral:
        ad_id = referral.get("sourceId") or referral.get("sourceUrl", "").split("/")[-1]

    if key.get("fromMe"):
        clientes_silenciados[f"{instancia}_{sender_id}"] = True
        return {"status": "ok"}

    if f"{instancia}_{sender_id}" not in clientes_silenciados:
        background_tasks.add_task(
            procesar_mensaje,
            sender_id=sender_id,
            texto=texto,
            plataforma="whatsapp",
            mid=key.get("id", ""),
            wa_name=data.get("pushName"),
            ad_id=ad_id,
            instancia=instancia,
        )
    return {"status": "ok"}


@app.post("/webhook")
async def recibir_meta(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive Meta Graph API webhooks for WhatsApp Cloud & Facebook Messenger."""
    payload = await request.json()
    plataforma_base = payload.get("object")
    biblioteca_anuncios = cargar_anuncios()

    if plataforma_base == "whatsapp_business_account":
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                wa_name = value.get("contacts", [{}])[0].get("profile", {}).get("name") if "contacts" in value else None
                for msg in value.get("messages", []):
                    sender_id, mid, msg_type = msg.get("from"), msg.get("id"), msg.get("type")
                    ad_title, ad_id = None, None
                    referral = msg.get("referral", {})
                    if referral:
                        source_id = str(referral.get("source_id", ""))
                        if source_id:
                            ad_id = source_id
                        if source_id in biblioteca_anuncios:
                            ad_title = biblioteca_anuncios[source_id]
                        else:
                            headline = referral.get("headline") or ""
                            body = referral.get("body") or ""
                            ad_title = f"{headline} {body}".strip() or (f"Ad ID: {source_id}" if source_id else None)

                    texto, media_id, tipo_media = "", None, "text"
                    if msg_type == "text":
                        texto = msg.get("text", {}).get("body", "")
                    elif msg_type == "audio":
                        texto = "[Voice note received]"
                        media_id, tipo_media = msg.get("audio", {}).get("id"), "audio"
                    elif msg_type == "image":
                        texto = msg.get("image", {}).get("caption", "[Image received]")
                        media_id, tipo_media = msg.get("image", {}).get("id"), "image"
                    elif msg_type in ["video", "document"]:
                        texto = f"[{msg_type} attachment received]"

                    if texto or media_id:
                        background_tasks.add_task(
                            procesar_mensaje,
                            sender_id=sender_id,
                            texto=texto,
                            plataforma="whatsapp",
                            mid=mid,
                            wa_name=wa_name,
                            ad_title=ad_title,
                            media_id=media_id,
                            tipo_media=tipo_media,
                            ad_id=ad_id,
                        )

    elif plataforma_base == "page":
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                if "message" in event and event["message"].get("is_echo"):
                    recipient_id = event.get("recipient", {}).get("id")
                    texto_echo = event["message"].get("text", "")
                    if hash(texto_echo) in mensajes_enviados_bot:
                        continue
                    if recipient_id:
                        clientes_silenciados[recipient_id] = True
                        conv_id, _, asignado_a_humano = puente_chatwoot(recipient_id, texto_echo, "messenger")
                        if conv_id:
                            if texto_echo and CW_URL and CW_KEY:
                                requests.post(
                                    f"{CW_URL}/api/v1/accounts/{CW_ACC}/conversations/{conv_id}/messages",
                                    json={"content": f"[Meta Business Suite] {texto_echo}", "message_type": "outgoing"},
                                    headers={"api-access-token": CW_KEY, "Content-Type": "application/json"},
                                    timeout=5,
                                )
                            if not asignado_a_humano:
                                asignar_a_humano(conv_id)
                    continue

                sender_id = event.get("sender", {}).get("id")
                if not sender_id or sender_id in clientes_silenciados:
                    continue

                if "referral" in event and "message" not in event and "postback" not in event:
                    ad_id = str(event["referral"].get("ad_id", ""))
                    if ad_id:
                        background_tasks.add_task(
                            procesar_mensaje,
                            sender_id=sender_id,
                            texto="[Customer entered via Ad referral]",
                            plataforma="messenger",
                            mid=f"ref_{datetime.now().timestamp()}",
                            ad_title=biblioteca_anuncios.get(ad_id, f"Ad ID: {ad_id}"),
                            ad_id=ad_id,
                        )
                    continue

                if "postback" in event:
                    texto = event["postback"].get("title", event["postback"].get("payload", ""))
                    mid = event.get("message", {}).get("mid", f"pb_{datetime.now().timestamp()}")
                    ref = event["postback"].get("referral") or event.get("referral", {})
                    ad_id = str(ref.get("ad_id", "")) if ref else None
                    ad_title = biblioteca_anuncios.get(ad_id) if ad_id else None
                    background_tasks.add_task(
                        procesar_mensaje,
                        sender_id=sender_id,
                        texto=texto,
                        plataforma="messenger",
                        mid=mid,
                        ad_title=ad_title,
                        ad_id=ad_id,
                    )

                elif "message" in event and not event["message"].get("is_echo"):
                    msg = event["message"]
                    texto = msg.get("text", "")
                    mid = msg.get("mid", f"msg_{datetime.now().timestamp()}")
                    ref = msg.get("referral") or event.get("referral", {})
                    ad_id = str(ref.get("ad_id", "")) if ref else None
                    ad_title = biblioteca_anuncios.get(ad_id) if ad_id else None

                    media_url, tipo_media, info_compartida = None, "text", ""
                    for att in msg.get("attachments", []):
                        att_type = att.get("type")
                        if att_type in ["share", "fallback", "template"]:
                            info_compartida = f"[Shared post/ad: {att.get('payload', {}).get('url', 'Link')}] "
                        elif att_type == "image":
                            media_url, tipo_media = att.get("payload", {}).get("url"), "image"
                            texto = texto or "[Image received]"
                            break
                        elif att_type == "audio":
                            media_url, tipo_media = att.get("payload", {}).get("url"), "audio"
                            texto = texto or "[Voice note received]"
                            break

                    background_tasks.add_task(
                        procesar_mensaje,
                        sender_id=sender_id,
                        texto=info_compartida + texto,
                        plataforma="messenger",
                        mid=mid,
                        ad_title=ad_title,
                        tipo_media=tipo_media,
                        media_url=media_url,
                        ad_id=ad_id,
                    )

    return {"status": "ok"}


@app.get("/webhook")
async def verificar_meta(request: Request) -> int:
    if VERIFY_TOKEN and request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return int(request.query_params.get("hub.challenge", 0))
    raise HTTPException(status_code=403, detail="Invalid verification token")


@app.post("/chatwoot")
async def recibir_chatwoot(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Relay outgoing human replies from Chatwoot back to WhatsApp/Messenger & sync tags."""
    try:
        payload = await request.json()
        if not payload:
            return {"status": "ok"}

        event = payload.get("event")
        if event == "conversation_updated":
            meta = payload.get("meta") or {}
            identifier = (meta.get("sender") or {}).get("identifier", "")
            sender_id = identifier.split("_")[-1] if identifier.startswith(("cw_whatsapp_", "cw_messenger_")) else None
            if sender_id:
                agente = (meta.get("assignee") or {}).get("name")
                etiquetas_validas = {"venta_cerrada", "lead_potencial", "curioso", "no_compra", "venta_perdida"}
                clasificacion = next(
                    (lbl.replace("_", " ").title() for lbl in (payload.get("labels") or []) if lbl in etiquetas_validas),
                    None,
                )
                if agente or clasificacion:
                    background_tasks.add_task(registrar_lead_sheets, telefono=sender_id, agente=agente, clasificacion=clasificacion)

        content_attrs = payload.get("content_attributes") or {}
        if content_attrs.get("bot_reply") or payload.get("private"):
            return {"status": "ok"}

        if event == "message_created" and payload.get("message_type") in [1, "outgoing"]:
            if (payload.get("sender") or {}).get("type") == "user":
                conv = payload.get("conversation") or {}
                identifier = ((conv.get("meta") or {}).get("sender") or {}).get("identifier", "")
                if identifier.startswith("cw_"):
                    partes = identifier.split("_")
                    if len(partes) >= 3:
                        plataforma, sender_id = partes[1], partes[2]
                        inbox_id = conv.get("inbox_id")
                        instancia = next(
                            (inst for inst, conf in CONFIG_WHATSAPP.items() if str(conf.get("inbox_id")) == str(inbox_id)),
                            None,
                        )
                        attachments = payload.get("attachments") or []
                        url_adjunto = attachments[0].get("data_url") if attachments else None
                        background_tasks.add_task(
                            enviar_mensaje_cliente,
                            sender_id=sender_id,
                            texto=payload.get("content") or "",
                            plataforma=plataforma,
                            url_adjunto=url_adjunto,
                            instancia=instancia,
                        )
    except Exception as exc:
        log_debug(f"Chatwoot webhook error: {exc}")
    return {"status": "ok"}


@app.get("/descargar-reporte")
async def descargar_reporte() -> FileResponse:
    """Trigger extraction script & download structured sales conversation log."""
    try:
        if os.path.exists(EXPORT_EXTRACTOR_SCRIPT):
            subprocess.run(["python3", EXPORT_EXTRACTOR_SCRIPT], check=True)
    except Exception:
        pass
    if os.path.exists(EXPORT_REPORT_PATH):
        return FileResponse(
            path=EXPORT_REPORT_PATH,
            filename=f"Sales_Conversation_Report_{datetime.now().strftime('%Y-%m-%d')}.txt",
            media_type="text/plain",
        )
    raise HTTPException(status_code=404, detail="Report file not available.")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
