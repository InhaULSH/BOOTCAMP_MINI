"""Presentation selection only; report and database versions are independent."""
import gzip
import hashlib
import os


def ui_version():
    value = os.getenv('UI_VERSION', 'old')
    if value not in ('old', 'new'):
        raise ValueError('UI_VERSION은 old 또는 new여야 합니다.')
    return value


def page_bytes(path):
    raw = path.read_bytes()
    if ui_version() == 'old':
        return raw
    text = raw.decode('utf-8')
    text = text.replace('<html lang="ko">', '<html lang="ko" data-ui-version="new">', 1)
    text = text.replace('</head>', '<link rel="stylesheet" href="/assets/ui-new.css">'
                        '<script defer src="/assets/ui-new.js"></script></head>', 1)
    text = text.replace('<p class="load-status">데이터를 불러오는 중입니다.</p>', skeleton(path.name), 1)
    return text.encode('utf-8')


def skeleton(page):
    """Reserve the same responsive card/chart regions before the first API reply."""
    line = '<span class="skeleton-bar"></span>'
    title = '<div class="skeleton-title">' + line * 2 + '</div>'
    if page == 'index.html':
        body = '<div class="sector-field skeleton-block"></div><div class="journey">' + (
            '<article class="skeleton-journey">' + line * 3 + '</article>') * 3 + '</div>'
    else:
        chart = '<article class="panel">' + line * 2 + '<div class="chart skeleton-block"></div></article>'
        insight = '<section class="ai skeleton-insight">' + line * 3 + '</section>'
        cards = ('<div class="detail-kpis">' if page == 'company.html' else '<div class="company-cards skeleton-companies">')
        cards += '<article class="company-card">' + line * 2 + '</article>'
        cards += ('<article class="company-card">' + line * 2 + '</article>') * (3 if page == 'company.html' else 4) + '</div>'
        body = '<section class="top-grid company-top">' + chart * 2 + '</section>' + insight + cards
        body += '<div class="skeleton-title">' + line + '</div><div class="metrics-grid">' + chart * 4 + '</div>'
        if page != 'company.html':
            body += '<section class="panel comparison skeleton-comparison">' + line * 6 + '</section>'
    return '<div class="ui-skeleton" role="status" aria-label="화면 데이터를 준비하고 있습니다."><span class="sr-only">화면 데이터를 준비하고 있습니다.</span><div aria-hidden="true">' + title + body + '</div></div>'


def page_asset(path, compress=False):
    raw = page_bytes(path)
    encoded = compress and len(raw) >= 1024
    body = gzip.compress(raw, compresslevel=3, mtime=0) if encoded else raw
    return body, '"' + hashlib.sha256(body).hexdigest() + '"', encoded
