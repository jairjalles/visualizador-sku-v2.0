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
MAX_CONCURRENT_REQUESTS = 10 
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
        
        delay = 0.2
        for _ in range(2): # Reduzido para 2 tentativas para maior agilidade
            try:
                resp = session.head(url, allow_redirects=True, timeout=timeout)
                if resp.status_code == 200:
                    return f"{url}?v={int(time.time())}"
                elif resp.status_code == 429:
                    time.sleep(delay * 2)
                else:
                    return None
            except requests.RequestException:
                time.sleep(delay)
        return None

    if specific_number is not None:
        hit = head_ok(specific_number)
        return [hit] if hit else []

    numbers = list(range(1, MAX_IMAGES_TO_CHECK + 1))
    
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as ex:
        results = list(ex.map(head_ok, numbers))

    found = [u for u in results if u]

    # Lógica especial Kit 6392 (se não achar nada do 1-5, tenta a 06 explicitamente)
    if not found and is_kit_6392:
        hit_06 = head_ok(6)
        if hit_06: found.append(hit_06)

    def num_key(u: str) -> int:
        m = re.search(r"_(\d{2})\.jpg", u)
        return int(m.group(1)) if m else 0

    return sorted(list(set(found)), key=num_key)

@st.cache_data(ttl="1h", show_spinner=False)
def find_images(normalized_sku: str, specific_number: int | None = None, force_refresh_token=None) -> list[str]:
    # 1. Tenta B2
    results = _search_hosting_location(NEW_IMAGE_BASE_URL, normalized_sku, False, specific_number)
    if results: return results

    # 2. Fallback Tiny
    return _search_hosting_location(OLD_IMAGE_BASE_URL, normalized_sku, True, specific_number)

def send_email_notification(report_data: dict):
    try:
        config = st.secrets["email_config"]
        sender_email, sender_password = config["sender_email"], config["sender_password"]
        recipient_email, smtp_server, smtp_port = config["recipient_email"], config["smtp_server"], config["smtp_port"]
        subject = f"Alerta de Imagem: SKU {report_data['sku']}"
        body = (f"Problema reportado por {report_data['user']}\nSKU: {report_data['sku']}\nMotivo: {report_data['reason']}\nObs: {report_data['comment']}")
        msg = MIMEText(body)
        msg['Subject'], msg['From'], msg['To'] = subject, sender_email, recipient_email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        st.toast("✅ Reporte enviado!", icon="📧")
    except Exception:
        st.warning("E-mail não configurado ou falhou.")

# --- INTERFACE ---
def copy_to_clipboard_button(text_to_copy, button_text="Copiar Link", key=None):
    html_code = f"""
    <button id="btn-{key}" onclick="navigator.clipboard.writeText('{text_to_copy}'); this.innerText='Copiado!'; setTimeout(()=>this.innerText='{button_text}', 1000)" 
    style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:5px; border-radius:5px; cursor:pointer;">{button_text}</button>
    """
    st.components.v1.html(html_code, height=40)

def create_shareable_link_button(skus_list: list[str]):
    skus_param = ",".join([quote(s) for s in skus_list])
    js_code = f"""
    <button onclick="const url=window.top.location.origin + window.top.location.pathname + '?skus={skus_param}'; navigator.clipboard.writeText(url); this.innerText='Link de Compartilhamento Copiado!'; setTimeout(()=>this.innerText='Compartilhar Pesquisa 🔗', 2000)" 
    style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:8px; border-radius:5px; cursor:pointer;">Compartilhar Pesquisa 🔗</button>
    """
    st.components.v1.html(js_code, height=50)

@st.dialog("Reportar Problema")
def show_report_dialog():
    with st.form("report_form"):
        sku = st.text_input("SKU com erro:")
        reason = st.selectbox("Motivo:", ["Imagem errada", "Qualidade", "Link quebrado", "Outro"])
        comment = st.text_area("Comentários:")
        if st.form_submit_button("Enviar"):
            if sku:
                send_email_notification({"user": st.session_state.user_name, "sku": sku, "reason": reason, "comment": comment})
                st.rerun()

def process_and_display_results(cleaned_inputs, force_refresh=False):
    if not cleaned_inputs: return
    
    create_shareable_link_button(cleaned_inputs)
    cache_buster = int(time.time()) if force_refresh else None

    for user_input in cleaned_inputs:
        with st.expander(f"**Resultados para: `{user_input}`**", expanded=True):
            # Identifica se é busca por imagem específica (ex: SKU_06)
            match = re.search(r'(.+?)[_-](\d{1,2})$', user_input)
            is_specific = False
            
            if match:
                base_sku, img_num = match.groups()
                is_specific = True
                images_found = find_images(base_sku, specific_number=int(img_num), force_refresh_token=cache_buster)
            else:
                images_found = find_images(user_input, force_refresh_token=cache_buster)

            if images_found:
                cols = st.columns(GRID_COLUMNS)
                for i, img_url in enumerate(images_found):
                    with cols[i % GRID_COLUMNS]:
                        st.image(img_url, use_container_width=True)
                        clean_url = img_url.split('?')[0]
                        copy_to_clipboard_button(clean_url, button_text="Copiar Link", key=f"btn-{user_input}-{i}")
            else:
                # SE FOR ESPECÍFICO (ex: imagem 06 não encontrada), FICA SILENCIOSO
                if not is_specific:
                    st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")
                else:
                    st.caption(f"ℹ️ A imagem específica `{user_input}` não foi localizada.")

def show_main_app():
    # Sidebar
    with st.sidebar:
        st.title("🖼️ Imagens")
        st.write(f"Olá, **{st.session_state.user_name}**")
        if st.button("⚠️ Reportar Problema", use_container_width=True): show_report_dialog()
        st.divider()
        st.header("Histórico")
        for i, hist in enumerate(reversed(st.session_state.search_history)):
            if st.button(hist, key=f"h_{i}", use_container_width=True):
                st.session_state.current_search = hist
                st.rerun()

    # Main
    st.header("Visualizador de Imagens de Produto")
    
    # Lógica de entrada via URL ou Sessão
    query_skus = st.query_params.get("skus")
    if query_skus:
        # Decodifica e limpa usando regex para garantir paridade com o manual
        raw_list = unquote(query_skus).replace(',', '\n')
        initial_search = raw_list
        st.query_params.clear() # Limpa para não entrar em loop
        auto_run = True
    else:
        initial_search = st.session_state.pop("current_search", "")
        auto_run = False

    with st.container(border=True):
        input_skus_str = st.text_area("Insira os SKUs (um por linha)", value=initial_search, height=130)
        c1, c2 = st.columns([3, 1])
        with c1: btn_search = st.button("🔍 Verificar", type="primary", use_container_width=True)
        with c2: force_refresh = st.checkbox("Ignorar Cache")

    if btn_search or auto_run:
        # Regex robusta para capturar SKUs independente de vírgula, espaço ou quebra de linha
        cleaned_inputs = list(dict.fromkeys([s.strip().upper() for s in re.split(r'[,\s\n]+', input_skus_str) if s.strip()]))
        
        if cleaned_inputs:
            # Histórico
            search_str = ", ".join(cleaned_inputs[:3]) + ("..." if len(cleaned_inputs)>3 else "")
            if search_str not in st.session_state.search_history:
                st.session_state.search_history.append(search_str)
            
            process_and_display_results(cleaned_inputs, force_refresh)
        else:
            st.warning("Insira um SKU.")

# Entry Point
if st.session_state.user_name is None:
    st.title("🖼️ Visualizador")
    name = st.text_input("Nome:")
    if st.button("Entrar"):
        if name:
            st.session_state.user_name = name.strip().title()
            st.rerun()
else:
    show_main_app()
