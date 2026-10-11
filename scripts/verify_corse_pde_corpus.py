# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Optional isolated fixture QA; not a Django service or a Prefect validator."""

import hashlib
import json
import tempfile
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from saxonche import PySaxonProcessor


def main() -> None:
    """Compare all XPath cases and the pinned upstream example with expected results."""
    root = Path(__file__).resolve().parents[1]
    corpus = json.loads(
        (root / "src/rpsd_config/exchange_agreement/data/corse_pde.json").read_text()
    )
    fixtures = root / "tests_integration/exchange_agreement/fixtures/corse_pde"
    cases = json.loads((fixtures / "cases.json").read_text())["cases"]
    sample = fixtures / "upstream"
    expected_bundle = corpus["bundle"]
    bundle = (sample / "netex.zip").read_bytes()
    if hashlib.sha256(bundle).hexdigest() != expected_bundle["sha256"]:
        raise ValueError("Bundle digest mismatch.")
    example = sample / "example_5t.xml"
    if hashlib.sha256(example.read_bytes()).hexdigest() != corpus["example"]["sha256"]:
        raise ValueError("Example digest mismatch.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with tempfile.TemporaryDirectory() as directory:
        with ZipFile(sample / "netex.zip") as archive:
            for name, digest in expected_bundle["files"].items():
                content = archive.read(name)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError("Schema source digest mismatch.")
                target = Path(directory) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        schema = etree.XMLSchema(
            etree.parse(str(Path(directory) / expected_bundle["entrypoint"]), parser)
        )
        schema.assertValid(etree.parse(str(example), parser))
        if schema.validate(etree.parse(str(fixtures / "nx-000_invalid.xml"), parser)):
            raise ValueError("Invalid root unexpectedly passed the XSD.")
    rules = [
        r for r in corpus["rules"] if r["requirement_type"] not in {"XSD", "STATO"}
    ]
    report = {
        "schema_valid_5t": True,
        "schema_invalid_fixture_rejected": True,
        "verification_scope": "isolated engines; no Prefect or ingestion",
        "cases": {},
    }
    with PySaxonProcessor(license=False) as processor:
        report["engine"] = processor.version
        for case in [*cases, {"file": str(example)}]:
            path = Path(case["file"])
            if not path.is_absolute():
                path = fixtures / path
            failures = {}
            for rule in rules:
                xpath = processor.new_xpath_processor()
                xpath.declare_namespace("n", "http://www.netex.org.uk/netex")
                xpath.declare_namespace("xs", "http://www.w3.org/2001/XMLSchema")
                xpath.set_context(file_name=str(path))
                result = xpath.evaluate(rule["definition"])
                count = result.size if result is not None else 0
                if count:
                    failures[rule["code"]] = count
            if path == example:
                if failures != {"NX-004": 1, "NX-013": 4}:
                    raise ValueError(f"Unexpected 5T results: {failures}")
            elif sorted(failures) != sorted(case["expected_failed_xpath_rules"]):
                raise ValueError(f"Unexpected results for {path.name}: {failures}")
            report["cases"][path.name] = failures
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
