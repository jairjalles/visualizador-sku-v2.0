import streamlit as st
import requests
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import smtplib
from email.mime.text import MIMEText

# --- CONFIGURAÇÃO DA PÁGINA (MAIS COMPLETA) ---
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

# --- INICIALIZAÇÃO DA SESSÃO ---
if 'user_name' not in st.session_state:
    st.session_state.user_name = None

# --- FUNÇÕES DE LÓGICA (SEM ALTERAÇÕES) ---
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

@st.cache_data(ttl="1h", show_spinner=False)
def find_images(normalized_sku: str, specific_number: int = None) -> list[str]:
    base_url = f"{IMAGE_BASE_URL}/{normalized_sku}/{normalized_sku}"
    urls_to_check = []
    # Verifica as extensões mais comuns
    extensions = [".jpg", ".jpeg", ".png"]

    if specific_number:
        for ext in extensions:
            urls_to_check.append(f"{base_url}_{specific_number:02d}{ext}")
    else:
        for i in range(1, MAX_IMAGES_TO_CHECK + 1):
            for ext in extensions:
                urls_to_check.append(f"{base_url}_{i:02d}{ext}")
    
    found_images = []
    def check_url(url):
        try:
            # Usar 'head' é mais eficiente para verificar se o arquivo existe
            response = requests.head(url, stream=True, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return f"{url}?v={int(time.time())}"
        except requests.exceptions.RequestException: pass
        return None

    with ThreadPoolExecutor(max_workers=len(urls_to_check) or 1) as executor:
        results = executor.map(check_url, urls_to_check)
        found_images = [url for url in results if url]
    return sorted(found_images)

# --- FUNÇÕES DE INTERFACE (UI) ---

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
        
        st.divider()
        with st.expander("Sobre esta Ferramenta"):
            st.info("""
            Esta plataforma foi desenvolvida para agilizar a verificação de imagens dos SKUs. 
            Utilize a busca para encontrar imagens por SKU.
                    
            Desenvolvido por: Jair Jales
            """)
        st.caption(f"Versão 2.0 | {datetime.now().year}")

    # --- TELA PRINCIPAL ---
    st.header("Visualizador de Imagens de Produto")
    st.markdown("Utilize o campo abaixo para buscar por um ou mais SKUs. A busca pode ser padrão ou por uma imagem específica (ex: `SKU_08`).")

    with st.container(border=True):
        input_skus_str = st.text_area(
            "Insira os SKUs ou nomes de imagem (um por linha)",
            height=130, 
            placeholder="Exemplos:\n7334\nK-7334-6392\nK-5678_08"
        )
        if st.button("🔍 Iniciar Verificação", type="primary", use_container_width=True):
            raw_inputs = [sku.strip().upper() for sku in re.split(r'[,\s\n]+', input_skus_str) if sku.strip()]
            cleaned_inputs = list(dict.fromkeys(raw_inputs))
            if not cleaned_inputs:
                st.warning("Por favor, insira ao menos um SKU para iniciar a verificação.")
            else:
                # O processamento dos resultados acontece aqui
                process_and_display_results(cleaned_inputs)

def process_and_display_results(cleaned_inputs):
    specific_pattern = re.compile(r'(.+?)[_-](\d{1,2})$')
    st.subheader("Resultados da Verificação")

    with st.spinner("Buscando imagens em nossos servidores..."):
        for user_input in cleaned_inputs:
            st.markdown(f"##### Exibindo para: `{user_input}`")
            images_found = []
            match = specific_pattern.match(user_input)
            
            if match:
                base_sku, img_number = match.groups()
                images_found = find_images(base_sku, specific_number=int(img_number))
            else:
                images_found = find_images(user_input)
            
            if images_found:
                with st.container(border=True):
                    cols = st.columns(GRID_COLUMNS)
                    for i, img_url in enumerate(images_found):
                        with cols[i % GRID_COLUMNS]:
                            st.image(img_url, use_container_width=True)
                            clean_url = img_url.split('?')[0]
                            st.text_input("Link:", value=clean_url, key=f"link_{clean_url}", label_visibility="collapsed", help="Link da imagem para copiar.")
            else:
                st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")
            st.write("") # Adiciona um espaço vertical

# --- PONTO DE ENTRADA PRINCIPAL ---
if st.session_state.user_name is None:
    show_login_screen()
else:
    show_main_app()
