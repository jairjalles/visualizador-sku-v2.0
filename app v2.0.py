import streamlit as st
import requests
import time
import re
from datetime import datetime
import requests.adapters
from concurrent.futures import ThreadPoolExecutor
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote, unquote

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Visualizador de Imagens",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES ---
OLD_IMAGE_BASE_URL = "https://topshop-tiny.com.br/wp-content/uploads/tiny"
NEW_IMAGE_BASE_URL = "https://f005.backblazeb2.com/file/topshop"

MAX_IMAGES_TO_CHECK = 6
REQUEST_TIMEOUT = 3
GRID_COLUMNS = 6
MAX_CONCURRENT_REQUESTS = 12  # Aumentado para links com muitos SKUs
MAX_HISTORY_ITEMS = 10

# --- INICIALIZAÇÃO DA SESSÃO ---
if 'user_name' not in st.session_state:
    st.session_state.user_name = None
if 'search_history' not in st.session_state:
    st.session_state.search_history = []

# --- FUNÇÕES DE LÓGICA ---
def _search_hosting_location(base_url: str, normalized_sku: str, is_old_hosting: bool, specific_number: int | None = None) -> list[str]:
    is_kit_6392 = bool(re.search(r"(?:-|_)?6392$", normalized_sku))

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_CONCURRENT_REQUESTS, pool_maxsize=MAX_CONCURRENT_REQUESTS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    def head_ok(num: int, timeout: float = REQUEST_TIMEOUT) -> str | None:
        filename = ""
        folder_sku = normalized_sku
        kit_pattern = re.match(r'^(K[2-5])-(\d+)$', normalized_sku)

        if is_old_hosting and kit_pattern:
            kit_prefix = kit_pattern.group(1)
            sku_number = kit_pattern.group(2)
            folder_sku = sku_number
            filename = f"{sku_number}{kit_prefix}_{num:02d}.jpg"
        else:
            filename = f"{normalized_sku}_{num:02d}.jpg"
        
        url = f"{base_url}/{folder_sku}/{filename}"
        
        try:
            resp = session.head(url, allow_redirects=True, timeout=timeout)
            if resp.status_code == 200:
                return f"{url}?v={int(time.time())}"
        except:
            pass
        return None

    if specific_number is not None:
        hit = head_ok(specific_number)
        return [hit] if hit else []

    numbers = list(range(1, MAX_IMAGES_TO_CHECK + 1))
    if is_kit_6392 and 6 not in numbers:
        numbers.append(6)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as ex:
        results = list(ex.map(head_ok, sorted(list(set(numbers)))))

    return [u for u in results if u]

@st.cache_data(ttl="1h", show_spinner=False)
def find_images(normalized_sku: str, specific_number: int | None = None, force_refresh_token=None) -> list[str]:
    # Tenta Backblaze B2 primeiro
    res = _search_hosting_location(NEW_IMAGE_BASE_URL, normalized_sku, False, specific_number)
    if res: return res
    # Fallback para Tiny/WordPress
    return _search_hosting_location(OLD_IMAGE_BASE_URL, normalized_sku, True, specific_number)

def send_email_notification(report_data: dict):
    try:
        config = st.secrets["email_config"]
        msg = MIMEText(f"Colaborador: {report_data['user']}\nSKU: {report_data['sku']}\nMotivo: {report_data['reason']}\nObs: {report_data['comment']}")
        msg['Subject'] = f"Alerta de Imagem: SKU {report_data['sku']}"
        msg['From'], msg['To'] = config["sender_email"], config["recipient_email"]
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["sender_email"], config["sender_password"])
            server.sendmail(config["sender_email"], config["recipient_email"], msg.as_string())
        st.toast("✅ Reporte enviado!", icon="📧")
    except:
        st.warning("Notificação por e-mail indisponível.")

# --- UI COMPONENTS ---
def copy_to_clipboard_button(text_to_copy, button_text="Copiar Link", key=None):
    html = f"""<button onclick="navigator.clipboard.writeText('{text_to_copy}'); this.innerText='Copiado!'; setTimeout(()=>{{this.innerText='{button_text}'}}, 1000)" style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:5px; border-radius:5px; cursor:pointer;">{button_text}</button>"""
    st.components.v1.html(html, height=40)

def create_shareable_link_button(skus_list: list[str]):
    skus_param = quote(",".join(skus_list))
    js = f"""<button onclick="const url=window.top.location.origin + window.top.location.pathname + '?skus={skus_param}'; navigator.clipboard.writeText(url); this.innerText='Link de Pesquisa Copiado!'; setTimeout(()=>{{this.innerText='Compartilhar Pesquisa 🔗'}}, 2000)" style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:8px; border-radius:5px; cursor:pointer; font-weight:bold;">Compartilhar Pesquisa 🔗</button>"""
    st.components.v1.html(js, height=50)

@st.dialog("Reportar Problema")
def show_report_dialog():
    with st.form("f_report"):
        sku = st.text_input("SKU com problema:")
        reason = st.selectbox("Motivo:", ["Imagem errada", "Qualidade", "Link quebrado", "Outro"])
        comment = st.text_area("Comentário:")
        if st.form_submit_button("Enviar Reporte"):
            if sku:
                send_email_notification({"user": st.session_state.user_name, "sku": sku, "reason": reason, "comment": comment})
                st.rerun()

def process_and_display_results(cleaned_inputs, force_refresh=False):
    st.subheader("Resultados")
    if cleaned_inputs: create_shareable_link_button(cleaned_inputs)
    
    cache_buster = int(time.time()) if force_refresh else None

    for user_input in cleaned_inputs:
        # Detecta se é pesquisa de imagem específica (_06, -05, etc)
        is_specific = bool(re.search(r'[_-]\d{1,2}$', user_input))
        
        with st.expander(f"**SKU: `{user_input}`**", expanded=True):
            match = re.compile(r'(.+?)[_-](\d{1,2})$').match(user_input)
            if match:
                base, num = match.groups()
                imgs = find_images(base, specific_number=int(num), force_refresh_token=cache_buster)
            else:
                imgs = find_images(user_input, force_refresh_token=cache_buster)

            if imgs:
                cols = st.columns(GRID_COLUMNS)
                for i, url in enumerate(imgs):
                    with cols[i % GRID_COLUMNS]:
                        st.image(url, use_container_width=True)
                        copy_to_clipboard_button(url.split('?')[0], key=f"cp_{user_input}_{i}")
            else:
                if is_specific:
                    st.caption(f"ℹ️ Imagem `{user_input}` não encontrada nos servidores.")
                else:
                    st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")

def show_main_app():
    with st.sidebar:
        st.title("🖼️ Visualizador")
        st.write(f"Usuário: **{st.session_state.user_name}**")
        if st.button("⚠️ Reportar Erro", use_container_width=True): show_report_dialog()
        st.divider()
        st.header("Histórico")
        for i, h in enumerate(reversed(st.session_state.search_history)):
            if st.button(h, key=f"hist_{i}", use_container_width=True):
                st.session_state.current_search = h
                st.rerun()

    # --- LÓGICA DE URL ---
    url_skus = st.query_params.get("skus")
    if url_skus and "url_done" not in st.session_state:
        st.session_state.current_search = unquote(url_skus).replace(',', '\n')
        st.session_state.url_done = True
        st.rerun()

    initial_val = st.session_state.pop("current_search", "")
    
    with st.container(border=True):
        input_skus = st.text_area("SKUs (um por linha):", value=initial_val, height=150)
        c1, c2 = st.columns([3, 1])
        btn_search = c1.button("🔍 Iniciar Verificação", type="primary", use_container_width=True)
        force_refresh = c2.checkbox("Forçar Atualização")

    if btn_search or ("url_done" in st.session_state and st.session_state.url_done):
        # Limpa o flag da URL após a primeira execução para permitir novas buscas manuais
        if "url_done" in st.session_state: del st.session_state["url_done"]
        
        raw = [s.strip().upper() for s in re.split(r'[,\s\n]+', input_skus) if s.strip()]
        cleaned = list(dict.fromkeys(raw))
        
        if cleaned:
            hist_item = ", ".join(cleaned[:2]) + ("..." if len(cleaned)>2 else "")
            if hist_item not in st.session_state.search_history:
                st.session_state.search_history.append(hist_item)
            process_and_display_results(cleaned, force_refresh)

# --- START ---
if st.session_state.user_name is None:
    st.title("🖼️ Acesso")
    name = st.text_input("Seu nome:")
    if st.button("Entrar") and name:
        st.session_state.user_name = name.strip().title()
        st.rerun()
else:
    show_main_app()
