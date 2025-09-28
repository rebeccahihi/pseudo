import re

from pseudonymscript import LegalPersonExtractor, pseudonymize_text, LegalPersonPseudonymizer  # Replace with your actual filename

# Add debug to the pseudonymizer
def debug_extract_name_from_entity_text(self, entity_text: str):
    """Extract just the name part from entity text with roles - WITH DEBUG"""
    print(f"DEBUG PSEUDONYMIZER: Extracting name from: '{entity_text}'")
    
    # Pattern: "Michael Tan (Partner)" -> "Michael Tan"
    match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text)
    if match:
        name = match.group(1).strip()
        print(f"DEBUG PSEUDONYMIZER: Found name via first pattern: '{name}'")
        return name
    
    # Pattern: "Plaintiff Michael Tan" -> "Michael Tan" 
    role_name_match = re.search(r'\b(?:plaintiff|defendant|dr\.?|mr\.?|mrs\.?|ms\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text, re.IGNORECASE)
    if role_name_match:
        name = role_name_match.group(1).strip()
        print(f"DEBUG PSEUDONYMIZER: Found name via second pattern: '{name}'")
        return name
    
    print(f"DEBUG PSEUDONYMIZER: No name pattern matched")
    return None

# Monkey patch the debug method
LegalPersonPseudonymizer._extract_name_from_entity_text = debug_extract_name_from_entity_text

# Original diagnostic test
print("="*60)
print("INDIVIDUAL EXTRACTOR TEST")
print("="*60)

extractor = LegalPersonExtractor()
test_cases = [
    "defendant Mary Johnson",
    "plaintiff John Smith", 
    "Defendant Mary Johnson",
    "attorney Sarah Wilson"
]

for case in test_cases:
    print(f"\nTesting: '{case}'")
    entities = extractor.extract(case)
    print(f"Found: {[e.text for e in entities]}")

print("\n" + "="*60)
print("FULL PIPELINE TEST")
print("="*60)

# Full pipeline test
test_text = "defendant Mary Johnson appeared"
result, mapping = pseudonymize_text(test_text)
print(f"Result: {result}")
print(f"Mapping: {mapping}")

print("\n" + "="*60)
print("COMPLEX TEST - PLAINTIFF WITH PARENTHESES")
print("="*60)

# Test the specific case you're seeing
complex_test = "Plaintiff Q Smith (ORG B LLP) filed a complaint"
result2, mapping2 = pseudonymize_text(complex_test)
print(f"Result: {result2}")
print(f"Mapping: {mapping2}")

print("\n" + "="*60)
print("ANALYSIS")
print("="*60)
print("If 'Smith' is appearing, it means the pseudonymizer is not")
print("properly extracting just the name part from 'Plaintiff Q Smith'")
print("Check the DEBUG PSEUDONYMIZER output above to see what's happening.")

# Add this to your test_extractor.py file after the existing tests

print("\n" + "="*60)
print("CEO EXTRACTION TEST")
print("="*60)

# Test CEO extraction specifically
ceo_test_cases = [
    "Michael Chen (CEO, Tech Innovations Pte Ltd)",
    "Sarah Wilson (President, Apple Inc)",
    "John Doe (Managing Director, Goldman Sachs LLP)",
    "CEO Michael Chen filed the report",
    "President Sarah Wilson signed the contract"
]

print("Testing individual CEO extractions:")
for case in ceo_test_cases:
    print(f"\nTesting: '{case}'")
    entities = extractor.extract(case)
    if entities:
        for entity in entities:
            print(f"  Found: '{entity.text}' (role: {entity.role if hasattr(entity, 'role') else 'no role'})")
    else:
        print("  No entities found")

print("\n" + "-"*40)
print("Testing CEO in full pipeline:")

# Test full pipeline with CEO
for case in ceo_test_cases:
    print(f"\nOriginal: {case}")
    result, mapping = pseudonymize_text(case)
    print(f"Result:   {result}")
    if mapping:
        print(f"Mapping:  {mapping}")
    else:
        print("Mapping:  No entities pseudonymized")

print("\n" + "="*60)
print("CHECKING LEGAL ROLES")
print("="*60)

# Check if CEO-related roles are in the legal_roles set
extractor = LegalPersonExtractor()
ceo_roles = ['ceo', 'president', 'managing director', 'director', 'manager', 'chairman', 'officer']

print("Checking if corporate roles are in legal_roles:")
for role in ceo_roles:
    in_roles = role in extractor.legal_roles
    print(f"  '{role}': {'✓' if in_roles else '✗'}")

print("\n" + "="*60)
print("PATTERN 7 DEBUG")
print("="*60)

# Test Pattern 7 specifically
import re

# Recreate Pattern 7 from your extractor
pattern_7 = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(\s*([^,]+),\s*([^)]+)\s*\)', re.IGNORECASE)

test_text = "Michael Chen (CEO, Tech Innovations Pte Ltd)"
print(f"Testing Pattern 7 on: '{test_text}'")
match = pattern_7.search(test_text)
if match:
    print(f"Pattern 7 matches: {match.groups()}")
    name = match.group(1)
    role = match.group(2) 
    org = match.group(3)
    print(f"  Name: '{name}'")
    print(f"  Role: '{role}'")
    print(f"  Organization: '{org}'")
    
    # Check if the role would be recognized
    role_recognized = role.lower() in extractor.legal_roles
    print(f"  Role '{role}' recognized: {'✓' if role_recognized else '✗'}")
else:
    print("Pattern 7 does not match")

print("\n" + "="*40)
print("DIAGNOSIS:")
print("If CEO roles are in legal_roles but Pattern 7 matches but entities aren't found,")
print("the issue is likely in _looks_like_role() or _is_valid_person_entity() validation.")