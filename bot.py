import os
import threading
from datetime import datetime
from uuid import uuid4
import pandas as pd
import time

import requests
import telebot


from telebot import types

from WildberriesParser import WildberriesParser
from sale import PriceComparer

TOKEN = '6802066525:AAHvwQ2IEQFhc-NvglNTmh_fNVro-CPa14o'

bot = telebot.TeleBot(TOKEN)
check_interval = 1800 #28800
time_sleep = 30
count = 31


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    # Проверяем, является ли команда /start или /help
    if message.text == '/start':
        # Отправляем описание бота

        bot.send_message(
            message.chat.id,
            "Добро пожаловать! Данный бот позволяет парсить ссылки с Wildberries, сравнивать цены и мониторить изменения цен. "
            "Парсинг до " + str((count - 1) * 100) + " товаров, мониторинг происходит каждые " + str(
                check_interval) + " секунды."
        )

        # Пауза для того, чтобы пользователь мог прочитать сообщение
        time.sleep(3)  # Пауза в 3 секунды

    # Создаем кнопки для выбора действий
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("Парсинг ссылки", callback_data="parse_link")
    btn2 = types.InlineKeyboardButton("Сравнение цен", callback_data="compare_prices")
    btn3 = types.InlineKeyboardButton("Мониторинг цены товаров каталога", callback_data="monitor_prices")
    markup.add(btn1, btn2, btn3)
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)


@bot.message_handler(commands=['stop_monitoring'])
def stop_monitoring(message):
    chat_id = message.chat.id
    if chat_id in monitoring_tasks:
        monitoring_tasks[chat_id]["stop"] = True
        bot.send_message(chat_id, "Мониторинг скоро будет завершен.")
    else:
        bot.send_message(chat_id, "Мониторинг не был запущен.")



@bot.callback_query_handler(func=lambda call: True)
def query_handler(call):
    bot.answer_callback_query(callback_query_id=call.id)
    chat_id = call.message.chat.id

    if call.data == "parse_link":
        msg = bot.send_message(chat_id, "Отправьте ссылку каталога товаров для парсинга:")
        bot.register_next_step_handler(msg, process_link)
    elif call.data == "compare_prices":
        bot.send_message(chat_id, "Отправьте первый (более старый) xlsx файл:")
        bot.register_next_step_handler_by_chat_id(chat_id, process_first_file)
    elif call.data == "monitor_prices":
        msg = bot.send_message(chat_id, "Отправьте ссылку каталога товаров для мониторинга:")
        bot.register_next_step_handler(msg, start_monitoring)


@bot.message_handler(func=lambda message: True, content_types=['text'])
def process_link(message):
    url = message.text
    try:
        bot.send_message(message.chat.id, "Пожалуйста, подождите.")
        parser = WildberriesParser(url)
        file_path = parser.run(False, count)  # Запускаем парсинг и получаем путь к файлу
        if file_path:  # Проверяем, что путь к файлу был получен
            with open(file_path, 'rb') as file:  # Открываем файл для чтения в бинарном режиме
                bot.send_document(message.chat.id, file)  # Отправляем файл пользователю
        else:
            bot.send_message(message.chat.id, "Не удалось обработать данные. Проверьте ссылку и попробуйте снова.")
        send_welcome(message)
        clean_up_temp_files([file_path])
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка при обработке вашего запроса: {e}")


# Глобальный словарь для хранения путей файлов
user_files = {}


def process_first_file(message):
    chat_id = message.chat.id
    if message.content_type == 'document':
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        # Сохраняем первый файл
        first_file_path = save_temp_file(downloaded_file, file_info.file_path)
        user_files[chat_id] = {'file1': first_file_path}

        msg = bot.send_message(chat_id, "Отправьте второй (более новый) xlsx файл:")
        bot.register_next_step_handler(msg, process_second_file)
    else:
        bot.send_message(chat_id, "Пожалуйста, отправьте файл.")


# Аналогично модифицируйте process_second_file для использования save_temp_file и clean_up_temp_files


def process_second_file(message):
    chat_id = message.chat.id
    if message.content_type == 'document' and chat_id in user_files and 'file1' in user_files[chat_id]:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        second_file_path = save_temp_file(downloaded_file, file_info.file_path)

        output_file = "result.xlsx"
        comparer = PriceComparer(user_files[chat_id]['file1'], second_file_path, output_file)
        average_discount_all, average_discount_changes, discount_info = comparer.compare_prices()

        # Отправляем результат пользователю
        with open(output_file, 'rb') as file:
            bot.send_document(chat_id, file)

        # Отправляем сообщения о средних изменениях цен
        if average_discount_all != 0 or average_discount_changes != 0:
            bot.send_message(chat_id, f"Среднее изменение цен по всем товарам: {average_discount_all:.2f}%. Среднее изменение цен по скидочным товарам: {average_discount_changes:.2f}%.\nСамый подешевевший товар: {discount_info}.")

        else:
            bot.send_message(chat_id, "Значительных изменений в ценах не обнаружено.")

        clean_up_temp_files([user_files[chat_id]['file1'], second_file_path, output_file])
        send_welcome(message)
        del user_files[chat_id]
    else:
        bot.send_message(chat_id, "Пожалуйста, отправьте файл.")

monitoring_tasks = {}

def start_monitoring(message):
    url = message.text
    chat_id = message.chat.id
    bot.send_message(chat_id, "Проверка ссылки, подождите.")
    # Используем save_initial_data для инициализации первого файла
    initial_file_path = save_initial_data(url, chat_id)
    if not initial_file_path:
        bot.send_message(chat_id, "Ошибка при попытке парсинга. Пожалуйста, проверьте ссылку и попробуйте снова.")
        return
    monitoring_tasks[chat_id] = {"url": url, "stop": False, "initial_file": initial_file_path}
    bot.send_message(chat_id, "Мониторинг цен начат. Для остановки отправьте команду /stop_monitoring.")
    monitor_prices(chat_id)



def save_initial_data(url, chat_id):
    # Инициализация парсера и выполнение парсинга
    parser = WildberriesParser(url)
    initial_file_path = parser.run(False, count)  # Получение пути к файлу с результатами парсинга

    # Проверка, успешно ли выполнен парсинг и сохранён файл
    if not initial_file_path:
        bot.send_message(chat_id, "Не удалось выполнить парсинг. Проверьте корректность ссылки и попробуйте ещё раз.")
        return None

    # Путь к файлу уже содержит уникальное имя, созданное в процессе парсинга
    return initial_file_path

def monitor_prices(chat_id):
    next_run_time = time.time() + check_interval
    initial_file_name = monitoring_tasks[chat_id].get("initial_file", None)

    while True:
        if monitoring_tasks[chat_id]["stop"]:
            bot.send_message(chat_id, "Мониторинг цен остановлен.")
            del monitoring_tasks[chat_id]
            break

        if time.time() >= next_run_time:
            url = monitoring_tasks[chat_id]["url"]
            parser = WildberriesParser(url)
            latest_file_name = parser.run(True)

            if not latest_file_name:
                bot.send_message(chat_id, "Ошибка при попытке парсинга.")
            else:
                if not initial_file_name:
                    initial_file_name = latest_file_name
                    monitoring_tasks[chat_id]["initial_file"] = latest_file_name
                else:
                    comparer = PriceComparer(initial_file_name, latest_file_name, "comparison_result.xlsx")
                    average_discount_all, average_discount_changes, discount_info = comparer.compare_prices()

                    if average_discount_all != 0 or average_discount_changes != 0:
                        bot.send_message(chat_id, f"Обнаружено изменение цен: среднее изменение всех товаров {average_discount_all:.2f}%. Среднее изменение цен по скидочным товарам: {average_discount_changes:.2f}%.\nСамый подешевевший товар: {discount_info}.\nПроверьте файл с результатами. Для остановки отправьте команду /stop_monitoring.")
                        with open("comparison_result.xlsx", 'rb') as file:
                            bot.send_document(chat_id, file)
                    else:
                        bot.send_message(chat_id, "Изменений в ценах не обнаружено.")

                    os.remove(latest_file_name)

            next_run_time = time.time() + check_interval
        else:
            time.sleep(time_sleep)


def save_temp_file(file_bytes, original_name):
    """
    Сохраняет файл из байтов во временной директории и возвращает путь к файлу.

    Args:
        file_bytes (bytes): Содержимое файла в байтах.
        original_name (str): Исходное имя файла для определения расширения.

    Returns:
        str: Путь к сохраненному файлу.
    """
    # Получаем расширение файла
    _, ext = os.path.splitext(original_name)
    # Генерируем уникальное имя файла для избежания конфликтов
    filename = f"{uuid4()}{ext}"
    # Путь к директории, где будут храниться временные файлы
    temp_dir = "temp_files"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    # Полный путь к файлу
    file_path = os.path.join(temp_dir, filename)
    # Сохраняем файл
    with open(file_path, "wb") as file:
        file.write(file_bytes)
    return file_path


def clean_up_temp_files(file_paths):
    """
    Удаляет файлы по указанным путям.

    Args:
        file_paths (list): Список путей к файлам для удаления.
    """
    for file_path in file_paths:
        try:
            os.remove(file_path)
        except OSError as e:
            print(f"Error: {e.strerror} - {e.filename}")



if __name__ == '__main__':
    bot.infinity_polling(timeout=10, long_polling_timeout=5)