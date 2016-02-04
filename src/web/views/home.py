import logging
from flask import jsonify
from calendar import timegm

from bootstrap import application as app

from flask import render_template, request, flash, url_for, redirect, g
from flask.ext.login import login_required
from flask.ext.babel import gettext

import conf
from web.lib.utils import redirect_url
from web import utils
from web.lib.view_utils import etag_match
from web.models import Article

from web.controllers import FeedController, \
                            ArticleController, CategoryController

from plugins import readability

logger = logging.getLogger(__name__)


@app.route('/')
@login_required
@etag_match
def home():
    return render_template('home.html', cdn=conf.CDN_ADDRESS)


@app.route('/menu')
@login_required
@etag_match
def get_menu():
    categories_order = [0]
    categories = {0: {'name': 'No category', 'id': 0}}
    for cat in CategoryController(g.user.id).read().order_by('name'):
        categories_order.append(cat.id)
        categories[cat.id] = cat.dump()
    unread = ArticleController(g.user.id).count_by_feed(readed=False)
    for cat_id in categories:
        categories[cat_id]['unread'] = 0
        categories[cat_id]['feeds'] = []
    feeds = {feed.id: feed.dump() for feed in FeedController(g.user.id).read()}
    for feed_id, feed in feeds.items():
        feed['created_stamp'] = timegm(feed['created_date'].timetuple()) * 1000
        feed['last_stamp'] = timegm(feed['last_retrieved'].timetuple()) * 1000
        feed['category_id'] = feed['category_id'] or 0
        feed['unread'] = unread.get(feed['id'], 0)
        if not feed['filters']:
            feed['filters'] = []
        if feed.get('icon_url'):
            feed['icon_url'] = url_for('icon.icon', url=feed['icon_url'])
        categories[feed['category_id']]['unread'] += feed['unread']
        categories[feed['category_id']]['feeds'].append(feed_id)
    return jsonify(**{'feeds': feeds, 'categories': categories,
                      'categories_order': categories_order,
                      'crawling_method': conf.CRAWLING_METHOD,
                      'max_error': conf.DEFAULT_MAX_ERROR,
                      'error_threshold': conf.ERROR_THRESHOLD,
                      'is_admin': g.user.is_admin(),
                      'all_unread_count': sum(unread.values())})


def _get_filters(in_dict):
    filters = {}
    query = in_dict.get('query')
    if query:
        search_title = in_dict.get('search_title') == 'true'
        search_content = in_dict.get('search_content') == 'true'
        if search_title:
            filters['title__ilike'] = "%%%s%%" % query
        if search_content:
            filters['content__ilike'] = "%%%s%%" % query
        if len(filters) == 0:
            filters['title__ilike'] = "%%%s%%" % query
        if len(filters) > 1:
            filters = {"__or__": filters}
    if in_dict.get('filter') == 'unread':
        filters['readed'] = False
    elif in_dict.get('filter') == 'liked':
        filters['like'] = True
    filter_type = in_dict.get('filter_type')
    if filter_type in {'feed_id', 'category_id'} and in_dict.get('filter_id'):
        filters[filter_type] = int(in_dict['filter_id']) or None
    return filters


def _articles_to_json(articles, fd_hash=None):
    return jsonify(**{'articles': [{'title': art.title, 'liked': art.like,
            'read': art.readed, 'article_id': art.id, 'selected': False,
            'feed_id': art.feed_id, 'category_id': art.category_id or 0,
            'feed_title': fd_hash[art.feed_id]['title'] if fd_hash else None,
            'icon_url': fd_hash[art.feed_id]['icon_url'] if fd_hash else None,
            'date': art.date, 'timestamp': timegm(art.date.timetuple()) * 1000}
            for art in articles.limit(1000)]})


@app.route('/middle_panel')
@login_required
@etag_match
def get_middle_panel():
    filters = _get_filters(request.args)
    art_contr = ArticleController(g.user.id)
    fd_hash = {feed.id: {'title': feed.title,
                         'icon_url': url_for('icon.icon', url=feed.icon_url)
                                     if feed.icon_url else None}
               for feed in FeedController(g.user.id).read()}
    articles = art_contr.read(**filters).order_by(Article.date.desc())
    return _articles_to_json(articles, fd_hash)


@app.route('/getart/<int:article_id>')
@app.route('/getart/<int:article_id>/<parse>')
@login_required
@etag_match
def get_article(article_id, parse=False):
    contr = ArticleController(g.user.id)
    article = contr.get(id=article_id).dump()
    if not article['readed']:
        contr.update({'id': article_id}, {'readed': True})
    article['category_id'] = article['category_id'] or 0
    feed = FeedController(g.user.id).get(id=article['feed_id'])
    article['icon_url'] = url_for('icon.icon', url=feed.icon_url) \
            if feed.icon_url else None
    readability_available = bool(g.user.readability_key
                                 or conf.READABILITY_KEY)
    article['readability_available'] = readability_available
    if parse or (not article['readability_parsed']
            and feed.readability_auto_parse and readability_available):
        article['readability_parsed'] = True
        article['content'] = readability.parse(article['link'],
                g.user.readability_key or conf.READABILITY_KEY)
        contr.update({'id': article['id']}, {'readability_parsed': True,
                                             'content': article['content']})
    return jsonify(**article)


@app.route('/mark_all_as_read', methods=['PUT'])
@login_required
def mark_all_as_read():
    filters, acontr = _get_filters(request.json), ArticleController(g.user.id)
    articles = _articles_to_json(acontr.read(**filters))
    acontr.update(filters, {'readed': True})
    return articles


@app.route('/fetch', methods=['GET'])
@app.route('/fetch/<int:feed_id>', methods=['GET'])
@login_required
def fetch(feed_id=None):
    """
    Triggers the download of news.
    News are downloaded in a separated process, mandatory for Heroku.
    """
    if conf.CRAWLING_METHOD == "classic" \
            and (not conf.ON_HEROKU or g.user.is_admin()):
        utils.fetch(g.user.id, feed_id)
        flash(gettext("Downloading articles..."), "info")
    else:
        flash(gettext("The manual retrieving of news is only available " +
                      "for administrator, on the Heroku platform."), "info")
    return redirect(redirect_url())
