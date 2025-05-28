import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
import requests  


TOKEN = "TOKEN"  # Ersetzen Sie TOKEN durch Ihren tatsächlichen Bot-Token


intents = discord.Intents.default()
intents.members = True
intents.message_content = True


bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'Eingeloggt als {bot.user}')


@bot.command()
async def redeem(ctx, key: str):
    conn = sqlite3.connect('key_system.db')
    conn.row_factory = sqlite3.Row  
    c = conn.cursor()

   
    c.execute('SELECT * FROM keys WHERE key = ?', (key,))
    result = c.fetchone()

    if result:
        uses_left = result['uses_left']
        duration_days = result['duration_days']

        if uses_left > 0:
            role_id = 1377257004577587271  # ID der Rolle "Buyer"
            role = ctx.guild.get_role(role_id)

            if role:
                await ctx.author.add_roles(role)
                await ctx.send(f"Key {key} wurde erfolgreich eingelöst! Rolle '{role.name}' wurde zugewiesen.")

                
                new_uses_left = uses_left - 1
                c.execute('UPDATE keys SET uses_left = ? WHERE key = ?', (new_uses_left, key))

               
                redeemed_at = datetime.now()
                expires_at = redeemed_at + timedelta(days=duration_days)
                user_id = str(ctx.author.id)
                discord_username = ctx.author.display_name


                c.execute('''
                    INSERT INTO redemptions (key, user_id, discord_username, redeemed_at, expires_at, active)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (key, user_id, discord_username, redeemed_at, expires_at, True))
               
                if new_uses_left == 0:
                    await ctx.send(f"Der Key {key} hat keine verbleibenden Nutzungen mehr und wird als verwendet markiert.")
                    try:
                        requests.post(f"http://localhost:5000/delete_key/{key}")
                    except requests.exceptions.RequestException as e:
                        print(f"Fehler beim Löschen des Keys: {e}")
                else:
                    try:
                        requests.post(f"http://localhost:5000/delete_key/{key}")
                    except requests.exceptions.RequestException as e:
                        print(f"Fehler beim Löschen des Keys: {e}")
            else:
                await ctx.send("Rolle nicht gefunden. Bitte den Bot-Administrator kontaktieren.")
        else:
            await ctx.send(f"Der Key {key} wurde bereits verwendet.")
    else:
        await ctx.send(f"Der Key {key} ist ungültig oder wurde nicht gefunden.")

    conn.commit()
    conn.close()


bot.run(TOKEN)
