# SPDX-License-Identifier: GPL-2.0-only
import json
from pathlib import Path
import unittest
from update_rules import compact, filter_direct, intersection, matches, parse_domains


class ScopeTests(unittest.TestCase):
    def test_suffix_boundary(self):
        scopes = {('DOMAIN-SUFFIX', 'qq.com')}
        self.assertFalse(matches('evilqq.com', scopes))
        self.assertFalse(matches('qq.com.attacker.cn', scopes))
        self.assertTrue(matches('a.qq.com', scopes))

    def test_broad_upstream_cannot_widen_scope(self):
        scope = {('DOMAIN-SUFFIX', 'qq.com'), ('DOMAIN', 'specific.shared.example')}
        upstream = {('DOMAIN-SUFFIX', 'com'), ('DOMAIN-SUFFIX', 'cn'),
                    ('DOMAIN-SUFFIX', 'shared.example'), ('DOMAIN-SUFFIX', 'aliyuncs.com'),
                    ('DOMAIN-SUFFIX', 'small-business.example.cn')}
        got = filter_direct(upstream, scope, set())
        self.assertEqual(got, scope)
        self.assertFalse(matches('other.shared.example', got))

    def test_exact_host_is_not_promoted_to_suffix(self):
        scope = {('DOMAIN-SUFFIX', 'qq.com')}
        got = filter_direct({('DOMAIN', 'a.qq.com')}, scope, set())
        self.assertEqual(got, {('DOMAIN', 'a.qq.com')})
        self.assertFalse(matches('child.a.qq.com', got))

    def test_domain_set_dot_semantics(self):
        rules, ignored = parse_domains('.qq.com\nonly.qq.com\ncn\n', True)
        self.assertEqual(rules, {('DOMAIN-SUFFIX', 'qq.com'), ('DOMAIN', 'only.qq.com')})
        self.assertEqual(ignored, {'invalid-domain': 1})

    def test_no_upstream_policy_or_ip_injection(self):
        rules, _ = parse_domains('GEOIP,CN\nIP-CIDR,0.0.0.0/0\nDOMAIN-KEYWORD,qq\nFINAL,DIRECT\n'
                                 'DOMAIN-SUFFIX,qq.com,DIRECT\nRULE-SET,https://bad.example\n'
                                 'DOMAIN-SUFFIX,qq.com\n')
        self.assertEqual(rules, {('DOMAIN-SUFFIX', 'qq.com')})

    def test_compaction_does_not_broaden(self):
        self.assertEqual(compact({('DOMAIN-SUFFIX', 'qq.com'), ('DOMAIN', 'a.qq.com'),
                                  ('DOMAIN-SUFFIX', 'b.qq.com')}), {('DOMAIN-SUFFIX', 'qq.com')})

    def test_generated_scope_invariants(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / 'rules/direct.list').exists():
            self.skipTest('Run updater to validate generated output')
        settings = json.loads((root / 'policy/approved-direct.json').read_text())
        rules, ignored = parse_domains((root / 'rules/direct.list').read_text())
        scopes = {tuple(r) for r in settings['approved_scope']}
        self.assertFalse(ignored)
        for rule in rules:
            self.assertTrue(any(intersection(rule, s) == rule for s in scopes), rule)
        for host in settings['required_direct_hosts']:
            self.assertTrue(matches(host, rules), host)
        for host in settings['required_proxy_hosts']:
            self.assertFalse(matches(host, rules), host)

    def test_fixed_profile_only_refreshes_two_lists(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'profiles/sr_cn_popular_direct_others_proxy_auto.conf').read_text()
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith('#')]
        self.assertFalse(any(l.startswith('update-url') for l in lines))
        remote = [l for l in lines if l.startswith('RULE-SET,')]
        base = 'RULE-SET,https://raw.githubusercontent.com/aiStone-pro/shadowrocket-rules/main/rules/'
        self.assertEqual(remote, [base + 'ads.list,REJECT', base + 'direct.list,DIRECT'])
        catchall = lines.index('DOMAIN-KEYWORD,.,PROXY')
        geoip = lines.index('GEOIP,CN,DIRECT,no-resolve')
        final = lines.index('FINAL,PROXY')
        self.assertLess(lines.index(remote[1]), catchall)
        self.assertLess(catchall, geoip)
        self.assertLess(geoip, final)


if __name__ == '__main__':
    unittest.main()
