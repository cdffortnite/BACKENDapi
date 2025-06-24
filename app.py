import os
import requests
import mysql.connector
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# Carrega variáveis de ambiente (.env)
load_dotenv()

app = Flask(__name__)
CORS(app)
Compress(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["50 per minute"]
)

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Configuração do banco MySQL (com base no seu Database.php)
db_config = {
    'host': os.getenv("MYSQL_HOST", "localhost"),
    'user': os.getenv("MYSQL_USER", "root"),
    'password': os.getenv("MYSQL_PASSWORD", ""),
    'database': os.getenv("MYSQL_DATABASE", "projetoantes")
}

# Histórico por usuário
user_conversations = {}

# Contexto base do sistema
CONTEXT_ESTOQUE_FUNCIONARIOS = (
    "Você é um assistente virtual do sistema de controle de estoque e funcionários da empresa. "
    "Você responde perguntas sobre produtos cadastrados, estoque atual e funcionários da equipe. "
    "Use os dados mais recentes do banco. "
    "Se não houver informação, diga: 'Não tenho essa informação no momento.' "
)

@app.route("/")
def home():
    return jsonify({"message": "API do Chatbot de Estoque e Funcionários (DeepSeek) rodando!"})

@app.route("/chat", methods=["POST"])
@limiter.limit("50 per minute")
def chat():
    data = request.json
    user_message = data.get("message", "").strip()
    user_id = data.get("user_id", "default_user")

    if not user_message:
        return jsonify({"error": "Nenhuma mensagem recebida."}), 400

    # Conecta no banco e busca dados
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) as total_produtos FROM estoque")
        estoque_info = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) as total_funcionarios FROM funcionarios")
        funcionarios_info = cursor.fetchone()

        cursor.execute("SELECT nome_produto FROM estoque ORDER BY data_entrada DESC LIMIT 1")
        ultimo_produto = cursor.fetchone()

        cursor.execute("SELECT nome FROM funcionarios WHERE cargo LIKE '%gerente%'")
        gerentes = cursor.fetchall()

        cursor.close()
        conn.close()

    except Exception as e:
        return jsonify({"error": f"Erro ao acessar banco de dados: {str(e)}"}), 500

    # Monta contexto dinâmico
    estoque_total = estoque_info['total_produtos']
    funcionarios_total = funcionarios_info['total_funcionarios']
    ultimo_nome = ultimo_produto['nome_produto'] if ultimo_produto else "Nenhum produto cadastrado"
    nomes_gerentes = ", ".join([g['nome'] for g in gerentes]) if gerentes else "Nenhum gerente cadastrado"

    system_prompt = (
        f"{CONTEXT_ESTOQUE_FUNCIONARIOS}\n"
        f"Dados atuais:\n"
        f"- Total de produtos no estoque: {estoque_total}\n"
        f"- Último produto cadastrado: {ultimo_nome}\n"
        f"- Total de funcionários: {funcionarios_total}\n"
        f"- Gerentes: {nomes_gerentes}\n"
    )

    # Histórico
    if user_id not in user_conversations:
        user_conversations[user_id] = [{"role": "system", "content": system_prompt}]

    user_conversations[user_id].append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 200,
        "messages": user_conversations[user_id]
    }

    response = requests.post(DEEPSEEK_URL, headers=headers, json=payload)

    if response.status_code != 200:
        return jsonify({"error": f"Erro na API DeepSeek: {response.status_code}"}), response.status_code

    deepseek_response = response.json().get("choices", [{}])[0].get("message", {}).get("content", "Erro na resposta.")

    user_conversations[user_id].append({"role": "assistant", "content": deepseek_response})

    return jsonify({"response": deepseek_response})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

