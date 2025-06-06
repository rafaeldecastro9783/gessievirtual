import requests
from bot.utils import registrar_mensagem

# Token e ID da administradora fixos por enquanto
token = "aaa9c67011b1d6eccc4fd33498c5276ae64b98d1"
administradora_id = "6695762979192832"

def enviar_texto_whatsapp_condomob(telefone: str, texto: str, client_config):
    if not telefone:
        print("⚠️ Número de telefone não informado!")
        return

    payload = {"phone": telefone, "message": texto}
    headers = {
        "Content-Type": "application/json",
        "Client-Token": client_config.zapi_token
    }

    try:
        response = requests.post(client_config.zapi_url_text, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"⚠️ Falha ao enviar mensagem WhatsApp: {response.status_code} | {response.text}")
        else:
            print("✅ Mensagem enviada com sucesso via WhatsApp!")
            # Opcional: salvar a mensagem como registro
            from bot.utils import registrar_mensagem
            registrar_mensagem(phone=telefone, mensagem=texto, enviado_por='gessie', client_config=client_config, tipo="texto")

    except Exception as e:
        print(f"❌ Erro ao tentar enviar mensagem via WhatsApp: {e}")

def consultar_boleto_condomob(cpfCnpj: str, telefone: str, client_config=None):
    try:
        # 1. Buscar unidade
        unidade_url = "https://financeiro.condomob.net/ws/chatbot/unidade/list/cpfCnpj"
        headers = {
            "Authorization": token,
            "administradora": administradora_id
        }
        unidade_resp = requests.get(unidade_url, headers=headers, params={"cpfCnpj": cpfCnpj})

        if unidade_resp.status_code != 200 or not unidade_resp.json():
            return "❌ Não foi possível localizar nenhuma unidade para este CPF."

        unidade_data = unidade_resp.json()[0]
        condominio_id = unidade_data["condominio"]
        unidade_nome = unidade_data["unidade"]

        # 2. Buscar boleto
        boleto_url = "https://financeiro.condomob.net/ws/chatbot/cobranca/latest"
        boleto_resp = requests.get(boleto_url, headers=headers, params={
            "cpfCnpj": cpfCnpj,
            "condominio": condominio_id,
            "unidade": unidade_nome
        })

        if boleto_resp.status_code != 200:
            return "❌ Não foi possível localizar boletos em aberto com os dados informados."

        resultado = boleto_resp.json()

        # 3. Montar mensagem
        mensagem = f"""
🔔 *2ª Via do Boleto Encontrada!*

🏢 Unidade: {resultado.get("unidade")}
💰 Valor: R$ {resultado.get("valor"):.2f}
📅 Vencimento: {resultado.get("vencimento")}
💳 Linha digitável:
{resultado.get("linhaDigitavel")}

📎 Link para o boleto:
{resultado.get("link")}

🔁 Caso prefira, você também pode pagar via *PIX*:
{resultado.get("pix")}
"""

        # 4. Registrar e enviar pelo WhatsApp
        if client_config:
            registrar_mensagem(telefone, mensagem, enviado_por="gessie", client_config=client_config, tipo="texto")
            enviar_texto_whatsapp_condomob(telefone, mensagem, client_config)

        return mensagem.strip()

    except Exception as e:
        print("❌ Erro ao consultar boleto:", str(e))
        return "❌ Ocorreu um erro inesperado ao consultar a 2ª via do boleto."

