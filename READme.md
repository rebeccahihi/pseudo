# Legal Document Pseudonymizer

Version 1.0 - Prototype

This tool was developed as a prototype to demonstrate automated pseudonymization of sensitive information in legal documents. It attempts to preserve document structure, readability, and consistency across references while handling legal persons with roles, organizations, dates, money amounts, and addresses.

---

## Overview

This prototype addresses the technical challenges of:
- Identifying legal persons with their roles (Plaintiff, Defendant, Attorney)
- Maintaining cross-reference consistency throughout documents
- Preserving document structure during entity replacement
- Handling multiple file formats and character encodings
- Managing entity overlap and priority resolution

---

## Limitations and Constraints

This is a prototype implementation with known limitations:

- Does not guarantee 100% entity detection coverage
- Some uncommon role patterns are not supported
- Standalone role words may not be consistently replaced
- Percentage values may occasionally remain unchanged due to randomization
- Not designed for production deployment
- Requires manual verification of all outputs
- Does not ensure GDPR/PDPA compliance

---

## Setup Instructions

### Requirements
- Python 3.8 or higher
- 2GB RAM minimum
- 1GB free disk space

### 1. Clone the Repository
```bash
git clone <repo-url>
cd pseudonymizer
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
.venv\Scripts\activate         # Windows
```
### 3. Install Dependencies
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```
### 4. Download spaCy model
```bash
# Recommended: Transformer model
python -m spacy download en_core_web_trf

# Alternative: Small model
python -m spacy download en_core_web_sm
```
### 5. Verify Installation
```bash
python --version
python -c "import spacy; nlp = spacy.load('en_core_web_sm'); print('spaCy model loaded')"
```
## Running the Application

### Web Interface
```bash
streamlit run pseudonymizer_app.py
```

### Command Line
```bash
python -c "from pseudonymscript import pseudonymize_text; \
result, mapping = pseudonymize_text(open('input.txt').read()); \
print(result)" > output.txt
```
## Usage Instructions

1. Upload a TXT, DOCX, or PDF file via the Document Processor tab
2. Review the side-by-side comparison of original and pseudonymized text
3. Examine the Entity Mapping table for all replacements
4. Download the pseudonymized document in PDF or TXT format
5. Manually verify all outputs before use

## Techincal Architecture
```bash
pseudonymizer/
├── pseudonymizer_app.py          # Streamlit interface
├── pseudonymscript.py            # Core pseudonymization logic
├── compare_test.py               # Test suite
├── requirements.txt              # Dependencies
└── README.md                     # Documentation
```

## Key Components
- Entity extractors for dates, organizations, money, addresses, and legal persons
- Entity pseudonymizers with caching for consistency
- Pipeline coordinator for extraction and replacement
- Document processors for TXT, DOCX, and PDF formats

## Dependencies
### Core dependencies:
- Streamlit 1.50.0 - Web interface
- spaCy 3.8.7 - Named entity recognition
- Pandas 2.3.2 - Data processing
- python-docx 1.2.0 - DOCX processing
- PyPDF2 3.0.1 / pdfplumber 0.11.7 - PDF processing
- reportlab 4.4.4 - PDF generation

Complete dependency list available in requirements.txt (50+ packages).


## Known Issues

### Technical Challenges Identified

1. Pattern Recognition
   - Complex legal role patterns may not be detected
   - Format variations require additional pattern definitions

2. Quote Character Handling
   - Curly quotes from Word documents require normalization
   - Character encoding inconsistencies across file formats

3. Entity Overlap Resolution
   - Priority system required to handle overlapping entity boundaries
   - Cross-reference tracking complexity

4. Randomization Consistency
   - Small percentage values may randomly remain unchanged
   - Trade-off between consistency and variation

5. Multi-Role Entity Confusion
   - Entities with multiple roles may be inconsistently classified
   - Role priority system may select unexpected primary role

### Entity Type Edge Cases

The following edge cases have been identified during development. This list is not exhaustive and additional limitations may exist.

1. Legal Persons
   - Unconventional role formats not covered by current patterns
   - Names with prefixes or suffixes may not be extracted correctly
   - Multiple people with identical names cannot be distinguished
   - Non-Western name structures may be misidentified

2. Organizations
   - Corporate suffixes outside the predefined list may not be recognized
   - Merged or hyphenated company names may be partially extracted
   - Organizations without formal suffixes are not detected
   - Parent-subsidiary relationships are not preserved

3. Dates
   - Non-standard date formats may not be parsed
   - Relative date expressions not supported
   - Fiscal year references are not recognized
   - Date ranges with varied formatting may be inconsistently handled

4. Money and Currency
   - Informal currency expressions not covered
   - Foreign currency symbols outside predefined set are missed
   - Financial notation variations may not be recognized
   - Compound financial expressions may be partially processed

5. Addresses
   - International address formats not fully supported
   - Post office boxes and non-standard addresses may be missed
   - Addresses split across multiple lines may not be detected
   - Building names without standard indicators are not recognized

6. Numbers and Percentages
   - Scientific notation not supported
   - Spelled-out numbers are not detected
   - Numbers within complex expressions may be overlooked
   - Unit conversions and measurements are not standardized

## Project Objectives
This prototype was developed to:

- Demonstrate technical feasibility of automated legal document pseudonymization
- Identify implementation challenges and edge cases
- Evaluate entity extraction accuracy across different document formats
- Assess computational requirements and performance constraints
- Document limitations for future development consideration


## Future Considerations
Potential enhancements identified during development:

- Additional legal role pattern support
- Batch document processing capability
- Pseudonymize directly on PDF to maintain PDF formatting
- Support for legal citations and case numbers (i.e Maintain the numbers in specific edge cases)

## License
Developed by: Ryan Heng
Date: 7th October 2025
Version: 1.0
For internal evaluation purposes only.
