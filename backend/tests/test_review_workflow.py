from pathlib import Path

from app.review.export_reviewed import (
    export_review_db_to_candidate_csvs,
)
from app.review.load_candidates import load_candidates


def write_candidate_files(candidate_dir: Path) -> None:
    candidate_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        candidate_dir / "candidate_concepts.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "slug,label,description,domain,status,concept_type,"
                    "is_public,external_source_slug,external_concept_id,"
                    "review_status,decision,target_concept_slug,notes"
                ),
                (
                    "gleam,Gleam,A small flash of light,light_and_sky,"
                    "active,external_synset,true,oewn-2025,oewn-test,"
                    "pending_review,accept,,"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidate_dir / "candidate_words.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "language_code,text,transliteration,part_of_speech,"
                    "external_entry_id,notes,source_slug,review_status"
                ),
                (
                    "en,gleam,,noun,oewn-gleam,"
                    "Imported from Open English Wordnet.,"
                    "oewn-2025,pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidate_dir / "candidate_word_senses.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "language_code,word_text,part_of_speech,concept_slug,"
                    "gloss,is_primary,equivalence_type,sense_rank,"
                    "external_sense_id,external_synset_id,source_slug,"
                    "source_locator,confidence,review_status"
                ),
                (
                    "en,gleam,noun,gleam,a small flash of light,true,"
                    "canonical,1,oewn-gleam-sense,oewn-gleam-synset,"
                    "oewn-2025,oewn-gleam-synset#sense,high,"
                    "pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidate_dir / "candidate_concept_relationships.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "source_concept_slug,target_concept_slug,"
                    "relationship_type,weight,source_slug,"
                    "source_locator,confidence,review_status"
                ),
                (
                    "illumination,gleam,near_synonym,0.80,"
                    "oewn-2025,manual:illumination-gleam,"
                    "high,pending_review"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (
        candidate_dir / "candidate_concept_mappings.csv"
    ).write_text(
        "\n".join(
            [
                (
                    "source_concept_slug,target_concept_slug,"
                    "mapping_type,weight,source_slug,source_locator,"
                    "confidence,review_status"
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_candidates_creates_review_db(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidates"
    db_path = tmp_path / "review.sqlite"

    write_candidate_files(candidate_dir)

    counts = load_candidates(
        candidate_dir=candidate_dir,
        db_path=db_path,
        replace=True,
    )

    assert db_path.exists()
    assert counts["concepts"] == 1
    assert counts["words"] == 1
    assert counts["word_senses"] == 1
    assert counts["relationships"] == 1


def test_export_review_db_only_exports_reviewed_rows(
    tmp_path: Path,
) -> None:
    candidate_dir = tmp_path / "candidates"
    db_path = tmp_path / "review.sqlite"
    export_dir = tmp_path / "exported"

    write_candidate_files(candidate_dir)

    load_candidates(
        candidate_dir=candidate_dir,
        db_path=db_path,
        replace=True,
    )

    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE review_concepts SET review_status = 'reviewed'"
    )
    conn.execute(
        "UPDATE review_words SET review_status = 'reviewed'"
    )
    conn.execute(
        "UPDATE review_word_senses SET review_status = 'reviewed'"
    )
    conn.commit()
    conn.close()

    counts = export_review_db_to_candidate_csvs(
        db_path=db_path,
        candidates_out=export_dir,
        replace=True,
    )

    assert counts["candidate_concepts.csv"] == 1
    assert counts["candidate_words.csv"] == 1
    assert counts["candidate_word_senses.csv"] == 1
    assert counts["candidate_concept_relationships.csv"] == 0

    exported_senses = (
        export_dir / "candidate_word_senses.csv"
    ).read_text(
        encoding="utf-8"
    )

    assert "gleam" in exported_senses