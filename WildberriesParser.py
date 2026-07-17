import datetime
import requests
import pandas as pd
from retry import retry

class WildberriesParser:

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/113.0",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://www.wildberries.ru",
        'Content-Type': 'application/json; charset=utf-8',
        'Transfer-Encoding': 'chunked',
        "Connection": "keep-alive",
        'Vary': 'Accept-Encoding',
        'Content-Encoding': 'gzip',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site"
    }
    CATALOG_URL = 'https://static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v2.json'
    def __init__(self, url, low_price=1, top_price=1000000, discount=0):
        self.url = url
        self.low_price = low_price
        self.top_price = top_price
        self.discount = discount

    def get_catalogs_wb(self):
        return requests.get(self.CATALOG_URL, headers=self.HEADERS).json()

    def get_data_category(self, catalogs_wb):
        catalog_data = []
        if isinstance(catalogs_wb, dict) and 'childs' not in catalogs_wb:
            catalog_data.append({
                'name': catalogs_wb['name'],
                'shard': catalogs_wb.get('shard'),
                'url': catalogs_wb['url'],
                'query': catalogs_wb.get('query')
            })
        elif isinstance(catalogs_wb, dict):
            catalog_data.extend(self.get_data_category(catalogs_wb['childs']))
        else:
            for child in catalogs_wb:
                catalog_data.extend(self.get_data_category(child))
        return catalog_data

    def search_category_in_catalog(self, url, catalog_list):
        for catalog in catalog_list:
            if catalog['url'] == url.split('https://www.wildberries.ru')[-1]:
                print(f'Найдено совпадение: {catalog["name"]}')
                return catalog
        return None

    def get_data_from_json(self, json_file):
        data_list = []
        for data in json_file['data']['products']:
            data_list.append({
                'id': data.get('id'),
                'Наименование': data.get('name'),
                'Цена': int(data.get("priceU") / 100),
                'Цена со скидкой': int(data.get('salePriceU') / 100),
                'Скидка': data.get('sale'),
                'Бренд': data.get('brand'),
                'Рейтинг': data.get('rating'),
                'Продавец': data.get('supplier'),
                'Рейтинг продавца': data.get('supplierRating'),
                'Кол-во отзывов': data.get('feedbacks'),
                'Рейтинг отзывов': data.get('reviewRating'),
                'Промо текст карточки': data.get('promoTextCard'),
                'Промо текст категории': data.get('promoTextCat'),
                'Ссылка': f'https://www.wildberries.ru/catalog/{data.get("id")}/detail.aspx?targetUrl=BP'
            })
        return data_list

    @retry(Exception, tries=-1, delay=0)
    def scrap_page(self, page, shard, query):
        url = f'https://catalog.wb.ru/catalog/{shard}/catalog?appType=1&curr=rub' \
              f'&dest=-1257786' \
              f'&locale=ru' \
              f'&page={page}' \
              f'&priceU={self.low_price * 100};{self.top_price * 100}' \
              f'&sort=popular&spp=0' \
              f'&{query}' \
              f'&discount={self.discount}'
        r = requests.get(url, headers=self.HEADERS)
        print(f'[+] Страница {page}')
        return r.json()

    from datetime import datetime

    def save_excel(self, data_list, filename, is_initial=False):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        if is_initial:
            filepath = f'{filename}.xlsx'
        else:
            filepath = f'{filename}_{timestamp}.xlsx'
        df = pd.DataFrame(data_list)
        df.to_excel(filepath, index=False)
        print(f'Все сохранено в {filepath}')
        return filepath

    def run(self, is_initial=False, count = 31):
        try:
            catalogs_wb = self.get_catalogs_wb()
            catalog_data = self.get_data_category(catalogs_wb)
            category = self.search_category_in_catalog(self.url, catalog_data)
            if category:
                data_list = []
                for page in range(1, count):  # Wildberries предоставляет до 50 страниц товаров
                    data = self.scrap_page(page, category['shard'], category['query'])
                    if data and 'data' in data and 'products' in data['data']:
                        new_data = self.get_data_from_json(data)
                        if new_data:
                            data_list.extend(new_data)
                        else:
                            break
                print(f'Сбор данных завершен. Собрано: {len(data_list)} товаров.')
                # Замечание: параметр is_initial определяет, как будет сгенерировано имя файла
                file_path = self.save_excel(data_list, f'{category["name"]}_from_{self.low_price}_to_{self.top_price}',
                                            is_initial)
                return file_path
        except Exception as e:
            print(f'Произошла ошибка: {e}')
            return None

