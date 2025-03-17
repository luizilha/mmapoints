
import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
import sqlite3
import re
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN") or ""
API_URL = os.getenv("API_URL") or ""

# Configuração do sistema de logs
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=TOKEN)
dp = Dispatcher()


async def get_admins(chat_id: int):
    try:
        administrators = await bot.get_chat_administrators(chat_id)
        logging.info(f"Admins obtidos para o chat {chat_id}")
        return administrators
    except Exception as e:
        logging.error(f"Erro ao obter administradores: {e}")
        return None


def criar_tabelas():
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        logging.info("Criando tabelas...")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS palpite (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_usuario INTEGER,
                username TEXT,
                id_luta INTEGER,
                escolha TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ranking (
                id_usuario INTEGER PRIMARY KEY,
                username TEXT,
                pontos INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        logging.info("Tabelas criadas com sucesso")
    except sqlite3.Error as e:
        logging.error(f"Erro ao criar tabelas: {e}")
    finally:
        conn.close()


@dp.message(Command("ranking"))
async def ranking(message: types.Message):
    try:
        conn = sqlite3.connect("bot.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, pontos FROM ranking WHERE username IS NOT NULL AND username != '' ORDER BY pontos DESC, username ASC LIMIT 10")

        ranking_data = cursor.fetchall()
        conn.close()

        if not ranking_data:
            await message.reply("Ranking vazio.")
            return

        ranking_msg = "🏆 *Ranking Top 10* 🏆\n\n"
        posicao = 1
        ultima_pontuacao = None
        empatados = []

        for username, pontos in ranking_data:
            if username is None:
                continue
            if ultima_pontuacao is None or pontos == ultima_pontuacao:
                empatados.append(f"@{username}")
            else:
                ranking_msg += (f"{posicao} - {', '.join(empatados)}"
                                f"({ultima_pontuacao} pontos)\n")
                posicao += len(empatados)
                empatados = [f"@{username}"]
            ultima_pontuacao = pontos
        if empatados:
            ranking_msg += (f"{posicao} - {', '.join(empatados)}"
                            f"({ultima_pontuacao} pontos)\n")

        await message.reply(ranking_msg)
    except sqlite3.Error as e:
        logging.error(f"Erro ao obter ranking: {e}")
        await message.reply("Erro ao buscar ranking.")


def atualizar_ranking(id_luta, vencedor):
    try:
        conn = sqlite3.connect("bot.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id_usuario, username FROM palpite WHERE id_luta = ? AND REPLACE(LOWER(escolha), ' ', '') = REPLACE(LOWER(?), ' ', '')", (id_luta, vencedor))

        apostadores = cursor.fetchall()
        logging.info(f"apostadores {apostadores}")

        for id_usuario, username in apostadores:
            cursor.execute(
                "INSERT INTO ranking (id_usuario, username, pontos) VALUES (?, ?, 1) ON CONFLICT(id_usuario) DO UPDATE SET pontos = pontos + 1", (id_usuario, username))

        conn.commit()
        logging.info(
            f"Ranking atualizado para luta {id_luta} e vencedor {vencedor}")

        # Removendo palpites da luta processada
        cursor.execute("DELETE FROM palpite WHERE id_luta = ?", (id_luta,))
        conn.commit()
        logging.info(f"Palpites removidos para a luta {id_luta}")
    except sqlite3.Error as e:
        logging.error(f"Erro ao atualizar ranking: {e}")
    finally:
        conn.close()


async def fetch_fights():
    async with aiohttp.ClientSession() as session:
        try:
            logging.info("Fazendo requisição para a API...")
            async with session.get(API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    fights = []
                    fight_card = data.get("LiveEventDetail", {}).get(
                        "FightCard")  # obtem o FightCard

                    for fight in fight_card:

                        if fight.get("CardSegment") == "Main":
                            vs = ""
                            commands = ""
                            winner = ""
                            fightId = fight.get('FightId')
                            for index, fighter in enumerate(fight.get("Fighters", [])):
                                name = fighter.get("Name", {})
                                commands += f"/ganha_{fightId}_{name.get('FirstName')}{name.get('LastName')}\n"

                                if fighter.get("Outcome").get("OutcomeId") == 1:
                                    winner += f"{name.get('FirstName')} {name.get('LastName')}"
                                vs += f"{name.get('FirstName')} {name.get('LastName')}"
                                vs += " VS " if index == 0 else "."

                            logging.error(f"STATUS: {fights.__len__()}")
                            if fights.__len__() > 4:
                                continue

                            fights.append(f"\U0001F94A {vs}\n")
                            status = fight.get("Status")

                            if status == "Final":
                                atualizar_ranking(fightId, winner)
                                fights.append(
                                    f"{fight.get('Result').get('Method')} = {winner} \n")
                            elif status == "Live":
                                fights.append("AO VIVO.\n")
                            else:
                                fights.append(f"{commands}")
                    return fights
                else:
                    logging.error(f"Erro na requisição: {response.status}")
                    return []
        except Exception as e:
            logging.error(f"Erro ao buscar lutas: {e}")
            return []


@dp.message(Command("start"))
async def start(message: types.Message):
    # admins = await get_admins(message.chat.id)
    # listaAdmins = "Qualquer treta incomode as quengas abaixo. \n"
    # for admin in admins:
    #     listaAdmins += f"@{admin.user.username} \n"
    logging.info(f"Comando /start recebido de {message.from_user.id}")
    fights = await fetch_fights()
    if fights:
        fights_text = "\n".join(fights)
        await message.reply((f"\nBem-vindo ao Bot de palpite de Lutas do"
                             f"UFC MIL GRAU \n{fights_text}"))
    else:
        await message.reply(("Bem-vindo ao Bot de palpite de Lutas!\n"
                             "Nenhuma luta encontrada"))


async def verificar_status_luta(fight_id):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    fight_card = data.get(
                        "LiveEventDetail", {}).get("FightCard")
                    for fight in fight_card:
                        if int(fight.get("FightId")) == int(fight_id):
                            if (fight.get("Status") == "Final" or fight.get("Status") == "Live"):
                                return True
                    return False
        except Exception as e:
            logging.error(f"Erro ao buscar status da luta: {e}")


@dp.message()
async def handle_ganha(message: types.Message):
    if message.text is not None:
        text = message.text.split("@")[0]
    else:
        return
    match = re.match(r"^/ganha_(\d+)_(\w+)([A-Z][a-z]+)$", text)
    if match:
        fight_id, first_name, last_name = match.groups()
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        if await verificar_status_luta(fight_id):
            await message.reply("Essa luta esta sendo transmitida ou já foi finalizada. Não é possível enviar palpites.")
            return

        logging.info(
            f"Palpite recebido: Nome: {first_name}, Sobrenome: {last_name}, Usuário: {user_id}")

        try:
            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM palpite WHERE id_usuario = ? AND id_luta = ?",
                (user_id, fight_id))
            existing = cursor.fetchone()

            if existing:
                cursor.execute(("UPDATE palpite SET escolha = ?"
                                "WHERE id_usuario = ? AND id_luta = ?"), (
                    f"{first_name} {last_name}", user_id, fight_id))
                # message_text = f"Seu palpite foi atualizado! @{username}"
            else:
                cursor.execute(("INSERT INTO palpite (id_usuario, id_luta, "
                                "username, escolha) VALUES (?, ?, ?, ?)"), (
                    user_id, fight_id, username, f"{first_name} {last_name}"))
                # message_text = f"Seu palpite foi registrado! @{username}"

            conn.commit()
            conn.close()
            # await message.reply(f"{message_text} Nome: *{first_name} {last_name}*")
        except sqlite3.Error as e:
            logging.error(f"Erro ao salvar palpite: {e}")
            await message.reply("Erro ao registrar o palpite. Tente novamente.")


async def main():
    logging.info("Iniciando bot...")
    criar_tabelas()
    session = AiohttpSession()
    bot = Bot(token=TOKEN, session=session)
    logging.info("Iniciando polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Erro crítico: {e}")
