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
from streamlit_copy_button import copy_button # UX MELHORIA: Botão de copiar

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Visualizador de Imagens",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES ---
IMAGE_BASE_URL = "https://topshop-tiny.com.br/wp-content/uploads/tiny"
MAX_IMAGES_TO_CHECK = 5
REQUEST_TIMEOUT = 3
GRID_COLUMNS = 5
MAX_CONCURRENT_REQUESTS = 8
MAX_HISTORY_ITEMS = 10

# --- INICIALIZAÇÃO DA SESSÃO ---
if 'user_name' not in st.session_state:
    st.session_state.user_name = None
if 'search_history' not in st.session_state:
    st.session_state.search_history = []

# --- FUNÇÕES DE LÓGICA ---
# ... (a função send_email_notification continua a mesma, sem alterações) ...
def send_email_notification(report_data: dict):
    try:
        config = st.secrets["email_config"]
        sender_email, sender_password = config["sender_email"], config["sender_password"]
        recipient_email, smtp_server, smtp_port = config["recipient_email"], config["smtp_server"], config["smtp_port"]
        subject = f"Alerta de Imagem: SKU {report_data['sku']}"
        body = (f"Novo problema reportado no Visualizador de Imagens.\n\n"
                f"========================================\n"
                f"Colaborador: {report_data['user']}\nSKU Reportado: {report_data['sku']}\n"
                f"Motivo: {report_data['reason']}\nComentário: {report_data['comment']}\n"
                f"========================================")
        msg = MIMEText(body)
        msg['Subject'], msg['From'], msg['To'] = subject, sender_email, recipient_email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        st.toast("✅ Reporte enviado com sucesso!", icon="📧")
    except (KeyError, FileNotFoundError):
        st.warning("Notificações por e-mail não configuradas.")
        print(f"REPORTE LOCAL (E-mail inativo): {report_data}")
    except Exception as e:
        st.error("Falha ao enviar e-mail de notificação.")
        print(f"Erro ao enviar e-mail: {e}")

# CORREÇÃO DE CACHE: Adicionado 'force_refresh_token' para invalidar o cache sob demanda
@st.cache_data(ttl="1h", show_spinner=False)
def find_images(normalized_sku: str, specific_number: int | None = None, force_refresh_token=None) -> list[str]:
    # O argumento 'force_refresh_token' não é usado, mas sua simples presença com um valor
    # diferente (como o timestamp atual) força o Streamlit a re-executar a função.
    base_url = f"{IMAGE_BASE_URL}/{normalized_sku}/{normalized_sku}"
    is_kit_6392 = bool(re.search(r"(?:-|_)?6392$", normalized_sku))

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_CONCURRENT_REQUESTS,
        pool_maxsize=MAX_CONCURRENT_REQUESTS
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    def head_ok(num: int, timeout: float = REQUEST_TIMEOUT) -> str | None:
        url = f"{base_url}_{num:02d}.jpg"
        delay = 0.3
        for _ in range(3):
            try:
                resp = session.head(url, allow_redirects=True, timeout=timeout)
                if resp.status_code == 200:
                    return f"{url}?v={int(time.time())}"
                elif resp.status_code == 429:
                    time.sleep(delay * 2)
                else:
                    time.sleep(delay)
            except requests.RequestException:
                time.sleep(delay)
            delay *= 2
        return None

    if specific_number is not None:
        hit = head_ok(specific_number)
        return [hit] if hit else []

    if is_kit_6392:
        if head_ok(1, timeout=min(1.5, REQUEST_TIMEOUT)) is None:
            hit_06 = head_ok(6)
            if hit_06:
                return [hit_06]

    numbers = list(range(1, MAX_IMAGES_TO_CHECK + 1))
    if is_kit_6392 and 6 not in numbers:
        numbers.append(6)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as ex:
        results = list(ex.map(head_ok, numbers))

    found = [u for u in results if u]

    def num_key(u: str) -> int:
        m = re.search(r"_(\d{2})\.jpg", u)
        return int(m.group(1)) if m else 0

    return sorted(found, key=num_key)

# --- FUNÇÕES DE INTERFACE (UI) ---
# ... (show_login_screen e show_report_dialog continuam os mesmos) ...
def show_login_screen():
    st.title("🖼️ Visualizador de Imagens")
    st.subheader("Por favor, identifique-se para acessar a ferramenta.")
    with st.form("login_form"):
        name_input = st.text_input("Seu nome completo", placeholder="Ex: João da Silva")
        if st.form_submit_button("Acessar Plataforma", use_container_width=True, type="primary"):
            if name_input:
                st.session_state.user_name = name_input.strip().title()
                st.rerun()
            else:
                st.error("O nome é obrigatório para o acesso.")

@st.dialog("Formulário de Reporte")
def show_report_dialog():
    st.write(f"Você está reportando como: **{st.session_state.user_name}**")
    with st.form("dialog_report_form"):
        st.info("Descreva o problema encontrado com o máximo de detalhes possível.", icon="ℹ️")
        sku_to_report = st.text_input("SKU ou nome da imagem com problema:")
        reason = st.selectbox("Motivo Principal:", ["Imagem errada", "Qualidade baixa", "Link quebrado", "Informação incorreta", "Outro"])
        comment = st.text_area("Descreva o problema:")
        if st.form_submit_button("Enviar Reporte de Problema", use_container_width=True):
            if sku_to_report and reason:
                send_email_notification({
                    "user": st.session_state.user_name, "sku": sku_to_report,
                    "reason": reason, "comment": comment or "Nenhum comentário.",
                })
                st.rerun()
            else:
                st.error("Os campos de SKU e Motivo são obrigatórios.")

def show_main_app():
    # --- BARRA LATERAL (SIDEBAR) ---
    with st.sidebar:
        st.title(f"🖼️ Visualizador de Imagens")
        st.write(f"Bem-vindo(a), **{st.session_state.user_name}**!")
        st.divider()
        
        st.header("Ações")
        if st.button("⚠️ Reportar um Problema", use_container_width=True, help="Clique aqui se encontrou uma imagem ou informação incorreta."):
            show_report_dialog()
        
        # UX MELHORIA 1: HISTÓRICO DE PESQUISAS
        st.divider()
        st.header("Histórico de Pesquisas")
        if not st.session_state.search_history:
            st.caption("Seu histórico aparecerá aqui.")
        else:
            # Mostra o histórico, com o mais recente no topo
            for i, search_term in enumerate(reversed(st.session_state.search_history)):
                if st.button(search_term, key=f"history_{i}", use_container_width=True):
                    # Ao clicar, atualiza o campo de busca e executa novamente
                    st.session_state.current_search = search_term
                    st.rerun()

        st.divider()
        with st.expander("Sobre esta Ferramenta"):
            st.info("""
            Esta plataforma foi desenvolvida para agilizar a verificação de imagens dos SKUs.
            Desenvolvido por: Jair Jales
            """)
        st.caption(f"Versão 3.0 | {datetime.now().year}")

    # --- TELA PRINCIPAL ---
    st.header("Visualizador de Imagens de Produto")
    st.markdown("Utilize o campo abaixo para buscar por um ou mais SKUs. A busca pode ser padrão ou por uma imagem específica (ex: `SKU_08`).")

    # Pega o valor do histórico, se houver, para preencher o campo
    initial_search_value = st.session_state.pop("current_search", "")

    with st.container(border=True):
        input_skus_str = st.text_area(
            "Insira os SKUs ou nomes de imagem (um por linha)",
            height=130,
            placeholder="Exemplos:\n7334\nK-7334-6392\nK-5678_08",
            value=initial_search_value
        )
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_button_clicked = st.button("🔍 Iniciar Verificação", type="primary", use_container_width=True)
        with col2:
            # CORREÇÃO DE CACHE: Checkbox para forçar a atualização
            force_refresh = st.checkbox("Forçar atualização", help="Marque esta opção se acabou de subir uma imagem e ela não está aparecendo. Ignora o cache de 1h.")

    if search_button_clicked:
        raw_inputs = [sku.strip().upper() for sku in re.split(r'[,\s\n]+', input_skus_str) if sku.strip()]
        cleaned_inputs = list(dict.fromkeys(raw_inputs))
        
        if not cleaned_inputs:
            st.warning("Por favor, insira ao menos um SKU para iniciar a verificação.")
        else:
            # UX MELHORIA 1: Adiciona ao histórico
            search_term_for_history = ", ".join(cleaned_inputs)
            if search_term_for_history not in st.session_state.search_history:
                st.session_state.search_history.append(search_term_for_history)
                # Mantém o histórico com no máximo 10 itens
                if len(st.session_state.search_history) > MAX_HISTORY_ITEMS:
                    st.session_state.search_history.pop(0)

            process_and_display_results(cleaned_inputs, force_refresh)


def process_and_display_results(cleaned_inputs, force_refresh=False):
    st.subheader("Resultados da Verificação")
    
    # CORREÇÃO DE CACHE: Gera um token único se a atualização for forçada
    cache_buster = int(time.time()) if force_refresh else None

    with st.spinner("Buscando imagens em nossos servidores..."):
        for user_input in cleaned_inputs:
            # UX MELHORIA 2: RESULTADOS AGRUPADOS (ACORDEÃO)
            with st.expander(f"**Resultados para: `{user_input}`**", expanded=True):
                images_found = []
                match = re.compile(r'(.+?)[_-](\d{1,2})$').match(user_input)
                
                if match:
                    base_sku, img_number = match.groups()
                    images_found = find_images(base_sku, specific_number=int(img_number), force_refresh_token=cache_buster)
                else:
                    images_found = find_images(user_input, force_refresh_token=cache_buster)
                
                if images_found:
                    cols = st.columns(GRID_COLUMNS)
                    for i, img_url in enumerate(images_found):
                        with cols[i % GRID_COLUMNS]:
                            st.image(img_url, use_container_width=True)
                            clean_url = img_url.split('?')[0]
                            # UX MELHORIA 3: BOTÃO DE COPIAR
                            copy_button(clean_url, label="Copiar Link da Imagem")
                else:
                    st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")

# --- PONTO DE ENTRADA PRINCIPAL ---
if st.session_state.user_name is None:
    show_login_screen()
else:
    show_main_app()
