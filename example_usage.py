"""
Example: Pseudonymizing a Legal Settlement Agreement

Demonstrates the pseudonymization tool on a realistic legal document with:
- Legal roles (Plaintiff, Defendant, Attorney)
- Organizations with corporate suffixes
- Multi-currency amounts
- Date interval preservation
- Cross-reference consistency (same person mentioned multiple times)

Usage:
    python example_usage.py
"""

from pseudonymscript import pseudonymize_text

# Sample legal document text
LEGAL_DOCUMENT = """Paragraph 1:
This Agreement is made on 3 May 2021 between Anna Lee, Director of Orion Holdings Ltd ("Plaintiff"), and Carlos Rivera ("Defendant"). The Plaintiff initiated proceedings at Marina Bay Financial Centre, Singapore, seeking recovery of USD 450,000 in outstanding service fees. The amount was to be settled by wire transfer to DBS Bank Ltd, Raffles Place Branch, no later than 15 August 2021.

Paragraph 2:
On 20 October 2021, the parties executed a Settlement Agreement. Anna Lee, in her capacity as Director of Orion Holdings Ltd, agreed to resolve the dispute with Carlos Rivera ("Defendant") on terms providing for payment of EUR 300,000. The Settlement was witnessed by Attorney Jason Tan and signed at One Raffles Quay, Singapore."""


def print_header(title):
    """Print a formatted section header"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def categorize_entities(mapping):
    """Categorize entities by type for organized display"""
    categories = {
        "Legal Persons": [],
        "Organizations": [],
        "Locations": [],
        "Addresses": [],
        "Money": [],
        "Dates": [],
        "Other": []
    }
    
    for original, replacement in mapping.items():
        if any(role in replacement for role in ["Plaintiff", "Defendant", "Attorney", "Director", "Partner"]):
            categories["Legal Persons"].append((original, replacement))
        elif replacement.startswith("ORG") or replacement.startswith("Bank"):
            categories["Organizations"].append((original, replacement))
        elif replacement.startswith(("Country", "City", "State", "Building")):
            categories["Locations"].append((original, replacement))
        elif replacement.startswith("[ADDRESS"):
            categories["Addresses"].append((original, replacement))
        elif any(currency in replacement for currency in ["USD", "EUR", "GBP", "SGD"]):
            categories["Money"].append((original, replacement))
        elif any(month in replacement for month in 
                ["January", "February", "March", "April", "May", "June", 
                 "July", "August", "September", "October", "November", "December"]):
            categories["Dates"].append((original, replacement))
        else:
            categories["Other"].append((original, replacement))
    
    return categories


def check_consistency(mapping, name):
    """Check if all occurrences of a name are pseudonymized consistently"""
    items = [(k, v) for k, v in mapping.items() if name in k]
    if not items:
        return None
    
    unique_replacements = set(v for k, v in items)
    return len(unique_replacements) == 1, unique_replacements, items


def main():
    print_header("LEGAL DOCUMENT PSEUDONYMIZATION EXAMPLE")
    
    print("\n📄 Original Document:")
    print("-" * 80)
    print(LEGAL_DOCUMENT)
    
    # Run pseudonymization
    print("\n⚙️  Processing with pseudonymization tool...")
    pseudonymized_text, entity_mapping = pseudonymize_text(LEGAL_DOCUMENT)
    
    print_header("PSEUDONYMIZED DOCUMENT")
    print(pseudonymized_text)
    
    print_header("ENTITY REPLACEMENTS BY CATEGORY")
    
    categories = categorize_entities(entity_mapping)
    
    for category_name, items in categories.items():
        if items:
            print(f"\n  {category_name}:")
            for original, replacement in items:
                print(f"    • '{original}'")
                print(f"      → '{replacement}'")
    
    print_header("CONSISTENCY VERIFICATION")
    
    # Check Anna Lee consistency
    print("\n  Checking 'Anna Lee' cross-references:")
    result = check_consistency(entity_mapping, "Anna Lee")
    if result:
        is_consistent, replacements, items = result
        for orig, repl in items:
            print(f"    • '{orig}' → '{repl}'")
        if is_consistent:
            print(f"    ✅ Consistent! All references → {list(replacements)[0]}")
        else:
            print(f"    ⚠️  Inconsistent: {replacements}")
    
    # Check Carlos Rivera consistency
    print("\n  Checking 'Carlos Rivera' cross-references:")
    result = check_consistency(entity_mapping, "Carlos Rivera")
    if result:
        is_consistent, replacements, items = result
        for orig, repl in items:
            print(f"    • '{orig}' → '{repl}'")
        if is_consistent:
            print(f"    ✅ Consistent! All references → {list(replacements)[0]}")
        else:
            print(f"    ⚠️  Inconsistent: {replacements}")
    
    # Check Orion Holdings consistency
    print("\n  Checking 'Orion Holdings Ltd' cross-references:")
    result = check_consistency(entity_mapping, "Orion Holdings")
    if result:
        is_consistent, replacements, items = result
        for orig, repl in items:
            print(f"    • '{orig}' → '{repl}'")
        if is_consistent:
            print(f"    ✅ Consistent! All references → {list(replacements)[0]}")
        else:
            print(f"    ⚠️  Inconsistent: {replacements}")
    
    print_header("DATE INTERVAL PRESERVATION CHECK")
    
    dates = [(k, v) for k, v in entity_mapping.items() if any(
        month in v for month in ["January", "February", "March", "April", 
                                 "May", "June", "July", "August", 
                                 "September", "October", "November", "December"])]
    
    print("\n  Original dates:")
    print("    • 3 May 2021")
    print("    • 15 August 2021 (3.5 months later)")
    print("    • 20 October 2021 (5.5 months after first date)")
    
    if dates:
        print("\n  Pseudonymized dates:")
        for original, replacement in dates:
            print(f"    • {replacement}")
        print("\n  ✓ The time intervals between dates should be preserved!")
    
    print_header("SUMMARY")
    print(f"\n  Total entities pseudonymized: {len(entity_mapping)}")
    print(f"  Original text length: {len(LEGAL_DOCUMENT):,} characters")
    print(f"  Pseudonymized text length: {len(pseudonymized_text):,} characters")
    print(f"\n  ✅ Pseudonymization complete!")
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()