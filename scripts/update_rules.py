#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch public lists and publish only rules inside the reviewed direct scope."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ADS_URL = 'https://raw.githubusercontent.com/privacy-protection-tools/anti-AD/master/anti-ad-surge.txt'
MAX_DOWNLOAD = 12_000_000


def valid_domain(value):
    if value != value.lower() or len(value) > 253 or '.' not in value:
        return False
    labels = value.split('.')
    if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in labels):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False


def under(host, suffix):
    return host == suffix or host.endswith('.' + suffix)


def parse_domains(text, domain_set=False):
    result = set()
    ignored = Counter()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';', '//')):
            continue
        if domain_set:
            kind = 'DOMAIN-SUFFIX' if line.startswith('.') else 'DOMAIN'
            value = line.lstrip('.')
        else:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) != 2 or parts[0] not in ('DOMAIN', 'DOMAIN-SUFFIX'):
                ignored[parts[0]] += 1
                continue
            kind, value = parts
        value = value.lower()
        if not valid_domain(value):
            ignored['invalid-domain'] += 1
            continue
        result.add((kind, value))
    return result, dict(ignored)


def intersection(rule, scope):
    """Intersection never emits a condition broader than either operand."""
    rk, rv = rule
    sk, sv = scope
    if rk == 'DOMAIN':
        return rule if (rv == sv if sk == 'DOMAIN' else under(rv, sv)) else None
    if sk == 'DOMAIN':
        return scope if under(sv, rv) else None
    if under(rv, sv):
        return rule
    if under(sv, rv):
        return scope
    return None


def compact(rules):
    suffixes = {v for k, v in rules if k == 'DOMAIN-SUFFIX'}
    kept = set()
    for kind, domain in rules:
        labels = domain.split('.')
        parents = ['.'.join(labels[i:]) for i in range(1, len(labels))]
        if any(p in suffixes for p in parents):
            continue
        if kind == 'DOMAIN' and domain in suffixes:
            continue
        kept.add((kind, domain))
    return kept


def filter_direct(upstream, scopes, pinned):
    selected = set(pinned)
    for rule in upstream:
        for scope in scopes:
            hit = intersection(rule, scope)
            if hit:
                selected.add(hit)
    selected = compact(selected)
    for rule in selected:
        assert any(intersection(rule, s) == rule for s in scopes), rule
    return selected


def matches(host, rules):
    return any(host == v if k == 'DOMAIN' else under(host, v) for k, v in rules)


def fetch(url, cache, offline):
    key = hashlib.sha256(url.encode()).hexdigest() + '.txt'
    path = cache / key
    if offline:
        return path.read_text(encoding='utf-8')
    if not url.startswith('https://raw.githubusercontent.com/'):
        raise ValueError('Unexpected upstream host')
    request = urllib.request.Request(url, headers={'User-Agent': 'shadowrocket-rules-updater/1.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read(MAX_DOWNLOAD + 1)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if attempt == 2:
                raise RuntimeError(f'Could not fetch {url}: {error}') from error
            time.sleep(attempt + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Upstream file exceeds size limit')
    text = data.decode('utf-8-sig')
    if not text.strip() or '<html' in text[:300].lower():
        raise ValueError('Invalid upstream response')
    path.write_text(text, encoding='utf-8')
    return text


def build(offline=False, output=None):
    settings = json.loads((ROOT / 'policy/approved-direct.json').read_text())
    scopes = {tuple(r) for r in settings['approved_scope']}
    pinned = {tuple(r) for r in settings['pinned_direct']}
    assert all(valid_domain(v) for _, v in scopes)
    assert pinned <= scopes
    cache = ROOT / '.cache'
    cache.mkdir(exist_ok=True)
    sources = settings['sources']
    urls = sorted({s['url'] for s in sources} | {ADS_URL})
    with ThreadPoolExecutor(max_workers=4) as pool:
        texts = dict(zip(urls, pool.map(lambda u: fetch(u, cache, offline), urls)))
    upstream = set()
    stats = []
    for source in sources:
        text = texts[source['url']]
        rules, ignored = parse_domains(text, source['format'] == 'domain-set')
        if len(rules) < source['min_domains']:
            raise ValueError(f"Source unexpectedly empty: {source['name']}")
        upstream |= rules
        stats.append({'name': source['name'], 'url': source['url'], 'domains': len(rules),
                      'ignored_types': ignored, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
    direct = filter_direct(upstream, scopes, pinned)
    if not 180 <= len(direct) <= 20000:
        raise ValueError(f'Unexpected direct-list size: {len(direct)}')
    for host in settings['required_direct_hosts']:
        if not matches(host, direct):
            raise ValueError(f'Required service disappeared: {host}')
    for host in settings['required_proxy_hosts']:
        if matches(host, direct):
            raise ValueError(f'Unapproved domain became direct: {host}')
    ads, ignored_ads = parse_domains(texts[ADS_URL])
    if ignored_ads or not 10000 <= len(ads) <= 500000:
        raise ValueError(f'Unexpected ad format/count: {len(ads)}, {ignored_ads}')
    for host in settings['required_direct_hosts'] + settings['required_proxy_hosts']:
        if matches(host, ads):
            raise ValueError(f'Ad list blocks a regression host: {host}')
    ad_text = '# Generated from anti-AD (MIT). See LICENSES/anti-AD-MIT.txt.\n'
    ad_text += '# Source: ' + ADS_URL + '\n'
    ad_text += '\n'.join(','.join(r) for r in sorted(ads)) + '\n'
    direct_text = '# Generated from reviewed service sources; GPL-2.0-only.\n'
    direct_text += '# Scope: policy/approved-direct.json; new roots require explicit review.\n'
    direct_text += '\n'.join(','.join(r) for r in sorted(direct)) + '\n'
    summary = {
        'updated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'approved_scope_count': len(scopes), 'direct_rules': len(direct), 'ad_rules': len(ads),
        'outside_scope_rules_ignored': sum(not any(intersection(r, s) for s in scopes) for r in upstream),
        'direct_sha256': hashlib.sha256(direct_text.encode()).hexdigest(),
        'ads_sha256': hashlib.sha256(ad_text.encode()).hexdigest(),
        'ad_source': ADS_URL, 'ad_source_sha256': hashlib.sha256(texts[ADS_URL].encode()).hexdigest(),
        'sources': stats,
    }
    # Validate all downloads and invariants before replacing any publishable output.
    target = Path(output) if output else ROOT / 'rules'
    target.mkdir(parents=True, exist_ok=True)
    for filename, data in [('ads.list', ad_text), ('direct.list', direct_text),
                           ('status.json', json.dumps(summary, ensure_ascii=False, indent=2) + '\n')]:
        temporary = target / (filename + '.tmp')
        temporary.write_text(data, encoding='utf-8')
        temporary.replace(target / filename)
    print(json.dumps({k: v for k, v in summary.items() if k != 'sources'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    build(args.offline, args.output)
