import streamlit as st
import requests
import time
import re
from datetime import datetime
import requests.adapters
from concurrent.futures import ThreadPoolExecutor
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote, unquote # NOVA FUNCIONALIDADE: Para codificar a URL

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
MAX_CONCURRENT_REQUESTS = 8

# --- INICIALIZAÇÃO DA SESSÃO ---
if 'user_name' not in st.session_state:
    st.session_state.user_name = None
if 'processed_url' not in st.session_state:
    st.session_state.processed_url = False

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
def find_images(normalized_sku: str, specific_number: int | None = None) -> list[str]:
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
        st.caption(f"Versão 2.1 | {datetime.now().year}")
        
    # --- NOVA FUNCIONALIDADE: LER SKUS DA URL AO CARREGAR A PÁGINA ---
    # Verifica se existem SKUs na URL e se ainda não foram processados nesta sessão.
    if "skus" in st.query_params and not st.session_state.processed_url:
        # Decodifica os SKUs da URL e os armazena no estado da sessão
        skus_from_url = unquote(st.query_params["skus"])
        # Substitui vírgulas por quebras de linha para preencher o text_area
        st.session_state.initial_search_text = skus_from_url.replace(",", "\n")
        st.session_state.processed_url = True # Marca como processado
    
    # Pega o texto inicial para o text_area, seja da URL ou vazio.
    initial_text = st.session_state.get("initial_search_text", "")

    # --- TELA PRINCIPAL ---
    st.header("Visualizador de Imagens de Produto")
    st.markdown("Utilize o campo abaixo para buscar por um ou mais SKUs. A busca pode ser padrão ou por uma imagem específica (ex: `SKU_08`).")

    with st.container(border=True):
        input_skus_str = st.text_area(
            "Insira os SKUs ou nomes de imagem (um por linha)",
            height=130,
            placeholder="Exemplos:\n7334\nK-7334-6392\nK-5678_08",
            value=initial_text # Define o valor inicial do campo de texto
        )
        
        search_button_clicked = st.button("🔍 Iniciar Verificação", type="primary", use_container_width=True)

    # --- LÓGICA DE EXECUÇÃO DA BUSCA ---
    # A busca é executada se o botão for clicado OU se houver texto inicial vindo da URL.
    if search_button_clicked or initial_text:
        # Se veio da URL, usa o texto inicial. Senão, usa o que está no campo de texto.
        text_to_process = initial_text if initial_text and not search_button_clicked else input_skus_str
        
        raw_inputs = [sku.strip().upper() for sku in re.split(r'[,\s\n]+', text_to_process) if sku.strip()]
        cleaned_inputs = list(dict.fromkeys(raw_inputs))
        
        if not cleaned_inputs:
            st.warning("Por favor, insira ao menos um SKU para iniciar a verificação.")
        else:
            process_and_display_results(cleaned_inputs)
        
        # NOVA FUNCIONALIDADE: Limpa o texto inicial após a primeira busca automática.
        if "initial_search_text" in st.session_state:
            del st.session_state["initial_search_text"]


def process_and_display_results(cleaned_inputs):
    specific_pattern = re.compile(r'(.+?)[_-](\d{1,2})$')
    st.subheader("Resultados da Verificação")

    with st.spinner("Buscando imagens em nossos servidores..."):
        all_found = True
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
                all_found = False
                st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")
            st.write("") # Adiciona um espaço vertical

    # --- NOVA FUNCIONALIDADE: GERAR LINK DE COMPARTILHAMENTO ---
    if all_found and cleaned_inputs:
        st.divider()
        st.subheader("🔗 Compartilhar esta Pesquisa")
        st.info("Copie o link abaixo para compartilhar exatamente esta visualização com outra pessoa.")
        
        # Junta os SKUs com vírgula para usar na URL
        skus_for_url = ",".join(cleaned_inputs)
        # Codifica os SKUs para garantir que a URL seja válida
        encoded_skus = quote(skus_for_url)
        # Cria o parâmetro final para a URL
        share_param = f"?skus={encoded_skus}"
        
        st.code(share_param, language=None)
        st.caption("Adicione o código acima ao final da URL principal do seu aplicativo para criar o link de compartilhamento.")


# --- PONTO DE ENTRADA PRINCIPAL ---
if st.session_state.user_name is None:
    show_login_screen()
else:
    show_main_app()
