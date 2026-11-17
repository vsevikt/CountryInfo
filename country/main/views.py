import json
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render


CACHE_KEY = 'countrylayer_all_countries'
CACHE_SECONDS = 24 * 60 * 60
VIEWS = {'countries', 'regions', 'languages'}


def home(request):
    params = request.GET
    view = params.get('view', 'countries')
    view = view if view in VIEWS else 'countries'
    query = params.get('q', '').strip()
    region = params.get('region', '').strip()
    language = params.get('language', '').strip()

    countries, error = get_countries()
    context = {
        'active_view': view,
        'page_title': view.capitalize(),
        'catalog_items': [],
        'country_items': [],
        'selected_country': None,
        'capital_detail': bool(params.get('capital')),
        'error': error,
        'search_query': query,
        'search_placeholder': f'Search {view}…',
        'clear_search_url': url(view=view, region=region, language=language),
        'back_url': url(view=view, q=query),
    }

    if not error:
        if params.get('country') or params.get('capital'):
            show_detail(context, countries, params)
        elif region or language or (query and view == 'countries'):
            show_countries(context, countries, view, query, region, language)
        else:
            show_catalog(context, countries, view, query)

    return render(request, 'main/index.html', context)


def show_detail(context, countries, params):
    capital = params.get('capital', '').strip()
    field = 'capital' if capital else 'name'
    name = capital or params.get('country', '').strip()
    selected = None
    for country in countries:
        if not same(country.get(field), name):
            continue
        if params.get('capital_country') and not same(country.get('name'), params['capital_country']):
            continue
        selected = country
        break

    if not selected:
        context['error'] = 'No details were found.'
        return

    context.update({
        'selected_country': format_country(selected),
        'detail_title': selected.get(field),
        'detail_subtitle': f"Capital of {selected.get('name')}" if capital else selected.get('region', ''),
    })
    if selected.get('capital') and not capital:
        context['capital_url'] = url(
            view=context['active_view'],
            region=params.get('region'), language=params.get('language'), q=params.get('q'),
            capital=selected['capital'], capital_country=selected.get('name'),
        )


def show_countries(context, countries, view, query, region, language):
    matches = countries
    if region:
        matches = [country for country in matches
                   if same(country.get('region'), region)]
    if language:
        matches = [country for country in matches
                   if any(same(name, language) for name in names(country.get('languages')))]
    if query:
        matches = [country for country in matches
                   if query.casefold() in str(country.get('name', '')).casefold()]

    context['country_items'] = country_links(
        matches, view=view, region=region, language=language, q=query,
    )
    if language:
        context['page_title'] = f'Countries speaking {language}'
    elif region:
        context['page_title'] = region
    elif query:
        context['page_title'] = f'Countries matching “{query}”'
    else:
        context['page_title'] = 'Countries'
    context['back_url'] = url(view='languages' if language else 'regions' if region else 'countries')


def show_catalog(context, countries, view, query):
    if view == 'countries':
        matches = [country for country in countries
                   if query.casefold() in str(country.get('name', '')).casefold()]
        context['catalog_items'] = country_links(matches, view=view)
    else:
        field, key = ('region', 'region') if view == 'regions' else ('languages', 'language')
        counts = count_by(countries, field)
        context['catalog_items'] = [
            {'name': name, 'count': count, 'url': url(view=view, **{key: name})}
            for name, count in sorted(counts.items())
            if query.casefold() in name.casefold()
        ]

    if query:
        context['page_title'] = f'{view.capitalize()} matching “{query}”'


def get_countries():
    countries = cache.get(CACHE_KEY)
    if countries is not None:
        return countries, None
    if not settings.COUNTRYLAYER_ACCESS_KEY:
        return None, 'Add your Countrylayer key to .env.'

    url = f"{settings.COUNTRYLAYER_BASE_URL.rstrip('/')}/all?access_key={settings.COUNTRYLAYER_ACCESS_KEY}"
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
    except (OSError, json.JSONDecodeError):
        return None, 'Countrylayer request failed.'

    if isinstance(data, dict) and (data.get('error') or data.get('message')):
        error = data.get('error') or data.get('message')
        if isinstance(error, dict):
            error = error.get('info') or error.get('message')
        return None, str(error or 'Countrylayer request failed.')
    if not isinstance(data, list):
        return None, 'Countrylayer returned an unexpected response.'

    countries = [country for country in data if isinstance(country, dict)]
    cache.set(CACHE_KEY, countries, CACHE_SECONDS)
    return countries, None


def country_links(countries, **filters):
    return [
        {
            'name': country.get('name') or 'Unknown country',
            'subtitle': country.get('region', ''),
            'url': url(**filters, country=country.get('name', '')),
        }
        for country in countries
    ]


def format_country(country):
    return {
        'name': country.get('name') or 'Unknown country',
        'capital': country.get('capital') or '—',
        'region': country.get('region') or country.get('subregion') or '—',
        'languages': ', '.join(names(country.get('languages'))) or '—',
        'currencies': ', '.join(names(country.get('currencies'))) or '—',
        'population': country.get('population') or '—',
        'area': country.get('area') or '—',
        'alpha2Code': country.get('alpha2Code') or '—',
        'alpha3Code': country.get('alpha3Code') or '—',
        'timezones': ', '.join(names(country.get('timezones'))) or '—',
    }


def names(value):
    if isinstance(value, dict):
        value = value.values()
    if isinstance(value, str):
        return [value] if value else []
    return [item.get('name', '') if isinstance(item, dict) else str(item)
            for item in value or [] if item]


def count_by(countries, field):
    counts = {}
    for country in countries:
        values = names(country.get(field)) if field == 'languages' else [country.get(field)]
        for value in values:
            if value:
                counts[value] = counts.get(value, 0) + 1
    return counts


def same(first, second):
    return str(first or '').casefold() == str(second or '').casefold()


def url(**params):
    return f'?{urlencode({key: value for key, value in params.items() if value})}'
