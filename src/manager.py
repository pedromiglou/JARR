#! /usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from flask_migrate import Migrate, MigrateCommand
from flask_script import Manager

import web.models

from bootstrap import application, conf, db
from scripts.probes import ArticleProbe, FeedProbe, FeedLatenessProbe
from web.controllers import FeedController, UserController

logger = logging.getLogger(__name__)
Migrate(application, db)
manager = Manager(application)
manager.add_command('db', MigrateCommand)


@manager.command
def db_empty():
    "Will drop every datas stocked in db."
    with application.app_context():
        web.models.db_empty(db)


@manager.command
def db_create(login='admin', password='admin'):
    "Will create the database from conf parameters."
    admin = {'is_admin': True, 'is_api': True,
             'login': login, 'password': password}
    with application.app_context():
        db.create_all()
        UserController(ignore_context=True).create(**admin)


@manager.command
def fetch(limit=100, retreive_all=False):
    "Crawl the feeds with the client crawler."
    from crawler.http_crawler import CrawlerScheduler
    scheduler = CrawlerScheduler(conf.CRAWLER_LOGIN, conf.CRAWLER_PASSWD)
    scheduler.run(limit=limit, retreive_all=retreive_all)
    scheduler.wait()


@manager.command
def reset_feeds():
    from web.models import User
    fcontr = FeedController(ignore_context=True)
    now = datetime.utcnow()
    last_conn_max = now - timedelta(days=30)

    feeds = list(fcontr.read().join(User).filter(User.is_active.__eq__(True),
                                    User.last_connection >= last_conn_max)
                        .with_entities(fcontr._db_cls.id)
                        .distinct())

    step = timedelta(seconds=3600 / len(feeds))
    for i, feed in enumerate(feeds):
        fcontr.update({'id': feed[0]},
                {'etag': '', 'last_modified': '',
                 'last_retrieved': now - i * step})


manager.add_command('probe_articles', ArticleProbe())
manager.add_command('probe_feeds', FeedProbe())
manager.add_command('probe_feeds_lateness', FeedLatenessProbe())

if __name__ == '__main__':  # pragma: no cover
    manager.run()
