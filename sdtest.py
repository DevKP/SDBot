import logging
from samplers import samplers
from errors import PassToUserException

from telegram import Message, __version__ as TG_VER

try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]

if __version_info__ < (20, 0, 0, "alpha", 1):
    raise RuntimeError(
        f"This example is not compatible with your current PTB version {TG_VER}. To view the "
        f"{TG_VER} version of this example, "
        f"visit https://docs.python-telegram-bot.org/en/v{TG_VER}/examples.html"
    )
from telegram import Update, InputMediaPhoto, InputMediaDocument, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest
from PIL import Image
import traceback
import datetime
import aiohttp
import asyncio
import base64
import html
import random
import json
import io


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        """Привіт! Просто надішли мені запит для генерації картинки і я все зроблю. 
        
Наприклад (натисни щоб скопіювати):
<code>white kitty, cute, masterpiece, detailed</code>
        
Для додаткового налаштування: /help"""
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_html("""<strong>Використання:</strong>
   <code>&lt;запит&gt; [налаштування]</code>
  
<strong>Приклад:</strong>
   <code>cat, big, white, cute -s ddim</code>
  
<strong>Доступні налаштування:</strong>
   <code>-s</code>  --  Назва семплера. Див. /samplers <b>Default:</b> <code>ddim</code>
   <code>-seed</code>  --  Число, яке визначає унікальність картинки. Не змінюючи число отримуєте ту саму картинку. <b>Default:</b> <code>-1</code>
  
<strong>Для досвідченних експерементаторів:</strong>
   <code>-steps</code>  --  Кількість кроків генерації. <b>Default:</b> <code>32</code>
   <code>-scale</code>  --  Визначає наскільки картинка має бути схожою на запит. <b>Default:</b> <code>7.0</code>
  
<strong>Приклад з усіма налаштуваннями:</strong>
   <code>cat, big, white, cute -s euler_a -seed 321 -scale 8.5 -steps 38</code>""")
    
async def samplers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_html("""
<strong>Список семплерів:</strong>

<code>ddim</code> (за замовчуванням)
<code>euler_a</code>
<code>euler</code>
<code>lms</code>
<code>heun</code>
<code>dpm_2</code>
<code>dpm_2_a</code>
<code>dpmpp_2s_a</code>
<code>dpmpp_2m</code>
<code>dpmpp_sde</code>
<code>dpm_fast</code>
<code>dpm_ad</code>
<code>lms_ka</code>
<code>dpm_2_ka</code>
<code>dpm_2_a_ka</code>
<code>dpmpp_2s_a_ka</code>
<code>dpmpp_2m_ka</code>
<code>dpmpp_sde_ka</code>

<strong>Раджу експерементувати у першу чергу з:</strong>

<code>ddim</code>
<code>euler_a</code>
<code>dpmpp_sde_ka</code>""")
    
running_jobs = []
lock = asyncio.Lock()

async def jobs_loop(context: ContextTypes.DEFAULT_TYPE):
    while True:
        if len(running_jobs) == 0:
            await asyncio.sleep(0.5)
            continue
    
        await lock.acquire()
    
        job = running_jobs[0]
        print("found job" + job["name"])
        await asyncio.gather(job["task"])
        running_jobs.remove(job)

        lock.release()

def is_job_exists_old(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    current_jobs = context.job_queue.jobs()
    return len(current_jobs) > 0

def is_job_exists(name: str) -> bool:
    return any(t["name"] == name for t in running_jobs)

async def generate_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await generate(update, context)

def get_options(msg_text: str) -> dict:
    message_parts = msg_text.split("-")
    options = {
        "s": "ddim",
        "seed": "-1",
        "scale": "7",
        "steps": "32",
        "batch": "1",
        "w": "512",
        "h": "512",
        "fix": "1",
        "file": "true",
        "negative": "",
        "prompt": "",
    }
    
    options["prompt"] = message_parts[0].strip()
    if len(message_parts) > 1:
        try:
            for i in range(1, len(message_parts)):
                command_parts = message_parts[i].lower().strip().split(" ")

                if len(command_parts) != 2:
                    raise Exception()

                options[command_parts[0].strip()] = command_parts[1].strip()
        except Exception:
            raise PassToUserException("Помилка в налаштуваннях. /help")

    try:
        options["s"] = samplers[options["s"].lower()]
    except Exception:
        raise PassToUserException("Невідомий семплер. /samplers")

    if float(options["fix"]) > 3:
        raise PassToUserException("<code>fix</code> - Максимальне значення = <code>3</code>.  /help")

    if int(options["batch"]) > 5:
        raise PassToUserException("<code>batch</code> - Максимальне значення = <code>5</code>.  /help")

    if int(options["steps"]) > 60:
        raise PassToUserException("<code>steps</code> - Максимальне значення = <code>60</code>.  /help")

    if int(options["w"]) > 768 or int(options["h"]) > 768:
        raise PassToUserException("<code>w/h</code> - Максимальне значення = <code>768 x 768</code>.  /help")

    #options['negative'] = "lowres, text, error, missing fingers, extra digit, fewer digits, cropped, (worst quality, low quality:1.4), jpeg artifacts, signature, bad anatomy, extra legs, extra arms, extra fingers, poorly drawn hands, poorly drawn feet, disfigured, out of frame, tiling, bad art, deformed, mutated, blurry, fuzzy, misshaped, mutant, gross, disgusting, ugly, watermark, watermarks," + options['negative']
    #options['negative'] = "lowres, (((deformed))), bad anatomy, low res, text, error, missing fingers, fused fingers, (poorly drawn hands), extra digit, fewer digits, cropped, (worst quality, low quality:1.4), signature, extra legs, extra arms, extra fingers, poorly drawn hands, poorly drawn feet, disfigured, out of frame, tiling, bad art, deformed, mutation, mutated, fuzzy, misshaped, mutant, gross, disgusting, ugly, watermark, watermarks, fused breasts, bad breasts, poorly drawn breasts, extra breasts, huge haunch, huge thighs, huge calf, bad hands, fused hand, missing hand, disappearing arms, disappearing thigh, disappearing calf, (disappearing legs), poorly drawn legs, bad ears, poorly drawn ears, extra ears, heavy ears, missing ears, fused animal ears, bad face, bad animal ears, poorly drawn animal ears, extra animal ears, heavy animal ears, missing animal ears, one hand with more than 5 fingers, one hand with less than 5 fingers, one hand with more than 5 digit, one hand with less than 5 digit, short arm, (missing arms), missing thighs, missing calf, missing legs, (extra legs), mutation, duplicate, mutilated, poorly drawn hands, more than 1 left hand, more than 1 right hand, deformed, bad asshole, poorly drawn asshole, fused asshole, missing asshole, bad anus, (((bad pussy))), bad crotch, badcrotch seam, fused anus, fused pussy, fused anus, fused crotch, poorly drawn crotch, fused seam, poorly drawn anus, ((poorly drawn pussy)), poorly drawn crotch, (bad thigh gap), missing thigh gap, (fused thigh gap),  (poorly drawn thigh gap), poorly drawn anus, (missing clit), (bad clit), fused clit, colorful clit, pubic hair, bad breasts, poorly drawn breasts, extra breasts, bad hands, fused hand, missing hand, disappearing arms, disappearing thigh, disappearing calf, disappearing legs, fuse dears, bad ears, poorly drawn ears, extra ears, missing limb, (missing arms), bad asshole, poorly drawn asshole, fused asshole, missing asshole, bad anus, bad pussy, bad crotch, seam, fused anus, (fused pussy), fused anus, fused crotch, poorly drawn crotch, fused seam, poorly drawn anus, (poorly drawn pussy), poorly drawn crotch, seam, bad thigh gap, missing thigh gap, fused thigh gap, poorly drawn thigh gap, poorly drawn anus, bad collarbone, fused collarbone, missing collarbone" + options['negative']
    options['negative'] = "EasyNegative, extra fingers,fewer fingers," + options['negative']

    return options
    
def get_payload(options: dict) -> dict:
    payload = {
            "prompt": options["prompt"],
            "negative_prompt": options["negative"],
            "seed": int(options["seed"]),
            "cfg_scale": float(options["scale"]),
            "sampler_index": options["s"],
            "sampler_name": options["s"],
            "steps": int(options["steps"]),
            "batch_size": int(options["batch"]),
            "width": int(options["w"]),
            "height": int(options["h"]),
            "enable_hr": True,
            "denoising_strength": 0.7,
            "hr_scale": float(options["fix"]),
            "hr_upscaler": "4x_foolhardy_Remacri",
            "hr_second_pass_steps": 0,
        }
    return payload

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messsage = update.message
    try:
        logger.info(rf"{messsage.text}")

        options = get_options(messsage.text)
        payload = get_payload(options)
        
        logger.info(options)

        await messsage.reply_text("Генерація..")
        
        context.job_queue.run_once(live_preview_job, 0, chat_id=messsage.chat_id)

        async with aiohttp.ClientSession() as session:
            async with session.post("http://192.168.1.89:7860/sdapi/v1/txt2img", json=payload, timeout=1200) as response:
            
                response.raise_for_status()
                responseJson = await response.json()

                info = json.loads(responseJson["info"])

                ecaped_prompt = html.escape(info["prompt"])
                escaped_message = html.escape(messsage.text)

                images = list(map(lambda x: InputMediaPhoto(io.BytesIO(base64.b64decode(x))), responseJson["images"]))
                await messsage.reply_media_group(images, parse_mode="HTML", caption=rf"""Prompt: {ecaped_prompt}
Sampler: {info["sampler_name"]}
Seed: <code>{info["seed"]}</code>
Steps: {info["steps"]}
Scale: {info["cfg_scale"]}
Size: {info["width"]}x{info["height"]}
Batch: {options["batch"]}

@very_stable_bot""")
                await messsage.reply_html(rf"""<code>{escaped_message}</code>""")

                if options["file"] == "true":
                    documents = []
                    raw_image_list = list(map(lambda x: io.BytesIO(base64.b64decode(x)), responseJson["images"]))
                    for i in range(len(raw_image_list)):
                        document = InputMediaDocument(raw_image_list[i], filename=rf"{random.randint(1, 99999)}_{int(info['seed'])+i}.png")
                        documents.append(document)
                    await messsage.reply_media_group(documents)

        logger.info("Successfuly generated")
    except PassToUserException as uE:
        await messsage.reply_html(uE.message)
    except Exception as e:
        traceback.print_exc()
        await messsage.reply_text("Сталась помилка, спробуй ще.")
  
async def prompt_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    if is_job_exists(str(chat_id)) == True:
        await update.message.reply_text("Вже в черзі, спочатку почекай результат минулого запиту.")
        return    
    
    running_jobs.append({"task": generate_job(update, context), "name": str(chat_id)})
    
    await update.message.reply_text(rf"""Ти {len(running_jobs)} в черзі на генерацію... В залежності від навантаженості це може зайняти до декількох хвилин..
Час очікування: бог його знає.""")
    
async def live_preview_job(context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(1)

    genMessage = await context.bot.send_photo(chat_id=context.job.chat_id, photo="placeholder.jpg")
    info_message = await context.bot.send_message(chat_id=context.job.chat_id, text="...")

    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get("http://192.168.1.89:7860/sdapi/v1/progress", timeout=200) as response:
                if response.status != 200:
                    raise Exception("Bad response")
                
                responseJson = await response.json()

                if int(responseJson["state"]["job_count"]) == 0:
                    await genMessage.delete()
                    await info_message.delete()
                    return
                
                if responseJson["current_image"] is None:
                    continue

                bytesArray = io.BytesIO(base64.b64decode(responseJson["current_image"]))
                image = Image.open(bytesArray)
                width, height = image.size
                image = image.resize((width * 4, height * 4))
                buf = io.BytesIO()
                image.save(buf, format='PNG')
                
                try:
                    await info_message.edit_text(text=rf"{round(float(responseJson['progress'])*100)}%",)
                    await genMessage.edit_media(media=InputMediaPhoto(media=buf.getvalue()))
                except BadRequest:
                    logger.error("Update preview error")
                    await asyncio.sleep(2)

            await asyncio.sleep(2)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Option 3", switch_inline_query_current_chat="/test")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_html("Hi!", reply_markup=reply_markup)
   
def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token("6247027158:AAEBPb6FhDIxQlD429j3eVppnhpq5bGPbjo").concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("samplers", samplers_command))
    application.add_handler(CommandHandler("test", test_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_message))
    application.job_queue.run_once(jobs_loop, 0.5)

    application.run_polling()


if __name__ == "__main__":
    main()