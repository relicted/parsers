import os
import re
import json
import argparse
import pymongo
from requests_html import HTMLSession

DOMAIN = 'https://www.thedetoxmarket.com'


def get_category_products(category, session=None):
    if not session:
        session = HTMLSession()

    products = []

    def get_products_from_page(page=0):
        page += 1
        xpath = '//div[@class="product-image"]//a[@class="product-grid-image"]/@href'
        r = session.get(f'{DOMAIN}/collections/{category}?page={page}')
        r.html.render(wait=0.4, sleep=1)
        etree = r.html.lxml
        page_products = etree.xpath(xpath)

        if page_products:
            products.extend(page_products)
            get_products_from_page(page=page)

    get_products_from_page()

    return products


def get_product_information(url, session=None):
    if not session:
        session = HTMLSession()

    variants = []
    product_variants = []

    r = session.get(url)

    def check_for_variants():

        etree = r.html.lxml
        script = etree.xpath('//script[contains(., "var meta")]/text()', first=True)
        if script:
            match = re.search('\"variants\":(.*?])},', script[0])
            if match:
                data = json.loads(match.group(1))
                variants.extend(data)
        return

    check_for_variants()
    if variants:
        # r.html.render(wait=0.4, sleep=1)
        for variant in variants:
            try:
                r = session.get(f'{url}?variant={variant.get("id")}')

                etree = r.html.lxml

                size_match = re.search('\d.+oz|\d.+ml', variant.get('sku'))
                size = size_match.group(0) if size_match else ''

                rating_path = etree.xpath('//meta[@itemprop="ratingValue"]/@content')
                rating = rating_path[0] if rating_path else ''

                images = [etree.xpath('//meta[@property="og:image"]/@content')[0]]

                ingredients = []
                div_id = etree.xpath('//a[@data-parent="#accordion" and contains(text(), "Ingredients")]/@href')
                if div_id:
                    div_id = div_id[0].replace('#', '')
                    text = etree.xpath(
                        f'//*[@id="{div_id}"]//*[@id="ingredients_area"]/div/text()'
                    )
                    text = ', '.join([x for x in text if x.strip()])

                    ingredients.extend([x.strip() for x in text.split(', ')])

                product_info = dict(
                    url=r.url,
                    product_id=etree.xpath('//div[@class="product"]//form[@data-productid]/@data-productid')[0],
                    variant_id=variant.get('id'),
                    name=variant.get('public_title'),
                    brand=etree.xpath('//meta[@name="twitter:data2"]/@content')[0],
                    price=variant.get('price') / 100,
                    currency=etree.xpath('//meta[@property="og:price:currency"]/@content')[0],
                    description=etree.xpath('//meta[@property="og:description"]/@content')[0],
                    rating=rating,
                    size=size,
                    images=images,
                    ingredients=ingredients
                )
                product_variants.append(product_info)
            except IndexError:
                return
    return product_variants


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--export', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()

    connection = pymongo.MongoClient(
        host=os.getenv('MONGO_HOST', '127.0.0.1'),
        port=os.getenv('MONGO_PORT', 27017)
    )
    db = connection.detox

    session = HTMLSession()

    categories = [
        'skin-care',
        'body-bath',
        'foundation',
        'blush',
        'highlighters-bronzers',
        'primer-concealer',
        'finishing-powder',
        'lips',
        'eyes-and-brows',
        'makeup-remover',
    ]
    if args.export:
        for category in categories:
            f = open('{}.csv'.format(category.replace('-', '_')), 'w')
            header = 'Brand;Name;Price;Currency;Rating;Size;Description;Images;URL;Ingredients\n'
            f.write(header)
            content = '{brand};{name};{price};{currency};{rating};{size};{description};{images};{url};{ingredients}\n'

            for p in db.products.find(filter={'category': category}, sort=[('_id', 1)]):
                f.write(content.format(
                    brand=p['brand'],
                    name=p['name'],
                    price=p['price'],
                    currency=p['currency'],
                    rating=p['rating'],
                    size=p['size'],
                    images=p['images'],
                    url=p['url'],
                    ingredients=p['ingredients'],
                    description=p['description']
                ))

            f.close()

    if args.run:
        for category in categories:
            products = get_category_products(category=category, session=session)

            for i, p in enumerate(products, start=1):
                product = get_product_information(DOMAIN + p, session=session)
                if not product:
                    continue

                if isinstance(product, list) or isinstance(product, tuple):
                    for x in product:
                        print(f'Processing: {x["url"]}')
                        print('\nINGREDIENTS:')
                        print(x['ingredients'])
                        x['category'] = category
                        db.products.find_and_modify(
                            query={'product_id': x['product_id'], 'variant_id': x['variant_id']},
                            update={'$set': x},
                            upsert=True
                        )
