from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import update_daily as updater  # noqa: E402


class UpdateDailyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.places = [
            updater.Place("Sévaré", "Mopti", 14.53, -4.10, updater.normalize_text("Sévaré")),
            updater.Place("Bamako", "Bamako", 12.64, -8.00, updater.normalize_text("Bamako")),
        ]

    def test_normalize_text_removes_accents(self) -> None:
        self.assertEqual(updater.normalize_text("Sécurité à Sévaré"), "securite a sevare")

    def test_parse_rfc822_and_gdelt_dates(self) -> None:
        self.assertEqual(updater.parse_date("20260901123000"), "2026-09-01")
        self.assertEqual(updater.parse_date("Tue, 01 Sep 2026 12:30:00 GMT"), "2026-09-01")

    def test_canonical_url_removes_tracking(self) -> None:
        cleaned = updater.canonical_url("https://Example.com/a?utm_source=x&id=7#part")
        self.assertEqual(cleaned, "https://example.com/a?id=7")
        self.assertEqual(updater.canonical_url("javascript:alert(1)"), "")

    def test_aggregator_source_suffix_is_removed(self) -> None:
        self.assertEqual(
            updater.strip_source_suffix("Un titre sur le Mali - RFI", "RFI"),
            "Un titre sur le Mali",
        )

    def test_place_matching_is_accent_insensitive(self) -> None:
        place = updater.match_place("Affrontements signalés près de Sevare", self.places)
        self.assertIsNotNone(place)
        self.assertEqual(place.name, "Sévaré")

    def test_relevant_article_becomes_cautious_signal(self) -> None:
        article = updater.Article(
            title="Attaque contre les FAMa à Bamako",
            url="https://example.org/article",
            source="Média test",
            source_system="RSS test",
            published="2026-08-30",
            summary="Une source publique rapporte un affrontement.",
            language="fr",
            tier="editorial",
        )
        place = updater.match_place(article.title, self.places)
        score = updater.relevance_score(article, place)
        event = updater.article_to_event(article, place, score, 2)
        feature = updater.event_to_feature(event)
        self.assertGreaterEqual(score, 4)
        self.assertEqual(event["status"], "Signal médiatique — vérification requise")
        self.assertEqual(event["actor"], "FAMa / État malien")
        self.assertEqual(feature["geometry"]["coordinates"], [-8.0, 12.64])

    def test_unlocated_signal_has_null_geometry(self) -> None:
        article = updater.Article(
            title="Conflit au Mali",
            url="https://example.org/mali",
            source="Média test",
            source_system="Agrégateur test",
            published=date.today().isoformat(),
            summary="Information à vérifier.",
            language="fr",
            tier="aggregator",
            query_matched=True,
        )
        event = updater.article_to_event(article, None, 5, 2)
        self.assertIsNone(updater.event_to_feature(event)["geometry"])

    def test_local_non_conflict_story_is_not_publishable(self) -> None:
        article = updater.Article(
            title="Exposition culturelle à Bamako",
            url="https://example.org/culture",
            source="Média test",
            source_system="RSS test",
            published="2026-08-30",
            summary="Une nouvelle exposition ouvre ses portes.",
            language="fr",
            tier="editorial",
        )
        place = updater.match_place(article.title, self.places)
        score = updater.relevance_score(article, place)
        self.assertFalse(updater.is_publishable(article, place, score, 4))

    def test_generic_security_word_does_not_create_conflict_signal(self) -> None:
        article = updater.Article(
            title="Sécurité routière à Bamako",
            url="https://example.org/road-safety",
            source="Média local",
            source_system="RSS local",
            published="2026-08-30",
            summary="Une campagne sur l'immatriculation des motos est lancée.",
            language="fr",
            tier="editorial",
        )
        place = updater.match_place(article.title, self.places)
        score = updater.relevance_score(article, place)
        self.assertFalse(updater.is_publishable(article, place, score, 4))

    def test_retained_events_are_rechecked_with_current_filter(self) -> None:
        self.assertFalse(
            updater.event_matches_current_filter(
                {"title": "Sécurité routière à Bamako", "summary": "Immatriculation des motos"}
            )
        )
        self.assertTrue(
            updater.event_matches_current_filter(
                {"title": "Attaque à Bamako", "summary": "Information à recouper"}
            )
        )

    def test_social_signal_requires_mali_and_conflict_context(self) -> None:
        article = updater.Article(
            title="Alerte sécurité sans lieu",
            url="https://x.com/example/status/1",
            source="Média local",
            source_system="X public — @example",
            published="2026-08-30",
            summary="Une attaque est rapportée.",
            language="fr",
            tier="social",
            query_matched=True,
        )
        score = updater.relevance_score(article, None)
        self.assertFalse(updater.is_publishable(article, None, score, 4))

    def test_social_target_can_use_a_public_rss_template(self) -> None:
        targets, sources = updater.normalize_social_targets(
            [
                {
                    "name": "Média test",
                    "platform": "x",
                    "handle": "Media_Test",
                    "profile_url": "https://x.com/Media_Test",
                }
            ],
            "https://rss.example.org/x/{handle}.xml",
        )
        self.assertEqual(targets[0]["handle"], "Media_Test")
        self.assertTrue(targets[0]["feed_active"])
        self.assertEqual(sources[0]["kind"], "social_rss")
        self.assertEqual(sources[0]["url"], "https://rss.example.org/x/Media_Test.xml")

    def test_rss_helpers_support_atom_links(self) -> None:
        entry = ET.fromstring(
            '<entry xmlns="http://www.w3.org/2005/Atom">'
            '<title>Actualité Mali</title>'
            '<link rel="alternate" href="https://example.org/story" />'
            '</entry>'
        )
        self.assertEqual(updater.first_xml_text(entry, {"title"}), "Actualité Mali")
        self.assertEqual(updater.rss_item_link(entry), "https://example.org/story")

    def test_duplicate_syndicated_headlines_are_merged(self) -> None:
        events = [
            {
                "id": "one",
                "date": "2026-08-30",
                "title": "Une actualité importante au Mali - RFI",
                "source": "RFI",
                "source_url": "https://example.org/one",
            },
            {
                "id": "two",
                "date": "2026-08-30",
                "title": "Une actualité importante au Mali - RFI",
                "source": "RFI",
                "source_url": "https://example.org/two",
            },
        ]
        self.assertEqual(len(updater.dedupe_events(events)), 1)


if __name__ == "__main__":
    unittest.main()
