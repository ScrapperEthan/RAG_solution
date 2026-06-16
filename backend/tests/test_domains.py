from __future__ import annotations

import unittest

from backend.domains import DEFAULT_NAMESPACE, domain_matches, domain_value, parse_domain


class DomainsTest(unittest.TestCase):
    def test_bare_value_is_default_namespace(self) -> None:
        self.assertEqual(parse_domain("人事服务"), (DEFAULT_NAMESPACE, "人事服务"))
        self.assertEqual(domain_value("人事服务"), "人事服务")

    def test_namespaced_value_parses(self) -> None:
        self.assertEqual(parse_domain("system:Integration"), ("system", "Integration"))
        self.assertEqual(domain_value("system:Integration"), "Integration")

    def test_bare_query_matches_across_namespaces(self) -> None:
        self.assertTrue(domain_matches("Integration", "Integration"))
        self.assertTrue(domain_matches("Integration", "system:Integration"))

    def test_namespaced_query_requires_namespace_and_value(self) -> None:
        self.assertTrue(domain_matches("system:Integration", "system:Integration"))
        self.assertFalse(domain_matches("system:Integration", "Integration"))
        self.assertFalse(domain_matches("area:Integration", "system:Integration"))


if __name__ == "__main__":
    unittest.main()
