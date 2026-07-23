import telebot
import yt_dlp
import os
import threading
import time
from collections import deque
from urllib.parse import urlparse

# ─────────────────────────────────────────
# الإعدادات
# ─────────────────────────────────────────
TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ALLOWED_USERS = [7369661601]

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
bot.remove_webhook()

# ─────────────────────────────────────────
# نظام التحميل
# ─────────────────────────────────────────
download_queue = deque()
active_downloads = {}
queue_lock = threading.Lock()

QUALITY_OPTIONS = {
    'best': 'best',
    '720': 'best[height<=720]',
    '480': 'best[height<=480]',
    '360': 'best[height<=360]',
    'audio': 'bestaudio/best',
}

user_quality = {}
user_format = {}

# ─────────────────────────────────────────
# المواقع المدعومة
# ─────────────────────────────────────────
SUPPORTED_SITES = [
    'youtube.com', 'youtu.be',
    'instagram.com', 'instagr.am',
    'tiktok.com', 'vm.tiktok.com',
    'twitter.com', 'x.com', 't.co',
    'facebook.com', 'fb.watch',
    'reddit.com', 'redd.it',
    'pinterest.com', 'pin.it',
    'linkedin.com',
    'twitch.tv',
    'vimeo.com',
    'dailymotion.com',
    'soundcloud.com',
    'spotify.com',
]

def is_supported_url(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return any(site in domain for site in SUPPORTED_SITES)
    except:
        return False

def is_allowed(user_id):
    return user_id in ALLOWED_USERS

# ─────────────────────────────────────────
# لوحة المفاتيح
# ─────────────────────────────────────────
def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add('Video', 'Audio', 'Quality', 'Queue')
    return markup

# ─────────────────────────────────────────
# الأوامر
# ─────────────────────────────────────────
@bot.message_handler(commands=['start'])
def start(message):
    if not is_allowed(message.from_user.id):
        bot.reply_to(message, "Access Denied!")
        return
    bot.send_message(
        message.chat.id,
        "Welcome! Send me any link from social media.",
        reply_markup=main_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == 'Video')
def set_video(message):
    user_format[message.from_user.id] = 'video'
    bot.reply_to(message, 'Mode: Video')

@bot.message_handler(func=lambda m: m.text == 'Audio')
def set_audio(message):
    user_format[message.from_user.id] = 'audio'
    bot.reply_to(message, 'Mode: Audio (MP3)')

@bot.message_handler(func=lambda m: m.text == 'Quality')
def set_quality(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton('Best', callback_data='q_best'),
        telebot.types.InlineKeyboardButton('720p', callback_data='q_720'),
        telebot.types.InlineKeyboardButton('480p', callback_data='q_480'),
        telebot.types.InlineKeyboardButton('360p', callback_data='q_360'),
        telebot.types.InlineKeyboardButton('Audio', callback_data='q_audio')
    )
    bot.send_message(message.chat.id, 'Select quality:', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('q_'))
def quality_callback(call):
    q = call.data.replace('q_', '')
    user_quality[call.from_user.id] = q
    bot.answer_callback_query(call.id, f'Quality: {q}')

@bot.message_handler(func=lambda m: m.text == 'Queue')
def show_queue(message):
    if not is_allowed(message.from_user.id):
        return
    user_id = message.from_user.id
    user_queue = [q for q in download_queue if q['user_id'] == user_id]
    if not user_queue:
        bot.reply_to(message, "Queue is empty!")
        return
    text = f"Your Queue ({len(user_queue)} items):\n\n"
    for i, item in enumerate(user_queue[:5], 1):
        text += f"{i}. {item['url'][:50]}...\n"
    bot.reply_to(message, text)

# ─────────────────────────────────────────
# معالجة الروابط
# ─────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text and ('http' in m.text or '://' in m.text))
def handle_link(message):
    if not is_allowed(message.from_user.id):
        return
    url = message.text.strip()
    user_id = message.from_user.id
    if not is_supported_url(url):
        bot.reply_to(message, "Unsupported URL!")
        return
    fmt = user_format.get(user_id, 'video')
    quality = user_quality.get(user_id, 'best')
    if fmt == 'audio':
        quality = 'audio'
    item = {
        'user_id': user_id,
        'chat_id': message.chat.id,
        'url': url,
        'quality': quality,
        'format': fmt,
    }
    with queue_lock:
        download_queue.append(item)
        queue_pos = len([q for q in download_queue if q['user_id'] == user_id])
    if user_id in active_downloads:
        bot.reply_to(message, f'Added to queue (#{queue_pos})')
    else:
        bot.reply_to(message, 'Downloading...')
        threading.Thread(target=process_queue, daemon=True).start()

# ─────────────────────────────────────────
# نظام التحميل المتقدم
# ─────────────────────────────────────────
def process_queue():
    while True:
        with queue_lock:
            if not download_queue:
                break
            item = download_queue.popleft()
        user_id = item['user_id']
        if user_id in active_downloads:
            with queue_lock:
                download_queue.appendleft(item)
            time.sleep(2)
            continue
        active_downloads[user_id] = True
        try:
            download_and_send(item)
        except Exception as e:
            bot.send_message(item['chat_id'], f'Error: {str(e)[:200]}')
        finally:
            if user_id in active_downloads:
                del active_downloads[user_id]
        time.sleep(1)

def download_and_send(item):
    chat_id = item['chat_id']
    url = item['url']
    quality = item['quality']
    fmt = item['format']
    msg = bot.send_message(chat_id, 'Preparing...')
    os.makedirs('downloads', exist_ok=True)
    ydl_opts = {
        'format': QUALITY_OPTIONS.get(quality, 'best'),
        'outtmpl': f'downloads/{item["user_id"]}_%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
    }
    if fmt == 'audio':
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
        ydl_opts['format'] = 'bestaudio/best'
    try:
        with yt_dlp.YoutubeDL({**ydl_opts, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            bot.edit_message_text(f'Downloading: {title[:50]}', chat_id, msg.message_id)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if fmt == 'audio' and not filename.endswith('.mp3'):
                filename = os.path.splitext(filename)[0] + '.mp3'
        file_size = os.path.getsize(filename)
        if file_size > 50 * 1024 * 1024:
            bot.edit_message_text(f'Too big: {file_size/1024/1024:.1f}MB', chat_id, msg.message_id)
            os.remove(filename)
            return
        bot.edit_message_text('Sending...', chat_id, msg.message_id)
        with open(filename, 'rb') as f:
            if fmt == 'audio':
                bot.send_audio(chat_id, f, title=title, caption=f'Audio: {title}')
            else:
                ext = os.path.splitext(filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                    bot.send_photo(chat_id, f, caption=f'Done: {title}')
                else:
                    bot.send_video(chat_id, f, caption=f'Done: {title}', supports_streaming=True)
        bot.delete_message(chat_id, msg.message_id)
        os.remove(filename)
    except Exception as e:
        error = str(e)
        if 'Unsupported URL' in error:
            bot.edit_message_text('Unsupported URL!', chat_id, msg.message_id)
        elif 'Private' in error or 'login' in error.lower():
            bot.edit_message_text('Private content!', chat_id, msg.message_id)
        else:
            bot.edit_message_text(f'Error: {error[:150]}', chat_id, msg.message_id)

# ─────────────────────────────────────────
# تشغيل البوت
# ─────────────────────────────────────────
print('Bot running 24/7...')
bot.polling(none_stop=True, interval=1, timeout=20)
