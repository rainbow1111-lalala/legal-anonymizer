#!/usr/bin/env python3
"""
Legal Document Anonymizer - CLI Interface
Legal Anonymizer - command-line interface

Usage:
    python cli.py anonymize input.pdf -o output.pdf
    python cli.py analyze input.docx
    python cli.py list-types
"""

import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional

from anonymizer import LegalAnonymizer


def load_entities_from_file(file_path: str) -> List[Dict]:
    """Load custom entities from a file."""
    path = Path(file_path)
    if not path.exists():
        return []

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_result_summary(result: Dict, quiet: bool = False):
    """Print a summary of the result."""
    if 'error' in result:
        if not quiet:
            print(f"❌ Error: {result['error']}", file=sys.stderr)
        return

    r = result['result']

    if not quiet:
        print("\n" + "=" * 60)
        print("✅ Processing complete")
        print("=" * 60)

        analysis = r.get('analysis', {})
        print(f"\n📊 Analysis stats:")
        print(f"  Sensitive information types found: {analysis.get('type_count', 0)}")
        print(f"  Total found: {analysis.get('total_findings', 0)}")

        print(f"\n🔒 Anonymization stats:")
        print(f"  Unique entities: {r.get('total_matched', 0)}")
        print(f"  Replacements made: {r.get('replacements_made', 0)}")

        if 'output_txt' in r:
            print(f"  Text output: {r['output_txt']}")
        if 'output_pdf' in r:
            print(f"  PDF output: {r['output_pdf']}")
        if 'output_docx' in r:
            print(f"  Word output: {r['output_docx']}")
        if 'output_md' in r:
            print(f"  Markdown output: {r['output_md']}")
        if 'text_backup' in r:
            print(f"  Text backup: {r['text_backup']}")
        if 'mapping_file' in r:
            print(f"  Mapping table: {r['mapping_file']}")

        print("\n⚠️  Note: the mapping table contains the original sensitive information. Keep it safe!")


def print_analysis_summary(result: Dict, quiet: bool = False, with_context: bool = False):
    """Print an analysis summary."""
    if 'error' in result:
        if not quiet:
            print(f"❌ Error: {result['error']}", file=sys.stderr)
        return

    r = result['result']
    analysis = r.get('analysis', {})
    findings = analysis.get('findings', {})

    if not quiet:
        print("\n" + "=" * 60)
        print("📋 Document sensitive-information analysis")
        print("=" * 60)

        print(f"\n📊 Stats:")
        print(f"  Sensitive information types: {analysis.get('type_count', 0)}")
        print(f"  Total found: {analysis.get('total_findings', 0)}")

        if findings:
            print(f"\n📝 Detailed findings:")
            for entity_type, examples in sorted(findings.items()):
                print(f"\n  [{entity_type}] ({len(examples)} found)")
                # Show at most 5 examples (show all when context is on, which helps review)
                limit = len(examples) if with_context else 3
                for i, example in enumerate(examples[:limit]):
                    if with_context and isinstance(example, dict):
                        # Context mode: show the surrounding text
                        print(f"    ▸ {example['context'][:120]}")
                    else:
                        text_val = example if isinstance(example, str) else example.get('text', '')
                        if i == 2 and len(examples) > 3 and not with_context:
                            print(f"    - {text_val[:50]}… ({len(examples)-2} more)")
                        else:
                            print(f"    - {text_val[:60]}")


def print_supported_types(anonymizer: LegalAnonymizer):
    """Print the supported types."""
    types = anonymizer.get_supported_types()

    print("\n" + "=" * 60)
    print("📋 Supported sensitive-information types")
    print("=" * 60)
    print()

    # Grouped display
    groups = {
        "Identity documents": ['id_card', 'passport', 'hk_macau_pass', 'taiwan_pass', 'military_id'],
        "Company / institution": ['credit_code', 'org_code', 'tax_number'],
        "Case / contract": ['case_number', 'contract_number', 'invoice_number'],
        "Contact details": ['phone', 'fax', 'toll_free', 'email', 'website'],
        "Network identifiers": ['ip_address', 'mac_address'],
        "Financial": ['bank_account', 'amount', 'price'],
        "Vehicle": ['license_plate', 'vin'],
        "Date / time": ['date', 'time', 'datetime'],
        "Address": ['full_address', 'postal_code', 'house_number'],
        "Certificates / permits": ['property_cert', 'permit_number'],
    }

    all_type_names = set(types.keys())
    shown_types = set()

    for group_name, group_types in groups.items():
        group_types_in_list = [t for t in group_types if t in types]
        if group_types_in_list:
            print(f"{group_name}:")
            for t in group_types_in_list:
                print(f"  • {t} - {types[t]}")
                shown_types.add(t)
            print()

    # Show the remaining types
    remaining = all_type_names - shown_types
    if remaining:
        print("Other:")
        for t in sorted(remaining):
            print(f"  • {t} - {types.get(t, '')}")
        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Legal Anonymizer (by Lingbao Huang) - all data is processed locally to protect privacy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage - anonymize a PDF file
  %(prog)s anonymize input.pdf -o output.pdf

  # Anonymize a text file
  %(prog)s anonymize input.txt -o output.txt

  # Anonymize a Word document
  %(prog)s anonymize input.docx -o output.docx

  # Use custom entities
  %(prog)s anonymize input.pdf -o output.pdf -e entities.json

  # Anonymize only specific fields
  %(prog)s anonymize input.pdf -o output.txt --only phone,email

  # Exclude certain fields from anonymization
  %(prog)s anonymize input.pdf -o output.txt --exclude amount,date

  # Use the partial mask strategy (keep part of the information)
  %(prog)s anonymize input.pdf -o output.pdf --mask-strategy partial

  # Analyze a document (without actually anonymizing)
  %(prog)s analyze input.pdf

  # List all supported fields
  %(prog)s list-types
        """
    )

    subparsers = parser.add_subparsers(title='Commands', dest='command', required=True)

    # ========== anonymize command ==========
    anonymize_parser = subparsers.add_parser('anonymize', help='Anonymize a file')
    anonymize_parser.add_argument('input', help='Input file path')
    anonymize_parser.add_argument('-o', '--output', help='Output file path')
    anonymize_parser.add_argument('-e', '--entities', help='Path to a custom-entities JSON file')
    anonymize_parser.add_argument('-f', '--format',
                                     default='auto',
                                     help='Output format: auto/txt/md/pdf/docx, or a comma-separated list (e.g. md,docx,pdf)')
    anonymize_parser.add_argument('--only', help='Anonymize only the specified fields, comma-separated')
    anonymize_parser.add_argument('--exclude', help='Exclude the specified fields, comma-separated')
    anonymize_parser.add_argument('--mask-strategy', choices=['placeholder', 'partial'],
                                     help='Mask strategy: placeholder or partial (partial mask)')
    anonymize_parser.add_argument('--all-strategy', choices=['placeholder', 'partial'],
                                     help='Set the mask strategy for all types')
    anonymize_parser.add_argument('--ocr', action='store_true', help='Use OCR on PDFs (for scanned documents)')
    anonymize_parser.add_argument('--ocr-engine', choices=['rapidocr', 'paddleocr', 'tesseract'],
                                     default='rapidocr',
                                     help='OCR engine: rapidocr (default, fast) | paddleocr (slower but more accurate on complex layouts) | tesseract')
    anonymize_parser.add_argument('--llm', action='store_true',
                                     help='Enable the OpenAI privacy-filter (1.5B) as an extra detection layer '
                                          '(first use downloads a ~2.6GB model; for Chinese documents it mainly catches English entities)')
    anonymize_parser.add_argument('--cn-llm', action='store_true',
                                     help='Enable CLUENER Chinese NER (RoBERTa-base) as an extra layer '
                                          '(~400MB; catches Chinese names/companies/addresses the rules miss)')
    anonymize_parser.add_argument('--ollama', action='store_true',
                                     help='Enable a local Ollama LLM as a 5th extra layer (no extra download; requires Ollama running locally)')
    anonymize_parser.add_argument('--ollama-url', default=None, metavar='URL',
                                     help='Ollama service address (default http://localhost:11434, '
                                          'or set via the LEGAL_ANONYMIZER_OLLAMA_URL environment variable)')
    anonymize_parser.add_argument('--ollama-model', default=None, metavar='MODEL',
                                     help='Ollama model name (default qwen2.5:7b, '
                                          'or set via the LEGAL_ANONYMIZER_OLLAMA_MODEL environment variable)')
    anonymize_parser.add_argument('--no-backup', action='store_true', help='Do not save a text backup')
    anonymize_parser.add_argument('--no-mapping', action='store_true', help='Do not save the mapping table')
    anonymize_parser.add_argument('-q', '--quiet', action='store_true', help='Quiet mode, output JSON only')

    # ========== analyze command ==========
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a document for sensitive information')
    analyze_parser.add_argument('input', help='Input file path')
    analyze_parser.add_argument('--only', help='Analyze only the specified fields, comma-separated')
    analyze_parser.add_argument('--exclude', help='Exclude the specified fields, comma-separated')
    analyze_parser.add_argument('--ocr', action='store_true', help='Use OCR on PDFs')
    analyze_parser.add_argument('--ocr-engine', choices=['rapidocr', 'paddleocr', 'tesseract'],
                                default='rapidocr',
                                help='OCR engine: rapidocr (default, fast) | paddleocr (slower but more accurate) | tesseract')
    analyze_parser.add_argument('--llm', action='store_true',
                                help='Enable the OpenAI privacy-filter as an extra detection layer')
    analyze_parser.add_argument('--cn-llm', action='store_true',
                                help='Enable CLUENER Chinese NER as an extra layer')
    analyze_parser.add_argument('--ollama', action='store_true',
                                help='Enable a local Ollama LLM as a 5th extra layer')
    analyze_parser.add_argument('--ollama-url', default=None, metavar='URL',
                                help='Ollama service address (default http://localhost:11434)')
    analyze_parser.add_argument('--ollama-model', default=None, metavar='MODEL',
                                help='Ollama model name (default qwen2.5:7b)')
    analyze_parser.add_argument('--context', action='store_true',
                                help='Show the surrounding text for each detection, to help judge false positives')
    analyze_parser.add_argument('--context-window', type=int, default=40,
                                help='Context window size (in characters, default 40)')
    analyze_parser.add_argument('-q', '--quiet', action='store_true', help='Quiet mode, output JSON only')

    # ========== list-types command ==========
    list_types_parser = subparsers.add_parser('list-types', help='List all supported fields')

    args = parser.parse_args()

    use_llm = getattr(args, 'llm', False)
    use_cn_llm = getattr(args, 'cn_llm', False)
    use_ollama = getattr(args, 'ollama', False)
    ollama_kw = {}
    if getattr(args, 'ollama_url', None):
        ollama_kw['base_url'] = args.ollama_url
    if getattr(args, 'ollama_model', None):
        ollama_kw['model'] = args.ollama_model
    anonymizer = LegalAnonymizer(
        use_llm=use_llm if use_llm else None,
        use_cn_llm=use_cn_llm if use_cn_llm else None,
        use_ollama=use_ollama if use_ollama else None,
        ollama_kwargs=ollama_kw or None,
    )

    if args.command == 'list-types':
        print_supported_types(anonymizer)
        return

    elif args.command == 'anonymize':
        # Load custom entities
        custom_entities = None
        if args.entities:
            custom_entities = load_entities_from_file(args.entities)

        # Parse the field filters
        only_types = args.only.split(',') if args.only else None
        exclude_types = args.exclude.split(',') if args.exclude else None

        # Set the mask strategy
        if args.all_strategy:
            anonymizer.set_all_mask_strategy(args.all_strategy)
        elif args.mask_strategy:
            # Apply partial masking to the common types
            partial_types = ['id_card', 'phone', 'fax', 'toll_free', 'bank_account',
                           'email', 'passport', 'credit_code', 'license_plate']
            for etype in partial_types:
                anonymizer.set_mask_strategy(etype, args.mask_strategy)

        # Parse --format: a single format string or a comma-separated list of formats
        fmt_arg = args.format
        if fmt_arg and ',' in fmt_arg:
            fmt_arg = [s.strip() for s in fmt_arg.split(',') if s.strip()]

        # Run anonymization
        result = anonymizer.anonymize_file(
            args.input,
            args.output,
            custom_entities=custom_entities,
            output_format=fmt_arg,
            only_types=only_types,
            exclude_types=exclude_types,
            use_ocr=args.ocr,
            ocr_engine=getattr(args, 'ocr_engine', 'rapidocr'),
            save_text_backup=not args.no_backup,
            save_mapping=not args.no_mapping
        )

        # Print the result
        print_result_summary(result, args.quiet)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == 'analyze':
        only_types = args.only.split(',') if args.only else None
        exclude_types = args.exclude.split(',') if args.exclude else None

        result = anonymizer.analyze_file(
            args.input,
            only_types=only_types,
            exclude_types=exclude_types,
            use_ocr=args.ocr,
            ocr_engine=getattr(args, 'ocr_engine', 'rapidocr'),
            with_context=args.context,
            context_window=args.context_window
        )

        print_analysis_summary(result, args.quiet, with_context=args.context)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
