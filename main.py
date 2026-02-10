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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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

if not OPENROUTER_API_KEY:
    print("❌ ERRO: OPENROUTER_API_KEY não encontrada!")
    print("📝 Obtenha em: https://openrouter.ai")
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

# ================= IA OPENROUTER PROFISSIONAL (COM REQUESTS) =================
class PolarDevAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.timeout = 30
        
        # Prompt profissional para OpenRouter
        self.system_prompt = """Você é PolarDev, especialista sênior em desenvolvimento Roblox Lua. Você possui 10+ anos de experiência criando sistemas complexos para produção.

SEU ESTILO:
1. Código Lua COMPLETO e pronto para uso
2. Explicações técnicas claras
3. Boas práticas de performance
4. Tratamento de erros robusto
5. Arquitetura modular e escalável

FORMATO DE RESPOSTA PARA CONVERSAS:
- Respostas diretas e informativas
- Exemplos de código quando relevante
- Dicas de otimização
- Referências à documentação oficial

FORMATO PARA CRIAÇÃO DE SISTEMAS:
--[[
    SISTEMA: [Nome]
    AUTOR: PolarDev
    DESCRIÇÃO: [Descrição breve]
    VERSÃO: 1.0.0
]]

-- Módulo principal
local Sistema = {}
Sistema.__index = Sistema

-- Configurações
local Configuracoes = {
    -- Configurações ajustáveis
}

-- Funções públicas
function Sistema.new()
    -- Implementação
end

-- Funções privadas
local function funcaoPrivada()
    -- Implementação
end

return Sistema

SEMPRE inclua:
1. Código Lua completo e funcional
2. Comentários explicativos em português
3. Instruções de implementação
4. Considerações de performance
5. Possíveis extensões"""

    async def make_request(self, messages: List[Dict], max_tokens: int = 2000, is_creation: bool = False) -> Optional[str]:
        """Faz requisição para OpenRouter API usando requests"""
        try:
            # Modelo mais poderoso do OpenRouter
            model = "mistralai/mixtral-8x7b-instruct"
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
                "stream": False
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://polar.dev",
                "X-Title": "PolarDev Bot"
            }
            
            # Usando requests com asyncio para não bloquear
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
                logger.warning("Rate limit atingido, aguardando...")
                await asyncio.sleep(5)
                return None
            else:
                error_text = response.text[:200]
                logger.error(f"OpenRouter Error {response.status_code}: {error_text}")
                return None
                
        except requests.Timeout:
            logger.warning("Timeout na requisição")
            return None
        except requests.RequestException as e:
            logger.error(f"Erro de conexão: {e}")
            return None
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            return None
    
    async def generate_response(self, message: str) -> str:
        """Gera resposta para conversas normais"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"PERGUNTA: {message}\n\nResponda de forma útil e direta sobre desenvolvimento Roblox."}
        ]
        
        response = await self.make_request(messages, max_tokens=1000)
        
        if response:
            return response
        else:
            return "🤖 Estou processando sua solicitação. Se a resposta demorar, tente reformular ou usar o botão de criação de sistemas."
    
    async def create_system(self, description: str) -> Optional[str]:
        """Cria um sistema Roblox completo"""
        prompt = f"""CRIE UM SISTEMA COMPLETO DE ROBLOX LUA

DESCRIÇÃO DO CLIENTE:
{description}

REQUISITOS TÉCNICOS:
1. Código Lua 100% funcional e completo
2. Organizado em ModuleScripts quando necessário
3. Tratamento de erros robusto com pcall()
4. Performance otimizada (sem waits desnecessários)
5. Comentários em português explicando cada seção
6. Pronto para copiar e colar no Roblox Studio

ESTRUTURA OBRIGATÓRIA:
--[[
    SISTEMA: [Nome apropriado baseado na descrição]
    AUTOR: PolarDev
    DESCRIÇÃO: [Descrição detalhada do sistema]
    VERSÃO: 1.0.0
    DATA: {datetime.now().strftime('%d/%m/%Y')}
]]

-- Módulo principal
local Sistema = {{}}
Sistema.__index = Sistema

-- Configurações (ajustáveis pelo desenvolvedor)
local Config = {{
    Debug = true,
    -- Adicione mais configurações conforme necessário
}}

-- Métodos privados
local function metodoPrivado()
    -- Implementação
end

-- Métodos públicos
function Sistema.new()
    local self = setmetatable({{}}, Sistema)
    -- Inicialização
    return self
end

function Sistema:Start()
    -- Lógica principal
end

-- Inicialização e retorno
return Sistema

FORNEÇA:
1. Código completo como especificado acima
2. Breve explicação de como implementar
3. Dicas de otimização específicas para este sistema
4. Exemplos de uso prático

O código deve ser PROFISSIONAL e PRONTO PARA PRODUÇÃO."""
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        # Tenta até 3 vezes com delays crescentes
        for attempt in range(3):
            response = await self.make_request(messages, max_tokens=3500, is_creation=True)
            if response:
                return response
            
            if attempt < 2:
                wait_time = (attempt + 1) * 3  # 3, 6 segundos
                logger.info(f"Tentativa {attempt + 1} falhou, aguardando {wait_time}s...")
                await asyncio.sleep(wait_time)
        
        return None

ai = PolarDevAI(OPENROUTER_API_KEY)

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
        
        # Inicia a task de mudar status
        self.loop.create_task(self.change_status())
    
    async def change_status(self):
        """Task para mudar status periodicamente"""
        await self.wait_until_ready()
        
        statuses = [
            discord.Activity(type=discord.ActivityType.watching, name=f"/ajuda • IA Profissional"),
            discord.Activity(type=discord.ActivityType.playing, name=f"Roblox Studio • {len(db.users)} usuários"),
            discord.Activity(type=discord.ActivityType.listening, name=f"/criar_chat • {len(db.chats)} chats"),
            discord.Activity(type=discord.ActivityType.watching, name=f"OpenRouter • Mixtral 8x7B")
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
    embed.set_footer(text="PolarDev • Sistema Criador Profissional")
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
            f"🛠️ **Criações feitas:** {user.get('total_creations', 0)}\n"
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
        
        base_name = nome.strip() if nome and nome.strip() else "dev"
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
            topic=f"Chat da PolarDev com {interaction.user.name} • Use /ajuda para comandos"
        )
        
        db.register_chat(str(channel.id), str(interaction.user.id), channel_name)
        
        welcome_embed = discord.Embed(
            title="🤖 Bem-vindo ao PolarDev Chat!",
            description=f"Olá {interaction.user.mention}! Eu sou a **PolarDev**, sua IA especializada em desenvolvimento Roblox.\n\n"
                       f"💬 **Para conversar:** Basta enviar mensagens\n"
                       f"🛠️ **Para criar sistemas:** Use o botão abaixo\n"
                       f"💰 **Custo por criação:** {format_credits(COST_PER_CREATION)}\n\n"
                       f"🎯 **Especialidades:**\n"
                       f"• Sistemas Lua complexos\n• Otimização de performance\n"
                       f"• Arquitetura de projetos\n• Solução de bugs\n• Boas práticas",
            color=COLORS["primary"],
            timestamp=datetime.now()
        )
        welcome_embed.set_footer(text="PolarDev • IA Profissional")
        
        class ChatView(discord.ui.View):
            def __init__(self, user_id: str):
                super().__init__(timeout=None)
                self.user_id = user_id
            
            @discord.ui.button(label="🛠️ Criar Sistema Roblox", style=discord.ButtonStyle.primary, emoji="🛠️", custom_id="create_system")
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
                
                modal = SystemCreationModal(self.user_id)
                await interaction.response.send_modal(modal)
        
        await channel.send(embed=welcome_embed, view=ChatView(str(interaction.user.id)))
        
        embed = create_embed(
            "✅ Chat Criado!",
            f"Seu chat privado foi criado: {channel.mention}\n\n"
            f"✨ **Agora você pode:**\n"
            f"• Conversar com a IA PolarDev\n"
            f"• Criar sistemas profissionais\n"
            f"• Obter suporte especializado\n\n"
            f"💡 **Dica:** Use o botão **🛠️ Criar Sistema Roblox** para gerar código Lua completo.",
            COLORS["success"]
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
    except Exception as e:
        logger.error(f"Erro criar_chat: {e}")
        await interaction.response.send_message(
            embed=create_embed("❌ Erro", "Não foi possível criar o chat.", COLORS["error"]),
            ephemeral=True
        )

class SystemCreationModal(discord.ui.Modal, title="🛠️ Criar Sistema Roblox"):
    def __init__(self, user_id: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        
        self.description = discord.ui.TextInput(
            label="Descreva o sistema em detalhes",
            placeholder="Ex: Sistema de inventário com UI drag-and-drop, database, otimizado para 50+ jogadores",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
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
        
        # Deduz créditos primeiro
        if not db.deduct_credits(self.user_id, COST_PER_CREATION):
            await interaction.followup.send(
                embed=create_embed("❌ Erro", "Falha ao processar créditos.", COLORS["error"]),
                ephemeral=True
            )
            return
        
        # Mostra que está processando
        processing_embed = create_embed(
            "⏳ Processando...",
            "A PolarDev está criando seu sistema profissional.\nIsso pode levar alguns segundos.",
            COLORS["info"]
        )
        await interaction.followup.send(embed=processing_embed)
        
        # Tenta criar o sistema
        try:
            creation_task = asyncio.create_task(ai.create_system(self.description.value))
            creation = await asyncio.wait_for(creation_task, timeout=45)
            
            if creation:
                # Sucesso
                success_embed = create_embed(
                    "✅ Sistema Criado com Sucesso!",
                    f"**Solicitação:** {self.description.value[:150]}...\n\n"
                    f"💰 **Custo:** {format_credits(COST_PER_CREATION)} deduzido\n"
                    f"💳 **Novo saldo:** {format_credits(user_data['credits'] - COST_PER_CREATION)}\n"
                    f"⏱️ **Tempo de criação:** {datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"📜 **Código Lua profissional gerado abaixo:**",
                    COLORS["creation"]
                )
                
                await interaction.channel.send(embed=success_embed)
                
                # Envia o código em partes se necessário
                if len(creation) > 1900:
                    chunks = [creation[i:i+1900] for i in range(0, len(creation), 1900)]
                    for i, chunk in enumerate(chunks, 1):
                        if chunk.strip():
                            await interaction.channel.send(f"**📄 Parte {i}:**\n```lua\n{chunk}\n```")
                else:
                    await interaction.channel.send(f"```lua\n{creation}\n```")
                    
                # Envia dica final
                tip_embed = create_embed(
                    "💡 Dicas de Implementação",
                    "**Para usar este código:**\n"
                    "1. Copie o código completo\n"
                    "2. Cole em um ModuleScript no Roblox Studio\n"
                    "3. Requira o módulo onde precisar\n"
                    "4. Ajuste as configurações conforme necessário\n\n"
                    "🔄 **Precisa de ajustes?** Basta pedir!",
                    COLORS["info"]
                )
                await interaction.channel.send(embed=tip_embed)
                
            else:
                # Falha - devolve créditos
                db.add_credits(self.user_id, COST_PER_CREATION)
                await interaction.followup.send(
                    embed=create_embed("❌ Falha na Criação", 
                                     "Não foi possível gerar o sistema no momento.\n"
                                     "**Seus créditos foram devolvidos.**\n\n"
                                     "Possíveis causas:\n"
                                     "• API temporariamente indisponível\n"
                                     "• Descrição muito complexa\n"
                                     "• Limite de requisições\n\n"
                                     "Tente novamente em alguns minutos.",
                                     COLORS["error"]),
                    ephemeral=True
                )
                
        except asyncio.TimeoutError:
            # Timeout - devolve créditos
            db.add_credits(self.user_id, COST_PER_CREATION)
            await interaction.followup.send(
                embed=create_embed("⏱️ Timeout", 
                                 "A criação demorou muito tempo.\n"
                                 "**Seus créditos foram devolvidos.**\n\n"
                                 "Tente com uma descrição mais específica ou aguarde alguns minutos.",
                                 COLORS["error"]),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Erro na criação: {e}")
            db.add_credits(self.user_id, COST_PER_CREATION)
            await interaction.followup.send(
                embed=create_embed("❌ Erro Inesperado", 
                                 "Ocorreu um erro inesperado.\n"
                                 "**Seus créditos foram devolvidos.**\n\n"
                                 "Tente novamente ou contate suporte.",
                                 COLORS["error"]),
                ephemeral=True
            )

@bot.tree.command(name="ping", description="🏓 Verifica latência do bot")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = create_embed(
        "🏓 Pong!",
        f"📡 **Latência:** {latency}ms\n"
        f"🤖 **IA:** OpenRouter (Mixtral 8x7B)\n"
        f"💾 **Usuários:** {len(db.users)}\n"
        f"💬 **Chats ativos:** {len(db.chats)}\n"
        f"🌐 **Status:** Online ✅",
        COLORS["primary"]
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ajuda", description="❓ Ajuda e comandos")
async def ajuda(interaction: discord.Interaction):
    embed = create_embed(
        "❓ Ajuda do PolarDev Bot",
        "**🤖 IA PolarDev - OpenRouter Mixtral 8x7B**\n"
        "Especializada em desenvolvimento Roblox profissional.\n\n"
        "**💎 Diferenciais:**\n"
        "✅ **Código de produção** - Pronto para usar\n"
        "✅ **Explicações detalhadas** - Entenda cada parte\n"
        "✅ **Performance otimizada** - Código eficiente\n"
        "✅ **Arquitetura modular** - Fácil manutenção\n"
        "✅ **Suporte em português** - Respostas claras",
        COLORS["primary"]
    )
    
    embed.add_field(
        name="🔑 **COMANDOS DE CRÉDITOS**",
        value=f"`/resgatar` - Resgatar key de créditos\n"
              f"`/saldo` - Ver seu saldo e estatísticas\n"
              f"`/criar_key` - Criar keys ({SUPPORT_ROLE}+)",
        inline=False
    )
    
    embed.add_field(
        name="💬 **COMANDOS DE CHAT**",
        value="`/criar_chat` - Criar chat privado com a IA",
        inline=False
    )
    
    embed.add_field(
        name="🛠️ **CRIAÇÃO DE SISTEMAS**",
        value=f"• No chat, clique em **🛠️ Criar Sistema Roblox**\n"
              f"• Descreva o sistema em detalhes\n"
              f"• Receba código Lua completo e profissional\n"
              f"• **Custo:** {format_credits(COST_PER_CREATION)} por criação",
        inline=False
    )
    
    embed.add_field(
        name="🎯 **EXEMPLOS DE SISTEMAS**",
        value="• Inventários complexos\n• Sistemas de combate\n• Economia e trading\n• UI/UX Roblox\n• Data stores\n• Matchmaking\n• E muito mais!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# ================= EVENTOS =================
@bot.event
async def on_ready():
    print(f"\n{'='*60}")
    print(f"🤖 POLARDEV BOT - OPENROUTER EDITION")
    print(f"🔗 Nome: {bot.user.name}")
    print(f"🆔 ID: {bot.user.id}")
    print(f"🧠 IA: OpenRouter Mixtral 8x7B")
    print(f"🌐 Flask: http://0.0.0.0:8080")
    print(f"👥 Usuários: {len(db.users)}")
    print(f"💬 Chats: {len(db.chats)}")
    print(f"{'='*60}\n")
    print("✅ Bot 100% funcional com IA profissional!")
    print("🌐 Flask rodando para manter ativo no Render")
    print("📝 Teste agora: /criar_chat → Conversar → 🛠️ Criar Sistema")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    
    if not isinstance(message.channel, discord.TextChannel):
        return
    
    if not message.channel.category:
        return
    
    if message.channel.category.name == CATEGORY_NAME:
        # Verifica se é um chat registrado
        if str(message.channel.id) not in db.chats:
            return
        
        # Ignora comandos com prefixo
        if message.content.startswith(('!', '/', '\\')):
            return
        
        try:
            # Mostra "digitando..."
            async with message.channel.typing():
                # Tenta gerar resposta com IA
                response = await ai.generate_response(message.content)
            
            # Envia resposta
            if response:
                await message.channel.send(response)
            else:
                await message.channel.send("🤖 Estou processando sua solicitação. Para sistemas complexos, use o botão 🛠️ Criar Sistema.")
        
        except Exception as e:
            logger.error(f"Erro ao responder: {e}")
            # Não envia erro para não poluir o chat

# ================= INICIALIZAÇÃO =================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 INICIANDO POLARDEV BOT COM OPENROUTER IA")
    print("="*60 + "\n")
    
    # Inicia Flask para manter ativo
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
