# coding: utf-8
import argparse
import re
from pprint import pprint
from lxml import etree as et

import pymongo
import datetime

from requests_html import HTMLSession


SEPHORA_URL = "https://www.sephora.com"
PAGE_SIZE = 300


def get_products_by_category(category, session=None):
    if not session:
        session = HTMLSession()

    products = []

    def get_products_from_page(page=0):
        page += 1
        r = session.get('{}/shop/{}?pageSize={}&currentPage={}'.format(SEPHORA_URL, category, PAGE_SIZE, page))
        r.html.render(wait=1, sleep=1, scrolldown=10)
        etree = r.html.lxml

        products_blocks = etree.xpath("//div[@data-comp='ProductGrid']")[0].getchildren()
        for prod_block in products_blocks:
            products.extend(prod_block.getchildren())

        products_count_text = etree.xpath("//h2[@class='css-1ukmsgi']")[0].text
        products_count = int(re.search('(\d+) products', products_count_text).group(1))

        if products_count // (PAGE_SIZE * page):
            get_products_from_page(page=page)

    get_products_from_page()

    return products


def get_product_info(product):
    try:
        stars_style = product.xpath("a//div[@data-comp='StarRating']/div[@class='css-dtomnp']")[0].get("style")
        rating = float(re.search(r'width: (\S+)%;', stars_style).group(1))

        url = product.xpath("a")[0].get("href")
        foreign_id = re.search(r':(\S+):', url).group(1)

        info = dict(
            brand=product.xpath('a//span[@data-at="sku_item_brand"]')[0].text,
            name=product.xpath('a//span[@data-at="sku_item_name"]')[0].text,
            price=product.xpath('a//span[@data-at="sku_item_price_list"]')[0].text.replace('$', ''),
            url=url,
            img=product.xpath('a//img[@data-comp="Image"]')[0].get("src"),
            foreign_id=foreign_id,
            rating=5 * rating / 100.,
            source='sephora'
        )

        return info

    except:
        return


def product_details(product_url, session=None):
    if not session:
        session = HTMLSession()

    r = session.get(SEPHORA_URL + product_url)
    r.html.render(wait=0.4, sleep=1)

    etree = r.html.lxml

    try:
        info_block = etree.xpath("//div[@data-comp='Info']")[0]
        tab_buttons = info_block.xpath('button/div')
        for idx, btn in enumerate(tab_buttons):
            if btn.text == 'Ingredients':
                raw_ingredients_html = info_block.xpath("div/div[{}]/div".format(idx + 1))[0]
                raw_ingredients = et.tostring(raw_ingredients_html)

                ingredients_parts = raw_ingredients.decode('utf-8').split('<br/><br/>')
                if len(ingredients_parts) > 1:
                    ingredients = ingredients_parts[1]
                else:
                    ingredients = raw_ingredients_html.text_content()

                ingredients = ingredients.replace('</div>', '').strip()
                ingredients = ingredients.split(',')
                ingredients = [ingr.replace('*', '').replace('.', '').lower().strip() for ingr in ingredients]
                raw_ingredients = raw_ingredients
                break
        else:
            ingredients, raw_ingredients = [], ""

    except IndexError:
        ingredients, raw_ingredients = [], ""

    return dict(ingredients=ingredients, raw_ingredients=raw_ingredients)


if __name__ == '__main__':
    mongo_connection = pymongo.MongoClient('127.0.0.1', 27017)
    db = mongo_connection.sephora

    session = HTMLSession()

    categories = [
        'moisturizing-cream-oils-mists',  # Moisturizers
        'cleanser',  # Cleansers
        'facial-treatments',  # Treatments
        'face-mask',  # Masks
        'eye-treatment-dark-circle-treatment',  # Eye Care
        'sunscreen-sun-protection',  # Sun Care
        'self-tanning-products',  # Self-tanners
        'lip-treatments'  # Lip Treatments
    ]

    for category in categories:
        parser = argparse.ArgumentParser()
        parser.add_argument('--run', action='store_true', help='Save data to db')
        parser.add_argument('--export', action='store_true', help='Export to csv')
        args = parser.parse_args()

        products = get_products_by_category(category=category, session=session)

        for i, p in enumerate(products):
            product = get_product_info(p)
            if not product:
                continue

            product['category'] = category

            db.products.find_and_modify(
                query={'foreign_id': product['foreign_id'], 'category': product['category']},
                update={'$set': product},
                fields={'_': 0},
                upsert=True
            )

        for i, product in enumerate(db.products.find(filter={'category': category}, sort=[('_id',  1)])):
            now = datetime.datetime.now().strftime('%H:%M:%S')
            print('[{}] {}. {}, {}, {}, {}'.format(
                now,
                i + 1,
                product['brand'],
                product['name'],
                product['foreign_id'],
                SEPHORA_URL + product['url']
            ))

            if not product.get('raw_ingredients'):
                details = product_details(product_url=product['url'], session=session)

                print("\nINGREDIENTS:")
                # pprint(details['raw_ingredients'])
                pprint(details['ingredients'])

                if args.run:
                    db.products.find_and_modify(
                        query={'_id': product['_id']},
                        update={'$set': details},
                        upsert=False
                    )

        if args.export:
            f = open('{}.csv'.format(category.replace('-', '_')), 'w')
            f.write('Brand;Name of product;Price range;Number of stars;Image URL;Product details page URL;Ingredients\n')


            for p in db.products.find(filter={'category': category}, sort=[('_id',  1)]):
                print(p.get('ingredients', []))
                f.write('{brand};{name};{price};{rating};{img};{url};{ingredients}\n'.format(
                    brand=p['brand'],
                    name=p['name'],
                    price=p['price'],
                    rating=p['rating'],
                    img=SEPHORA_URL + p['img'],
                    url=SEPHORA_URL + p['url'],
                    ingredients=p.get('ingredients', [])
                ))

            f.close()
