"""
Legal Document Pseudonymization Tool
====================================

This tool pseudonymizes sensitive entities in legal documents while preserving
document structure and relationships (e.g., date intervals).

For new developers:
1. Each entity type has its own Extractor and Pseudonymizer class
2. To add new entity types: inherit from the abstract base classes
3. The PseudonymizationPipeline orchestrates everything
4. All configuration is in PseudonymConfig

Architecture:
- EntityExtractor (ABC) -> DateExtractor, OrganizationExtractor, etc.
- EntityPseudonymizer (ABC) -> DatePseudonymizer, OrganizationPseudonymizer, etc.
- PseudonymizationPipeline -> coordinates all extractors and pseudonymizers
"""

import spacy
import random
import datetime
import re
import logging
import hashlib
from typing import List
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod

# ============================================================================
# SHARED UTILITIES
# ============================================================================

class NumberRandomizer:
    """Shared logic for randomizing numerical values"""
    @staticmethod
    def randomize_number(value: float, preserve_small: bool = True) -> float:
        if preserve_small and 0 < value <= 10:
            # Replace small numbers with different small numbers
            return random.choice([x for x in range(1, 11) if x != int(value)])
        else:
            # Apply ±15% variation
            multiplier = random.uniform(0.85, 1.15)
            return value * multiplier


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entity:
    """Represents an extracted entity from text"""
    start: int
    end: int
    label: str
    text: str
    confidence: Optional[float] = None


@dataclass
class PseudonymConfig:
    """Configuration for pseudonymization settings
    
    Modify these settings to customize behavior for your use case.
    """
    # spaCy model to use (with fallbacks)
    model_name: str = "en_core_web_trf"
    
    # Date range for generating realistic shifted dates
    date_range_start: datetime.date = datetime.date(2000, 1, 1)
    date_range_end: datetime.date = datetime.date(2025, 12, 31)
    
    # Enable/disable specific entity types
    enable_date_extraction: bool = True
    enable_organization_extraction: bool = True
    enable_money_extraction: bool = True
    enable_number_extraction: bool = True          
    enable_address_extraction: bool = True
    enable_legal_person_extraction: bool = True
    enable_spacy_extraction: bool = True  # Person, GPE, FAC via spaCy
    
    def __post_init__(self):
        # Entity types that will be pseudonymized
        self.target_labels = {"PERSON", "ORG", "GPE", "MONEY", "NUMBER", "ADDRESS", "DATE", "FAC", "LEGAL_PERSON"}


# ============================================================================
# ABSTRACT BASE CLASSES (Interface Contracts)
# ============================================================================

class EntityExtractor(ABC):
    """Base class for all entity extractors
    
    To create a new extractor:
    1. Inherit from this class
    2. Implement extract() method - return List[Entity]
    3. Implement entity_types property - return List[str] of labels you handle
    4. Add your extractor to PseudonymizationPipeline.__init__()
    
    Example:
        class EmailExtractor(EntityExtractor):
            @property
            def entity_types(self) -> List[str]:
                return ["EMAIL"]
            
            def extract(self, text: str) -> List[Entity]:
                # Your extraction logic here
                return entities
    """
    
    @abstractmethod
    def extract(self, text: str) -> List[Entity]:
        """Extract entities of this type from text
        
        Args:
            text: Input text to analyze
            
        Returns:
            List of Entity objects, sorted by start position
        """
        pass
    
    @property
    @abstractmethod
    def entity_types(self) -> List[str]:
        """Return list of entity type labels this extractor handles"""
        pass
    
    def _overlaps_existing(self, start: int, end: int, entities: List[Entity]) -> bool:
        """Helper: Check if span overlaps with existing entities"""
        return any(start < e.end and end > e.start for e in entities)


class EntityPseudonymizer(ABC):
    """Base class for all entity pseudonymizers
    
    To create a new pseudonymizer:
    1. Inherit from this class
    2. Implement pseudonymize() method
    3. Optionally implement prepare() for document-wide preprocessing
    4. Add your pseudonymizer to PseudonymizationPipeline.__init__()
    
    The base class handles caching so the same entity always gets
    the same replacement within a document.
    """
    
    def __init__(self):
        self.replacement_cache: Dict[str, str] = {}
    
    @abstractmethod
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate pseudonymized version of entity
        
        Args:
            original_text: The original entity text
            entity_label: The entity type (DATE, ORG, etc.)
            
        Returns:
            Pseudonymized replacement text
        """
        pass
    
    def prepare(self, all_entities: List[Entity]) -> None:
        """Optional: Prepare pseudonymizer with all entities from document
        
        Use this for cases where you need to see all entities first,
        e.g., to preserve relationships between dates.
        """
        pass
    
    def get_replacement(self, original_text: str, entity_label: str) -> str:
        """Get cached replacement or create new one"""
        if original_text not in self.replacement_cache:
            self.replacement_cache[original_text] = self.pseudonymize(original_text, entity_label)
        return self.replacement_cache[original_text]


# ============================================================================
# DATE HANDLING (Most Complex - Preserves Intervals)
# ============================================================================

class DateExtractor(EntityExtractor):
    """Extracts dates with context awareness
    
    Handles patterns like:
    - "no later than 30 September 2020"
    - "14 February 2019" 
    - "Feb 14, 2019"
    """
    
    def __init__(self):
        self.date_patterns = {
            # Context-aware patterns (e.g., "no later than X")
            'no_later_than': re.compile(
                r"\bno\s+later\s+than\s+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b", 
                re.IGNORECASE
            ),
            
            # Standard date formats
            'day_month_year': re.compile(
                r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b",
                re.IGNORECASE
            ),
            'month_day_year': re.compile(
                r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
                re.IGNORECASE
            ),
            'abbreviated_months': re.compile(
                r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\b",
                re.IGNORECASE
            )
        }
    
    @property
    def entity_types(self) -> List[str]:
        return ["DATE"]
    
    def extract(self, text: str) -> List[Entity]:
        """Extract all date entities from text"""
        entities = []
        
        for pattern_name, pattern in self.date_patterns.items():
            for match in pattern.finditer(text):
                # Extract just the date part (group 1)
                date_text = match.group(1).strip()
                start_pos = match.start(1)
                end_pos = match.end(1)
                
                # Avoid overlaps with existing date entities
                if not self._overlaps_existing(start_pos, end_pos, entities):
                    entities.append(Entity(
                        start=start_pos,
                        end=end_pos,
                        label="DATE",
                        text=date_text
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class DatePseudonymizer(EntityPseudonymizer):
    """Pseudonymizes dates while preserving relative intervals
    
    Key feature: If original document has dates 3 months apart,
    the pseudonymized dates will also be 3 months apart.
    """
    
    def __init__(self):
        super().__init__()
        self.date_mapping: Dict[datetime.date, datetime.date] = {}
        
        # Supported date formats for parsing
        self.date_formats = [
            '%d %B %Y',      # "14 February 2019"
            '%B %d %Y',      # "February 14 2019" 
            '%B %d, %Y',     # "February 14, 2019"
            '%d %b %Y',      # "14 Feb 2019"
            '%b %d %Y',      # "Feb 14 2019"
            '%b %d, %Y',     # "Feb 14, 2019"
            '%Y-%m-%d',      # "2019-02-14"
            '%d/%m/%Y',      # "14/02/2019"
            '%m/%d/%Y',      # "02/14/2019"
            '%d-%m-%Y',      # "14-02-2019"
            '%m-%d-%Y'       # "02-14-2019"
        ]
    
    def prepare(self, all_entities: List[Entity]) -> None:
        """Build date mapping that preserves intervals between dates"""
        # Get all date entities
        date_entities = [e for e in all_entities if e.label == "DATE"]
        if not date_entities:
            self.date_mapping = {}
            return
        
        # Parse all dates
        parsed_dates = []
        for entity in date_entities:
            parsed_date = self._parse_date(entity.text)
            if parsed_date:
                parsed_dates.append(parsed_date)
        
        if not parsed_dates:
            self.date_mapping = {}
            return
        
        # Remove duplicates and sort
        unique_dates = sorted(list(set(parsed_dates)))
        
        if len(unique_dates) == 1:
            # Single date - just shift randomly
            self._create_single_date_mapping(unique_dates[0])
        else:
            # Multiple dates - preserve intervals
            self._create_interval_preserving_mapping(unique_dates)
    
    def _create_single_date_mapping(self, original_date: datetime.date) -> None:
        """Create mapping for single date"""
        # Shift by random amount (±20 years)
        random_days = random.randint(-7300, 7300)
        base_date = datetime.date(2010, 1, 1)
        new_date = base_date + datetime.timedelta(days=random_days)
        self.date_mapping = {original_date: new_date}
    
    def _create_interval_preserving_mapping(self, unique_dates: List[datetime.date]) -> None:
        """Create mapping that preserves intervals between dates"""
        earliest_date = unique_dates[0]
        
        # Generate random start date
        random_days = random.randint(-7300, 7300)
        base_date = datetime.date(2010, 1, 1)
        new_start_date = base_date + datetime.timedelta(days=random_days)
        
        # Map each date preserving its offset from the earliest
        self.date_mapping = {}
        for original_date in unique_dates:
            days_from_start = (original_date - earliest_date).days
            new_date = new_start_date + datetime.timedelta(days=days_from_start)
            self.date_mapping[original_date] = new_date
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Convert date to pseudonymized version"""
        parsed_date = self._parse_date(original_text.strip())
        
        if parsed_date and parsed_date in self.date_mapping:
            shifted_date = self.date_mapping[parsed_date]
            return self._format_date_like_original(shifted_date, original_text)
        else:
            return f"[UNPARSEABLE DATE: {original_text}]"
    
    def _parse_date(self, date_str: str) -> Optional[datetime.date]:
        """Parse date string into datetime.date object"""
        for date_format in self.date_formats:
            try:
                return datetime.datetime.strptime(date_str, date_format).date()
            except ValueError:
                continue
        return None
    
    def _format_date_like_original(self, date_obj: datetime.date, original_str: str) -> str:
        """Format date to match style of original"""
        # Detect original format and match it
        if any(month in original_str for month in ['January', 'February', 'March', 'April', 'May', 'June', 
                                                   'July', 'August', 'September', 'October', 'November', 'December']):
            return date_obj.strftime('%d %B %Y')
        elif any(month in original_str for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
            return date_obj.strftime('%d %b %Y')
        elif '-' in original_str:
            if original_str.startswith('20') or original_str.startswith('19'):
                return date_obj.strftime('%Y-%m-%d')
            else:
                return date_obj.strftime('%d-%m-%Y')
        elif '/' in original_str:
            return date_obj.strftime('%d/%m/%Y')
        else:
            return date_obj.strftime('%d %B %Y')


# ============================================================================
# ORGANIZATION HANDLING
# ============================================================================

class OrganizationExtractor(EntityExtractor):
    """Extracts organization names using comprehensive regex patterns
    
    Captures companies with various corporate suffixes including:
    - Pte Ltd, Ltd, Limited
    - LLP, LLC, PLLC
    - Inc, Corp, Corporation
    - Co, Holdings, Group
    - And other common business entity types
    
    Examples:
    - "DBS Bank Ltd, Raffles Place Branch, Singapore"
    - "Beta Energy Pte Ltd"
    - "Microsoft Corporation"
    - "Goldman Sachs LLP"
    - "Apple Inc"
    - "Alpha Inc.," (with trailing punctuation)
    """
    
    def __init__(self):
        # Comprehensive list of corporate suffixes
        self.corporate_suffixes = [
            "Pte Ltd", "Pvt Ltd", "Private Limited", "Ltd", "Limited",
            "LLP", "LLC", "PLLC", "LP", "L.P.", "L.L.C.", "L.L.P.",
            "Inc","Incorporated", "Corp", "Corporation", 
            "Co", "Company", "Holdings", "Group", "PLC", "plc",
            "AG", "GmbH", "S.A.", "SAS", "SARL", "B.V.", "N.V.",
            "Pty Ltd", "Pty Limited"
        ]
        
        # Create regex pattern for all suffixes (case insensitive)
        # Handle short suffixes (AG, Co) specially to avoid partial word matches
        long_suffixes = [s for s in self.corporate_suffixes if len(s) > 2]
        short_suffixes = [s for s in self.corporate_suffixes if len(s) <= 2]
        
        # For long suffixes, use word boundaries
        long_suffix_pattern = "|".join([re.escape(suffix) for suffix in long_suffixes])
        
        # For short suffixes, ensure they're standalone words (not part of other words)
        short_suffix_pattern = "|".join([rf"\b{re.escape(suffix)}\b" for suffix in short_suffixes])
        
        # Combine both patterns
        if long_suffixes and short_suffixes:
            suffix_pattern = f"(?:{long_suffix_pattern}|{short_suffix_pattern})"
        elif long_suffixes:
            suffix_pattern = long_suffix_pattern
        else:
            suffix_pattern = short_suffix_pattern
        
        self.company_patterns = [
    # Banks with specific branch info 
    re.compile(rf"\b[A-Z]{{2,4}}\s+Bank\s+(?:{suffix_pattern})(?:,\s*[A-Z][a-z\s]+Branch)?(?:,\s*Singapore)?[.,;:]*\b", re.IGNORECASE),
    
    # General banks 
    re.compile(rf"(?<!to\s)(?<!by\s)\b[A-Z][A-Za-z\s]{{1,30}}(?:Bank|Banking)\s+(?:{suffix_pattern})[.,;:]*\b", re.IGNORECASE),
    
    # Simple company pattern: exactly 2-3 capitalized words + suffix
    re.compile(rf"\b[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+\s+(?:{suffix_pattern})[.,;:]*\b", re.IGNORECASE),
    
    # Single word + suffix
    re.compile(rf"\b[A-Z][A-Za-z]+\s+(?:{suffix_pattern})[.,;:]*\b", re.IGNORECASE),
    
    # Three word + suffix  
    re.compile(rf"\b[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+\s+(?:{suffix_pattern})[.,;:]*\b", re.IGNORECASE)
]
        
        # Words that often appear in false positives
        self.exclusion_words = {
            "payable", "transfer", "wire", "to", "by", "from", 
            "agreed", "sell", "having", "incorporated", "and", "with", "signed",
            "the", "this", "that", "said", "such", "other", "any", "all"
        }

    @property
    def entity_types(self) -> List[str]:
        return ["ORG"]

    def extract(self, text: str) -> List[Entity]:
        """Extract organization entities with comprehensive corporate suffix matching"""
        entities = []
        
        for pattern in self.company_patterns:
            for match in pattern.finditer(text):
                company_name = match.group(0).strip()
                
                # ADD DEBUG FOR Alpha Capital Inc.
                if "Alpha Capital" in company_name:
                    print(f"DEBUG: Found potential match: '{company_name}' at {match.start()}-{match.end()}")
                    print(f"  Length check: {len(company_name)} > 5 = {len(company_name) > 5}")
                    print(f"  Exclusion check: {self._contains_exclusion_words(company_name)}")
                    print(f"  Overlap check: {self._overlaps_existing(match.start(), match.end(), entities)}")
                    print(f"  Valid name check: {self._is_valid_company_name(company_name)}")
                
                # Quality filters
                if (len(company_name) > 5
                    and not self._contains_exclusion_words(company_name)
                    and not self._overlaps_existing(match.start(), match.end(), entities)
                    and self._is_valid_company_name(company_name)):
                    
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="ORG",
                        text=company_name
                    ))
        
        return sorted(entities, key=lambda x: x.start)

    def _contains_exclusion_words(self, text: str) -> bool:
        """Check if text contains words that indicate false positive"""
        text_lower = text.lower()
        words = text_lower.split()
        
        # Check if any word (except the suffix) is in exclusion list
        for word in words[:-2]:  # Exclude last 2 words which are likely the suffix
            if word in self.exclusion_words:
                return True
        return False
    
    def _is_valid_company_name(self, text: str) -> bool:
        """Additional validation for company names"""
        # Must have at least one alphabetic character before the suffix
        words = text.split()
        if len(words) < 2:
            return False
        
        # Check if the part before suffix has valid company name structure
        name_part = " ".join(words[:-1]) if len(words) > 1 else words[0]
        
        # Must have substantial alphabetic content
        if not re.search(r'[A-Za-z]{2,}', name_part):
            return False
            
        # Reject if it starts with articles or common legal words
        first_word = words[0].lower()
        if first_word in ["a", "an", "the", "such", "said", "other"]:
            return False
        
        return True


class OrganizationPseudonymizer(EntityPseudonymizer):
    """Replace organizations while preserving their corporate suffix
    
    Examples:
    - "Apple Inc" → "ORG A Inc"
    - "Beta Energy Pte Ltd" → "ORG B Pte Ltd"
    - "Goldman Sachs LLP" → "ORG C LLP"
    - "Alpha Inc.," → "ORG D Inc"
    """
    
    def __init__(self):
        super().__init__()
        self.counter = 0
        
        # Same corporate suffixes as extractor for consistency
        self.corporate_suffixes = [
            "Pte Ltd", "Pvt Ltd", "Private Limited", "Ltd", "Limited",
            "LLP", "LLC", "PLLC", "LP", "L.P.", "L.L.C.", "L.L.P.",
            "Inc", "Incorporated", "Corp", "Corporation", 
            "Co", "Company", "Holdings", "Group", "PLC", "plc",
            "AG", "GmbH", "S.A.", "SAS", "SARL", "B.V.", "N.V.",
            "Pty Ltd", "Pty Limited"
        ]

    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate ORG A/B/C etc while preserving corporate suffix"""
        self.counter += 1
        letter = chr(ord("A") + (self.counter - 1) % 26)
        
        # Find and preserve the corporate suffix
        suffix = self._extract_corporate_suffix(original_text)
        
        if suffix:
            return f"ORG {letter} {suffix}"
        else:
            # Fallback if no recognized suffix found
            return f"ORG {letter}"
    
    def _extract_corporate_suffix(self, text: str) -> str:
        """Extract the corporate suffix from the company name, handling trailing punctuation"""
        text = text.strip()
        
        # Remove trailing punctuation first
        cleaned_text = re.sub(r'[.,;:]+\s*$', '', text)
        
        # Try to match suffixes in order of length (longest first) to avoid partial matches
        sorted_suffixes = sorted(self.corporate_suffixes, key=len, reverse=True)
        
        for suffix in sorted_suffixes:
            # Case-insensitive matching but preserve original case
            if cleaned_text.lower().endswith(suffix.lower()):
                # Return the actual suffix as it appears in the cleaned text
                start_pos = len(cleaned_text) - len(suffix)
                return cleaned_text[start_pos:]
        
        return ""

# ============================================================================
# MONEY HANDLING (Multi-Currency)
# ============================================================================

class MoneyExtractor(EntityExtractor):
    """Extracts money amounts in multiple currencies"""
    
    def __init__(self):
        # Patterns for different currency formats
        self.money_patterns = [
            # Full format with written amounts (USD, EUR, GBP, etc.)
            re.compile(r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+[\d,]+(?:,\d{3})*(?:\.\d{2})?\s+\([^)]*(?:dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)[^)]*\)", re.IGNORECASE),
            
            # Simple currency + amount format
            re.compile(r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+[\d,]+(?:,\d{3})*(?:\.\d{2})?", re.IGNORECASE),
            
            # Amount with currency symbol
            re.compile(r"[\$€£¥₹₩₪₽¢]\s*[\d,]+(?:,\d{3})*(?:\.\d{2})?"),
            
            # Written currency amounts
            re.compile(r"[\d,]+(?:,\d{3})*(?:\.\d{2})?\s+(?:dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)", re.IGNORECASE)
        ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["MONEY"]
    
    def extract(self, text: str) -> List[Entity]:
        """Extract money entities in multiple currencies"""
        entities = []
        
        for pattern in self.money_patterns:
            for match in pattern.finditer(text):
                if not self._overlaps_existing(match.start(), match.end(), entities):
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="MONEY",
                        text=match.group(0)
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class MoneyPseudonymizer(EntityPseudonymizer):
    """Replace money amounts with randomized amounts across multiple currencies"""
    
    def __init__(self):
        super().__init__()
        
        # Currency symbol mappings
        self.currency_symbols = {
            'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CNY': '¥',
            'CAD': 'C$', 'AUD': 'A$', 'SGD': 'S$', 'HKD': 'HK$',
            'CHF': 'CHF', 'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr'
        }
        
        # Written currency names
        self.currency_words = {
            'USD': 'Dollars', 'EUR': 'Euros', 'GBP': 'Pounds', 'JPY': 'Yen', 
            'CNY': 'Yuan', 'CAD': 'Canadian Dollars', 'AUD': 'Australian Dollars',
            'SGD': 'Singapore Dollars', 'HKD': 'Hong Kong Dollars',
            'CHF': 'Swiss Francs', 'SEK': 'Swedish Krona', 'NOK': 'Norwegian Krone', 'DKK': 'Danish Krone'
        }

    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Replace with randomized money amount preserving currency and format"""
        
        # Try different parsing approaches
        result = self._handle_full_format(original_text)
        if result: return result
        
        result = self._handle_currency_code_format(original_text)
        if result: return result
        
        result = self._handle_symbol_format(original_text)
        if result: return result
        
        result = self._handle_written_format(original_text)
        if result: return result
        
        # Fallback
        return "[REDACTED AMOUNT]"
    
    def _handle_full_format(self, text: str) -> str:
        """Handle: USD 325,000,000 (Three Hundred... Dollars)"""
        pattern = r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+([\d,]+(?:\.\d{2})?)\s+\(([^)]*)\)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            currency = match.group(1).upper()
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            # Randomize amount
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            new_amount_int = int(round(new_amount))
            
            # Format with commas
            formatted_amount = f"{new_amount_int:,}"
            
            # Generate written form
            written_amount = self._number_to_written(new_amount_int)
            currency_word = self.currency_words.get(currency, "Units")
            
            return f"{currency} {formatted_amount} ({written_amount} {currency_word})"
        
        return None
    
    def _handle_currency_code_format(self, text: str) -> str:
        """Handle: USD 325,000,000"""
        pattern = r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+([\d,]+(?:\.\d{2})?)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            currency = match.group(1).upper()
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            # Preserve decimal places if original had them
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{currency} {formatted_amount}"
        
        return None
    
    def _handle_symbol_format(self, text: str) -> str:
        """Handle: $325,000 or €1,500.50"""
        pattern = r"([\$€£¥₹₩₪₽¢])\s*([\d,]+(?:\.\d{2})?)"
        match = re.search(pattern, text)
        
        if match:
            symbol = match.group(1)
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            # Preserve decimal places if original had them
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{symbol}{formatted_amount}"
        
        return None
    
    def _handle_written_format(self, text: str) -> str:
        """Handle: 325,000 dollars"""
        pattern = r"([\d,]+(?:\.\d{2})?)\s+(dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).replace(',', '')
            currency_word = match.group(2).lower()
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            # Preserve decimal places if original had them
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{formatted_amount} {currency_word}"
        
        return None
    
    def _number_to_written(self, amount: int) -> str:
        """Convert number to written form like 'Three Hundred Twenty-Five Million'"""
        if amount == 0:
            return "Zero"
        
        if amount >= 1_000_000_000:
            billions = amount // 1_000_000_000
            remainder = amount % 1_000_000_000
            result = f"{self._convert_hundreds(billions)} Billion"
            if remainder >= 1_000_000:
                millions = remainder // 1_000_000
                result += f" {self._convert_hundreds(millions)} Million"
            return result
        elif amount >= 1_000_000:
            millions = amount // 1_000_000
            remainder = amount % 1_000_000
            result = f"{self._convert_hundreds(millions)} Million"
            if remainder >= 1_000:
                thousands = remainder // 1_000
                result += f" {self._convert_hundreds(thousands)} Thousand"
            return result
        elif amount >= 1_000:
            thousands = amount // 1_000
            remainder = amount % 1_000
            result = f"{self._convert_hundreds(thousands)} Thousand"
            if remainder > 0:
                result += f" {self._convert_hundreds(remainder)}"
            return result
        else:
            return self._convert_hundreds(amount)
    
    def _convert_hundreds(self, num: int) -> str:
        """Convert numbers up to 999 to written form"""
        if num == 0:
            return ""
        
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        if num < 20:
            return ones[num]
        elif num < 100:
            return tens[num // 10] + ("-" + ones[num % 10] if num % 10 != 0 else "")
        else:
            result = ones[num // 100] + " Hundred"
            remainder = num % 100
            if remainder > 0:
                result += " " + self._convert_hundreds(remainder)
            return result
        

# ============================================================================
# NUMBER HANDLING (Percentages, Ages, Quantities, etc.)
# ============================================================================

class NumberExtractor(EntityExtractor):
    """Extracts standalone numbers, percentages, and quantities"""
    
    def __init__(self):
        self.number_patterns = [
            # Percentages: 45%, 12.5%, 0.75%
            re.compile(r"\b\d+(?:\.\d+)?%", re.IGNORECASE),
            
            # Large numbers with commas (but exclude years): 1,500 but not 2019
            re.compile(r"\b\d{1,3}(?:,\d{3})+(?!\s*(?:AD|BC|CE|BCE))\b"),
            
            # Decimal numbers: 3.5, 12.75 (but avoid dates like 14.02.2019)
            re.compile(r"(?<!\d\.)\b\d+\.\d+(?![\.\d])\b"),
            
            # Numbers with units (excluding time periods to preserve date intervals): "25 people", "100 shares"
            re.compile(r"\b\d+(?:\.\d+)?\s+(?:people|persons?|shares?|units?|times?|fold|percent|percentage|items?|pieces?|copies?)\b", re.IGNORECASE),
            
            # Standalone integers (but exclude years, case numbers, addresses)
            re.compile(r"(?<![\d\-\.])\b(?!(?:19|20)\d{2}\b)(?!\d{1,4}\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard|St|Rd|Ave|Dr|Ln|Blvd))\d{2,6}(?![\d\-\.])\b"),
            
            # Ratios: 3:1, 2:3, 1:4
            re.compile(r"\b\d+:\d+\b"),
            
            # Fractions: 1/4, 3/8, 2/3
            re.compile(r"\b\d+/\d+\b")
        ]
        
        # Exclusion patterns to avoid false positives
        self.exclusion_patterns = [
            # Years: 2019, 2020, 1995-2020
            re.compile(r"\b(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\b"),
            
            # Dates: 14.02.2019, 12/25/2020
            re.compile(r"\b\d{1,2}[\.\/\-]\d{1,2}[\.\/\-](?:\d{2}|\d{4})\b"),
            
            # Phone numbers: +65 1234 5678
            re.compile(r"[\+\(]?\d{1,4}[\)\s\-]?\d{3,4}[\s\-]?\d{3,4}"),
            
            # Postal codes: 079903, SW1A 1AA
            re.compile(r"\b\d{5,6}\b|\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b"),
            
            # Case/reference numbers: Case No. 12345
            re.compile(r"(?:case|ref|no|number)[\.\s]*\d+", re.IGNORECASE)
        ]

    @property
    def entity_types(self) -> List[str]:
        return ["NUMBER"]

    def extract(self, text: str) -> List[Entity]:
        """Extract number entities while avoiding dates, addresses, etc."""
        entities = []
        
        for pattern in self.number_patterns:
            for match in pattern.finditer(text):
                number_text = match.group(0).strip()
                start_pos = match.start()
                end_pos = match.end()
                
                # Check if this match should be excluded
                if (not self._should_exclude(text, start_pos, end_pos)
                    and not self._overlaps_existing(start_pos, end_pos, entities)
                    and self._is_valid_number(number_text)):
                    
                    entities.append(Entity(
                        start=start_pos,
                        end=end_pos,
                        label="NUMBER",
                        text=number_text
                    ))
        
        return sorted(entities, key=lambda x: x.start)

    def _should_exclude(self, text: str, start: int, end: int) -> bool:
        """Check if the number should be excluded based on context"""
        # Get surrounding context
        context_start = max(0, start - 20)
        context_end = min(len(text), end + 20)
        context = text[context_start:context_end]
        
        # Check exclusion patterns in the context
        for pattern in self.exclusion_patterns:
            if pattern.search(context):
                return True
        
        return False

    def _is_valid_number(self, text: str) -> bool:
        """Additional validation for numbers"""
        # Skip time periods that should be handled by date logic
        if re.search(r'\b(?:years?|months?|weeks?|days?|hours?|minutes?|seconds?)\b', text, re.IGNORECASE):
            return False
        
        # Must contain at least one digit
        if not re.search(r'\d', text):
            return False
        
        # Skip very large numbers that are likely IDs or codes
        number_match = re.search(r'\d+', text)
        if number_match:
            number_value = int(number_match.group(0))
            if number_value > 1_000_000:  # Numbers over 1M are likely IDs/codes
                return False
        
        return True


class NumberPseudonymizer(EntityPseudonymizer):
    """Randomize numbers while preserving format and context"""
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate randomized number preserving format"""
        text = original_text.strip()
        
        # Handle percentages
        if text.endswith('%'):
            return self._handle_percentage(text)
        
        # Handle ratios (3:1)
        if ':' in text:
            return self._handle_ratio(text)
        
        # Handle fractions (1/4)
        if '/' in text:
            return self._handle_fraction(text)
        
        # Handle numbers with units (3.5 years)
        unit_match = re.search(r'(\d+(?:\.\d+)?)\s+(\w+)', text)
        if unit_match:
            return self._handle_number_with_unit(unit_match.group(1), unit_match.group(2))
        
        # Handle comma-separated numbers (1,500)
        if ',' in text:
            return self._handle_comma_number(text)
        
        # Handle decimal numbers (12.75)
        if '.' in text:
            return self._handle_decimal(text)
        
        # Handle plain integers
        return self._handle_integer(text)

    def _handle_percentage(self, text: str) -> str:
        """Handle percentages like 45% or 12.5%"""
        number_str = text[:-1]  # Remove %
        try:
            original_value = float(number_str)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            # Keep same decimal precision as original
            if '.' in number_str:
                decimal_places = len(number_str.split('.')[1])
                return f"{new_value:.{decimal_places}f}%"
            else:
                return f"{int(round(new_value))}%"
        except ValueError:
            return text

    def _handle_ratio(self, text: str) -> str:
        """Handle ratios like 3:1"""
        parts = text.split(':')
        if len(parts) == 2:
            try:
                left = float(parts[0])
                right = float(parts[1])
                new_left = NumberRandomizer.randomize_number(left, preserve_small=True)
                new_right = NumberRandomizer.randomize_number(right, preserve_small=True)
                return f"{int(round(new_left))}:{int(round(new_right))}"
            except ValueError:
                pass
        return text

    def _handle_fraction(self, text: str) -> str:
        """Handle fractions like 1/4"""
        parts = text.split('/')
        if len(parts) == 2:
            try:
                numerator = float(parts[0])
                denominator = float(parts[1])
                new_num = NumberRandomizer.randomize_number(numerator, preserve_small=True)
                new_den = NumberRandomizer.randomize_number(denominator, preserve_small=True)
                return f"{int(round(new_num))}/{int(round(new_den))}"
            except ValueError:
                pass
        return text

    def _handle_number_with_unit(self, number_str: str, unit: str) -> str:
        """Handle numbers with units like '3.5 years'"""
        try:
            original_value = float(number_str)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            # Preserve decimal places for certain units
            if unit.lower() in ['years', 'months', 'weeks', 'hours']:
                return f"{new_value:.1f} {unit}"
            else:
                return f"{int(round(new_value))} {unit}"
        except ValueError:
            return f"{number_str} {unit}"

    def _handle_comma_number(self, text: str) -> str:
        """Handle comma-separated numbers like 1,500"""
        try:
            number_value = float(text.replace(',', ''))
            new_value = NumberRandomizer.randomize_number(number_value, preserve_small=False)
            return f"{int(round(new_value)):,}"
        except ValueError:
            return text

    def _handle_decimal(self, text: str) -> str:
        """Handle decimal numbers like 12.75"""
        try:
            original_value = float(text)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            # Preserve decimal places
            decimal_places = len(text.split('.')[1])
            return f"{new_value:.{decimal_places}f}"
        except ValueError:
            return text

    def _handle_integer(self, text: str) -> str:
        """Handle plain integers"""
        try:
            original_value = int(text)
            new_value = NumberRandomizer.randomize_number(float(original_value), preserve_small=True)
            return str(int(round(new_value)))
        except ValueError:
            return text

# ============================================================================
# ADDRESS HANDLING WITH HASH-BASED PSEUDONYMIZATION
# ============================================================================

class AddressExtractor(EntityExtractor):
    """Extracts address patterns including Singapore-specific formats"""
    
    def __init__(self):
        self.address_patterns = [
            # Singapore addresses with postal codes
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard|Quay),\s*Singapore\s+\d{6}\b"),
            
            # Singapore building names (One Raffles Quay, Marina Bay, etc.)
            re.compile(r"\b(?:One|Two|Three|Four|Five|\d+)\s+[A-Z][a-z]*\s+(?:Quay|Plaza|Square|Tower|Building|Centre|Center)(?:,\s*Level\s*\d+)?(?:,\s*\d+\s+[A-Z][a-z]*\s+(?:Street|Road|Quay))?(?:,\s*Singapore\s+\d{6})?\b"),
            
            # US/International addresses  
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard),\s*[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}\b"),
            
            # Partial addresses (street names with numbers)
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Lane|Ln|Boulevard|Blvd|Walk|Close|Crescent|Place|Park|Gardens|Heights|View|Terrace|Rise|Hill|Grove|Way|Circuit|Centre|Center|Quay)\b"),
            
            # Building names with written numbers
            re.compile(r"\b(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)\s+[A-Z][a-z]*\s+(?:Street|Road|Avenue|Quay|Boulevard|Plaza|Square|Tower|Building|Centre|Center)\b")
        ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["ADDRESS"]
    
    def extract(self, text: str) -> List[Entity]:
        """Extract address entities"""
        entities = []
        
        for pattern in self.address_patterns:
            for match in pattern.finditer(text):
                if not self._overlaps_existing(match.start(), match.end(), entities):
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="ADDRESS",
                        text=match.group(0)
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class AddressPseudonymizer(EntityPseudonymizer):
    """Replace addresses with consistent 6-digit hash-based codes"""
    
    def __init__(self, salt: str = "legal_doc_addresses_2024"):
        super().__init__()
        self.salt = salt  # Salt for consistent but unpredictable hashing
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate consistent 6-digit address code using hash"""
        # Normalize the address for consistent hashing
        normalized_address = self._normalize_address(original_text)
        
        # Create hash with salt
        hash_input = f"{self.salt}:{normalized_address}".encode('utf-8')
        hash_object = hashlib.sha256(hash_input)
        hash_hex = hash_object.hexdigest()
        
        # Convert first 6 hex characters to 6-digit number
        # This ensures consistent mapping: same address always gets same code
        hex_substring = hash_hex[:6]
        address_code = str(int(hex_substring, 16) % 1000000).zfill(6)
        
        return f"[ADDRESS {address_code}]"
    
    def _normalize_address(self, address: str) -> str:
        """Normalize address for consistent hashing"""
        # Convert to lowercase and remove extra whitespace
        normalized = re.sub(r'\s+', ' ', address.lower().strip())
        
        # Normalize common variations for consistency
        replacements = {
            ' st ': ' street ',
            ' rd ': ' road ',
            ' ave ': ' avenue ',
            ' dr ': ' drive ',
            ' ln ': ' lane ',
            ' blvd ': ' boulevard ',
            'centre': 'center',  # Normalize British vs American spelling
            ',': '',  # Remove commas for consistency
            '.': ''   # Remove periods
        }
        
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        
        return normalized.strip()


# Alternative implementation with configurable format
class FlexibleAddressPseudonymizer(EntityPseudonymizer):
    """More flexible address pseudonymizer with different output formats"""
    
    def __init__(self, salt: str = "legal_doc_addresses_2024", format_type: str = "code"):
        super().__init__()
        self.salt = salt
        self.format_type = format_type  # "code", "letter", "building"
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate address pseudonym in specified format"""
        normalized_address = self._normalize_address(original_text)
        
        # Create consistent hash
        hash_input = f"{self.salt}:{normalized_address}".encode('utf-8')
        hash_object = hashlib.sha256(hash_input)
        hash_hex = hash_object.hexdigest()
        
        if self.format_type == "code":
            # 6-digit code: [ADDRESS 123456]
            hex_substring = hash_hex[:6]
            address_code = str(int(hex_substring, 16) % 1000000).zfill(6)
            return f"[ADDRESS {address_code}]"
        
        elif self.format_type == "letter":
            # Letter-based: [ADDRESS A], [ADDRESS B], etc.
            # Uses hash to determine letter consistently
            letter_index = int(hash_hex[:2], 16) % 26
            letter = chr(ord('A') + letter_index)
            return f"[ADDRESS {letter}]"
        
        elif self.format_type == "building":
            # Building-style: Building 123, Office Complex 456, etc.
            building_num = int(hash_hex[:4], 16) % 9999 + 1
            building_types = ["Building", "Office Complex", "Tower", "Plaza"]
            building_type = building_types[int(hash_hex[4:6], 16) % len(building_types)]
            return f"{building_type} {building_num}"
        
        else:
            return f"[ADDRESS {hash_hex[:6].upper()}]"
    
    def _normalize_address(self, address: str) -> str:
        """Normalize address for consistent hashing"""
        normalized = re.sub(r'\s+', ' ', address.lower().strip())
        
        replacements = {
            ' st ': ' street ', ' rd ': ' road ', ' ave ': ' avenue ',
            ' dr ': ' drive ', ' ln ': ' lane ', ' blvd ': ' boulevard ',
            'centre': 'center', ',': '', '.': ''
        }
        
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        
        return normalized.strip()


# Example usage and testing
if __name__ == "__main__":
    # Test consistency
    pseudonymizer = AddressPseudonymizer()
    
    test_addresses = [
        "10 Anson Road, Singapore 079903",
        "10 Anson Rd, Singapore 079903",  # Should get same code (normalized)
        "One Raffles Quay, Singapore 048583",
        "1200 Market Street, Wilmington, DE 19801",
        "Marina Bay Financial Centre, Tower 2"
    ]
    
    print("Testing address pseudonymization:")
    for address in test_addresses:
        result = pseudonymizer.get_replacement(address, "ADDRESS")
        print(f"'{address}' -> '{result}'")
    
    # Test that same address gives same result
    print(f"\nConsistency test:")
    addr1 = pseudonymizer.get_replacement("10 Anson Road, Singapore 079903", "ADDRESS")
    addr2 = pseudonymizer.get_replacement("10 Anson Road, Singapore 079903", "ADDRESS")
    print(f"Same address twice: {addr1} == {addr2} ? {addr1 == addr2}")
    
    # Test normalization consistency
    addr3 = pseudonymizer.get_replacement("10 Anson Rd, Singapore 079903", "ADDRESS")
    print(f"Normalized version: {addr3} == {addr1} ? {addr3 == addr1}")


# ============================================================================
# LEGAL ROLE-AWARE PERSON HANDLING (CLEANED VERSION)
# ============================================================================

@dataclass
class PersonEntity(Entity):
    """Extended entity class for persons with legal roles"""
    role: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None

class LegalPersonExtractor(EntityExtractor):
    """Extracts persons with explicit legal roles only - spaCy handles bare names"""
    
    def __init__(self):
        # Legal roles and titles commonly found in legal documents
        self.legal_roles = {
            # Litigation roles
            'plaintiff', 'defendant', 'complainant', 'respondent', 'petitioner', 
            'appellant', 'appellee', 'cross-defendant', 'third-party defendant',
            'intervenor', 'amicus', 'witness', 'expert witness',
            
            # Contract roles  
            'grantor', 'grantee', 'licensor', 'licensee', 'buyer', 'seller',
            'vendor', 'purchaser', 'contractor', 'subcontractor', 'guarantor',
            'borrower', 'lender', 'mortgagor', 'mortgagee', 'lessor', 'lessee',
            'trustee', 'beneficiary', 'settlor', 'executor', 'administrator',
            
            # Corporate roles
            'ceo', 'cfo', 'coo', 'president', 'chairman', 'director', 'officer',
            'manager', 'partner', 'shareholder', 'stockholder', 'member',
            'managing director', 'general counsel', 'secretary', 'treasurer',
            
            # Legal professionals
            'attorney', 'lawyer', 'counsel', 'advocate', 'barrister', 'solicitor',
            'judge', 'magistrate', 'arbitrator', 'mediator', 'paralegal',
            'legal assistant', 'court reporter', 'clerk',
            
            # Other legal roles
            'guardian', 'conservator', 'agent', 'representative', 'proxy',
            'assignor', 'assignee', 'successor', 'heir', 'beneficiary'
        }
        
        # Professional titles
        self.professional_titles = {
            'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'hon',
            'honorable', 'justice', 'chief justice', 'associate justice'
        }
        
        # Create sorted lists for better regex construction (longest first to avoid partial matches)
        sorted_roles = sorted(self.legal_roles, key=len, reverse=True)
        sorted_titles = sorted(self.professional_titles, key=len, reverse=True)
        
        # Escape special regex characters and create pattern strings
        roles_pattern = '|'.join(re.escape(role) for role in sorted_roles)
        titles_pattern = '|'.join(re.escape(title) for title in sorted_titles)
        
        # Role-based extraction patterns
        self.role_patterns = [
            # Pattern 1: Name (Role) - "Michael Tan (Partner)"
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
            
            # Pattern 2: Name, Role - "Michael Tan, Partner"  
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([a-zA-Z\s]+?)(?:,|\.|$)', re.IGNORECASE),
            
            # Pattern 3: Role Name - "Plaintiff John Smith" (using all legal roles)
            re.compile(r'\b(' + roles_pattern + r')\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?=\s+[a-z(]|\s*[.,(;:]|\s*$)', re.IGNORECASE),
            
            # Pattern 4: Name, the Role - "John Smith, the Defendant"
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+the\s+([a-zA-Z\s]+?)(?:,|\.|$)', re.IGNORECASE),
            
            # Pattern 5: Title Name - "Dr. Michael Tan", "Hon. Justice Smith"
            re.compile(r'\b(' + titles_pattern + r')\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', re.IGNORECASE),
            
            # Pattern 6: Name as Role - "Michael Tan as Managing Partner"
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+as\s+([a-zA-Z\s]+?)(?:,|\.|$|\s+of)', re.IGNORECASE),
            
            # Pattern 7: Complex corporate patterns - "Michael Tan (Partner, Rajah & Tann LLP)"
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(\s*([^,]+),\s*([^)]+)\s*\)', re.IGNORECASE)
            ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["LEGAL_PERSON"]
    
    def extract(self, text: str) -> List[Entity]:
        """Extract persons with explicit legal roles only"""
        entities = []
        
        print(f"DEBUG: Extracting from text: '{text}'")
        print(f"DEBUG: Legal roles include 'defendant': {'defendant' in self.legal_roles}")
        
        # Only extract names with explicit roles - let spaCy handle bare names
        for i, pattern in enumerate(self.role_patterns):
            print(f"DEBUG: Testing pattern {i+1}")
            for match in pattern.finditer(text):
                print(f"  Found match: '{match.group(0)}' with groups: {match.groups()}")
                person_entity = self._process_role_match(match)
                print(f"  Processed to: {person_entity}")
                
                if person_entity and self._is_valid_person_entity(person_entity):
                    print(f"  Valid entity: {person_entity.text} (role: {person_entity.role})")
                    if not self._overlaps_existing(person_entity.start, person_entity.end, entities):
                        entities.append(person_entity)
                        print(f"  Added to entities list")
                    else:
                        print(f"  Skipped due to overlap")
                else:
                    print(f"  Invalid or None entity")
        
        print(f"DEBUG: Final entities: {[(e.text, e.role if hasattr(e, 'role') else 'no role') for e in entities]}")
        return sorted(entities, key=lambda x: x.start)
    
    def _process_role_match(self, match: re.Match) -> Optional[PersonEntity]:
        """Process regex match to extract person and role information"""
        groups = match.groups()
        
        # Different patterns have different group structures
        if len(groups) == 2:
            name_candidate = groups[0].strip()
            role_candidate = groups[1].strip()
            
            print(f"    Checking: name='{name_candidate}', role='{role_candidate}'")
            print(f"    _looks_like_name('{name_candidate}'): {self._looks_like_name(name_candidate)}")
            print(f"    _looks_like_role('{role_candidate}'): {self._looks_like_role(role_candidate)}")
            
            # Determine if first group is name or role based on capitalization and content
            if self._looks_like_name(name_candidate) and self._looks_like_role(role_candidate):
                name, role = name_candidate, role_candidate
            elif self._looks_like_role(name_candidate) and self._looks_like_name(role_candidate):
                role, name = name_candidate, role_candidate
            else:
                return None
            
            return PersonEntity(
                start=match.start(),
                end=match.end(),
                label="LEGAL_PERSON",
                text=match.group(0),
                role=self._normalize_role(role)
            )
        
        elif len(groups) == 3:
            # Complex pattern: Name (Role, Organization)
            name = groups[0].strip()
            role = groups[1].strip()
            organization = groups[2].strip()
            
            return PersonEntity(
                start=match.start(),
                end=match.end(),
                label="LEGAL_PERSON", 
                text=match.group(0),
                role=self._normalize_role(role),
                organization=organization
            )
        
        return None
    
    def _looks_like_name(self, text: str) -> bool:
        """Check if text looks like a person's name"""
        words = text.split()
        if len(words) < 1 or len(words) > 4:
            return False
        
        # Names typically have proper capitalization
        return all(word[0].isupper() and word[1:].islower() for word in words if word.isalpha())
    
    def _looks_like_role(self, text: str) -> bool:
        """Check if text looks like a legal role or title"""
        text_lower = text.lower().strip()
        
        # Remove common prefixes/suffixes
        text_clean = re.sub(r'^(the\s+|a\s+|an\s+)', '', text_lower)
        text_clean = re.sub(r'\s+(thereof|therein)$', '', text_clean)
        
        result = (text_clean in self.legal_roles or 
                text_clean in self.professional_titles or
                any(role in text_clean for role in self.legal_roles))
        
        print(f"      _looks_like_role debug: '{text}' -> '{text_clean}' -> {result}")
        return result
    
    def _normalize_role(self, role: str) -> str:
        """Normalize role text for consistent pseudonymization"""
        role_lower = role.lower().strip()
        
        # Remove articles and common prefixes
        role_clean = re.sub(r'^(the\s+|a\s+|an\s+)', '', role_lower)
        
        # Map common variations to standard forms
        role_mappings = {
            'atty': 'attorney',
            'counsel': 'attorney', 
            'lawyer': 'attorney',
            'mgr': 'manager',
            'mgmt': 'management',
            'chmn': 'chairman',
            'chrmn': 'chairman',
            'pres': 'president',
            'v.p.': 'vice president',
            'vp': 'vice president'
        }
        
        return role_mappings.get(role_clean, role_clean)
    
    def _is_valid_person_entity(self, entity: PersonEntity) -> bool:
        """Validate that this is likely a real person entity"""
        # Basic validation
        if len(entity.text) < 3 or len(entity.text) > 100:
            return False
        
        # Skip if it looks like a company name or other entity
        company_indicators = ['inc', 'corp', 'ltd', 'llc', 'llp', 'company', 'co.']
        text_lower = entity.text.lower()
        
        if any(indicator in text_lower for indicator in company_indicators):
            return False
        
        return True
    
class LegalPersonPseudonymizer(EntityPseudonymizer):
    """Pseudonymize persons based on their legal roles with cross-reference tracking"""
    
    def __init__(self, use_hash_consistency: bool = True):
        super().__init__()
        self.use_hash_consistency = use_hash_consistency
        self.role_counters = {}
        self.hash_salt = "legal_persons_2024"
        self.name_to_role_registry = {}  # Track name -> role mapping
        self.processed_entities = []  # Track all processed entities for cross-reference
    
    def prepare(self, all_entities: List[Entity]) -> None:
        """Build name-to-role mappings from all entities in document"""
        legal_persons = [e for e in all_entities if e.label == "LEGAL_PERSON"]
        bare_persons = [e for e in all_entities if e.label == "PERSON"]
        
        self.name_to_role_registry = {}
        
        # First pass: Extract names with explicit roles
        for entity in legal_persons:
            if isinstance(entity, PersonEntity) and entity.role:
                # Extract the name from the entity text
                name = self._extract_name_from_entity_text(entity.text)
                if name:
                    self.name_to_role_registry[name.lower()] = entity.role
        
        # Second pass: Check if any bare persons match known roles
        for entity in bare_persons:
            matched_role = self._find_matching_role(entity.text)
            if matched_role:
                # This bare name should inherit the legal role
                # Pre-populate cache for cross-reference
                self.replacement_cache[entity.text] = self._generate_hash_based_pseudonym(entity.text, matched_role)
    
    def _extract_name_from_entity_text(self, entity_text: str) -> Optional[str]:
        """Extract just the name part from entity text with roles"""
        # Pattern: "Michael Tan (Partner)" -> "Michael Tan"
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text)
        if match:
            return match.group(1).strip()
        
        # Pattern: "Plaintiff Michael Tan" -> "Michael Tan" 
        role_name_match = re.search(r'\b(?:plaintiff|defendant|dr\.?|mr\.?|mrs\.?|ms\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text, re.IGNORECASE)
        if role_name_match:
            return role_name_match.group(1).strip()
        
        return None
    
    def _find_matching_role(self, bare_name: str) -> Optional[str]:
        """Find if this bare name matches any known name with a role"""
        bare_name_lower = bare_name.lower().strip()
        
        # Direct exact match
        if bare_name_lower in self.name_to_role_registry:
            return self.name_to_role_registry[bare_name_lower]
        
        # Partial matching for name variations
        for known_name, role in self.name_to_role_registry.items():
            # Check if bare name is contained in known name or vice versa
            if (self._names_likely_same_person(bare_name_lower, known_name) or
                self._names_likely_same_person(known_name, bare_name_lower)):
                return role
        
        return None
    
    def _names_likely_same_person(self, name1: str, name2: str) -> bool:
        """Determine if two names likely refer to the same person"""
        name1_parts = name1.split()
        name2_parts = name2.split()
        
        # Same exact name
        if name1 == name2:
            return True
        
        # First and last name match (ignore middle names/initials)
        if (len(name1_parts) >= 2 and len(name2_parts) >= 2 and
            name1_parts[0] == name2_parts[0] and  # First name match
            name1_parts[-1] == name2_parts[-1]):  # Last name match
            return True
        
        # One name is subset of another (Michael Tan vs Michael J. Tan)
        if (len(name1_parts) >= 2 and len(name2_parts) >= 2):
            # Check if all parts of shorter name appear in longer name
            shorter = name1_parts if len(name1_parts) <= len(name2_parts) else name2_parts
            longer = name2_parts if len(name1_parts) <= len(name2_parts) else name1_parts
            
            if all(part in longer for part in shorter):
                return True
        
        return False
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate role-based pseudonym for legal persons"""
        # Extract person details from the original entity
        person_info = self._parse_person_info(original_text)
        
        if person_info['role']:
            return self._generate_role_based_pseudonym(person_info)
        else:
            return self._generate_generic_pseudonym()
    
    def get_replacement(self, original_text: str, entity_label: str) -> str:
        """Override to handle PersonEntity objects with role inheritance"""
        if original_text not in self.replacement_cache:
            # Check if we have a PersonEntity with role information
            if hasattr(self, '_current_entity') and isinstance(self._current_entity, PersonEntity):
                replacement = self._generate_role_based_pseudonym_from_entity(self._current_entity)
            else:
                # Fallback: try to find role from name registry for bare names
                matched_role = self._find_matching_role(original_text.strip())
                if matched_role:
                    replacement = self._generate_role_based_pseudonym({'name': original_text, 'role': matched_role})
                else:
                    replacement = self.pseudonymize(original_text, entity_label)
            self.replacement_cache[original_text] = replacement
        return self.replacement_cache[original_text]
    
    def _parse_person_info(self, text: str) -> Dict[str, Optional[str]]:
        """Parse person information from text"""
        patterns = [
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(\s*([^)]+)\s*\)',
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([^,]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return {'name': match.group(1), 'role': match.group(2).strip()}
        
        return {'name': None, 'role': None}
    
    def _generate_role_based_pseudonym_from_entity(self, entity: PersonEntity) -> str:
        """Generate pseudonym from PersonEntity object"""
        role = entity.role if entity.role else "person"
        
        if self.use_hash_consistency:
            # Use the name part for consistent hashing, not the full entity text
            name_for_hash = self._extract_name_from_entity_text(entity.text) or entity.text
            return self._generate_hash_based_pseudonym(name_for_hash, role)
        else:
            return self._generate_counter_based_pseudonym(role)
    
    def _generate_role_based_pseudonym(self, person_info: Dict[str, Optional[str]]) -> str:
        """Generate role-based pseudonym from parsed info"""
        role = person_info.get('role', 'person') or 'person'
        
        if self.use_hash_consistency:
            name_for_hash = person_info.get('name', '') or 'unknown'
            return self._generate_hash_based_pseudonym(name_for_hash, role)
        else:
            return self._generate_counter_based_pseudonym(role)
    
    def _generate_hash_based_pseudonym(self, name: str, role: str) -> str:
        """Generate consistent hash-based pseudonym using the name"""
        # Normalize the role and name
        role_normalized = self._normalize_role_for_pseudonym(role)
        name_normalized = name.lower().strip()
        
        # Create hash for consistency - use name as primary key
        hash_input = f"{self.hash_salt}:{name_normalized}:{role_normalized}".encode('utf-8')
        hash_object = hashlib.sha256(hash_input)
        hash_hex = hash_object.hexdigest()
        
        # Use hash to determine letter/number
        letter_index = int(hash_hex[:2], 16) % 26
        letter = chr(ord('A') + letter_index)
        
        return f"{role_normalized} {letter}"
    
    def _generate_counter_based_pseudonym(self, role: str) -> str:
        """Generate counter-based pseudonym"""
        role_normalized = self._normalize_role_for_pseudonym(role)
        
        if role_normalized not in self.role_counters:
            self.role_counters[role_normalized] = 0
        
        self.role_counters[role_normalized] += 1
        letter = chr(ord('A') + (self.role_counters[role_normalized] - 1) % 26)
        
        return f"{role_normalized} {letter}"
    
    def _normalize_role_for_pseudonym(self, role: str) -> str:
        """Normalize role for pseudonym generation"""
        role_clean = role.lower().strip()
        
        # Map to standard pseudonym formats
        role_mappings = {
            'plaintiff': 'Plaintiff',
            'defendant': 'Defendant', 
            'attorney': 'Counsel',
            'lawyer': 'Counsel',
            'counsel': 'Counsel',
            'partner': 'Partner',
            'ceo': 'CEO',
            'president': 'President',
            'director': 'Director',
            'judge': 'Judge',
            'witness': 'Witness',
            'buyer': 'Buyer',
            'seller': 'Seller',
            'grantor': 'Grantor',
            'grantee': 'Grantee',
            'trustee': 'Trustee'
        }
        
        return role_mappings.get(role_clean, 'Person')
    
    def _generate_generic_pseudonym(self) -> str:
        """Generate generic person pseudonym when role is unknown"""
        return self._generate_counter_based_pseudonym('person')
# ============================================================================
# SPACY-BASED EXTRACTION (Person, GPE, FAC, ORG)
# ============================================================================

class SpacyExtractor(EntityExtractor):
    """Uses spaCy NER for general entity types"""
    
    def __init__(self, nlp_model, target_labels: set):
        self.nlp = nlp_model
        self.target_labels = target_labels
        self.exclusion_words = {
            "payable", "transfer", "wire", "agreed", "sell", "having", "incorporated"
        }
    
    @property
    def entity_types(self) -> List[str]:
        return list(self.target_labels)
    
    def extract(self, text: str) -> List[Entity]:
        """Extract entities using spaCy NER"""
        entities = []
        doc = self.nlp(text)
        
        for ent in doc.ents:
            if (ent.label_ in self.target_labels 
                and len(ent.text.strip()) >= 2 
                and not self._contains_exclusion_words(ent.text)
                and self._is_valid_entity(ent)):
                
                entities.append(Entity(
                    start=ent.start_char,
                    end=ent.end_char,
                    label=ent.label_,
                    text=ent.text
                ))
        
        return sorted(entities, key=lambda x: x.start)
    
    def _contains_exclusion_words(self, text: str) -> bool:
        """Check for exclusion words that indicate false positives"""
        text_lower = text.lower()
        return any(word in text_lower for word in self.exclusion_words)
    
    def _is_valid_entity(self, ent) -> bool:
        """Additional validation for spaCy entities"""
        # Skip PERSON entities that might have legal context - let LegalPersonExtractor handle them
        if ent.label_ == "PERSON":
            # Quick check for legal role indicators nearby
            context_window = 50
            start_context = max(0, ent.start_char - context_window)
            end_context = min(len(ent.doc.text), ent.end_char + context_window)
            context = ent.doc.text[start_context:end_context].lower()
            
            # If legal indicators found, skip and let LegalPersonExtractor handle it
            legal_indicators = ['(', 'plaintiff', 'defendant', 'counsel', 'attorney', 'partner', 'judge', 'witness', 'dr.', 'hon.']
            if any(indicator in context for indicator in legal_indicators):
                return False
        
        # Skip orgs that were already handled by regex patterns
        if ent.label_ == "ORG":
            text_lower = ent.text.lower()
            if any(word in text_lower for word in ['bank', 'branch']) and 'ltd' in text_lower:
                return False
        
        # Skip problematic DATE entities
        if ent.label_ == "DATE":
            # Skip contextual phrases
            if re.search(r"\b(?:no\s+later\s+than|before|after|during|within)\b", ent.text, re.IGNORECASE):
                return False
            # Must contain actual date components
            if not re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2})\b", ent.text, re.IGNORECASE):
                return False
        
        return True


# ============================================================================
# GENERIC COUNTER-BASED PSEUDONYMIZERS
# ============================================================================

class CounterBasedPseudonymizer(EntityPseudonymizer):
    """Generic pseudonymizer that uses counters (Person A, Location A, etc.)"""
    
    def __init__(self, prefix: str, use_hash: bool = True):
        super().__init__()
        self.prefix = prefix
        self.counter = 0
        self.use_hash = use_hash
        self.salt = f"{prefix.lower()}_pseudonyms_2024"
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate prefixed counter (e.g., Person A, Person B)"""
        if self.use_hash:
            # Hash-based for consistency across documents
            hash_input = f"{self.salt}:{original_text}".encode('utf-8')
            hash_object = hashlib.sha256(hash_input)
            letter_index = int(hash_object.hexdigest()[:2], 16) % 26
            letter = chr(ord("A") + letter_index)
        else:
            # Counter-based (original behavior)
            self.counter += 1
            letter = chr(ord("A") + (self.counter - 1) % 26)
        
        return f"{self.prefix} {letter}"


class GPEPseudonymizer(EntityPseudonymizer):
    """Handles geographic/political entities with subcategories"""
    
    def __init__(self, use_hash: bool = True):
        super().__init__()
        self.countries = self._load_countries()
        self.states = self._load_states()
        self.counters = {"COUNTRY": 0, "STATE": 0, "CITY": 0}
        self.use_hash = use_hash
        self.salt = "gpe_pseudonyms_2024"
    
    def _load_countries(self) -> set:
        """Load country names"""
        return {
            "Singapore", "Malaysia", "Thailand", "Indonesia", "Philippines", 
            "Vietnam", "Myanmar", "Cambodia", "Laos", "Brunei",
            "China", "Japan", "South Korea", "Taiwan", "Hong Kong", "Macau",
            "India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal",
            "United States", "USA", "US", "United Kingdom", "UK", "Canada",
            "Australia", "New Zealand", "Germany", "France", "Italy", "Spain"
        }
    
    def _load_states(self) -> set:
        """Load state/province names"""
        return {
            "Delaware", "California", "New York", "Texas", "Florida",
            "Johor", "Selangor", "Penang", "Sabah", "Sarawak",
            "Jakarta", "West Java", "Bangkok", "Ontario", "Quebec"
        }
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Categorize GPE and generate appropriate replacement"""
        text = original_text.strip()
        
        # Determine category
        if text in self.countries:
            category = "COUNTRY"
            prefix = "Country"
        elif text in self.states:
            category = "STATE"
            prefix = "State"
        else:
            category = "CITY"
            prefix = "City"
        
        if self.use_hash:
            # Hash-based for consistency across documents
            hash_input = f"{self.salt}:{category}:{text}".encode('utf-8')
            hash_object = hashlib.sha256(hash_input)
            letter_index = int(hash_object.hexdigest()[:2], 16) % 26
            letter = chr(ord("A") + letter_index)
        else:
            # Counter-based (original behavior)
            self.counters[category] += 1
            letter = chr(ord("A") + (self.counters[category] - 1) % 26)
        
        return f"{prefix} {letter}"


# ============================================================================
# MAIN PIPELINE (Orchestrates Everything)
# ============================================================================

class PseudonymizationPipeline:
    """Main pipeline that coordinates all extractors and pseudonymizers
    
    This is the main entry point. It:
    1. Loads spaCy model
    2. Initializes all extractors based on config
    3. Initializes all pseudonymizers
    4. Orchestrates the full pseudonymization process
    """
    
    def __init__(self, config: Optional[PseudonymConfig] = None):
        self.config = config or PseudonymConfig()
        self.nlp = self._load_spacy_model()
        
        # Initialize extractors based on config
        self.extractors = self._initialize_extractors()
        
        # Initialize pseudonymizers
        self.pseudonymizers = self._initialize_pseudonymizers()
    
    def _load_spacy_model(self):
        """Load spaCy model with fallback options"""
        models_to_try = [self.config.model_name, "en_core_web_md", "en_core_web_sm"]
        
        for model in models_to_try:
            try:
                return spacy.load(model)
            except OSError:
                logging.warning(f"Could not load spaCy model: {model}")
                continue
        
        raise RuntimeError("No spaCy model found. Please install: python -m spacy download en_core_web_sm")
    
    def _initialize_extractors(self) -> List[EntityExtractor]:
        """Initialize extractors based on configuration"""
        extractors = []
        
        if self.config.enable_date_extraction:
            extractors.append(DateExtractor())
        
        if self.config.enable_organization_extraction:
            extractors.append(OrganizationExtractor())
        
        if self.config.enable_money_extraction:
            extractors.append(MoneyExtractor())

        if self.config.enable_number_extraction:
            extractors.append(NumberExtractor())
        
        if self.config.enable_address_extraction:
            extractors.append(AddressExtractor())
        
        if self.config.enable_legal_person_extraction:
            extractors.append(LegalPersonExtractor())
        
        if self.config.enable_spacy_extraction:
            extractors.append(SpacyExtractor(self.nlp, {"PERSON", "GPE", "FAC", "ORG"}))
        
        return extractors
    
    def _initialize_pseudonymizers(self) -> Dict[str, EntityPseudonymizer]:
        """Initialize pseudonymizers for each entity type"""
        return {
            "DATE": DatePseudonymizer(),
            "ORG": OrganizationPseudonymizer(),
            "MONEY": MoneyPseudonymizer(),
            "NUMBER": NumberPseudonymizer(),
            "ADDRESS": AddressPseudonymizer(),
            "LEGAL_PERSON": LegalPersonPseudonymizer(use_hash_consistency=True),
            "PERSON": CounterBasedPseudonymizer("Person", use_hash=True),
            "GPE": GPEPseudonymizer(use_hash=True),
            "FAC": CounterBasedPseudonymizer("Building", use_hash=True)
        }
    
    def pseudonymize(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Main pseudonymization function
        
        Args:
            text: Input text to pseudonymize
            
        Returns:
            Tuple of (pseudonymized_text, replacement_mapping)
        """
        if not text or not text.strip():
            return text, {}
        
        # Step 1: Extract all entities
        all_entities = self._extract_all_entities(text)
        
        # Step 2: Remove overlapping entities
        all_entities = self._remove_overlaps(all_entities)
        
        # Step 3: Prepare pseudonymizers (e.g., build date mappings)
        self._prepare_pseudonymizers(all_entities)
        
        # Step 4: Apply pseudonymization
        return self._apply_pseudonymization(text, all_entities)
    
    def _extract_all_entities(self, text: str) -> List[Entity]:
        """Run all extractors and collect entities"""
        all_entities = []
        
        for extractor in self.extractors:
            try:
                entities = extractor.extract(text)
                print(f"{extractor.__class__.__name__} found: {[(e.text, e.start, e.end) for e in entities]}")
                all_entities.extend(entities)
                logging.debug(f"{extractor.__class__.__name__} found {len(entities)} entities")
            except Exception as e:
                logging.error(f"Error in {extractor.__class__.__name__}: {e}")
        
        print(f"Before overlap removal: {[(e.text, e.start, e.end, e.label) for e in all_entities]}")
        return all_entities
    
    def _remove_overlaps(self, entities: List[Entity]) -> List[Entity]:
        """Remove overlapping entities, prioritizing legal roles over generic persons"""
        if not entities:
            return entities

        # Priority order: LEGAL_PERSON > PERSON > ORG > others
        priority_order = {"LEGAL_PERSON": 1, "PERSON": 2, "ORG": 3, "GPE": 4, "FAC": 5, "ADDRESS": 6, "MONEY": 7, "NUMBER": 8, "DATE": 9}
        
        # Sort by start position
        sorted_entities = sorted(entities, key=lambda e: e.start)
        result = []
        
        for entity in sorted_entities:
            overlaps = False
            for i, accepted in enumerate(result):
                if entity.start < accepted.end and entity.end > accepted.start:
                    # Use priority instead of just length
                    entity_priority = priority_order.get(entity.label, 10)
                    accepted_priority = priority_order.get(accepted.label, 10)
                    
                    if entity_priority < accepted_priority:  # Lower number = higher priority
                        result[i] = entity
                    elif entity_priority == accepted_priority and len(entity.text) > len(accepted.text):
                        # Same priority, use length as tiebreaker
                        result[i] = entity
                    overlaps = True
                    break
            
            if not overlaps:
                result.append(entity)
        
        print(f"After overlap removal: {[(e.text, e.start, e.end, e.label) for e in result]}")
        return result
    
    def _prepare_pseudonymizers(self, all_entities: List[Entity]) -> None:
        """Prepare pseudonymizers with document-wide context"""
        for label, pseudonymizer in self.pseudonymizers.items():
            relevant_entities = [e for e in all_entities if e.label == label]
            if relevant_entities:
                pseudonymizer.prepare(relevant_entities)
    
    def _apply_pseudonymization(self, text: str, entities: List[Entity]) -> Tuple[str, Dict[str, str]]:
        """Apply pseudonymization and build replacement mapping"""
        result_text = text
        replacement_mapping = {}
        
        # Process entities in reverse order to maintain text positions
        for entity in sorted(entities, key=lambda e: e.start, reverse=True):
            if entity.label in self.pseudonymizers:
                pseudonymizer = self.pseudonymizers[entity.label]
                
                # Special handling for PersonEntity objects
                if isinstance(entity, PersonEntity):
                    pseudonymizer._current_entity = entity
                
                replacement = pseudonymizer.get_replacement(entity.text, entity.label)
                replacement_mapping[entity.text] = replacement
                
                # Replace in text
                result_text = result_text[:entity.start] + replacement + result_text[entity.end:]
        
        return result_text, replacement_mapping


# ============================================================================
# PUBLIC API (Simple Interface for External Use)
# ============================================================================

def pseudonymize_text(text: str, config: Optional[PseudonymConfig] = None) -> Tuple[str, Dict[str, str]]:
    """Simple function interface for pseudonymization
    
    Args:
        text: Text to pseudonymize
        config: Optional configuration (uses defaults if not provided)
        
    Returns:
        Tuple of (pseudonymized_text, replacement_mapping)
        
    Example:
        result, mapping = pseudonymize_text("John Smith works at Apple Inc.")
        print(result)  # "Person A works at ORG A Inc."
        print(mapping)  # {"John Smith": "Person A", "Apple Inc": "ORG A Inc"}
    """
    pipeline = PseudonymizationPipeline(config)
    return pipeline.pseudonymize(text)


def create_custom_config(
    enable_date: bool = True,
    enable_organizations: bool = True,
    enable_money: bool = True,
    enable_numbers: bool = True,
    enable_addresses: bool = True,
    enable_legal_persons: bool = True,
    enable_spacy: bool = True,
    spacy_model: str = "en_core_web_sm"
) -> PseudonymConfig:
    """Helper function to create custom configuration
    
    Args:
        enable_date: Extract and pseudonymize dates
        enable_organizations: Extract and pseudonymize organizations  
        enable_money: Extract and pseudonymize money amounts
        enable_numbers: Extract and pseudonymize numbers/percentages
        enable_addresses: Extract and pseudonymize addresses
        enable_legal_persons: Extract and pseudonymize legal roles (Partner, Plaintiff, etc.)
        enable_spacy: Use spaCy for persons, locations, facilities
        spacy_model: Which spaCy model to use
        
    Returns:
        PseudonymConfig object
    """
    config = PseudonymConfig(model_name=spacy_model)
    config.enable_date_extraction = enable_date
    config.enable_organization_extraction = enable_organizations
    config.enable_money_extraction = enable_money
    config.enable_number_extraction = enable_numbers
    config.enable_address_extraction = enable_addresses
    config.enable_legal_person_extraction = enable_legal_persons
    config.enable_spacy_extraction = enable_spacy
    return config


# ============================================================================
# TESTING AND EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Configure logging for development
    logging.basicConfig(level=logging.INFO)
    
    # Test with enhanced legal document example
    test_text = """On 14 February 2019, Temasek Holdings Pte Ltd, incorporated in Singapore, entered into a Share Purchase Agreement with Alpha Capital Inc. The agreement was negotiated by Michael Tan (Partner, Rajah & Tann Singapore LLP) representing the buyer, and Sarah Wilson, counsel for the seller. Pursuant to the Agreement, Beta Energy Pte Ltd agreed to sell a 45% stake for USD 325,000,000 (Three Hundred Twenty-Five Million United States Dollars), payable by wire transfer to DBS Bank Ltd, Raffles Place Branch, Singapore, no later than 30 September 2020. Later, Michael Tan confirmed all terms were acceptable."""
    
    print("="*80)
    print("LEGAL DOCUMENT PSEUDONYMIZATION TOOL - TEST")
    print("="*80)
    
    print("\nOriginal Text:")
    print("-" * 40)
    print(test_text)
    
    # Test with default configuration
    result, mapping = pseudonymize_text(test_text)
    
    print("\nPseudonymized Text:")
    print("-" * 40)  
    print(result)
    
    print("\nReplacement Mapping:")
    print("-" * 40)
    for original, replacement in mapping.items():
        print(f"'{original}' -> '{replacement}'")
    
    print("\n" + "="*80)
    print("ENHANCED FEATURES:")
    print("="*80)
    print("""
    1. LEGAL ROLE AWARENESS:
       - "Michael Tan (Partner)" -> "Partner A" 
       - Later "Michael Tan" -> "Partner A" (cross-reference)
       - "Sarah Wilson" -> "Person A" (spaCy fallback)
    
    2. HASH-BASED CONSISTENCY:
       - Same entities get same pseudonyms across documents
       - Addresses use 6-digit hash codes
       - Maintains legal document relationships
    
    3. MULTI-CURRENCY SUPPORT:
       - USD, EUR, GBP, SGD, CHF and more
       - Preserves currency format and written amounts
       - ±15% randomization of amounts
    
    4. SINGAPORE LEGAL FOCUS:
       - Singapore address patterns (One Raffles Quay, etc.)
       - Legal role extraction (Plaintiff, Counsel, Partner)
       - Corporate suffix preservation (Pte Ltd, LLP)
    
    5. COMPREHENSIVE ENTITY TYPES:
       - Legal persons with roles
       - Multi-currency amounts  
       - Hash-based addresses
       - Randomized percentages/numbers
       - Date interval preservation
    
    Ready for production legal document processing!
    """)


# ============================================================================
# ADDITIONAL UTILITIES FOR DEVELOPMENT TEAM
# ============================================================================

class PseudonymizationAnalyzer:
    """Utility class for analyzing pseudonymization results"""
    
    @staticmethod
    def analyze_entities(text: str, config: Optional[PseudonymConfig] = None) -> Dict[str, List[str]]:
        """Extract and categorize entities without pseudonymizing
        
        Useful for debugging and understanding what gets extracted.
        """
        pipeline = PseudonymizationPipeline(config)
        all_entities = pipeline._extract_all_entities(text)
        
        entity_groups = {}
        for entity in all_entities:
            if entity.label not in entity_groups:
                entity_groups[entity.label] = []
            entity_groups[entity.label].append(entity.text)
        
        return entity_groups
    
    @staticmethod
    def test_individual_extractor(extractor_class, text: str, *args, **kwargs):
        """Test a specific extractor in isolation"""
        extractor = extractor_class(*args, **kwargs)
        entities = extractor.extract(text)
        
        print(f"\n{extractor_class.__name__} Results:")
        print("-" * 40)
        for entity in entities:
            print(f"  {entity.label}: '{entity.text}' at positions {entity.start}-{entity.end}")
        
        return entities


# Example usage for development team:
if __name__ == "__main__" and False:  # Set to True to run examples
    # Analyze what entities are found without pseudonymizing
    analysis = PseudonymizationAnalyzer.analyze_entities(test_text)
    print("\nEntity Analysis:")
    for label, entities in analysis.items():
        print(f"  {label}: {entities}")
    
    # Test individual extractors
    PseudonymizationAnalyzer.test_individual_extractor(DateExtractor, test_text)
    PseudonymizationAnalyzer.test_individual_extractor(LegalPersonExtractor, test_text)