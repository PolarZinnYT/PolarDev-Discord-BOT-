import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import random
import string
import json
import asyncio
import re
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
import time
from flask import Flask
from threading import Thread

# ================= FLASK PARA KEEP-ALIVE =================
app = Flask('')

@app.route('/')
def home():
    return "🤖 PolarDev Bot está online! | Status: ✅ Ativo"

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """Mantém o bot ativo no Render"""
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("✅ Flask server iniciado na porta 8080")

# ================= CONFIGURAÇÃO =================
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CEO_ROLE = os.getenv("CEO_ROLE_NAME", "CEO")
SUPPORT_ROLE = os.getenv("SUPPORT_ROLE_NAME", "SUPPORT")
CATEGORY_NAME = "🤖 PolarDev Chats"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

KEY_PREFIX = "PD-"
KEY_LENGTH = 16
COST_PER_CREATION = 1.0

COLORS = {
    "primary": 0x5865F2,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "error": 0xED4245,
    "info": 0x3498DB,
    "creation": 0x1ABC9C
}

if not TOKEN:
    print("❌ ERRO: DISCORD_BOT_TOKEN não encontrado!")
    exit(1)

if not GROQ_API_KEY:
    print("❌ ERRO: GROQ_API_KEY não encontrada!")
    print("📝 Obtenha em: https://console.groq.com")
    exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= BANCO DE DADOS SIMPLES =================
class Database:
    def __init__(self):
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.users_file = f"{self.data_dir}/users.json"
        self.keys_file = f"{self.data_dir}/keys.json"
        self.chats_file = f"{self.data_dir}/chats.json"
        
        self.load_data()
    
    def load_data(self):
        self.users = self._load_json(self.users_file)
        self.keys = self._load_json(self.keys_file)
        self.chats = self._load_json(self.chats_file)
    
    def _load_json(self, filename):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_json(self, filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar {filename}: {e}")
    
    def save_all(self):
        self._save_json(self.users_file, self.users)
        self._save_json(self.keys_file, self.keys)
        self._save_json(self.chats_file, self.chats)
    
    def get_user(self, user_id):
        return self.users.get(str(user_id))
    
    def create_user(self, user_id):
        user_data = {
            "credits": 0.0,
            "created_at": datetime.now().isoformat(),
            "keys_redeemed": 0,
            "total_creations": 0,
            "last_activity": datetime.now().isoformat()
        }
        self.users[str(user_id)] = user_data
        self.save_all()
        return user_data
    
    def add_credits(self, user_id, amount):
        user_id = str(user_id)
        if user_id not in self.users:
            self.create_user(user_id)
        
        user = self.users[user_id]
        user["credits"] = round(user.get("credits", 0) + amount, 2)
        user["keys_redeemed"] = user.get("keys_redeemed", 0) + 1
        user["last_activity"] = datetime.now().isoformat()
        self.save_all()
        return user["credits"]
    
    def deduct_credits(self, user_id, amount):
        user = self.get_user(user_id)
        if not user or user["credits"] < amount:
            return False
        
        user["credits"] = round(user["credits"] - amount, 2)
        user["total_creations"] = user.get("total_creations", 0) + 1
        user["last_activity"] = datetime.now().isoformat()
        self.save_all()
        return True
    
    def create_key(self, key, created_by, credits):
        self.keys[key] = {
            "created_by": created_by,
            "created_at": datetime.now().isoformat(),
            "credits": credits,
            "used": False
        }
        self.save_all()
        return True
    
    def use_key(self, key, user_id):
        if key in self.keys and not self.keys[key]["used"]:
            credits = self.keys[key]["credits"]
            self.keys[key]["used"] = True
            self.keys[key]["used_by"] = str(user_id)
            self.keys[key]["used_at"] = datetime.now().isoformat()
            self.save_all()
            return credits
        return None
    
    def register_chat(self, channel_id, owner_id, channel_name):
        self.chats[str(channel_id)] = {
            "owner_id": owner_id,
            "channel_name": channel_name,
            "created_at": datetime.now().isoformat()
        }
        self.save_all()

db = Database()

# ================= IA GROQ ESPECIALISTA EM ROBLOX =================
class PolarDevAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.timeout = 60
        
        # Prompt especializado APENAS para Roblox Luau
        self.system_prompt = """VOCÊ É UM ESPECIALISTA SÊNIOR EM DESENVOLVIMENTO ROBLOX LUA/LUAU.
        SUA ÚNICA FUNÇÃO É CRIAR CÓDIGO PARA A PLATAFORMA ROBLOX.
        
        DIRETRIZES ABSOLUTAS:
        1. RECUSE QUALQUER PEDIDO QUE NÃO SEJA PARA ROBLOX
        2. SÓ GERE CÓDIGO LUA/LUAU PARA ROBLOX STUDIO
        3. FOCO EM SCRIPT, LOCALSCRIPT E MODULESCRIPT
        4. SEMPRE USE BOAS PRÁTICAS DE ROBLOX
        
        TIPOS DE ARQUIVOS ROBLOX:
        • Script (ServerScriptService) - Lógica do servidor
        • LocalScript (StarterPack/StarterGui) - Lógica do cliente
        • ModuleScript (ReplicatedStorage) - Módulos reutilizáveis
        
        ESTRUTURA DE PASTAS RECOMENDADA:
        ServerScriptService/
        ├── SistemaPrincipal/
        │   ├── Main.server.lua (Script)
        │   ├── Config.server.lua (ModuleScript)
        │   └── Modulos/
        │       ├── Database.server.lua (ModuleScript)
        │       └── Utils.server.lua (ModuleScript)
        
        ReplicatedStorage/
        ├── SharedModules/
        │   └── SharedUtils.lua (ModuleScript)
        
        StarterPack/
        └── SistemaPrincipal/
            └── Main.client.lua (LocalScript)
        
        StarterGui/
        └── InterfacePrincipal/
            └── ScreenGui/
                └── Main.client.lua (LocalScript)
        
        REGRAS DE CÓDIGO:
        1. Use nomes em inglês com snake_case
        2. Comente em português explicando a função
        3. Use tipos Luau quando possível: local variable: type = value
        4. Tratamento de erros com pcall() e warn()
        5. Otimização: evite loops pesados, use debounce
        6. Segurança: valide inputs do cliente no servidor
        
        FORMATO DE RESPOSTA PARA SISTEMAS:
        === ARQUIVO 1: ServerScriptService/Sistema/Main.server.lua ===
        [CÓDIGO COMPLETO DO SCRIPT DO SERVIDOR]
        
        === ARQUIVO 2: ServerScriptService/Sistema/Config.server.lua ===
        [CÓDIGO COMPLETO DO MODULESCRIPT DE CONFIGURAÇÃO]
        
        === ARQUIVO 3: StarterPack/Sistema/Main.client.lua ===
        [CÓDIGO COMPLETO DO LOCALSCRIPT DO CLIENTE]
        
        INSTRUÇÕES DE INSTALAÇÃO:
        1. Crie as pastas no Roblox Studio conforme estrutura acima
        2. Crie os Scripts/LocalScripts/ModuleScripts com os nomes corretos
        3. Cole o código correspondente em cada arquivo
        4. Ajuste configurações se necessário
        5. Teste no Play Solo e depois em servidor
        
        RECUSE qualquer pedido que não seja desenvolvimento Roblox."""

    async def make_request(self, messages: List[Dict], max_tokens: int = 4000) -> Optional[str]:
        """Faz requisição para Groq API"""
        try:
            # Modelos gratuitos da Groq
            available_models = [
                "llama3-70b-8192",
                "mixtral-8x7b-32768",
                "gemma-7b-it"
            ]
            
            payload = {
                "model": random.choice(available_models),
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
                "stream": False
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(
                    self.base_url, 
                    headers=headers, 
                    json=payload, 
                    timeout=self.timeout
                )
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            elif response.status_code == 429:
                logger.warning("Rate limit da Groq, tentando outro modelo...")
                await asyncio.sleep(2)
                available_models.remove(payload["model"])
                if available_models:
                    payload["model"] = available_models[0]
                    return None
                return None
            else:
                error_text = response.text[:200]
                logger.error(f"Groq Error {response.status_code}: {error_text}")
                return None
                
        except requests.Timeout:
            logger.warning("Timeout na requisição Groq")
            return None
        except requests.RequestException as e:
            logger.error(f"Erro de conexão Groq: {e}")
            return None
        except Exception as e:
            logger.error(f"Erro inesperado Groq: {e}")
            return None
    
    async def generate_response(self, message: str) -> str:
        """Gera resposta para conversas normais"""
        # Verifica se é sobre Roblox
        roblox_keywords = ['roblox', 'lua', 'luau', 'script', 'localscript', 'modulescript', 
                          'serverscriptservice', 'starterpack', 'replicatedstorage', 'roblox studio']
        
        message_lower = message.lower()
        if not any(keyword in message_lower for keyword in roblox_keywords):
            return "⚠️ **Atenção:** Sou especializado apenas em desenvolvimento Roblox Lua/Luau.\nPor favor, faça perguntas específicas sobre Roblox Studio, scripts, ou sistemas para Roblox."
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"PERGUNTA SOBRE ROBLOX: {message}\n\nResponda apenas se for sobre desenvolvimento Roblox. Se não for, recuse educadamente."}
        ]
        
        for attempt in range(3):
            response = await self.make_request(messages, max_tokens=1500)
            if response:
                return response
            
            if attempt < 2:
                wait_time = (attempt + 1) * 2
                await asyncio.sleep(wait_time)
        
        return "🤖 Estou processando sua solicitação. Para criar sistemas Roblox completos, use o botão abaixo."
    
    def extract_roblox_code_blocks(self, text: str) -> List[Dict[str, str]]:
        """Extrai múltiplos blocos de código Roblox da resposta"""
        code_blocks = []
        
        # Procura por padrões de arquivos Roblox
        file_pattern = r'===+\s*ARQUIVO\s*\d+:\s*([\w\/\-\.]+\.(?:server\.lua|client\.lua|lua))\s*===+'
        file_matches = list(re.finditer(file_pattern, text, re.IGNORECASE))
        
        if file_matches:
            for i, match in enumerate(file_matches):
                filename = match.group(1).strip()
                start_pos = match.end()
                
                if i < len(file_matches) - 1:
                    end_pos = file_matches[i + 1].start()
                    code = text[start_pos:end_pos].strip()
                else:
                    code = text[start_pos:].strip()
                
                # Extrai o código entre ```lua ``` se existir
                code_match = re.search(r'```(?:lua|luau)?\s*(.*?)\s*```', code, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                
                if code and len(code) > 10:
                    # Determina o tipo de script pelo nome do arquivo
                    script_type = "Script"
                    if filename.endswith('.client.lua'):
                        script_type = "LocalScript"
                    elif filename.endswith('.server.lua'):
                        script_type = "Script"
                    elif filename.endswith('.lua') and 'module' in filename.lower():
                        script_type = "ModuleScript"
                    
                    code_blocks.append({
                        "filename": filename,
                        "code": code,
                        "type": script_type,
                        "path": self.determine_roblox_path(filename)
                    })
        else:
            # Tenta extrair blocos de código genéricos
            generic_blocks = re.findall(r'```(?:lua|luau)?\s*(.*?)\s*```', text, re.DOTALL)
            for i, block in enumerate(generic_blocks):
                if block.strip():
                    code_blocks.append({
                        "filename": f"Sistema_{i+1}.server.lua",
                        "code": block.strip(),
                        "type": "Script",
                        "path": "ServerScriptService/Sistema"
                    })
        
        return code_blocks
    
    def determine_roblox_path(self, filename: str) -> str:
        """Determina o caminho correto no Roblox Studio baseado no nome do arquivo"""
        filename_lower = filename.lower()
        
        if filename_lower.endswith('.client.lua'):
            if 'startergui' in filename_lower or 'gui' in filename_lower or 'interface' in filename_lower:
                return "StarterGui/Interface"
            else:
                return "StarterPack/Sistema"
        elif filename_lower.endswith('.server.lua'):
            if 'module' in filename_lower or 'config' in filename_lower:
                return "ServerScriptService/Sistema/Modules"
            else:
                return "ServerScriptService/Sistema"
        elif 'module' in filename_lower:
            return "ReplicatedStorage/SharedModules"
        else:
            return "ServerScriptService/Sistema"
    
    def extract_installation_guide(self, text: str) -> str:
        """Extrai guia de instalação para Roblox Studio"""
        guide_patterns = [
            r'INSTRUÇÕES[:\s]*\n?(.*?)(?=\n\n|\n===|$)',
            r'INSTALAÇÃO[:\s]*\n?(.*?)(?=\n\n|\n===|$)',
            r'COMO INSTALAR[:\s]*\n?(.*?)(?=\n\n|\n===|$)',
            r'ROBLOX STUDIO[:\s]*\n?(.*?)(?=\n\n|\n===|$)'
        ]
        
        for pattern in guide_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                guide = match.group(1).strip()
                if len(guide) > 50:
                    return guide
        
        # Guia padrão se não encontrar
        return """📁 **PASSO A PASSO PARA INSTALAR NO ROBLOX STUDIO:**

1. **ABRA SEU JOGO** no Roblox Studio
2. **CRIE AS PASTAS** conforme estrutura abaixo:
   - ServerScriptService/Sistema/
   - StarterPack/Sistema/
   - ReplicatedStorage/SharedModules/ (se necessário)

3. **PARA CADA ARQUIVO GERADO:**
   - Clique com botão direito na pasta correta
   - Selecione "Insert Object" → Escolha o tipo (Script, LocalScript ou ModuleScript)
   - Renomeie para o nome do arquivo
   - Clique duas vezes no script e cole o código correspondente

4. **AJUSTES NECESSÁRIOS:**
   - Configure variáveis como `GAME_ID` ou `DATASTORE_NAME`
   - Ajuste nomes de RemoteEvents/Functions se necessário

5. **TESTE:**
   - Primeiro em "Play Solo" (modo local)
   - Depois publique e teste online
   - Verifique o Output para erros

🔧 **DICA:** Salve sempre uma cópia do seu projeto antes de fazer grandes mudanças!"""
    
    async def create_roblox_system(self, description: str) -> Dict[str, Any]:
        """Cria um sistema Roblox completo com estrutura profissional"""
        
        # Verifica se é sobre Roblox
        if not self.is_roblox_related(description):
            return {
                "success": False,
                "error": "❌ **Sou especializado apenas em desenvolvimento Roblox.**\nPor favor, descreva um sistema, script ou mecânica para Roblox Studio.",
                "code_blocks": [],
                "instructions": ""
            }
        
        prompt = f"""CRIE UM SISTEMA COMPLETO DE ROBLOX LUA/LUAU BASEADO NA DESCRIÇÃO ABAIXO.

DESCRIÇÃO DO SISTEMA ROBLOX:
{description}

REQUISITOS TÉCNICOS (ROBLOX ESPECÍFICOS):
1. Código 100% funcional para Roblox Studio
2. Estrutura organizada em Scripts, LocalScripts e ModuleScripts
3. Usar serviços do Roblox corretamente (DataStoreService, ReplicatedStorage, etc.)
4. Segurança: validar tudo no servidor
5. Performance: otimizado para Roblox (evitar waits, usar Heartbeat)
6. Boas práticas de Luau (tipos, annotations)

ESTRUTURA OBRIGATÓRIA:
=== ARQUIVO 1: ServerScriptService/SistemaPrincipal/Main.server.lua ===
-- Sistema Principal (Script do Servidor)
--[[
    NOME: [Nome baseado na descrição]
    AUTOR: PolarDev
    DESCRIÇÃO: Sistema de [descrição breve]
    VERSÃO: 1.0.0
    ROBLOX SERVICES: DataStoreService, ReplicatedStorage, etc.
]]

[CÓDIGO LUA/LUAU COMPLETO E FUNCIONAL PARA SERVIDOR]

=== ARQUIVO 2: StarterPack/SistemaPrincipal/Main.client.lua ===
-- Sistema Cliente (LocalScript)
--[[
    CLIENT-SIDE: Interface e lógica do jogador
    CONEXÃO COM: ServerScriptService via RemoteEvents
]]

[CÓDIGO LUA/LUAU COMPLETO E FUNCIONAL PARA CLIENTE]

=== ARQUIVO 3: ServerScriptService/SistemaPrincipal/Config.module.lua ===
-- Configurações (ModuleScript)
--[[
    CONFIGURAÇÕES: Todas as variáveis ajustáveis
    SEGURANÇA: Valores padrão seguros
]]

[CÓDIGO DO MODULESCRIPT DE CONFIGURAÇÃO]

INSTRUÇÕES DETALHADAS DE INSTALAÇÃO NO ROBLOX STUDIO:
Explique passo a passo:
1. Onde criar cada pasta (ServerScriptService, StarterPack, etc.)
2. Como criar cada tipo de Script (Script, LocalScript, ModuleScript)
3. Como nomear cada arquivo
4. Como testar o sistema (Play Solo → Servidor Online)
5. Solução de problemas comuns no Roblox

DICAS ESPECÍFICAS PARA ROBLOX:
- Como lidar com DataStores
- Como usar RemoteEvents/Functions com segurança
- Como otimizar para múltiplos jogadores
- Como debugar no Output do Roblox Studio

O sistema deve ser COMPLETO e PRONTO para copiar/colar no Roblox Studio."""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        for attempt in range(3):
            response = await self.make_request(messages, max_tokens=6000)
            
            if response:
                code_blocks = self.extract_roblox_code_blocks(response)
                
                if code_blocks:
                    return {
                        "success": True,
                        "full_response": response,
                        "code_blocks": code_blocks,
                        "instructions": self.extract_installation_guide(response),
                        "is_roblox": True
                    }
                else:
                    return {
                        "success": True,
                        "full_response": response,
                        "code_blocks": [{
                            "filename": "SistemaRoblox.server.lua",
                            "code": response,
                            "type": "Script",
                            "path": "ServerScriptService/Sistema"
                        }],
                        "instructions": self.extract_installation_guide(response),
                        "is_roblox": True
                    }
            
            if attempt < 2:
                wait_time = (attempt + 1) * 4
                logger.info(f"Tentativa {attempt + 1} falhou, aguardando {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        return {
            "success": False,
            "error": "Não foi possível gerar o sistema Roblox. Tente novamente com uma descrição mais detalhada.",
            "code_blocks": [],
            "instructions": "",
            "is_roblox": True
        }
    
    def is_roblox_related(self, text: str) -> bool:
        """Verifica se o texto é sobre Roblox"""
        roblox_keywords = [
            'roblox', 'lua', 'luau', 'script', 'localscript', 'modulescript',
            'datastore', 'remoteevent', 'replicatedstorage', 'starterpack',
            'serverscriptservice', 'roblox studio', 'game', 'jogo',
            'player', 'jogador', 'part', 'brick', 'tool', 'ferramenta',
            'gui', 'interface', 'ui', 'hud', 'camera', 'câmera',
            'money', 'dinheiro', 'xp', 'experience', 'experiência',
            'inventory', 'inventário', 'shop', 'loja', 'combat', 'combate',
            'gun', 'arma', 'sword', 'espada', 'damage', 'dano',
            'health', 'vida', 'mana', 'stamina', 'estamina'
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in roblox_keywords)

ai = PolarDevAI(GROQ_API_KEY)

# ================= BOT SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class PolarDevBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.db = db
        self.ai = ai
    
    async def setup_hook(self):
        """Configuração inicial assíncrona"""
        await self.tree.sync()
        logger.info("✅ Comandos sincronizados")
        
        self.loop.create_task(self.change_status())
    
    async def change_status(self):
        """Task para mudar status periodicamente"""
        await self.wait_until_ready()
        
        statuses = [
            discord.Activity(type=discord.ActivityType.watching, name=f"/ajuda • Roblox Expert"),
            discord.Activity(type=discord.ActivityType.playing, name=f"Roblox Studio • {len(db.users)} devs"),
            discord.Activity(type=discord.ActivityType.listening, name=f"/criar_chat • {len(db.chats)} sistemas"),
            discord.Activity(type=discord.ActivityType.watching, name=f"Luau • Roblox Lua • Scripts")
        ]
        
        while not self.is_closed():
            for status in statuses:
                await self.change_presence(activity=status, status=discord.Status.online)
                await asyncio.sleep(60)

bot = PolarDevBot()

# ================= FUNÇÕES AUXILIARES =================
def generate_key() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    random_part = ''.join(random.choices(chars, k=KEY_LENGTH))
    return f"{KEY_PREFIX}{random_part[:4]}-{random_part[4:8]}-{random_part[8:12]}-{random_part[12:]}"

def format_credits(amount: float) -> str:
    return f"**{amount:.2f}** ⭐"

def create_embed(title: str, description: str = "", color: int = COLORS["primary"]) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now()
    )
    embed.set_footer(text="PolarDev • Especialista em Roblox Lua/Luau")
    return embed

def has_role(member: discord.Member, role_name: str) -> bool:
    return any(role.name == role_name for role in member.roles)

def is_ceo(member: discord.Member) -> bool:
    return has_role(member, CEO_ROLE)

def is_support(member: discord.Member) -> bool:
    return has_role(member, SUPPORT_ROLE) or is_ceo(member)

# ================= COMANDOS =================
@bot.tree.command(name="criar_key", description="🔑 Criar keys de créditos (CEO/Support)")
@app_commands.describe(
    creditos="Valor da key em créditos",
    quantidade="Quantidade de keys (1-5)"
)
async def criar_key(interaction: discord.Interaction, creditos: float, quantidade: int = 1):
    if not is_support(interaction.user):
        await interaction.response.send_message(
            embed=create_embed("❌ Permissão Negada", f"Requer cargo {SUPPORT_ROLE}+", COLORS["error"]),
            ephemeral=True
        )
        return
    
    if creditos <= 0 or quantidade > 5:
        await interaction.response.send_message(
            embed=create_embed("❌ Valores inválidos", "Créditos > 0 e Quantidade ≤ 5", COLORS["error"]),
            ephemeral=True
        )
        return
    
    keys = []
    for _ in range(quantidade):
        key = generate_key()
        db.create_key(key, str(interaction.user.id), creditos)
        keys.append(key)
    
    keys_text = "\n".join([f"`{k}`" for k in keys])
    
    embed = create_embed(
        "✅ Keys Criadas",
        f"**{quantidade}** key(s) de {format_credits(creditos)} cada:\n\n{keys_text}",
        COLORS["success"]
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="resgatar", description="🎁 Resgatar uma key de créditos")
@app_commands.describe(key="Digite a key para resgatar")
async def resgatar(interaction: discord.Interaction, key: str):
    if not key.startswith(KEY_PREFIX):
        await interaction.response.send_message(
            embed=create_embed("❌ Formato inválido", f"Key deve começar com {KEY_PREFIX}", COLORS["error"]),
            ephemeral=True
        )
        return
    
    credits = db.use_key(key, str(interaction.user.id))
    if credits is None:
        await interaction.response.send_message(
            embed=create_embed("❌ Key inválida", "Key não existe ou já foi usada", COLORS["error"]),
            ephemeral=True
        )
        return
    
    new_balance = db.add_credits(str(interaction.user.id), credits)
    
    embed = create_embed(
        "🎉 Key Resgatada!",
        f"✅ **Key:** `{key}`\n"
        f"💰 **Valor:** {format_credits(credits)}\n"
        f"👤 **Usuário:** {interaction.user.mention}\n"
        f"💳 **Novo saldo:** {format_credits(new_balance)}",
        COLORS["success"]
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="saldo", description="💰 Ver seus créditos")
async def saldo(interaction: discord.Interaction):
    user = db.get_user(str(interaction.user.id))
    
    if not user:
        embed = create_embed(
            "💳 Sistema de Créditos",
            "Você ainda não tem créditos.\nUse `/resgatar` com uma key válida para começar!",
            COLORS["info"]
        )
    else:
        embed = create_embed(
            f"💰 Saldo de {interaction.user.name}",
            f"💳 **Saldo atual:** {format_credits(user['credits'])}\n"
            f"🔑 **Keys resgatadas:** {user['keys_redeemed']}\n"
            f"🛠️ **Sistemas criados:** {user.get('total_creations', 0)}\n"
            f"📅 **Última atividade:** {datetime.fromisoformat(user['last_activity']).strftime('%d/%m %H:%M') if 'last_activity' in user else 'Nunca'}",
            COLORS["success"]
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="criar_chat", description="💬 Criar chat privado (GRÁTIS)")
@app_commands.describe(nome="Nome do chat (opcional)")
async def criar_chat(interaction: discord.Interaction, nome: Optional[str] = None):
    try:
        guild = interaction.guild
        
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            try:
                category = await guild.create_category(CATEGORY_NAME)
            except:
                await interaction.response.send_message(
                    embed=create_embed("❌ Erro", "Sem permissão para criar categoria.", COLORS["error"]),
                    ephemeral=True
                )
                return
        
        for channel in category.channels:
            if str(interaction.user.id) in channel.name:
                await interaction.response.send_message(
                    embed=create_embed("⚠️ Chat Existente", f"Você já tem um chat: {channel.mention}", COLORS["warning"]),
                    ephemeral=True
                )
                return
        
        base_name = nome.strip() if nome and nome.strip() else "roblox-dev"
        base_name = re.sub(r'[^\w\s-]', '', base_name)[:20]
        channel_name = f"{base_name}-{interaction.user.discriminator}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"🤖 Chat PolarDev com {interaction.user.name} • Especialista em Roblox Lua/Luau"
        )
        
        db.register_chat(str(channel.id), str(interaction.user.id), channel_name)
        
        welcome_embed = discord.Embed(
            title="🤖 BEM-VINDO AO POLARDEV ROBLOX STUDIO!",
            description=f"Olá {interaction.user.mention}! Sou a **PolarDev**, especialista em desenvolvimento Roblox Lua/Luau.\n\n"
                       f"🎮 **ESPECIALIZAÇÃO:**\n"
                       f"• Scripts, LocalScripts e ModuleScripts\n"
                       f"• Sistemas completos para Roblox Studio\n"
                       f"• Otimização e segurança Roblox\n"
                       f"• UI/UX, Databases, Gameplay\n\n"
                       f"💬 **PARA CONVERSAR:** Apenas pergunte sobre Roblox\n"
                       f"🛠️ **PARA CRIAR SISTEMAS:** Use o botão abaixo\n"
                       f"💰 **CUSTO:** {format_credits(COST_PER_CREATION)} por sistema completo\n\n"
                       f"⚠️ **ATENÇÃO:** Só respondo perguntas sobre Roblox!",
            color=COLORS["primary"],
            timestamp=datetime.now()
        )
        welcome_embed.set_footer(text="PolarDev • Especialista Roblox Lua/Luau")
        
        class ChatView(discord.ui.View):
            def __init__(self, user_id: str):
                super().__init__(timeout=None)
                self.user_id = user_id
            
            @discord.ui.button(label="🛠️ Criar Sistema Roblox", style=discord.ButtonStyle.primary, emoji="🎮", custom_id="create_roblox_system")
            async def create_system(self, interaction: discord.Interaction, button: discord.ui.Button):
                if str(interaction.user.id) != self.user_id:
                    await interaction.response.send_message("❌ Apenas o dono deste chat pode criar sistemas.", ephemeral=True)
                    return
                
                user_data = db.get_user(self.user_id)
                if not user_data or user_data["credits"] < COST_PER_CREATION:
                    await interaction.response.send_message(
                        f"❌ Créditos insuficientes. Você precisa de {format_credits(COST_PER_CREATION)}.\n"
                        f"Use `/resgatar` para adicionar créditos.",
                        ephemeral=True
                    )
                    return
                
                modal = RobloxSystemCreationModal(self.user_id)
                await interaction.response.send_modal(modal)
        
        await channel.send(embed=welcome_embed, view=ChatView(str(interaction.user.id)))
        
        embed = create_embed(
            "✅ Chat Roblox Criado!",
            f"Seu chat privado foi criado: {channel.mention}\n\n"
            f"🎮 **AGORA VOCÊ PODE:**\n"
            f"• Criar sistemas completos para Roblox\n"
            f"• Obter código Lua/Luau profissional\n"
            f"• Aprender desenvolvimento Roblox\n"
            f"• Resolver problemas específicos\n\n"
            f"💡 **DICA:** Use o botão **🎮 Criar Sistema Roblox** para gerar\n"
            f"Scripts, LocalScripts e ModuleScripts completos!",
            COLORS["success"]
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
    except Exception as e:
        logger.error(f"Erro criar_chat: {e}")
        await interaction.response.send_message(
            embed=create_embed("❌ Erro", "Não foi possível criar o chat.", COLORS["error"]),
            ephemeral=True
        )

class RobloxSystemCreationModal(discord.ui.Modal, title="🎮 Criar Sistema Roblox"):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        
        self.description = discord.ui.TextInput(
            label="Descreva o sistema Roblox em detalhes",
            placeholder="Ex: Sistema de inventário com arrastar/soltar UI, salvar no DataStore, otimizado para 50 jogadores, com slots e categorias",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        
        self.add_item(self.description)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        user_data = db.get_user(self.user_id)
        if not user_data or user_data["credits"] < COST_PER_CREATION:
            await interaction.followup.send(
                embed=create_embed("❌ Créditos Insuficientes", f"Você precisa de {format_credits(COST_PER_CREATION)}.", COLORS["error"]),
                ephemeral=True
            )
            return
        
        if not db.deduct_credits(self.user_id, COST_PER_CREATION):
            await interaction.followup.send(
                embed=create_embed("❌ Erro", "Falha ao processar créditos.", COLORS["error"]),
                ephemeral=True
            )
            return
        
        processing_embed = create_embed(
            "⏳ PolarDev está criando seu sistema Roblox...",
            f"**SISTEMA:** {self.description.value[:200]}...\n\n"
            f"🎮 **PLATAFORMA:** Roblox Studio\n"
            f"📝 **LINGUAGEM:** Lua/Luau\n"
            f"📦 **SAÍDA:** Scripts, LocalScripts, ModuleScripts\n"
            f"⚡ **STATUS:** Gerando código profissional...\n\n"
            f"Isso pode levar até 45 segundos para sistemas complexos.",
            COLORS["info"]
        )
        await interaction.followup.send(embed=processing_embed)
        
        try:
            creation_task = asyncio.create_task(ai.create_roblox_system(self.description.value))
            result = await asyncio.wait_for(creation_task, timeout=60)
            
            if result["success"]:
                success_embed = create_embed(
                    "✅ SISTEMA ROBLOX CRIADO COM SUCESSO!",
                    f"**DESCRIÇÃO:** {self.description.value[:150]}...\n\n"
                    f"🎮 **PLATAFORMA:** Roblox Studio\n"
                    f"📦 **ARQUIVOS:** {len(result['code_blocks'])} scripts gerados\n"
                    f"💰 **CUSTO:** {format_credits(COST_PER_CREATION)} deduzido\n"
                    f"💳 **NOVO SALDO:** {format_credits(user_data['credits'] - COST_PER_CREATION)}\n"
                    f"🤖 **IA:** Groq Llama 3 70B\n\n"
                    f"⬇️ **CÓDIGO LUA/LUAU ABAIXO:**",
                    COLORS["creation"]
                )
                
                await interaction.channel.send(embed=success_embed)
                
                for code_block in result["code_blocks"]:
                    filename = code_block["filename"]
                    code = code_block["code"]
                    script_type = code_block["type"]
                    path = code_block["path"]
                    
                    file_embed = create_embed(
                        f"📄 {filename}",
                        f"**TIPO:** {script_type}\n"
                        f"**LOCAL:** {path}\n"
                        f"**TAMANHO:** {len(code)} caracteres",
                        COLORS["info"]
                    )
                    await interaction.channel.send(embed=file_embed)
                    
                    if len(code) > 1900:
                        chunks = [code[i:i+1900] for i in range(0, len(code), 1900)]
                        for i, chunk in enumerate(chunks, 1):
                            if chunk.strip():
                                await interaction.channel.send(f"**Parte {i}/{len(chunks)}:**\n```lua\n{chunk}\n```")
                    else:
                        await interaction.channel.send(f"```lua\n{code}\n```")
                    
                    await asyncio.sleep(1)
                
                instructions_embed = create_embed(
                    "📋 GUIA DE INSTALAÇÃO NO ROBLOX STUDIO",
                    f"{result['instructions']}\n\n"
                    f"🔧 **DICAS IMPORTANTES PARA ROBLOX:**\n"
                    f"1. Teste SEMPRE em Play Solo primeiro\n"
                    f"2. Verifique o Output para erros\n"
                    f"3. Ajuste IDs e nomes conforme seu jogo\n"
                    f"4. Faça backup antes de publicar",
                    COLORS["primary"]
                )
                await interaction.channel.send(embed=instructions_embed)
                
                final_embed = create_embed(
                    "🎯 PRONTO PARA USAR!",
                    f"Seu sistema Roblox está completo e pronto para implementar.\n\n"
                    f"🔧 **PRECISA DE AJUSTES?**\n"
                    f"Descreva o problema no chat e eu ajudo a corrigir!\n\n"
                    f"🎮 **BOA SORTE COM SEU JOGO ROBLOX!**",
                    COLORS["success"]
                )
                await interaction.channel.send(embed=final_embed)
                
            else:
                db.add_credits(self.user_id, COST_PER_CREATION)
                await interaction.followup.send(
                    embed=create_embed("❌ ERRO NA CRIAÇÃO", 
                                     f"{result['error']}\n\n"
                                     "**Seus créditos foram devolvidos.**\n\n"
                                     "Possíveis causas:\n"
                                     "• Descrição não é sobre Roblox\n"
                                     "• API temporariamente indisponível\n"
                                     "• Descrição muito vaga\n\n"
                                     "**SUGESTÕES:**\n"
                                     "1. Seja específico sobre Roblox\n"
                                     "2. Descreva scripts, mecânicas, sistemas\n"
                                     "3. Tente novamente em 1-2 minutos",
                                     COLORS["error"]),
                    ephemeral=True
                )
                
        except asyncio.TimeoutError:
            db.add_credits(self.user_id, COST_PER_CREATION)
            await interaction.followup.send(
                embed=create_embed("⏱️ TIMEOUT", 
                                 "A criação demorou muito (mais de 60 segundos).\n"
                                 "**Seus créditos foram devolvidos.**\n\n"
                                 "Tente com uma descrição mais específica.",
                                 COLORS["error"]),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Erro na criação: {e}")
            db.add_credits(self.user_id, COST_PER_CREATION)
            await interaction.followup.send(
                embed=create_embed("❌ ERRO INESPERADO", 
                                 f"Ocorreu um erro inesperado.\n"
                                 "**Seus créditos foram devolvidos.**\n\n"
                                 "Tente novamente ou contate suporte.",
                                 COLORS["error"]),
                ephemeral=True
            )

@bot.tree.command(name="ping", description="🏓 Verifica latência do bot")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = create_embed(
        "🏓 Pong! - Roblox Specialist",
        f"📡 **Latência:** {latency}ms\n"
        f"🎮 **ESPECIALIDADE:** Roblox Lua/Luau\n"
        f"🤖 **IA:** Groq (Llama 3 70B) - GRATUITA\n"
        f"👥 **Desenvolvedores:** {len(db.users)}\n"
        f"💬 **Sistemas ativos:** {len(db.chats)}\n"
        f"🌐 **Status:** Online ✅",
        COLORS["primary"]
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ajuda", description="❓ Ajuda e comandos")
async def ajuda(interaction: discord.Interaction):
    embed = create_embed(
        "❓ AJUDA DO POLARDEV - ROBLOX SPECIALIST",
        "**🤖 POLARDEV - ESPECIALISTA EM ROBLOX LUA/LUAU**\n"
        "Sou especializado exclusivamente em desenvolvimento Roblox.\n\n"
        "**🎮 O QUE POSSO FAZER:**\n"
        "✅ **Scripts Roblox** - Server e Client\n"
        "✅ **Sistemas completos** - Inventário, Combate, UI, etc.\n"
        "✅ **Otimização** - Performance para múltiplos jogadores\n"
        "✅ **Segurança** - Anti-exploit e validações\n"
        "✅ **Boas práticas** - Código limpo e organizado\n\n"
        "**⚠️ RESTRIÇÕES:**\n"
        "❌ NÃO crio código para outras plataformas\n"
        "❌ NÃO respondo perguntas não relacionadas a Roblox\n"
        "❌ NÃO gero conteúdo fora do Roblox Studio",
        COLORS["primary"]
    )
    
    embed.add_field(
        name="🔑 **COMANDOS DE CRÉDITOS**",
        value=f"`/resgatar` - Resgatar key de créditos\n"
              f"`/saldo` - Ver seu saldo\n"
              f"`/criar_key` - Criar keys ({SUPPORT_ROLE}+)",
        inline=False
    )
    
    embed.add_field(
        name="💬 **COMANDOS DE CHAT**",
        value="`/criar_chat` - Criar chat privado para Roblox",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ **CRIAÇÃO DE SISTEMAS ROBLOX**",
        value=f"• No chat, clique em **🎮 Criar Sistema Roblox**\n"
              f"• Descreva o sistema EM DETALHES\n"
              f"• Receba Scripts, LocalScripts e ModuleScripts\n"
              f"• Guia completo de instalação no Roblox Studio\n"
              f"• **Custo:** {format_credits(COST_PER_CREATION)} por sistema",
        inline=False
    )
    
    embed.add_field(
        name="🎯 **EXEMPLOS DE SISTEMAS ROBLOX**",
        value="• Sistema de Inventário com UI\n• Sistema de Combate com hitboxes\n• Loja com economia segura\n• Sistema de XP e níveis\n• GUI complexa com animações\n• DataStore otimizado\n• Sistema de missões\n• Ferramentas customizadas\n• Qualquer sistema para Roblox!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# ================= EVENTOS =================
@bot.event
async def on_ready():
    print(f"\n{'='*60}")
    print(f"🤖 POLARDEV BOT - ESPECIALISTA ROBLOX")
    print(f"🔗 Nome: {bot.user.name}")
    print(f"🆔 ID: {bot.user.id}")
    print(f"🎮 ESPECIALIDADE: Roblox Lua/Luau")
    print(f"🧠 IA: Groq (Llama 3 70B) - GRATUITA")
    print(f"🌐 Flask: http://0.0.0.0:8080")
    print(f"👥 Desenvolvedores: {len(db.users)}")
    print(f"💬 Sistemas Roblox: {len(db.chats)}")
    print(f"{'='*60}\n")
    print("✅ Bot 100% funcional como especialista Roblox!")
    print("🎮 Só responde perguntas sobre Roblox Studio")
    print("📝 Teste: /criar_chat → 🎮 Criar Sistema Roblox")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    
    if not isinstance(message.channel, discord.TextChannel):
        return
    
    if not message.channel.category:
        return
    
    if message.channel.category.name == CATEGORY_NAME:
        if str(message.channel.id) not in db.chats:
            return
        
        if message.content.startswith(('!', '/', '\\')):
            return
        
        try:
            async with message.channel.typing():
                response = await ai.generate_response(message.content)
            
            if response:
                await message.channel.send(response)
            else:
                await message.channel.send("🤖 Estou processando. Para sistemas completos, use o botão 🎮 Criar Sistema Roblox.")
        
        except Exception as e:
            logger.error(f"Erro ao responder: {e}")

# ================= INICIALIZAÇÃO =================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 INICIANDO POLARDEV - ESPECIALISTA ROBLOX")
    print("="*60 + "\n")
    
    keep_alive()
    print("✅ Flask iniciado - Bot sempre ativo no Render")
    
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\n👋 Bot interrompido pelo usuário")
        db.save_all()
    except discord.LoginFailure:
        print("❌ TOKEN DO DISCORD INVÁLIDO!")
        print("Verifique o arquivo .env")
    except Exception as e:
        print(f"❌ ERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
