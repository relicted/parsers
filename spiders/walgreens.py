import os
import re
import json
import argparse
import pymongo
from requests_html import HTMLSession

DOMAIN = 'https://www.walgreens.com'
PAGE_SIZE = 72


def get_products_by_category(category, session=None):
    if not session:
        session = HTMLSession()

    product_pages = []
    products = []

    r = session.get(f'{DOMAIN}/store/c/{category[0]}/ID={category[1]}-tier2general')
    r.html.render(wait=0.4, sleep=1)
    etree = r.html.lxml

    sub_ids = etree.xpath('//a[@class="tracktier2Prop30" and contains(@href, "ID=")]/@href')
    for x in sub_ids:
        _id = re.search('ID=(\d+)', x).group(1)
        product_pages.append(
            f'{DOMAIN}/store/store/category/productlist.jsp?N={_id}&Erp={PAGE_SIZE}'
        )

    def get_products_from_page(product_page, start=0):
        # print(product_page)
        r = session.get(f'{product_page}&No={start}')
        r.html.render(wait=2, sleep=2)
        etree = r.html.lxml
        page_products = etree.xpath('//a[contains(@ng-if, "productDet.productInfo.productUR")]/@href')
        products.extend(page_products)
        next_page = etree.xpath('//*[@id="arrow-2" and not(@disabled)]')
        if next_page:
            get_products_from_page(product_page, start=start + 72)

    for page in product_pages:
        get_products_from_page(page)

    return products


def get_product_info(product, session=None):
    if not session:
        session = HTMLSession()
    print(DOMAIN + product)
    # r.html.render(wait=0.4, sleep=1)3 e=
    try:
        r = session.get(DOMAIN + product)

        etree = r.html.lxml

        product_id = re.search('ID=(.*?)-', product).group(1)

        res = etree.xpath("""//script[contains(., '{"@context":"http://schema.org/"')]/text()""")[0]
        data = json.loads(res)

        raw_ingredients = []
        ingredients = etree.xpath('//div[@name="description-Ingredients"]//span/text()')
        if ingredients:
            text = re.sub('\(.*?\)', '', ''.join(ingredients))
            raw_ingredients.extend(text.split(','))
        product_info = dict(
            url=DOMAIN + product,
            product_id=product_id,
            brand=data.get('brand', {}).get('name', ''),
            name=data.get('name'),
            size=data.get('weight'),
            rating=data.get('aggregateRating', {}).get('ratingValue', ''),
            price=data.get('offers', {}).get('priceCurrency'),
            currency=data.get('offers', {}).get('priceCurrency'),
            source='walgreens',
            ingredients=ingredients,
            img=data.get('image')
        )

        return product_info
    except:
        return


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='Save data to db')
    parser.add_argument('--export', action='store_true', help='Export to csv')
    args = parser.parse_args()

    mongo_connection = pymongo.MongoClient('127.0.0.1', 27017)
    db = mongo_connection.walgreens

    session = HTMLSession()
    categories = (
        # (category, id)
        ('cosmetics', '360337'),
        ('hair-care-products', '360339'),
        ('skin-care-products', '360323'),
        ('bath-and-body-products', '360341'),
        ('sun-care-products', '360333'),
        ('fragrance', '360335'),
        ('beauty-gift-sets', '360329'),
        ('nails', '360445'),
        ('accessories-and-clothing', '360331'),
        ('beauty-for-men', '360327'),
        ('natural-and-organic-beauty-products', '360325')
    )

    for category in categories:
        products = get_products_by_category(category=category, session=session)

        for i, p in enumerate(products):
            product = get_product_info(product=p, session=session)
            if not product:
                continue
            product['category'] = category[0]

            db.products.find_and_modify(
                query={'product_id': product['product_id'], 'category': product['category']},
                update={'$set': product},
                upsert=True
            )

        if args.export:
            f = open('{}.csv'.format(category[0].replace('-', '_')), 'w')
            f.write(
                'Brand;Name of product;Price range;Number of stars;Image URL;Product details page URL;Ingredients\n')

            for p in db.products.find(filter={'category': category[0]}, sort=[('_id', 1)]):
                f.write('{brand};{name};{price};{rating};{img};{url};{ingredients}\n'.format(
                    brand=p['brand'],
                    name=p['name'],
                    price=p['price'],
                    rating=p['rating'],
                    img=p['img'],
                    url=DOMAIN + p['url'],
                    ingredients=p.get('ingredients', [])
                ))
            f.close()