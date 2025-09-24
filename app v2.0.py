import streamlit as st
import requests
import time
import re
from datetime import datetime
import requests.adapters
from concurrent.futures import ThreadPoolExecutor
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Visualizador de Imagens",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTES ---
OLD_IMAGE_BASE_URL = "https://topshop-tiny.com.br/wp-content/uploads/tiny"
NEW_IMAGE_BASE_URL = "https://f005.backblazeb2.com/file/topshop-tiny"

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
def _search_hosting_location(base_url: str, normalized_sku: str, is_old_hosting: bool, specific_number: int | None = None) -> list[str]:
    """
    Função auxiliar que realiza a busca em uma única URL base.
    is_old_hosting: Flag para lidar com a estrutura de URL diferente da hospedagem antiga.
    """
    is_kit_6392 = bool(re.search(r"(?:-|_)?6392$", normalized_sku))

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_CONCURRENT_REQUESTS, pool_maxsize=MAX_CONCURRENT_REQUESTS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    def head_ok(num: int, timeout: float = REQUEST_TIMEOUT) -> str | None:
        """Verifica se uma URL de imagem existe."""
        filename = f"{normalized_sku}_{num:02d}.jpg"
        
        # A estrutura do caminho é a mesma para ambas as hospedagens agora
        url = f"{base_url}/{normalized_sku}/{filename}"
            
        delay = 0.3
        for _ in range(3):
            try:
                resp = session.head(url, allow_redirects=True, timeout=timeout)
                if resp.status_code == 200:
                    return f"{url}?v={int(time.time())}" # Cache buster
                elif resp.status_code == 429:
                    time.sleep(delay * 2)
                else:
                    return None # Se não for 200 ou 429, provavelmente não existe.
            except requests.RequestException:
                time.sleep(delay)
            delay *= 2
        return None

    if specific_number is not None:
        hit = head_ok(specific_number)
        return [hit] if hit else []

    if is_kit_6392 and is_old_hosting: # Heurística específica da hospedagem antiga
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


@st.cache_data(ttl="1h", show_spinner=False)
def find_images(normalized_sku: str, specific_number: int | None = None, force_refresh_token=None) -> list[str]:
    """
    Coordena a busca de imagens, priorizando a nova hospedagem e usando a antiga como fallback.
    """
    # 1. Tenta buscar na NOVA hospedagem primeiro
    new_hosting_results = _search_hosting_location(
        base_url=NEW_IMAGE_BASE_URL,
        normalized_sku=normalized_sku,
        is_old_hosting=False,
        specific_number=specific_number
    )

    if new_hosting_results:
        st.info(f"✅ Imagens para `{normalized_sku}` encontradas na nova hospedagem (B2).", icon="🚀")
        return new_hosting_results

    # 2. Se não encontrar, busca na ANTIGA hospedagem como fallback
    old_hosting_results = _search_hosting_location(
        base_url=OLD_IMAGE_BASE_URL,
        normalized_sku=normalized_sku,
        is_old_hosting=True,
        specific_number=specific_number
    )
    
    if old_hosting_results:
        st.warning(f"Imagens para `{normalized_sku}` encontradas apenas na hospedagem antiga.", icon="💾")

    return old_hosting_results

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

# --- FUNÇÕES DE INTERFACE (UI) ---
def copy_to_clipboard_button(text_to_copy, button_text="Copiar Link", key=None):
    button_id = f"copy-button-{key or text_to_copy}"
    
    html_code = f"""
    <button id="{button_id}" onclick="copyToClipboard(this, '{text_to_copy}')" style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:5px; border-radius:5px; cursor:pointer;">{button_text}</button>
    <script>
    function copyToClipboard(element, text) {{
        navigator.clipboard.writeText(text).then(function() {{
            element.innerText = 'Copiado!';
            setTimeout(function() {{ element.innerText = '{button_text}'; }}, 1000);
        }}, function(err) {{
            console.error('Erro ao copiar: ', err);
        }});
    }}
    </script>
    """
    st.components.v1.html(html_code, height=40)

# NOVO: Função para criar e copiar o link de compartilhamento
def create_shareable_link_button(skus_list: list[str], button_text: str = "Compartilhar Pesquisa 🔗", key: str = "share_link"):
    """Cria um botão que copia a URL atual com os SKUs da pesquisa como query params."""
    
    # Converte a lista de SKUs em uma string segura para URL (ex: SKU1,SKU2)
    skus_param = ",".join([quote(s) for s in skus_list])
    button_id = f"share-button-{key}"
    
    # O JavaScript foi corrigido para usar `top.location.href`
    # Isso garante que ele capture a URL principal da aplicação, e não a do iframe do componente.
    js_code = f"""
    <script>
    function createAndCopyShareLink(element) {{
        const skus = "{skus_param}";
        
        // CORREÇÃO: Pega a URL da janela principal (top) e remove quaisquer parâmetros existentes.
        const parentUrl = top.location.href;
        const baseUrl = parentUrl.split('?')[0]; // Remove query params
        
        const shareUrl = `${{baseUrl}}?skus=${{skus}}`;
        
        navigator.clipboard.writeText(shareUrl).then(function() {{
            element.innerText = 'Link Copiado!';
            setTimeout(function() {{ element.innerText = '{button_text}'; }}, 1500);
        }}, function(err) {{
            console.error('Erro ao copiar o link de compartilhamento: ', err);
            element.innerText = 'Erro ao Copiar';
        }});
    }}
    </script>
    <button id="{button_id}" onclick="createAndCopyShareLink(this)" style="width:100%; border:1px solid #4A4A4A; background-color:#2A2A2A; color:white; padding:8px; border-radius:5px; cursor:pointer;">{button_text}</button>
    """
    st.components.v1.html(js_code, height=50)

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
        st.header("Histórico de Pesquisas")
        if not st.session_state.search_history:
            st.caption("Seu histórico aparecerá aqui.")
        else:
            for i, search_term in enumerate(reversed(st.session_state.search_history)):
                if st.button(search_term, key=f"history_{i}", use_container_width=True):
                    st.session_state.current_search = search_term
                    st.rerun()

        st.divider()
        with st.expander("Sobre esta Ferramienta"):
            st.info("""
            Esta plataforma foi desenvolvida para agilizar a verificação de imagens dos SKUs.
            Desenvolvido por: Jair Jales
            """)
        st.caption(f"Versão 4.1 | {datetime.now().year}")

    # --- TELA PRINCIPAL ---
    st.header("Visualizador de Imagens de Produto")
    st.markdown("Utilize o campo abaixo para buscar por um ou mais SKUs. A busca pode ser padrão ou por uma imagem específica (ex: `SKU_08`).")

    # MODIFICADO: Verifica se há SKUs na URL para executar a busca automaticamente
    skus_from_url = st.query_params.get("skus")
    if skus_from_url:
        # Decodifica e limpa os SKUs da URL
        cleaned_inputs = list(dict.fromkeys([s.strip().upper() for s in skus_from_url.split(',') if s.strip()]))
        # Formata para exibição no text_area
        initial_search_value = "\n".join(cleaned_inputs)
        # Remove o parâmetro da URL para evitar re-buscas em interações futuras
        st.query_params.clear()
        # Define um flag para indicar que a busca deve ser processada
        run_search_on_load = True
    else:
        initial_search_value = st.session_state.pop("current_search", "")
        cleaned_inputs = []
        run_search_on_load = False


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
            force_refresh = st.checkbox("Forçar atualização", help="Marque esta opção se acabou de subir uma imagem e ela não está aparecendo. Ignora o cache de 1h.")

    if search_button_clicked and not run_search_on_load:
        raw_inputs = [sku.strip().upper() for sku in re.split(r'[,\s\n]+', input_skus_str) if sku.strip()]
        cleaned_inputs = list(dict.fromkeys(raw_inputs))
        
        if not cleaned_inputs:
            st.warning("Por favor, insira ao menos um SKU para iniciar a verificação.")
        else:
            search_term_for_history = ", ".join(cleaned_inputs)
            if search_term_for_history not in st.session_state.search_history:
                st.session_state.search_history.append(search_term_for_history)
                if len(st.session_state.search_history) > MAX_HISTORY_ITEMS:
                    st.session_state.search_history.pop(0)
            
            process_and_display_results(cleaned_inputs, force_refresh)
    
    # MODIFICADO: Executa a busca se os SKUs vieram da URL
    elif run_search_on_load:
        process_and_display_results(cleaned_inputs, force_refresh)

def process_and_display_results(cleaned_inputs, force_refresh=False):
    st.subheader("Resultados da Verificação")
    
    # NOVO: Adiciona o botão de compartilhar a pesquisa
    if cleaned_inputs:
        create_shareable_link_button(cleaned_inputs)

    cache_buster = int(time.time()) if force_refresh else None

    with st.spinner("Buscando imagens em nossos servidores..."):
        for user_input in cleaned_inputs:
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
                            copy_to_clipboard_button(clean_url, button_text="Copiar Link", key=clean_url)
                else:
                    st.error(f"Nenhuma imagem encontrada para `{user_input}`.", icon="❌")

# --- PONTO DE ENTRADA PRINCIPAL ---
if st.session_state.user_name is None:
    show_login_screen()
else:
    show_main_app()
