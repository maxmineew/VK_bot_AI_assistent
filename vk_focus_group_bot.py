# -*- coding: utf-8 -*-
"""
VK-бот фокус-группы для сообщества vk.ru/AIassistants (нетворкинг 19.11).

Сценарий (один в один с vk_карточка_фокус-группа.html):
  первое сообщение  -> приветствие + [🚀 Хочу в фокус-группу] [❓ Что за продукт?]
  «Что за продукт?» -> 10 задач + [🚀 Ок, я в деле]
  далее             -> «Чем занимаетесь?» (текст)
                     -> «Что съедает время?» (5 кнопок; «✏️ Другое» -> свой текст)
                     -> «Когда удобно созвониться?» (4 кнопки)
                     -> финал + сводка Максиму в Telegram + строка в CSV

Заявки:  заявки_фокус-группа.csv (открывается экселем, ';' + BOM)
Состояние диалогов: vk_bot_state.json (перезапуск скрипта не теряет диалоги)
Лог: vk_bot.log
Токены: .env — никому не отправлять этот файл

Быстрая проверка без ВК и токенов:  python vk_focus_group_bot.py --selftest
Рабочий запуск:                     python vk_focus_group_bot.py

Ручная настройка сообщества (однократно):
  1) Управление → Работа с API → Ключи доступа → ключ с правом «Сообщения»
  2) Там же → Long Poll API (Bots Long Poll) → включить, событие «Новые сообщения»
  3) Управление → Сообщения → включить; приветствие и автоответы ВЫКЛЮЧИТЬ
  4) Всё вписать в .env (рядом со скриптом)
"""

import csv
import json
import logging
import os
import random
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, ".env")
STATE_PATH = os.path.join(BASE, "vk_bot_state.json")
LEADS_PATH = os.path.join(BASE, "заявки_фокус-группа.csv")
LOG_PATH = os.path.join(BASE, "vk_bot.log")

CONFIG_KEYS = ("VK_TOKEN", "TG_TOKEN", "TG_CHAT")          # обязательные
DEFAULT_REF = "netw1911"                                    # метка QR со слайда 12

# ═══════════════════ ТЕКСТЫ СЦЕНАРИЯ ═══════════════════
WELCOME = ("Привет! Это карточка фокус-группы Максима Минеева 👋\n\n"
           "Собираю тестировщиков «российского Клода»: мини-ИИ-помощник "
           "бесплатно, до месяца.\n\n"
           "Три вопроса — меньше минуты. После этого Максим сам напишет вам "
           "и договорится о созвоне на 15 минут.")

PRODUCT = ("ИИ-помощники для экспертов и малого бизнеса. Забирают:\n\n"
           "• контент на месяц — за 2 часа\n• ответы клиентам ночью и в праздники\n"
           "• типовые вопросы: цена, запись, скидки\n• ведение клиента по программе\n"
           "• визитки с нетворкинга → карточки лидов\n• автопостинг по расписанию\n"
           "• расшифровку и разбор звонков\n• разведку рынка и конкурентов\n"
           "• документы: прайсы, договоры, КП\n• возврат «остывшей» базы\n\n"
           "Первая группа влияет на продукт и получает его первой.")

ASK_NICHE = "Чем занимаетесь? Одним предложением 🙌"
ASK_PAIN = "Понял. Что из этого съедает больше всего времени?"
ASK_PAIN_OTHER = "Опишите своими словами — что именно съедает ваши часы?"
ASK_TIME = "И последнее: когда удобнее созвониться на 15 минут?"
FINAL = ("Готово! ✅\n\nЗаявка у Максима — он напишет прямо здесь в течение дня "
         "и предложит конкретное время.\n\nКейсы и цены: t.me/signea_cases_bot")

BTN_START = "🚀 Хочу в фокус-группу"
BTN_WHAT = "❓ Что за продукт?"
BTN_OK = "🚀 Ок, я в деле"
BTN_OTHER = "✏️ Другое"

WELCOME_ROWS = [[BTN_START], [BTN_WHAT]]
PAIN_ROWS = [["📷 Контент и соцсети", "💬 Ответы клиентам"],
             ["📋 Заявки и запись", "📊 Таблицы и рутина"],
             [BTN_OTHER]]
TIME_ROWS = [["Будни, утро", "Будни, день"],
             ["Будни, вечер", "Пусть Максим предложит"]]

# ═══════════════════ ЛОГ ═══════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("vkbot")

# ═══════════════════ КОНФИГ / СОСТОЯНИЕ / ЗАЯВКИ ═══════════════════

def load_env(path=ENV_PATH):
    """Мини-парсер .env: KEY=VALUE, '#' — комментарий, кавычки снимаются."""
    vals = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k:
                    vals[k] = v
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Файл .env не прочитался (%s). Проверьте кодировку (UTF-8)." % e)
    return vals


def load_config():
    """Токены: сначала .env рядом со скриптом, затем переменные окружения
    (панель хостинга задаёт их без файла — например, bothost.ru)."""
    cfg = dict(load_env())
    for k in CONFIG_KEYS + ("ADMIN_VK_ID",):
        if not cfg.get(k, "").strip() and os.environ.get(k, "").strip():
            cfg[k] = os.environ[k].strip()
    missing = [k for k in CONFIG_KEYS if not cfg.get(k, "").strip()]
    if missing:
        print("Не заполнены: %s (файл .env или переменные окружения)" % ", ".join(missing))
        print_instruction()
        sys.exit(1)
    return cfg


def print_instruction():
    print("\nКак заполнить (5 минут):")
    print('  1. VK_TOKEN  — Управление сообщества → Работа с API → Ключи доступа →')
    print('     создать ключ с правом «Сообщения сообщества».')
    print('  2. Там же включите Long Poll API (Bots Long Poll), событие «Новые сообщения».')
    print('  3. Управление → Сообщения → включить; приветствие/автоответы выключить.')
    print('  4. TG_TOKEN  — токен бота Telegram от @BotFather.')
    print('  5. TG_CHAT   — ваш chat_id (узнать у @userinfobot).')
    print('  6. ADMIN_VK_ID — ваш ЧИСЛОВОЙ VK id (для /reset), можно оставить пустым.')
    print('Создайте файл .env рядом со скриптом:\n')
    print("VK_TOKEN=...\nTG_TOKEN=...\nTG_CHAT=123456789\nADMIN_VK_ID=")


def load_state(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("state-файл не прочитан (%s), начинаю с пустого", e)
        return {}


def save_state(state, path):
    try:
        json.dump(state, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        log.error("не удалось сохранить state: %s", e)


CSV_FIELDS = ["время заявки", "имя", "профиль vk", "ниша", "боль", "удобное время", "метка"]

def append_lead(row, path):
    """Дописывает заявку в CSV (utf-8-sig + ';' — открывается экселем без танцев)."""
    new_file = not os.path.exists(path)
    try:
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            if new_file:
                w.writerow(CSV_FIELDS)
            w.writerow(row)
        return True
    except Exception as e:
        log.error("не удалось дописать заявку в %s: %s", path, e)
        return False

# ═══════════════════ КЛАВИАТУРЫ ═══════════════════

def keyboard(rows):
    return json.dumps({"one_time": True, "buttons": [
        [{"action": {"type": "text", "label": label,
                     "payload": json.dumps({"v": label}, ensure_ascii=False)},
          "color": "primary"} for label in row] for row in rows]}, ensure_ascii=False)


CLEAR_KEYBOARD = json.dumps({"one_time": True, "buttons": []}, ensure_ascii=False)

# ═══════════════════ ОТПРАЛЬЩИКИ ═══════════════════

class VkSender:
    """Реальная отправка через VK API: каждая попытка — с одним повтором при сбое."""

    def __init__(self, vk):
        self.vk = vk

    def _call(self, fn, **kw):
        for attempt in (1, 2):
            try:
                return fn(**kw)
            except Exception as e:
                log.warning("VK вызов не прошёл (попытка %s): %s", attempt, e)
                time.sleep(1)
        log.error("VK вызов окончательно не прошёл: %s", kw.get("peer_id"))
        return None

    def send(self, peer, text, rows=None):
        self._call(self.vk.messages.send, peer_id=peer, message=text,
                   random_id=random.getrandbits(31),
                   keyboard=keyboard(rows) if rows else CLEAR_KEYBOARD)

    def user_info(self, peer):
        res = self._call(self.vk.users.get, user_ids=peer)
        if res:
            u = res[0]
            return "%s %s" % (u.get("first_name", ""), u.get("last_name", "")), u.get("id", peer)
        return "Гость", peer


def make_tg_notifier(cfg):
    """Пуш сводки Максиму в Telegram; при сбое — повтор."""
    import requests
    url = "https://api.telegram.org/bot%s/sendMessage" % cfg["TG_TOKEN"]

    def notify(text):
        for attempt in (1, 2):
            try:
                requests.get(url, params={"chat_id": cfg["TG_CHAT"], "text": text}, timeout=10)
                return True
            except Exception as e:
                log.warning("TG push не прошёл (попытка %s): %s", attempt, e)
                time.sleep(1)
        return False

    return notify

# ═══════════════════ ЛОГИКА ДИАЛОГА ═══════════════════

def norm_admin_id(raw):
    """ADMIN_VK_ID могут вписать как угодно: 12345, «id12345», vk.com/id12345.
    Достаём цифры; не нашли числовой id (напр. ссылка на сообщество) — None."""
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits.lstrip("0") or None


class Bot:
    """
    Машина состояний: menu → niche → pain (→ pain_other) → time → финал.
    Сеть только через sender/notifier — поэтому в selftest подставляются моки.
    """

    def __init__(self, sender, notifier, state, admin_id=None,
                 state_path=STATE_PATH, leads_path=LEADS_PATH):
        self.sender = sender
        self.notifier = notifier
        self.state = state
        self.admin_id = norm_admin_id(admin_id)
        self.state_path = state_path
        self.leads_path = leads_path
        if admin_id and not self.admin_id:
            log.warning("ADMIN_VK_ID «%s» — не числовой id; /reset и дубль сводки отключены",
                        admin_id)

    # ── helpers ──
    def _send(self, peer, text, rows=None):
        try:
            self.sender.send(peer, text, rows)
        except Exception as e:
            log.exception("send упал: %s", e)

    def _save(self):
        save_state(self.state, self.state_path)

    # ── главный вход ──
    def handle(self, peer, text, ref=DEFAULT_REF):
        text = (text or "").strip()
        key = str(peer)
        st = self.state.get(key)

        # /reset — сброс диалога (только админ, для тестов)
        if text.lower() == "/reset":
            if self.admin_id and str(peer) == self.admin_id:
                self.state.pop(key, None)
                self._save()
                self._send(peer, "Диалог сброшен — следующий тест с чистого листа.")
            return

        # первый контакт или новый круг после финала
        if st is None:
            self.state[key] = {"step": "menu", "ref": ref}
            self._send(peer, WELCOME, WELCOME_ROWS)

        elif text == BTN_WHAT:
            self._send(peer, PRODUCT, [[BTN_OK]])

        elif st["step"] == "menu":
            st["step"] = "niche"
            self._send(peer, ASK_NICHE)

        elif st["step"] == "niche":
            st["niche"] = text
            st["step"] = "pain"
            self._send(peer, ASK_PAIN, PAIN_ROWS)

        elif st["step"] == "pain":
            if text == BTN_OTHER:
                st["step"] = "pain_other"
                self._send(peer, ASK_PAIN_OTHER)
            else:                                  # кнопку нажали или описали сами — принимаем
                st["pain"] = text
                st["step"] = "time"
                self._send(peer, ASK_TIME, TIME_ROWS)

        elif st["step"] == "pain_other":
            st["pain"] = text
            st["step"] = "time"
            self._send(peer, ASK_TIME, TIME_ROWS)

        elif st["step"] == "time":
            self.finish(peer, st, text)

        self._save()

    # ── финал: заявка + уведомления ──
    def finish(self, peer, st, when):
        try:
            name, uid = self.sender.user_info(peer)
        except Exception:
            name, uid = "Гость", peer
        ref = st.get("ref") or DEFAULT_REF
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M")

        summary = ("🔥 Фокус-группа · новая заявка (%s)\n"
                   "%s — vk.com/id%s\nНиша: %s\nБоль: %s\nВремя: %s" %
                   (ref, name.strip(), uid, st.get("niche", ""), st.get("pain", ""), when))
        log.info("ЗАЯВКА: %s", summary.replace("\n", " | "))

        try:
            self.notifier(summary)
        except Exception as e:
            log.exception("notifier упал: %s", e)
        if self.admin_id:
            self._send(int(self.admin_id), summary)   # дубль в личку сообщества

        append_lead([stamp, name.strip(), "vk.com/id%s" % uid, st.get("niche", ""),
                     st.get("pain", ""), when, ref], self.leads_path)

        self._send(peer, FINAL)
        self.state.pop(str(peer), None)               # следующий круг начнётся с приветствия

# ═══════════════════ REF ИЗ СОБЫТИЯ (оборонительно) ═══════════════════

def extract_ref(event):
    """Ищет 'ref' в сырых полях события (в vk_api формат не стандартизован).
    Не нашли — вернём None, вызывающий подставит DEFAULT_REF: в день нетворкинга
    весь трафик идёт с QR (ref=netw1911), так что метка верна и так."""
    try:
        def walk(o, depth=0):
            if depth > 4 or o is None:
                return None
            if isinstance(o, dict):
                v = o.get("ref")
                if isinstance(v, str) and v.strip():
                    return v.strip()
                for x in o.values():
                    r = walk(x, depth + 1)
                    if r:
                        return r
            elif isinstance(o, (list, tuple)):
                for x in o:
                    r = walk(x, depth + 1)
                    if r:
                        return r
            return None

        candidates = list(vars(event).values()) if hasattr(event, "__dict__") else []
        for val in candidates:
            r = walk(val)
            if r:
                return r
    except Exception:
        pass
    return None

# ═══════════════════ ЗАПУСК ═══════════════════

def main():
    if "--selftest" in sys.argv:
        return selftest()

    cfg = load_config()

    import requests          # noqa: F401 — проверка зависимости до старта
    import vk_api
    from vk_api.longpoll import VkLongPoll, VkEventType

    try:
        session = vk_api.VkApi(token=cfg["VK_TOKEN"])
        vk = session.get_api()
        longpoll = VkLongPoll(session)
    except Exception as e:
        print("Не удалось подключиться к VK: %s" % e)
        print("Проверьте VK_TOKEN и что Long Poll API включён (Работа с API → Long Poll API).")
        sys.exit(1)

    bot = Bot(VkSender(vk), make_tg_notifier(cfg), load_state(STATE_PATH),
              admin_id=cfg.get("ADMIN_VK_ID") or None)

    log.info("Бот запущен для vk.ru/AIassistants — жду сообщения (Ctrl+C для остановки)…")
    for event in longpoll.listen():
        if event.type != VkEventType.MESSAGE_NEW or not event.to_me:
            continue
        try:
            bot.handle(event.peer_id, event.text, extract_ref(event) or DEFAULT_REF)
        except Exception:
            log.exception("Ошибка обработки сообщения от peer %s", getattr(event, "peer_id", "?"))

# ═══════════════════ САМОТЕСТ (без ВК и токенов) ═══════════════════

def selftest():
    class MockSender:
        def __init__(self):
            self.sent = []

        def send(self, peer, text, rows=None):
            self.sent.append((peer, text.split("\n")[0][:58], rows))

        def user_info(self, peer):
            return "Тест Тестов", peer

    test_leads = os.path.join(BASE, "_selftest_leads.csv")
    test_state = os.path.join(BASE, "_selftest_state.json")
    for p in (test_leads, test_state):
        if os.path.exists(p):
            os.remove(p)

    tg, sender = [], MockSender()
    state = load_state(test_state)
    bot = Bot(sender, tg.append, state, admin_id="1",
              state_path=test_state, leads_path=test_leads)

    peer = 101
    flow = [
        "привет",                # → приветствие + 2 кнопки
        BTN_WHAT,                # → 10 задач + кнопка
        BTN_OK,                  # → вопрос про нишу
        "Фотограф",              # → вопрос про боль
        BTN_OTHER,               # → «опишите своими словами»
        "Всё делаю сама, руками",  # → вопрос про время
        "Будни, вечер",          # → финал + заявка №1
        "Хочу поменять время",   # финал был → снова приветствие
        BTN_START,               # → вопрос про нишу
        "Нутрициолог",           # → вопрос про боль
        "💬 Ответы клиентам",    # → вопрос про время (кнопка, без ветки)
        "Пусть Максим предложит",  # → финал + заявка №2
    ]
    print("── Прогон сценария ──")
    for msg in flow:
        bot.handle(peer, msg, "netw1911")
        what = sender.sent[-1][1]
        print("  гость: %-28s → бот: %s" % (msg[:26], what))

    bot.handle(1, "/reset")     # админский сброс
    print("  админ: /reset                       → ок (диалог сброшен)")

    # проверки
    checks = [
        ("заявок в Telegram пришло", len(tg) == 2),
        ("CSV-файл создан", os.path.exists(test_leads)),
        ("state-файл создан", os.path.exists(test_state)),
        ("state пуст после финалов", load_state(test_state) == {}),
        ("в сводке есть vk-ссылка", "vk.com/id" in tg[0]),
        ("в сводке есть метка", "netw1911" in tg[0]),
        ("в сводке есть боль из «Другое»", "Всё делаю сама, руками" in tg[0]),
    ]
    rows = list(csv.reader(open(test_leads, encoding="utf-8-sig"), delimiter=";"))
    checks.append(("в CSV 1 шапка + 2 заявки", len(rows) == 3))
    checks.append(("CSV: ниша второй заявки — Нутрициолог", rows and rows[2][3] == "Нутрициолог"))

    print("\n── Проверки ──")
    ok = True
    for name, passed in checks:
        print("  [%s] %s" % ("✓" if passed else "✗", name))
        ok = ok and passed
    print("\nИтог selftest: %s" % ("ВСЁ ПРОШЛО ✓" if ok else "ЕСТЬ ОШИБКИ ✗"))
    for p in (test_leads, test_state):
        if os.path.exists(p):
            os.remove(p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
