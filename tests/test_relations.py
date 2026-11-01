"""Binary relationship syntax and invalid input checks."""

import unittest

from apt_graph.relations import (
    Relation,
    parse_provides,
    parse_relation,
    parse_relations,
)


class RelationTests(unittest.TestCase):
    """Preserve mandatory groups and the declared alternative ordering."""

    def test_groups_and_qualifiers(self):
        """Parse constraints, folding whitespace and architecture qualifiers."""
        parsed = parse_relations("foo:any (>= 1:2.0-1) |\n bar, baz:native")
        self.assertEqual(parsed, (
            (Relation("foo", ">=", "1:2.0-1", "any"), Relation("bar")),
            (Relation("baz", architecture="native"),),
        ))
        self.assertEqual(parse_relations(""), ())
        self.assertEqual(parse_relation("libc6:amd64").architecture, "amd64")

    def test_provides(self):
        """Versioned virtual packages use equality declarations only."""
        self.assertEqual(parse_provides("virtual (= 2), other"), (
            Relation("virtual", "=", "2"), Relation("other"),
        ))
        for text in ["one | two", "virtual (>= 2)"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_provides(text)

    def test_invalid_relationships(self):
        """Reject empty alternatives, bad operators and source-only syntax."""
        for text in ["foo,", "foo |", "foo (> 1)", "foo [amd64]", "@foo"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_relations(text)
