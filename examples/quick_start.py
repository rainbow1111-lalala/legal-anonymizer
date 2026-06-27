#!/usr/bin/env python3
"""
Quick start examples - Legal Document Anonymizer.
"""

import sys
from pathlib import Path

# Add the parent directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anonymizer import LegalAnonymizer


def example_1_basic_text():
    """Example 1: basic text redaction."""
    print("=" * 60)
    print("Example 1: basic text redaction")
    print("=" * 60)

    anonymizer = LegalAnonymizer()

    text = """
张三是北京示例科技有限公司的法定代表人，
他的手机号是13800001111，身份证号是110101199001011234，
邮箱是zhangsan@example.com。
    """.strip()

    print("\nOriginal text:")
    print("-" * 60)
    print(text)

    anonymized, mapping = anonymizer.anonymize_text(text)

    print("\n\nAfter redaction:")
    print("-" * 60)
    print(anonymized)

    print("\n\nMapping table:")
    print("-" * 60)
    for placeholder, info in mapping.items():
        print(f"{placeholder} -> {info['original']} ({info['type']})")

    print()


def example_2_custom_entities():
    """Example 2: using custom entities."""
    print("=" * 60)
    print("Example 2: using custom entities")
    print("=" * 60)

    anonymizer = LegalAnonymizer()

    # Add custom entities
    anonymizer.add_custom_entity("person", "张三")
    anonymizer.add_custom_entity("person", "李四")
    anonymizer.add_custom_entity("company", "北京示例科技有限公司")
    anonymizer.add_custom_entity("company", "示例科技")
    anonymizer.add_custom_entity("address", "北京市海淀区中关村大街1号")
    anonymizer.add_custom_entity("law_firm", "北京市某某律师事务所")

    text = """
张三和李四代表北京示例科技有限公司（示例科技），
于2026年2月27日在北京市海淀区中关村大街1号
与北京市某某律师事务所签订了合同。
    """.strip()

    print("\nOriginal text:")
    print("-" * 60)
    print(text)

    anonymized, mapping = anonymizer.anonymize_text(text)

    print("\n\nAfter redaction:")
    print("-" * 60)
    print(anonymized)

    print()


def example_3_partial_masking():
    """Example 3: partial masking strategy."""
    print("=" * 60)
    print("Example 3: partial masking strategy (keep some information)")
    print("=" * 60)

    anonymizer = LegalAnonymizer()

    # Set the partial masking strategy
    anonymizer.set_mask_strategy("id_card", "partial")
    anonymizer.set_mask_strategy("phone", "partial")
    anonymizer.set_mask_strategy("email", "partial")
    anonymizer.set_mask_strategy("bank_account", "partial")

    text = """
身份证号：110101197001011234
手机号：13812345678
邮箱：zhangsan@example.com
银行卡号：6222021234567890123
    """.strip()

    print("\nOriginal text:")
    print("-" * 60)
    print(text)

    anonymized, mapping = anonymizer.anonymize_text(text)

    print("\n\nAfter redaction (partial masking):")
    print("-" * 60)
    print(anonymized)

    print()


def example_4_analyze():
    """Example 4: analyze a document (without actually redacting)."""
    print("=" * 60)
    print("Example 4: analyze sensitive information in a document")
    print("=" * 60)

    anonymizer = LegalAnonymizer()

    text = """
张三，身份证号110101199001011234，电话13800001111，
任职于北京示例科技有限公司（统一社会信用代码：91110000000000000X），
地址：北京市海淀区中关村大街1号，
邮箱：zhangsan@example.com，网址：http://www.example.com。
    """.strip()

    analysis = anonymizer.analyze_text(text)

    print(f"\nFound {analysis['total_findings']} items of sensitive information")
    print(f"Across {analysis['type_count']} types\n")

    for entity_type, examples in analysis['findings'].items():
        print(f"[{entity_type}] ({len(examples)} item(s)):")
        for example in examples:
            print(f"  - {example}")
        print()


def example_5_file_processing():
    """Example 5: file processing."""
    print("=" * 60)
    print("Example 5: file processing")
    print("=" * 60)

    sample_file = Path(__file__).parent / "sample.txt"

    if not sample_file.exists():
        print(f"Sample file not found: {sample_file}")
        return

    anonymizer = LegalAnonymizer()

    # Add custom entities
    entities_file = Path(__file__).parent / "sample_entities.json"
    anonymizer.load_entities_from_file(str(entities_file))

    # Analyze the file
    print("\n[1/3] Analyzing the file...")
    analysis_result = anonymizer.analyze_file(str(sample_file))

    if 'error' in analysis_result:
        print(f"Error: {analysis_result['error']}")
        return

    analysis = analysis_result['result']['analysis']
    print(f"  Found {analysis['total_findings']} items of sensitive information")

    # Redact the file
    print("\n[2/3] Redacting the file...")
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # First use the placeholder strategy
    result = anonymizer.anonymize_file(
        str(sample_file),
        str(output_dir / "sample_anonymized.txt"),
        output_format="txt",
        save_mapping=True
    )

    if 'error' in result:
        print(f"Error: {result['error']}")
        return

    r = result['result']
    print(f"  Made {r['replacements_made']} replacements")

    # Then use the partial masking strategy
    print("\n[3/3] Using the partial masking strategy...")
    anonymizer.reset()
    anonymizer.load_entities_from_file(str(entities_file))

    # Set partial masking
    partial_types = ['id_card', 'phone', 'fax', 'toll_free', 'bank_account',
                   'email', 'passport', 'credit_code', 'license_plate']
    for etype in partial_types:
        anonymizer.set_mask_strategy(etype, "partial")

    result2 = anonymizer.anonymize_file(
        str(sample_file),
        str(output_dir / "sample_partial_masked.txt"),
        output_format="txt",
        save_mapping=True
    )

    print("\nDone. Output files:")
    print(f"  - {output_dir / 'sample_anonymized.txt'}")
    print(f"  - {output_dir / 'sample_partial_masked.txt'}")
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Legal Document Anonymizer - Quick start examples")
    print("=" * 60)

    examples = [
        ("Basic text redaction", example_1_basic_text),
        ("Custom entities", example_2_custom_entities),
        ("Partial masking strategy", example_3_partial_masking),
        ("Analyze a document", example_4_analyze),
        ("File processing", example_5_file_processing),
    ]

    for i, (name, func) in enumerate(examples, 1):
        print(f"\n\n\n[{i}/{len(examples)}] {name}")
        try:
            func()
        except Exception as e:
            print(f"Example failed: {e}")
            import traceback
            traceback.print_exc()

        print()
        input("Press Enter to continue to the next example...")

    print("\n" + "=" * 60)
    print("All examples complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
